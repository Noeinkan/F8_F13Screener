"""
SEC API client for fetching 13F filings
"""
import re
import logging
import time
from typing import List, Dict
from functools import lru_cache
import requests
import feedparser

logger = logging.getLogger(__name__)


class SECClient:
    """Client for interacting with SEC EDGAR API"""

    def __init__(self, user_agent: str, max_retries: int = 3, retry_delay: int = 60):
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session = requests.Session()
        self._session.headers.update({'User-Agent': user_agent})

    def fetch_13f_feed(self, rss_url: str) -> feedparser.FeedParserDict:
        """
        Fetch the 13F-HR RSS feed from SEC

        Args:
            rss_url: URL of the SEC RSS feed

        Returns:
            Parsed feed dictionary
        """
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Scaricamento feed SEC (tentativo {attempt+1}/{self.max_retries})...")
                response = self._session.get(rss_url, timeout=30)

                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    logger.info(f"Feed scaricato: {len(feed.entries)} entry trovate")
                    return feed
                else:
                    logger.warning(f"Errore SEC HTTP {response.status_code}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Eccezione scaricamento feed: {e}")

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)

        logger.error("Fallito scaricamento feed dopo tutti i tentativi")
        return feedparser.FeedParserDict()

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
            accession_number, filing_url and filer_name.
        """
        cik_padded = cik.zfill(10)
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

        for attempt in range(self.max_retries):
            try:
                response = self._session.get(submissions_url, timeout=30)
                if response.status_code != 200:
                    logger.warning(
                        "Errore submissions SEC per CIK %s HTTP %s",
                        cik,
                        response.status_code,
                    )
                else:
                    data = response.json()
                    recent = data.get('filings', {}).get('recent', {})
                    forms_list = recent.get('form', [])
                    accession_numbers = recent.get('accessionNumber', [])
                    filing_dates = recent.get('filingDate', [])
                    acceptance_datetimes = recent.get('acceptanceDateTime', [])
                    primary_documents = recent.get('primaryDocument', [])
                    filer_name = data.get('name', '').strip()

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
                            'primary_document': primary_document,
                            'filing_url': filing_url,
                            'filer_name': filer_name,
                        })

                        if len(filings) >= max_entries:
                            break

                    return filings

            except requests.exceptions.RequestException as e:
                logger.error("Eccezione submissions SEC per CIK %s: %s", cik, e)
            except ValueError as e:
                logger.error("JSON non valido da submissions SEC per CIK %s: %s", cik, e)

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)

        return []

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
