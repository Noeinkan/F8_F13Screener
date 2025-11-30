"""
13F Holdings parser with robust HTML/XML parsing
"""
import re
import logging
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class HoldingsParser:
    """Parser for 13F Information Table"""

    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    def get_information_table_url(self, filing_index_url: str) -> Optional[str]:
        """
        Download filing index page and find Information Table HTML URL

        Args:
            filing_index_url: URL of the filing index page

        Returns:
            URL of the Information Table or None if not found
        """
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(filing_index_url, headers=headers, timeout=30)

            if response.status_code != 200:
                logger.error(f"Errore scaricamento index: HTTP {response.status_code}")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')

            # Method 1: Search for link containing "infotable" (XSLT rendered form)
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text(strip=True).lower()

                # Search "infotable" in link text or href
                if 'infotable' in link_text or 'infotable' in href.lower():
                    # Build complete URL
                    if href.startswith('http'):
                        logger.debug(f"Found infotable (method 1): {href}")
                        return href
                    else:
                        # Relative URL
                        if href.startswith('/'):
                            full_url = f"https://www.sec.gov{href}"
                            logger.debug(f"Found infotable (method 1): {full_url}")
                            return full_url
                        else:
                            base_url = '/'.join(filing_index_url.split('/')[:-1])
                            full_url = f"{base_url}/{href}"
                            logger.debug(f"Found infotable (method 1): {full_url}")
                            return full_url

            # Method 2: Search in document table (old format)
            for row in soup.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) >= 3:
                    # Search "INFORMATION TABLE" in description
                    description = ' '.join([cell.get_text(strip=True).upper() for cell in cells])
                    if 'INFORMATION TABLE' in description or 'INFO TABLE' in description:
                        # Find link to HTML file
                        for cell in cells:
                            link = cell.find('a', href=True)
                            if link and (link['href'].lower().endswith('.html') or link['href'].lower().endswith('.htm')):
                                href = link['href']
                                if href.startswith('http'):
                                    logger.debug(f"Found infotable (method 2): {href}")
                                    return href
                                else:
                                    base_url = '/'.join(filing_index_url.split('/')[:-1])
                                    full_url = f"{base_url}/{href}"
                                    logger.debug(f"Found infotable (method 2): {full_url}")
                                    return full_url

            # Method 3: Search for XML file (form13fInfoTable.xml)
            base_url = '/'.join(filing_index_url.split('/')[:-1])
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text(strip=True).lower()
                
                # Look for XML files with "table" or "13f" in name
                if href.lower().endswith('.xml') and ('table' in href.lower() or '13f' in href.lower() or 'info' in href.lower()):
                    if href.startswith('http'):
                        logger.debug(f"Found XML table (method 3): {href}")
                        return href
                    else:
                        if href.startswith('/'):
                            full_url = f"https://www.sec.gov{href}"
                        else:
                            full_url = f"{base_url}/{href}"
                        logger.debug(f"Found XML table (method 3): {full_url}")
                        return full_url

            logger.warning(f"Information Table HTML non trovata nella pagina: {filing_index_url}")
            # Log available files for debugging
            all_files = [link.get('href') for link in soup.find_all('a', href=True) if link.get('href', '').endswith(('.xml', '.html', '.htm'))]
            if all_files:
                logger.debug(f"Available files: {', '.join(all_files[:10])}")
            return None

        except Exception as e:
            logger.error(f"Errore parsing index page: {e}")
            return None

    def parse_information_table(self, html_url: str) -> List[Dict]:
        """
        Download and parse Information Table HTML file

        Args:
            html_url: URL of the Information Table

        Returns:
            List of holdings dictionaries
        """
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(html_url, headers=headers, timeout=30)

            if response.status_code != 200:
                logger.error(f"Errore scaricamento Information Table: HTTP {response.status_code}")
                return []

            # Try parsing XML/HTML with BeautifulSoup
            content = response.content
            soup_xml = BeautifulSoup(content, 'xml')
            soup_html = BeautifulSoup(content, 'html.parser')

            # First: Try XML style parsing
            holdings = self._parse_xml_format(soup_xml)
            if holdings:
                logger.info(f"Parsate {len(holdings)} holdings da XML Information Table")
                return holdings

            # Fallback: HTML table parsing
            holdings = self._parse_html_format(soup_html)
            logger.info(f"Parsate {len(holdings)} holdings dalla Information Table (HTML)")
            return holdings

        except Exception as e:
            logger.error(f"Errore parsing Information Table: {e}")
            return []

    def _parse_xml_format(self, soup_xml: BeautifulSoup) -> List[Dict]:
        """Parse XML format Information Table"""
        holdings = []

        info_entries = soup_xml.find_all(['infoTable', 'informationTable', 'infotable'])
        if not info_entries:
            return []

        logger.info(f"Information Table XML trovata: {len(info_entries)} entries")

        for entry in info_entries:
            def get_tag_text(tag_name):
                tag = entry.find(tag_name)
                return tag.get_text(strip=True) if tag else ''

            issuer = get_tag_text('nameOfIssuer') or get_tag_text('nameofissuer') or get_tag_text('NAMEOFISSUER')
            share_class = get_tag_text('titleOfClass') or get_tag_text('titleofclass')
            cusip = get_tag_text('cusip')
            figi = get_tag_text('figi')
            value_raw = get_tag_text('value')

            # shrsOrPrn can be nested
            sh_qty = ''
            sh_tag = entry.find('shrsOrPrn')
            if sh_tag:
                amt = sh_tag.find(['sshPrnamt', 'sshPrnAmt', 'sshpnamt'])
                if amt:
                    sh_qty = amt.get_text(strip=True)
                else:
                    sh_qty = sh_tag.get_text(strip=True)
            else:
                sh_qty = get_tag_text('shrsOrPrn') or get_tag_text('amount')

            put_call = get_tag_text('putCall')
            investment_discretion = get_tag_text('investmentDiscretion')
            other_manager = get_tag_text('otherManager')

            # VotingAuthority may be structured
            voting_sole = ''
            voting_shared = ''
            voting_none = ''
            va = entry.find('votingAuthority') or entry.find('votingauthority')
            if va:
                s = va.find(['sole', 'Sole'])
                if s:
                    voting_sole = s.get_text(strip=True)
                sh = va.find(['shared', 'Shared'])
                if sh:
                    voting_shared = sh.get_text(strip=True)
                n = va.find(['none', 'None'])
                if n:
                    voting_none = n.get_text(strip=True)

            holding = {
                'issuer_name': issuer,
                'share_class': share_class,
                'cusip': cusip,
                'figi': figi,
                'value_x1000': value_raw,
                'value': self._to_int(value_raw),
                'shares_raw': sh_qty,
                'shares': self._to_int(sh_qty),
                'sh_prn': '',
                'put_call': put_call,
                'investment_discretion': investment_discretion,
                'other_manager': other_manager,
                'other_managers_raw': other_manager,
                'voting_authority_sole': self._to_int(voting_sole),
                'voting_authority_shared': self._to_int(voting_shared),
                'voting_authority_none': self._to_int(voting_none),
                'voting_authority_raw': '',
                'all_columns_raw': ' | '.join([str(x) for x in [issuer, share_class, cusip, value_raw, sh_qty] if x])
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
            'value_x1000': ['VALUE', 'MARKET VALUE'],
            'shares': ['SHRS OR PRN AMT', 'AMOUNT', 'SHARE', 'SHRS'],
            'sh_prn': ['SH/PRN'],
            'put_call': ['PUT/CALL'],
            'investment_discretion': ['INVESTMENT DISCRETION', 'DISCRETION'],
            'other_manager': ['OTHER', 'OTHER MANAGER', 'OTHER MANAGERS'],
            'voting_authority_sole': ['VOTING AUTH. - SOLE', 'SOLE VOTING', 'VOTING SOLE'],
            'voting_authority_shared': ['VOTING AUTH. - SHARED', 'SHARED VOTING', 'VOTING SHARED'],
            'voting_authority_none': ['VOTING AUTH. - NONE', 'NONE VOTING', 'VOTING NONE'],
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

                    for key, variants in canonical_keys.items():
                        for v in variants:
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
                        else:
                            holding[key] = clean_val

            # Numeric conversions
            holding['value'] = self._to_int(holding.get('value_x1000'))
            holding['shares'] = self._to_int(holding.get('shares'))

            # Parse voting authority if combined
            if holding.get('voting_authority_raw') and not (holding.get('voting_authority_sole') or holding.get('voting_authority_shared') or holding.get('voting_authority_none')):
                parts = re.split(r'[\s/|-]+', holding['voting_authority_raw'])
                nums = [p for p in parts if p.isdigit()]
                if len(nums) == 3:
                    holding['voting_authority_sole'] = nums[0]
                    holding['voting_authority_shared'] = nums[1]
                    holding['voting_authority_none'] = nums[2]

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
