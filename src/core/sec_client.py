"""
SEC API client for fetching 13F filings
"""
import re
import logging
import random
import time
from typing import Any, Callable, List, Dict, Optional
from functools import lru_cache
import requests
import feedparser

logger = logging.getLogger(__name__)

# Backoff between attempts: base * 2^(attempt-1), jittered, never above the cap.
# With three attempts a fund that keeps failing costs ~6 s of waiting, not the
# two minutes the old fixed 60 s sleep did - which, times ~58 funds, stretched a
# cycle past the reporter's staleness threshold during an SEC outage.
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SECONDS = 2.0
DEFAULT_BACKOFF_CAP_SECONDS = 30.0
# (connect, read). A host that does not even accept the connection is down; no
# point waiting 30 s to find that out.
DEFAULT_TIMEOUT = (10, 30)


class SECFetchError(Exception):
    """SEC could not be read. Distinct from a successful answer with no filings.

    ``reason`` is a short, human-readable cause ("HTTP 403", "timeout") suited
    to a health message; ``status_code`` is set when SEC answered at all.
    """

    def __init__(
        self,
        reason: str,
        url: str = '',
        status_code: Optional[int] = None,
        attempts: int = 0,
    ):
        self.reason = reason
        self.url = url
        self.status_code = status_code
        self.attempts = attempts
        detail = f" ({url})" if url else ''
        super().__init__(f"{reason}{detail}")


def _looks_like_html(response: requests.Response) -> bool:
    """SEC answers some outages and throttles with a 200 and an HTML page."""
    content_type = str(response.headers.get('Content-Type', '') or '').lower()
    if 'text/html' in content_type:
        return True
    head = (response.content or b'')[:512].lstrip().lower()
    return head.startswith(b'<!doctype html') or head.startswith(b'<html')


def _retry_after_seconds(response: requests.Response) -> Optional[float]:
    """The ``Retry-After`` header in its seconds form; the HTTP-date form is ignored."""
    raw = str(response.headers.get('Retry-After', '') or '').strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class SECClient:
    """Client for interacting with SEC EDGAR API"""

    def __init__(
        self,
        user_agent: str,
        max_retries: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay: Optional[float] = None,
        *,
        backoff_cap: float = DEFAULT_BACKOFF_CAP_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ):
        """
        Args:
            max_retries: total attempts per request (1 = no retry).
            retry_delay: backoff base in seconds; ``None`` uses the default
                (2 s). Every wait is capped at ``backoff_cap``.
            sleep, jitter: injectable so tests run without waiting.
        """
        self.user_agent = user_agent
        self.max_retries = max(1, int(max_retries))
        self.retry_delay = DEFAULT_BACKOFF_BASE_SECONDS if retry_delay is None else float(retry_delay)
        self.backoff_cap = float(backoff_cap)
        self._sleep = sleep
        self._jitter = jitter
        self._session = requests.Session()
        self._session.headers.update({'User-Agent': user_agent})

    # -- transport --------------------------------------------------------- #

    def _backoff_seconds(self, attempt: int, retry_after: Optional[float]) -> float:
        """How long to wait after failed ``attempt`` (1-based)."""
        if retry_after is not None:
            return min(retry_after, self.backoff_cap)
        ceiling = min(self.retry_delay * (2 ** (attempt - 1)), self.backoff_cap)
        # "Equal jitter": at least half the backoff, so a fleet of retries
        # neither synchronises nor collapses to zero.
        return ceiling / 2 + self._jitter(0, ceiling / 2)

    def _get(self, url: str, expect: str) -> Any:
        """GET ``url`` with the retry policy and return the usable body.

        ``expect`` is 'json' (returns the parsed object, which must be a dict)
        or 'xml' (returns the raw bytes).

        Retried: 429, 5xx, connection errors, timeouts, and a 200 whose body is
        an HTML error page or unparseable JSON. Not retried: any other 4xx - a
        403 or 404 will not change in six seconds.

        Raises:
            SECFetchError: when no attempt produced a usable answer.
        """
        failure: Optional[SECFetchError] = None

        for attempt in range(1, self.max_retries + 1):
            retry_after: Optional[float] = None
            try:
                response = self._session.get(url, timeout=DEFAULT_TIMEOUT)
            except requests.exceptions.Timeout as exc:
                failure = SECFetchError('timeout', url, attempts=attempt)
                logger.warning("SEC timeout (tentativo %s/%s) %s: %s", attempt, self.max_retries, url, exc)
            except requests.exceptions.ConnectionError as exc:
                failure = SECFetchError('connessione fallita', url, attempts=attempt)
                logger.warning(
                    "SEC connessione fallita (tentativo %s/%s) %s: %s", attempt, self.max_retries, url, exc
                )
            except requests.exceptions.RequestException as exc:
                # Malformed URL, too many redirects...: retrying cannot help.
                raise SECFetchError(f"richiesta non valida: {exc}", url, attempts=attempt) from exc
            else:
                status = response.status_code
                if status == 200:
                    body, problem = self._usable_body(response, expect)
                    if problem is None:
                        return body
                    failure = SECFetchError(problem, url, status_code=status, attempts=attempt)
                    logger.warning(
                        "SEC ha risposto 200 ma %s (tentativo %s/%s): %s",
                        problem, attempt, self.max_retries, url,
                    )
                elif status == 429 or status >= 500:
                    failure = SECFetchError(f"HTTP {status}", url, status_code=status, attempts=attempt)
                    retry_after = _retry_after_seconds(response)
                    logger.warning(
                        "SEC HTTP %s (tentativo %s/%s) %s", status, attempt, self.max_retries, url
                    )
                else:
                    logger.warning("SEC HTTP %s, non ritento: %s", status, url)
                    raise SECFetchError(f"HTTP {status}", url, status_code=status, attempts=attempt)

            if attempt < self.max_retries:
                self._sleep(self._backoff_seconds(attempt, retry_after))

        assert failure is not None  # the loop only falls through after a failure
        logger.error("SEC non raggiungibile dopo %s tentativi: %s", self.max_retries, failure)
        raise failure

    @staticmethod
    def _usable_body(response: requests.Response, expect: str) -> tuple[Any, Optional[str]]:
        """Return ``(body, None)`` or ``(None, problem)`` for a 200 response."""
        if _looks_like_html(response):
            return None, f"pagina HTML al posto di {expect.upper()}"
        if expect != 'json':
            return response.content, None
        try:
            data = response.json()
        except ValueError:
            return None, 'JSON non valido'
        if not isinstance(data, dict):
            return None, 'JSON non valido'
        return data, None

    # -- endpoints --------------------------------------------------------- #

    def fetch_13f_feed(self, rss_url: str) -> feedparser.FeedParserDict:
        """
        Fetch the 13F-HR RSS feed from SEC

        Args:
            rss_url: URL of the SEC RSS feed

        Returns:
            Parsed feed dictionary (possibly with no entries: a quiet feed).

        Raises:
            SECFetchError: SEC could not be read - not the same as an empty feed.
        """
        logger.info("Scaricamento feed SEC...")
        content = self._get(rss_url, expect='xml')
        feed = feedparser.parse(content)
        logger.info(f"Feed scaricato: {len(feed.get('entries', []))} entry trovate")
        return feed

    def fetch_recent_13f_for_cik(
        self,
        cik: str,
        max_entries: int = 10,
        forms: tuple[str, ...] = ('13F-HR', '13F-HR/A'),
    ) -> List[Dict[str, str]]:
        """
        Fetch recent 13F filings for one CIK from SEC submissions endpoint.

        Returns:
            List of dicts with form, filing_date, acceptance_datetime,
            accession_number, report_date (the quarter end reported on),
            filing_url and filer_name. Empty means SEC answered and the fund
            has no recent 13F.

        Raises:
            SECFetchError: SEC could not be read. Callers must not treat this
                as "no filings" - that is how an outage looked like a quiet day.
        """
        cik_padded = cik.zfill(10)
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

        data = self._get(submissions_url, expect='json')

        filings_block = data.get('filings')
        recent = filings_block.get('recent') if isinstance(filings_block, dict) else None
        if not isinstance(recent, dict):
            recent = {}
        forms_list = recent.get('form', [])
        accession_numbers = recent.get('accessionNumber', [])
        filing_dates = recent.get('filingDate', [])
        acceptance_datetimes = recent.get('acceptanceDateTime', [])
        primary_documents = recent.get('primaryDocument', [])
        report_dates = recent.get('reportDate', [])
        filer_name = str(data.get('name') or '').strip()

        filings: List[Dict[str, str]] = []
        for idx, form in enumerate(forms_list):
            if form not in forms:
                continue

            accession_number = accession_numbers[idx] if idx < len(accession_numbers) else ''
            filing_date = filing_dates[idx] if idx < len(filing_dates) else ''
            acceptance_datetime = (
                acceptance_datetimes[idx] if idx < len(acceptance_datetimes) else ''
            )
            primary_document = (
                primary_documents[idx] if idx < len(primary_documents) else ''
            )

            filing_url = self.build_filing_index_url(cik, accession_number)

            filings.append({
                'cik': cik,
                'form': form,
                'filing_date': filing_date,
                'acceptance_datetime': acceptance_datetime,
                'accession_number': accession_number,
                'report_date': report_dates[idx] if idx < len(report_dates) else '',
                'primary_document': primary_document,
                'filing_url': filing_url,
                'filer_name': filer_name,
            })

            if len(filings) >= max_entries:
                break

        return filings

    @staticmethod
    @lru_cache(maxsize=1000)
    def extract_cik_from_link(link: str) -> str:
        """
        Extract CIK from EDGAR URL (cached for performance)

        Args:
            link: EDGAR URL containing CIK

        Returns:
            CIK number or 'N/A' if not found
        """
        try:
            # Pattern: /data/XXXXXX/ or CIK=XXXXXX
            match = re.search(r'(?:CIK=|/data/)(\d+)', link)
            if match:
                return match.group(1)
            return 'N/A'
        except Exception as e:
            logger.debug(f"Errore estrazione CIK: {e}")
            return 'N/A'

    @staticmethod
    def extract_accession_number(link: str) -> str:
        """
        Extract accession number from filing URL

        Args:
            link: Filing URL

        Returns:
            Accession number or 'N/A' if not found
        """
        try:
            # Pattern: XXXXXXXXXX-XX-XXXXXX
            match = re.search(r'(\d{10}-\d{2}-\d{6})', link)
            return match.group(1) if match else 'N/A'
        except Exception as e:
            logger.debug(f"Errore estrazione accession number: {e}")
            return 'N/A'

    @staticmethod
    def build_filing_index_url(cik: str, accession_number: str) -> str:
        """Build SEC filing index URL from CIK and accession number."""
        if not accession_number:
            return ''

        accession_no_dashes = accession_number.replace('-', '')
        cik_no_leading = cik.lstrip('0') if cik else ''
        return (
            f"https://www.sec.gov/Archives/edgar/data/{cik_no_leading}/"
            f"{accession_no_dashes}/{accession_number}-index.htm"
        )

    @staticmethod
    def extract_filer_name_from_title(title: str) -> str:
        """
        Extract filer name from RSS entry title

        Args:
            title: RSS entry title (format: "13F-HR - FUND NAME (CIK) (Filer)")

        Returns:
            Filer name
        """
        try:
            # Remove "13F-HR - " prefix
            if '13F-HR - ' in title:
                name_part = title.split('13F-HR - ', 1)[1]
                # Remove " (CIK...)" suffix
                if '(' in name_part:
                    filer_name = name_part.split('(')[0].strip()
                    if filer_name:
                        return filer_name

            # Alternative pattern: extract before first parenthesis
            if '(' in title and ')' in title:
                name_before_paren = title.split('(')[0].strip()
                if name_before_paren and '13F-HR' not in name_before_paren:
                    return name_before_paren
                # Otherwise search after "13F-HR -"
                if '13F-HR -' in name_before_paren:
                    name = name_before_paren.replace('13F-HR -', '').strip()
                    if name:
                        return name

            return title  # Fallback: return full title
        except Exception as e:
            logger.debug(f"Errore estrazione filer name: {e}")
            return 'Filer Sconosciuto'

    def should_notify(self, filer_name: str, filing_link: str, cik_filter: Dict[str, str]) -> tuple[bool, str]:
        """
        Check if a filer matches the CIK filter

        Args:
            filer_name: Filer name (for logging)
            filing_link: Filing URL containing CIK
            cik_filter: Dictionary of CIK -> Fund Name

        Returns:
            Tuple of (match_found, fund_name)
        """
        if not cik_filter:
            return True, "ALL"  # No filter, notify all

        # Extract CIK from URL
        cik = self.extract_cik_from_link(filing_link)

        # Validation: check if extraction failed
        if cik == 'N/A' or not cik:
            logger.warning(f"⚠ CIK extraction failed per {filer_name} - Link: {filing_link}")
            return False, ""

        # Normalize CIK (remove leading zeros for flexible matching)
        cik_normalized = cik.lstrip('0') if cik else ''

        # Search for CIK in filter (with and without leading zeros)
        for filter_cik, fund_name in cik_filter.items():
            filter_cik_normalized = filter_cik.lstrip('0')

            if cik == filter_cik or cik_normalized == filter_cik_normalized:
                logger.info(f"✓ MATCH trovato: CIK {cik} → {fund_name}")
                return True, fund_name

        # No match found
        logger.debug(f"✗ Nessun match per: {filer_name} (CIK: {cik})")
        return False, ""
