"""
13F Holdings parser with robust HTML/XML parsing
"""
import re
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class HoldingsParser:
    """Parser for 13F Information Table"""

    # Ranking of Information Table links on a filing index page; lower wins.
    # EDGAR lists the table twice: the raw XML the filer submitted, and an
    # ``xslForm13F_X0N/<name>.xml`` link that is SEC's XSLT rendering of that
    # XML as an HTML page. Both end in ``.xml``, so the extension alone cannot
    # tell them apart. The raw XML is exact and parses with the XML path; the
    # rendering is kept only as the last resort.
    _RANK_RAW_XML = 0
    _RANK_HTML = 1
    _RANK_XSL_RENDERED = 2
    _RANK_OTHER = 3

    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    @staticmethod
    def _href_path(href: str) -> str:
        return href.split('#', 1)[0].split('?', 1)[0].lower()

    @classmethod
    def _information_table_link_rank(cls, href: str) -> int:
        path = cls._href_path(href)
        if path.endswith('.xml'):
            return cls._RANK_XSL_RENDERED if 'xslform' in path else cls._RANK_RAW_XML
        if path.endswith(('.html', '.htm')):
            return cls._RANK_HTML
        return cls._RANK_OTHER

    def get_information_table_url(self, filing_index_url: str) -> Optional[str]:
        """
        Download filing index page and find Information Table HTML URL

        Args:
            filing_index_url: URL of the filing index page

        Returns:
            URL of the Information Table or None if not found
        """
        urls = self.get_information_table_urls(filing_index_url)
        return urls[0] if urls else None

    def get_information_table_urls(self, filing_index_url: str) -> List[str]:
        """All Information Table links on the filing index page, best first.

        The alternatives are what gives a malformed raw XML a second chance:
        SEC's rendering of the same table is usually listed right beside it.
        """
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(filing_index_url, headers=headers, timeout=30)

            if response.status_code != 200:
                logger.error(f"Errore scaricamento index: HTTP {response.status_code}")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')
            base_url = '/'.join(filing_index_url.split('/')[:-1])

            def build_full_url(href: str) -> str:
                if href.startswith('http'):
                    return href
                if href.startswith('/'):
                    return f"https://www.sec.gov{href}"
                return f"{base_url}/{href}"

            def ranked(hrefs: List[str]) -> List[str]:
                # Stable sort: equal ranks keep the order they appear on the page.
                ordered = sorted(
                    enumerate(hrefs),
                    key=lambda item: (self._information_table_link_rank(item[1]), item[0]),
                )
                return list(dict.fromkeys(build_full_url(href) for _, href in ordered))

            # Method 1: Prefer rows explicitly labeled INFORMATION TABLE.
            row_hrefs: List[str] = []
            for row in soup.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) < 3:
                    continue

                row_text = ' '.join(cell.get_text(' ', strip=True) for cell in cells).upper()
                if 'INFORMATION TABLE' not in row_text and 'INFO TABLE' not in row_text:
                    continue

                for cell in cells:
                    link = cell.find('a', href=True)
                    if not link:
                        continue
                    href = link['href']
                    if self._information_table_link_rank(href) < self._RANK_OTHER:
                        row_hrefs.append(href)

            urls = ranked(row_hrefs)
            if urls:
                logger.debug(f"Found infotable (method 1): {urls}")
                return urls

            # Method 2: Search for link containing "infotable" in its text or href.
            infotable_hrefs = [
                link['href']
                for link in soup.find_all('a', href=True)
                if 'infotable' in link.get_text(strip=True).lower() or 'infotable' in link['href'].lower()
            ]
            urls = ranked(infotable_hrefs)
            if urls:
                logger.debug(f"Found infotable (method 2): {urls}")
                return urls

            # Method 3: Any XML file except the primary cover document.
            xml_hrefs = [
                link['href']
                for link in soup.find_all('a', href=True)
                if self._href_path(link['href']).endswith('.xml')
                and 'primary_doc' not in link['href'].lower()
            ]
            urls = ranked(xml_hrefs)
            if urls:
                logger.debug(f"Found XML table (method 3): {urls}")
                return urls

            logger.warning(f"Information Table HTML non trovata nella pagina: {filing_index_url}")
            # Log available files for debugging
            all_files = [link.get('href') for link in soup.find_all('a', href=True) if link.get('href', '').endswith(('.xml', '.html', '.htm'))]
            if all_files:
                logger.debug(f"Available files: {', '.join(all_files[:10])}")
            return []

        except Exception as e:
            logger.error(f"Errore parsing index page: {e}")
            return []

    def parse_filing_holdings(self, filing_index_url: str) -> Tuple[Optional[str], List[Dict]]:
        """Find and parse a filing's Information Table, trying each link in turn.

        A link is passed over when it does not download, when it is raw XML that
        is not well-formed, or when it yields no holdings. Malformed XML is never
        used even though it "parses": the XML reader recovers silently and keeps
        only the rows before the break, which the diff would then report as
        positions closed. Holdings without a single value are kept only when no
        other link does better.

        Returns ``(url used, holdings)``, or ``(None, [])`` when no link gave any.
        """
        urls = self.get_information_table_urls(filing_index_url)
        fallback: Tuple[Optional[str], List[Dict]] = (None, [])

        for url in urls:
            content = self._download_information_table(url)
            if content is None:
                continue
            if self._information_table_link_rank(url) == self._RANK_RAW_XML and not self._is_well_formed_xml(content):
                logger.warning(f"Information Table XML malformata, provo il link successivo: {url}")
                continue
            holdings = self.parse_information_table_content(content)
            if not holdings:
                logger.warning(f"Nessuna holding in {url}, provo il link successivo")
                continue
            if any(holding.get('value') is not None for holding in holdings):
                return url, holdings
            logger.warning(f"Holdings senza alcun valore in {url}, provo il link successivo")
            if not fallback[1]:
                fallback = (url, holdings)

        if urls and not fallback[1]:
            logger.error(f"Nessun link dell'Information Table ha dato holdings utilizzabili: {filing_index_url}")
        return fallback

    @staticmethod
    def _is_well_formed_xml(content: bytes | str) -> bool:
        """Strict parse, no recovery. Leading whitespace is tolerated, as EDGAR files sometimes carry it."""
        try:
            ET.fromstring(content.lstrip())
            return True
        except ET.ParseError:
            return False

    def _download_information_table(self, url: str) -> Optional[bytes]:
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(url, headers=headers, timeout=30)
        except Exception as e:
            logger.error(f"Errore scaricamento Information Table {url}: {e}")
            return None
        if response.status_code != 200:
            logger.error(f"Errore scaricamento Information Table: HTTP {response.status_code} ({url})")
            return None
        return response.content

    def parse_information_table(self, html_url: str) -> List[Dict]:
        """
        Download and parse Information Table HTML file

        Args:
            html_url: URL of the Information Table

        Returns:
            List of holdings dictionaries
        """
        content = self._download_information_table(html_url)
        if content is None:
            return []
        try:
            return self.parse_information_table_content(content)
        except Exception as e:
            logger.error(f"Errore parsing Information Table: {e}")
            return []

    def parse_information_table_content(self, content: bytes | str) -> List[Dict]:
        """Parse an already-downloaded Information Table: XML first, HTML table fallback."""
        # First: Try XML style parsing
        holdings = self._parse_xml_format(BeautifulSoup(content, 'xml'))
        if holdings:
            logger.info(f"Parsate {len(holdings)} holdings da XML Information Table")
            return holdings

        # Fallback: HTML table parsing
        holdings = self._parse_html_format(BeautifulSoup(content, 'html.parser'))
        logger.info(f"Parsate {len(holdings)} holdings dalla Information Table (HTML)")
        return holdings

    @staticmethod
    def _local_name(tag) -> str:
        """Tag name without namespace prefix, lower-cased (``ns1:infoTable`` -> ``infotable``)."""
        name = getattr(tag, 'name', None) or ''
        return name.rsplit(':', 1)[-1].lower()

    @classmethod
    def _find_local(cls, parent, *names: str):
        """First descendant whose local name matches one of ``names``, ignoring case and prefix."""
        wanted = {name.lower() for name in names}
        return parent.find(lambda tag: cls._local_name(tag) in wanted)

    @staticmethod
    def _rendered_number(raw: str) -> str:
        """Format an integer the way SEC's XSLT rendering prints it (``1016782`` -> ``1,016,782``)."""
        if re.fullmatch(r'-?\d+', raw or ''):
            return f"{int(raw):,}"
        return raw

    def _parse_xml_format(self, soup_xml: BeautifulSoup) -> List[Dict]:
        """Parse XML format Information Table.

        Each holding is one ``infoTable`` element. The document root is
        ``informationTable``, which must never be read as a holding: its
        descendant search would pick up fields from whichever row carries them
        first, inventing a row out of pieces of the real ones.
        """
        holdings = []

        info_entries = soup_xml.find_all(lambda tag: self._local_name(tag) == 'infotable')
        if not info_entries:
            return []

        logger.info(f"Information Table XML trovata: {len(info_entries)} entries")

        for entry in info_entries:
            def get_tag_text(*tag_names, parent=entry):
                tag = self._find_local(parent, *tag_names)
                return tag.get_text(strip=True) if tag else ''

            issuer = get_tag_text('nameOfIssuer')
            share_class = get_tag_text('titleOfClass')
            cusip = get_tag_text('cusip')
            figi = get_tag_text('figi')
            value_raw = get_tag_text('value', 'marketValue')

            # shrsOrPrn can be nested
            sh_qty = ''
            sh_prn_type = ''
            sh_tag = self._find_local(entry, 'shrsOrPrn')
            if sh_tag:
                amt = self._find_local(sh_tag, 'sshPrnamt')
                sh_qty = amt.get_text(strip=True) if amt else ''
                sh_prn_type = get_tag_text('sshPrnamtType', parent=sh_tag)
                if not amt and not sh_prn_type:
                    sh_qty = sh_tag.get_text(strip=True)
            else:
                sh_qty = get_tag_text('amount')

            put_call = get_tag_text('putCall')
            investment_discretion = get_tag_text('investmentDiscretion')
            other_manager = get_tag_text('otherManager')

            # VotingAuthority may be structured
            voting_sole = ''
            voting_shared = ''
            voting_none = ''
            va = self._find_local(entry, 'votingAuthority')
            if va:
                voting_sole = get_tag_text('sole', parent=va)
                voting_shared = get_tag_text('shared', parent=va)
                voting_none = get_tag_text('none', parent=va)

            # Mirror the HTML path's raw trace: every column of SEC's rendered
            # table, in its order, numbers with thousands separators.
            rendered_cells = [
                issuer, share_class, cusip, figi,
                self._rendered_number(value_raw), self._rendered_number(sh_qty), sh_prn_type,
                put_call, investment_discretion, other_manager,
                self._rendered_number(voting_sole), self._rendered_number(voting_shared),
                self._rendered_number(voting_none),
            ]

            holding = {
                'issuer_name': issuer,
                'share_class': share_class,
                'cusip': cusip,
                'figi': figi,
                'value_x1000': value_raw,
                'value': self._to_int(value_raw),
                'shares_raw': sh_qty,
                'shares': self._to_int(sh_qty),
                'sh_prn': sh_prn_type,
                'put_call': put_call,
                'investment_discretion': investment_discretion,
                'other_manager': other_manager,
                'other_managers_raw': other_manager,
                'voting_authority_sole': self._to_int(voting_sole),
                'voting_authority_shared': self._to_int(voting_shared),
                'voting_authority_none': self._to_int(voting_none),
                'voting_authority_raw': '',
                'all_columns_raw': ' | '.join(rendered_cells).strip(),
            }

            if holding['cusip'] or holding['issuer_name']:
                holdings.append(holding)

        return holdings

    def _parse_html_format(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse HTML table format Information Table"""
        holdings = []

        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue

            # Find header row
            header_map = self._map_table_headers(rows)
            if not header_map:
                continue

            # Parse data rows
            header_row_index = header_map['header_row_index']
            column_map = header_map['column_map']
            extras_headers = header_map['extras_headers']

            for row in rows[header_row_index + 1:]:
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue

                holding = self._parse_table_row(cells, column_map, extras_headers)
                if holding and (holding['cusip'] or holding['issuer_name']):
                    holdings.append(holding)

            if holdings:
                break

        return holdings

    def _map_table_headers(self, rows: List) -> Optional[Dict]:
        """Map table headers to canonical keys"""
        canonical_keys = {
            'issuer_name': ['NAME OF ISSUER', 'ISSUER', 'NAME'],
            'share_class': ['TITLE OF CLASS', 'TITLE', 'CLASS'],
            'cusip': ['CUSIP'],
            'figi': ['FIGI'],
            'value_x1000': ['VALUE', 'MARKET VALUE', 'MKT VALUE', 'TO THE NEAREST DOLLAR', 'X$1000', 'X 1000'],
            'shares': ['SHRS OR PRN AMT', 'PRN AMT', 'AMOUNT', 'SHARE', 'SHRS', 'SHARES'],
            'sh_prn': ['SH/PRN', 'PRN', 'SH PRN'],
            'put_call': ['PUT/CALL', 'CALL', 'PUT CALL'],
            'investment_discretion': ['INVESTMENT DISCRETION', 'DISCRETION', 'INV DISCRETION'],
            'other_manager': ['OTHER MANAGER', 'OTHER MANAGERS', 'OTHER', 'MANAGER'],
            'voting_authority_sole': ['VOTING AUTH. - SOLE', 'SOLE VOTING', 'VOTING SOLE', 'SOLE'],
            'voting_authority_shared': ['VOTING AUTH. - SHARED', 'SHARED VOTING', 'VOTING SHARED', 'SHARED'],
            'voting_authority_none': ['VOTING AUTH. - NONE', 'NONE VOTING', 'VOTING NONE', 'NONE'],
            'voting_authority_raw': ['VOTING AUTHORITY', 'VOTING AUTH']
        }

        for i, row in enumerate(rows[:8]):
            cells = row.find_all(['td', 'th'])
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            norm_texts = [t.upper() for t in cell_texts]

            # Check if this is the header row
            if any('CUSIP' in text for text in norm_texts) and any('ISSUER' in text or 'NAME' in text for text in norm_texts):
                header_map = {}
                extras_headers = []

                for idx, raw_label in enumerate(cell_texts):
                    label = raw_label.strip()
                    upper = label.upper()
                    mapped = None

                    # Priorità: match più specifici prima di match generici
                    # Per evitare che "SOLE" matchi "OTHER" prima di "VOTING SOLE"
                    priority_keys = [
                        'voting_authority_sole', 'voting_authority_shared', 'voting_authority_none',
                        'issuer_name', 'share_class', 'cusip', 'figi', 'value_x1000', 
                        'shares', 'sh_prn', 'put_call', 'investment_discretion',
                        'other_manager', 'voting_authority_raw'
                    ]
                    
                    for key in priority_keys:
                        if key not in canonical_keys:
                            continue
                        for v in canonical_keys[key]:
                            if v in upper:
                                mapped = key
                                break
                        if mapped:
                            break

                    if mapped:
                        header_map[idx] = mapped
                    else:
                        extra_key = f"extra_col_{idx}"
                        header_map[idx] = extra_key
                        extras_headers.append((extra_key, label))

                return {
                    'header_row_index': i,
                    'column_map': header_map,
                    'extras_headers': extras_headers
                }

        return None

    def _parse_table_row(self, cells: List, column_map: Dict, extras_headers: List) -> Optional[Dict]:
        """Parse a single table row"""
        try:
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            if not cell_texts or cell_texts[0].upper() in ['NAME OF ISSUER', 'COLUMN 1', '']:
                return None

            holding = {
                'issuer_name': '', 'share_class': '', 'cusip': '', 'figi': '',
                'value_x1000': '', 'value': None, 'shares': None, 'shares_raw': '', 'sh_prn': '', 'put_call': '',
                'investment_discretion': '', 'other_manager': '', 'other_managers_raw': '',
                'voting_authority_sole': '', 'voting_authority_shared': '', 'voting_authority_none': '',
                'voting_authority_raw': '', 'all_columns_raw': ''
            }

            for idx, val in enumerate(cell_texts):
                key = column_map.get(idx)
                clean_val = val.replace('\xa0', ' ').strip()
                if not key:
                    continue

                if key.startswith('extra_col_'):
                    extra_label = next((lbl for k, lbl in extras_headers if k == key), None)
                    extra_label = extra_label or key
                    holding['all_columns_raw'] += f"{extra_label}: {clean_val}; "
                elif key == 'voting_authority_raw':
                    holding['voting_authority_raw'] = clean_val
                elif key == 'other_manager':
                    holding['other_manager'] = clean_val
                    holding['other_managers_raw'] = clean_val
                else:
                    if key in holding:
                        if key in ('value_x1000', 'shares', 'voting_authority_sole', 'voting_authority_shared', 'voting_authority_none'):
                            holding[key] = clean_val.replace(',', '')
                            if key == 'shares':
                                holding['shares_raw'] = clean_val.replace(',', '')
                        else:
                            holding[key] = clean_val

            # Numeric conversions
            holding['value'] = self._to_int(holding.get('value_x1000'))
            if not holding.get('shares_raw'):
                holding['shares_raw'] = holding.get('shares', '')
            holding['shares'] = self._to_int(holding.get('shares'))

            # Parse voting authority if combined
            if holding.get('voting_authority_raw') and not (holding.get('voting_authority_sole') or holding.get('voting_authority_shared') or holding.get('voting_authority_none')):
                parts = re.split(r'[\s/|-]+', holding['voting_authority_raw'])
                nums = [p for p in parts if p.isdigit()]
                if len(nums) == 3:
                    holding['voting_authority_sole'] = nums[0]
                    holding['voting_authority_shared'] = nums[1]
                    holding['voting_authority_none'] = nums[2]

            # Same type as the XML path and as the INTEGER/BIGINT columns they land in.
            for key in ('voting_authority_sole', 'voting_authority_shared', 'voting_authority_none'):
                holding[key] = self._to_int(holding.get(key))

            holding['all_columns_raw'] = holding['all_columns_raw'] or (' | '.join(cell_texts)).strip()
            return holding

        except Exception as e:
            logger.debug(f"Errore parsing riga HTML: {e}")
            return None

    @staticmethod
    def _to_int(s: str) -> Optional[int]:
        """Convert string to integer, handling various formats"""
        if s is None:
            return None
        s = str(s).strip()
        if s in ['', '-', 'N/A', 'NA']:
            return None

        # Remove commas and common non-digit chars
        s_clean = re.sub(r'[(),]', '', s)
        # Remove trailing non-numeric suffixes like 'SH' or 'PRN'
        s_clean = re.sub(r'[A-Za-z%]+$', '', s_clean).strip()

        try:
            if s_clean == '':
                return None
            # allow floats (e.g., '12.0') -> int
            return int(float(s_clean))
        except Exception:
            return None
