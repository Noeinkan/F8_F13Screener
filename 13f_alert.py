import requests
import feedparser
import json
import time
import logging
import os
import subprocess
import sys
import tempfile
import csv
import re
from datetime import datetime, timedelta
from typing import Set, List, Dict, Optional
from bs4 import BeautifulSoup
from message_bridge import save_message_to_viewer  # Per visualizzatore locale
from hedge_funds_config import HEDGE_FUNDS_CIK  # Configurazione centralizzata
from paths import LAST_CHECK_FILE, REALTIME_REALTIME_HOLDINGS_CSV, REALTIME_LOG_FILE

# ==================== CONFIGURAZIONE ====================
# Carica credenziali da config_secret.py (git-ignored) o variabili d'ambiente
try:
    from config_secret import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SEC_USER_AGENT
    BOT_TOKEN = TELEGRAM_BOT_TOKEN
    CHAT_ID = TELEGRAM_CHAT_ID
    USER_AGENT = SEC_USER_AGENT
except ImportError:
    # Fallback a variabili d'ambiente
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    USER_AGENT = os.getenv('SEC_USER_AGENT')

    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError(
            "ERRORE: Credenziali mancanti!\n"
            "Crea il file config_secret.py (vedi config_secret.template.py)\n"
            "oppure imposta le variabili d'ambiente TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID"
        )

# Configurazioni avanzate
RSS_URL = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=13F-HR&count=100&output=atom'  # 10 per TEST, 100 per PRODUZIONE
# LAST_CHECK_FILE now imported from paths.py
DAILY_SUMMARY_FILE = 'data/realtime/13f_daily_summary.json'  # Tracker per filings filtrati
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
POLL_INTERVAL = 30  # 30 secondi per TEST (cambia in 900 per produzione = 15 minuti)
MAX_RETRIES = 3
RETRY_DELAY = 60  # secondi
# REALTIME_REALTIME_HOLDINGS_CSV now imported from paths.py

# Auto-avvio viewer (True = avvia automaticamente, False = solo programma principale)
AUTO_LAUNCH_VIEWER = True  # Cambia in False per disabilitare l'auto-avvio

# Filtro per CIK: SOLO questi 25 hedge funds value investing saranno monitorati
# Usare CIK è più affidabile del nome perché è univoco e immutabile
# Lista importata da hedge_funds_config.py
HEDGE_FUNDS_CIK_FILTER = HEDGE_FUNDS_CIK

# ==================== SETUP LOGGING ====================
# Gestione logging con fallback se il file è bloccato
log_handlers = [logging.StreamHandler()]

# Prova prima nella directory logs/, poi nel temp
log_locations = [
    REALTIME_LOG_FILE,  # From paths.py
    os.path.join(tempfile.gettempdir(), '13f_alerts.log'),  # Temp directory fallback
]

log_file_created = False

for log_path in log_locations:
    try:
        log_handlers.append(logging.FileHandler(log_path, encoding='utf-8'))
        print(f"Log file creato: {log_path}")
        log_file_created = True
        break
    except PermissionError:
        continue

if not log_file_created:
    # Ultima risorsa: file con timestamp nella temp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    fallback_log = os.path.join(tempfile.gettempdir(), f'13f_alerts_{timestamp}.log')
    try:
        log_handlers.append(logging.FileHandler(fallback_log, encoding='utf-8'))
        print(f"Usando file log di fallback: {fallback_log}")
    except PermissionError:
        print("Impossibile creare file log, solo output console")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

# ==================== FUNZIONI CORE ====================

def launch_telegram_viewer():
    """Avvia il visualizzatore Telegram in una finestra separata"""
    try:
        base_dir = os.path.dirname(__file__) if __file__ else os.getcwd()
        viewer_path = os.path.join(base_dir, 'telegram_viewer.py')
        batch_path = os.path.join(base_dir, 'launch_viewer.bat')
        
        if not os.path.exists(viewer_path):
            logger.warning(f"File {viewer_path} non trovato")
            return False
        
        # Su Windows, prova prima con il batch file (più affidabile)
        if sys.platform == 'win32' and os.path.exists(batch_path):
            try:
                subprocess.Popen(
                    [batch_path],
                    shell=True,
                    cwd=base_dir
                )
                logger.info("Telegram Viewer avviato con successo (via batch)!")
                return True
            except Exception as e:
                logger.warning(f"Fallback da batch, provo metodo diretto: {e}")
        
        # Fallback o altri sistemi operativi
        if sys.platform == 'win32':
            # Su Windows, usa pythonw.exe per evitare finestra console
            python_exe = sys.executable.replace('python.exe', 'pythonw.exe')
            if not os.path.exists(python_exe):
                python_exe = sys.executable
            
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                [python_exe, viewer_path],
                creationflags=DETACHED_PROCESS,
                shell=False,
                cwd=base_dir
            )
        else:
            subprocess.Popen(
                [sys.executable, viewer_path],
                close_fds=True,
                cwd=base_dir
            )
        
        logger.info("Telegram Viewer avviato con successo!")
        return True
        
    except Exception as e:
        logger.error(f"Errore avvio Telegram Viewer: {e}")
        return False

def load_last_seen() -> Set[str]:
    """Carica gli ID dei filing già processati"""
    try:
        with open(LAST_CHECK_FILE, 'r') as f:
            data = json.load(f)
            logger.info(f"Caricati {len(data.get('last_ids', []))} ID dalla cache")

            # Log statistiche se disponibili
            if 'stats' in data:
                stats = data['stats']
                logger.info(f"Statistiche cache: {stats.get('total_checked', 0)} totali | {stats.get('matched', 0)} matched | {stats.get('filtered', 0)} filtrati")
                if stats.get('last_match_date'):
                    logger.info(f"Ultimo match: {stats['last_match_date']}")

            return set(data.get('last_ids', []))
    except FileNotFoundError:
        logger.warning(f"File {LAST_CHECK_FILE} non trovato, creazione nuovo")
        return set()
    except json.JSONDecodeError:
        logger.error("Errore parsing JSON cache, reset cache")
        return set()

def save_last_seen(last_ids: Set[str], stats: Optional[Dict] = None) -> None:
    """Salva gli ID processati (mantiene ultimi 500) con statistiche"""
    try:
        # Carica dati esistenti per preservare statistiche
        existing_stats = {}
        if os.path.exists(LAST_CHECK_FILE):
            try:
                with open(LAST_CHECK_FILE, 'r') as f:
                    old_data = json.load(f)
                    existing_stats = old_data.get('stats', {})
            except:
                pass

        # Aggiorna statistiche
        if stats:
            existing_stats['total_checked'] = existing_stats.get('total_checked', 0) + stats.get('total_checked', 0)
            existing_stats['matched'] = existing_stats.get('matched', 0) + stats.get('matched', 0)
            existing_stats['filtered'] = existing_stats.get('filtered', 0) + stats.get('filtered', 0)

            if stats.get('matched', 0) > 0:
                existing_stats['last_match_date'] = datetime.now().isoformat()

        # Mantieni solo ultimi 500 per evitare file troppo grandi
        ids_to_save = list(last_ids)[-500:] if len(last_ids) > 500 else list(last_ids)

        with open(LAST_CHECK_FILE, 'w') as f:
            json.dump({
                'last_ids': ids_to_save,
                'last_update': datetime.now().isoformat(),
                'stats': existing_stats
            }, f, indent=2)
        logger.info(f"Cache salvata con {len(ids_to_save)} ID")
    except Exception as e:
        logger.error(f"Errore salvataggio cache: {e}")

def send_telegram(message: str, retries: int = MAX_RETRIES) -> bool:
    """Invia notifica Telegram con retry automatico"""
    payload = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    
    for attempt in range(retries):
        try:
            response = requests.post(TELEGRAM_URL, data=payload, timeout=10)
            if response.status_code == 200:
                logger.info("Notifica Telegram inviata con successo")
                return True
            else:
                logger.warning(f"Errore Telegram (tentativo {attempt+1}/{retries}): {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Eccezione Telegram (tentativo {attempt+1}/{retries}): {e}")
        
        if attempt < retries - 1:
            time.sleep(RETRY_DELAY)
    
    logger.error("Fallito invio notifica Telegram dopo tutti i tentativi")
    return False

def fetch_13f_feed(retries: int = MAX_RETRIES) -> feedparser.FeedParserDict:
    """Scarica feed RSS SEC con retry"""
    headers = {'User-Agent': USER_AGENT}
    
    for attempt in range(retries):
        try:
            logger.info(f"Scaricamento feed SEC (tentativo {attempt+1}/{retries})...")
            response = requests.get(RSS_URL, headers=headers, timeout=30)
            
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                logger.info(f"Feed scaricato: {len(feed.entries)} entry trovate")
                return feed
            else:
                logger.warning(f"Errore SEC HTTP {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Eccezione scaricamento feed: {e}")
        
        if attempt < retries - 1:
            time.sleep(RETRY_DELAY)
    
    logger.error("Fallito scaricamento feed dopo tutti i tentativi")
    return feedparser.FeedParserDict()

def should_notify(filer_name: str, filing_link: str) -> tuple[bool, str]:
    """
    Verifica se il filer corrisponde ai filtri tramite CIK.
    Questo è molto più affidabile del matching per nome.

    Args:
        filer_name: Nome del filer (per logging)
        filing_link: URL del filing EDGAR (contiene il CIK)

    Returns:
        (match_found, fund_name): True se il CIK corrisponde, e il nome del fund
    """
    if not HEDGE_FUNDS_CIK_FILTER:
        return True, "ALL"  # Nessun filtro, notifica tutto

    # Estrai CIK dall'URL
    cik = extract_cik_from_link(filing_link)

    # Validazione: controlla se estrazione fallita
    if cik == 'N/A' or not cik:
        logger.warning(f"⚠ CIK extraction failed per {filer_name} - Link: {filing_link}")
        return False, ""

    # Normalizza il CIK (rimuovi zeri leading per matching flessibile)
    cik_normalized = cik.lstrip('0') if cik else ''

    # Cerca il CIK nel filtro (con e senza zeri leading)
    for filter_cik, fund_name in HEDGE_FUNDS_CIK_FILTER.items():
        filter_cik_normalized = filter_cik.lstrip('0')

        if cik == filter_cik or cik_normalized == filter_cik_normalized:
            logger.info(f"✓ MATCH trovato: CIK {cik} → {fund_name}")
            return True, fund_name

    # Nessun match trovato
    logger.debug(f"✗ Nessun match per: {filer_name} (CIK: {cik})")
    return False, ""

def extract_filing_url_from_link(link: str) -> Optional[str]:
    """
    Estrae l'URL del filing detail dalla entry EDGAR.
    Input: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000754811&type=13F-HR&dateb=&owner=exclude&count=100
    Output: URL del filing detail tipo https://www.sec.gov/Archives/edgar/data/754811/000143774925031428/0001437749-25-031428-index.htm
    """
    try:
        # Il link nell'entry RSS è già il link al filing detail se è un link diretto
        # Ma se è un link getcompany, dobbiamo estrarre il CIK e cercare il filing
        if 'Archives/edgar/data' in link:
            return link
        
        # Altrimenti il link nel messaggio dovrebbe essere già quello giusto
        # Per ora ritorniamo il link così com'è
        return link
    except Exception as e:
        logger.error(f"Errore estrazione URL filing: {e}")
        return None

def get_information_table_url(filing_index_url: str) -> Optional[str]:
    """
    Scarica la pagina index del filing e trova l'URL del file Information Table HTML
    """
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(filing_index_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Errore scaricamento index: HTTP {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Metodo 1: Cerca link che contiene "infotable" (forma renderizzata XSLT)
        for link in soup.find_all('a', href=True):
            href = link['href']
            link_text = link.get_text(strip=True).lower()
            
            # Cerca "infotable" nel testo del link o nell'href
            if 'infotable' in link_text or 'infotable' in href.lower():
                # Costruisci URL completo
                if href.startswith('http'):
                    return href
                else:
                    # URL relativo
                    if href.startswith('/'):
                        return f"https://www.sec.gov{href}"
                    else:
                        base_url = '/'.join(filing_index_url.split('/')[:-1])
                        return f"{base_url}/{href}"
        
        # Metodo 2: Cerca nella tabella dei documenti (vecchio formato)
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 3:
                # Cerca "INFORMATION TABLE" nella descrizione
                description = ' '.join([cell.get_text(strip=True).upper() for cell in cells])
                if 'INFORMATION TABLE' in description or 'INFO TABLE' in description:
                    # Trova il link al file HTML
                    for cell in cells:
                        link = cell.find('a', href=True)
                        if link and (link['href'].lower().endswith('.html') or link['href'].lower().endswith('.htm')):
                            href = link['href']
                            if href.startswith('http'):
                                return href
                            else:
                                base_url = '/'.join(filing_index_url.split('/')[:-1])
                                return f"{base_url}/{href}"
        
        logger.warning("Information Table HTML non trovata nella pagina")
        return None
        
    except Exception as e:
        logger.error(f"Errore parsing index page: {e}")
        return None

def parse_information_table(html_url: str) -> List[Dict]:
    """
    Scarica e parsa il file HTML della Information Table
    Ritorna una lista di dict con le holdings
    """
    def _to_int(s: str) -> Optional[int]:
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

    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(html_url, headers=headers, timeout=30)

        if response.status_code != 200:
            logger.error(f"Errore scaricamento Information Table: HTTP {response.status_code}")
            return []

        # Proviamo parse XML/HTML con BeautifulSoup
        # se è XML (url termina con .xml o contiene tag infoTable) gestiamo come XML
        content = response.content
        soup_xml = BeautifulSoup(content, 'xml')
        soup_html = BeautifulSoup(content, 'html.parser')

        holdings = []

        # First: XML style (infoTable / informationTable)
        info_entries = soup_xml.find_all(['infoTable', 'informationTable', 'infotable'])
        if info_entries:
            logger.info(f"Information Table XML trovata: {len(info_entries)} entries")
            for entry in info_entries:
                def gt(tag):
                    t = entry.find(tag)
                    return t.get_text(strip=True) if t else ''

                issuer = gt('nameOfIssuer') or gt('nameofissuer') or gt('NAMEOFISSUER')
                share_class = gt('titleOfClass') or gt('titleofclass')
                cusip = gt('cusip')
                figi = gt('figi')
                value_raw = gt('value')
                # shrsOrPrn can be nested
                sh_qty = ''
                sh_tag = entry.find('shrsOrPrn')
                if sh_tag:
                    # try common nested tag
                    amt = sh_tag.find(['sshPrnamt', 'sshPrnAmt', 'sshpnamt'])
                    if amt:
                        sh_qty = amt.get_text(strip=True)
                    else:
                        sh_qty = sh_tag.get_text(strip=True)
                else:
                    sh_qty = gt('shrsOrPrn') or gt('amount')

                put_call = gt('putCall')
                investment_discretion = gt('investmentDiscretion')
                other_manager = gt('otherManager')

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
                    'value': _to_int(value_raw),
                    'shares_raw': sh_qty,
                    'shares': _to_int(sh_qty),
                    'sh_prn': '',
                    'put_call': put_call,
                    'investment_discretion': investment_discretion,
                    'other_manager': other_manager,
                    'other_managers_raw': other_manager,
                    'voting_authority_sole': _to_int(voting_sole),
                    'voting_authority_shared': _to_int(voting_shared),
                    'voting_authority_none': _to_int(voting_none),
                    'voting_authority_raw': '',
                    'all_columns_raw': ''
                }

                holding['all_columns_raw'] = ' | '.join([str(x) for x in [issuer, share_class, cusip, value_raw, sh_qty] if x])
                if holding['cusip'] or holding['issuer_name']:
                    holdings.append(holding)

            logger.info(f"Parsate {len(holdings)} holdings da XML Information Table")
            return holdings

        # Fallback HTML parsing: cerca tabelle e mappa header dinamicamente
        soup = soup_html
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue

            header_found = False
            header_row_index = -1
            header_labels = []
            for i, row in enumerate(rows[:8]):
                cells = row.find_all(['td', 'th'])
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                norm_texts = [t.upper() for t in cell_texts]
                if any('CUSIP' in text for text in norm_texts) and any('ISSUER' in text or 'NAME' in text for text in norm_texts):
                    header_found = True
                    header_row_index = i
                    header_labels = cell_texts
                    break

            if not header_found:
                continue

            # map headers
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

            header_map = {}
            extras_headers = []
            for idx, raw_label in enumerate(header_labels):
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

            for row in rows[header_row_index + 1:]:
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue
                try:
                    cell_texts = [cell.get_text(strip=True) for cell in cells]
                    if not cell_texts or cell_texts[0].upper() in ['NAME OF ISSUER', 'COLUMN 1', '']:
                        continue
                    holding = {
                        'issuer_name': '', 'share_class': '', 'cusip': '', 'figi': '',
                        'value_x1000': '', 'value': None, 'shares': None, 'shares_raw': '', 'sh_prn': '', 'put_call': '',
                        'investment_discretion': '', 'other_manager': '', 'other_managers_raw': '',
                        'voting_authority_sole': '', 'voting_authority_shared': '', 'voting_authority_none': '',
                        'voting_authority_raw': '', 'all_columns_raw': ''
                    }
                    for idx, val in enumerate(cell_texts):
                        key = header_map.get(idx)
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

                    # numeric conversions
                    holding['value'] = _to_int(holding.get('value_x1000'))
                    holding['shares'] = _to_int(holding.get('shares'))
                    if holding.get('voting_authority_raw') and not (holding.get('voting_authority_sole') or holding.get('voting_authority_shared') or holding.get('voting_authority_none')):
                        parts = re.split(r'[\s/|-]+', holding['voting_authority_raw'])
                        nums = [p for p in parts if p.isdigit()]
                        if len(nums) == 3:
                            holding['voting_authority_sole'] = nums[0]
                            holding['voting_authority_shared'] = nums[1]
                            holding['voting_authority_none'] = nums[2]

                    holding['all_columns_raw'] = holding['all_columns_raw'] or (' | '.join(cell_texts)).strip()
                    if holding['cusip'] or holding['issuer_name']:
                        holdings.append(holding)
                except Exception as e:
                    logger.debug(f"Errore parsing riga HTML: {e}")
                    continue

            if holdings:
                break

        logger.info(f"Parsate {len(holdings)} holdings dalla Information Table (HTML/XML)")
        return holdings

    except Exception as e:
        logger.error(f"Errore parsing Information Table: {e}")
        return []

def save_holdings_to_csv(holdings: List[Dict], filer_name: str, filing_date: str, cik: str, accession_number: str = 'N/A', filing_url: str = ''):
    """
    Salva le holdings nel CSV tracker con nomi colonne migliorati per leggibilità
    """
    try:
        # Determina se il file esiste già
        file_exists = os.path.exists(REALTIME_HOLDINGS_CSV)
        
        # Estrai solo la data (rimuovi timestamp)
        filing_date_clean = filing_date.split('T')[0] if 'T' in filing_date else filing_date
        
        # Nomi colonne più descrittivi e leggibili - ordine ottimizzato per analisi
        fieldnames = [
            'Filing Date',
            'Fund Name',
            'Fund CIK',
            'Accession Number',
            'Filing URL',
            'Name of Issuer',
            'Title of Class',
            'CUSIP',
            'FIGI',
            'Value ($)',
            'Shares/Principal Amount',
            'SH/PRN',
            'Put/Call',
            'Investment Discretion',
            'Other Manager',
            # Raw fallback columns to avoid data loss when forms have different layouts
            'Other Managers (raw)',
            'All Columns (raw)',
            'Voting Authority - Sole',
            'Voting Authority - Shared',
            'Voting Authority - None'
        ]
        
        # Apri in modalità append (crea se non esiste)
        with open(REALTIME_HOLDINGS_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # Scrivi header solo se file nuovo o vuoto
            if not file_exists or os.path.getsize(REALTIME_HOLDINGS_CSV) == 0:
                writer.writeheader()
                logger.info(f"Creato nuovo CSV tracker: {REALTIME_HOLDINGS_CSV}")
            
            # Scrivi ogni holding con mapping dei nomi
            for holding in holdings:
                row = {
                    'Filing Date': filing_date_clean,
                    'Fund Name': filer_name,
                    'Fund CIK': cik,
                    'Accession Number': accession_number,
                    'Filing URL': filing_url,
                    'Name of Issuer': holding.get('issuer_name', ''),
                    'Title of Class': holding.get('share_class', ''),
                    'CUSIP': holding.get('cusip', ''),
                    'FIGI': holding.get('figi', ''),
                    'Value ($)': holding.get('value_x1000', ''),
                    'Shares/Principal Amount': holding.get('shares', ''),
                    'SH/PRN': holding.get('sh_prn', ''),
                    'Put/Call': holding.get('put_call', ''),
                    'Investment Discretion': holding.get('investment_discretion', ''),
                    'Other Manager': holding.get('other_manager', ''),
                    'Other Managers (raw)': holding.get('other_managers_raw', ''),
                    'All Columns (raw)': holding.get('all_columns_raw', ''),
                    'Voting Authority - Sole': holding.get('voting_authority_sole', ''),
                    'Voting Authority - Shared': holding.get('voting_authority_shared', ''),
                    'Voting Authority - None': holding.get('voting_authority_none', '')
                }
                writer.writerow(row)
        
        logger.info(f"Salvate {len(holdings)} holdings nel CSV tracker")
        return True
        
    except Exception as e:
        logger.error(f"Errore salvataggio CSV: {e}")
        # Tenta di creare il file anche in caso di errore
        try:
            logger.warning(f"Tentativo di ricreare il CSV tracker...")
            with open(REALTIME_HOLDINGS_CSV, 'w', newline='', encoding='utf-8') as f:
                fieldnames = [
                    'Filing Date', 'Fund Name', 'Fund CIK', 'Accession Number', 'Filing URL',
                    'Name of Issuer', 'Title of Class', 'CUSIP', 'FIGI',
                    'Value ($)', 'Shares/Principal Amount', 'SH/PRN', 'Put/Call',
                    'Investment Discretion', 'Other Manager',
                    'Other Managers (raw)', 'All Columns (raw)',
                    'Voting Authority - Sole', 'Voting Authority - Shared', 'Voting Authority - None'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            logger.info(f"CSV tracker ricreato con successo")
            # Riprova a salvare
            return save_holdings_to_csv(holdings, filer_name, filing_date, cik, accession_number)
        except Exception as retry_error:
            logger.error(f"Impossibile ricreare CSV: {retry_error}")
            return False

def extract_cik_from_link(link: str) -> str:
    """
    Estrae il CIK dall'URL EDGAR
    """
    try:
        # Pattern: /data/XXXXXX/ or CIK=XXXXXX
        match = re.search(r'(?:CIK=|/data/)(\d+)', link)
        if match:
            return match.group(1)
        return 'N/A'
    except:
        return 'N/A'

def track_filtered_filing(entry_id: str, filer_name: str, cik: str, filing_date: str) -> None:
    """
    Salva un filing filtrato per il daily summary
    """
    try:
        # Carica dati esistenti
        if os.path.exists(DAILY_SUMMARY_FILE):
            with open(DAILY_SUMMARY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}

        # Estrai solo la data (senza timestamp)
        date_key = filing_date.split('T')[0] if 'T' in filing_date else filing_date

        # Inizializza struttura per questa data se non esiste
        if date_key not in data:
            data[date_key] = {
                'count': 0,
                'filings': []
            }

        # Aggiungi filing
        data[date_key]['count'] += 1
        data[date_key]['filings'].append({
            'entry_id': entry_id,
            'filer_name': filer_name,
            'cik': cik,
            'filing_date': filing_date
        })

        # Salva
        with open(DAILY_SUMMARY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        logger.error(f"Errore tracking filtered filing: {e}")

def send_daily_summary() -> bool:
    """
    Invia il summary giornaliero dei filings filtrati
    """
    try:
        if not os.path.exists(DAILY_SUMMARY_FILE):
            logger.info("Nessun summary da inviare")
            return True

        # Carica dati
        with open(DAILY_SUMMARY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data:
            logger.info("Daily summary vuoto")
            return True

        # Trova la data di ieri
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()

        # Se non ci sono dati di ieri, controlla se ci sono dati vecchi da inviare
        dates_to_send = [d for d in data.keys() if d <= yesterday]

        if not dates_to_send:
            logger.info("Nessun summary da inviare per ieri")
            return True

        # Prepara messaggio per ogni data
        for date_key in sorted(dates_to_send):
            date_data = data[date_key]
            count = date_data['count']
            filings = date_data['filings']

            # Conta i filer più frequenti
            filer_counts = {}
            for filing in filings:
                filer = filing['filer_name']
                filer_counts[filer] = filer_counts.get(filer, 0) + 1

            # Top 5 filers
            top_filers = sorted(filer_counts.items(), key=lambda x: x[1], reverse=True)[:5]

            # Formatta messaggio
            message = (
                f"📋 <b>Daily Summary - {date_key}</b>\n\n"
                f"🔍 Filings filtrati: <b>{count}</b>\n"
                f"(Non corrispondono ai 51 hedge funds monitorati)\n\n"
                f"📊 <b>Top Filers:</b>\n"
            )

            for filer, filing_count in top_filers:
                message += f"  • {filer}: {filing_count}\n"

            message += f"\n💡 Questi filing sono stati esclusi perché non fanno parte della watchlist."

            # Invia
            if send_telegram(message):
                logger.info(f"✓ Daily summary inviato per {date_key}")
                # Rimuovi questa data dai dati
                del data[date_key]
            else:
                logger.error(f"✗ Fallito invio daily summary per {date_key}")
                return False

        # Salva dati aggiornati (senza le date già inviate)
        with open(DAILY_SUMMARY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return True

    except Exception as e:
        logger.error(f"Errore invio daily summary: {e}")
        return False

def process_filing_holdings(filing_link: str, filer_name: str, filing_date: str) -> bool:
    """
    Processa un filing: scarica, parsa e salva le holdings
    """
    try:
        logger.info(f"Processamento holdings per: {filer_name}")
        
        # Estrai CIK e Accession Number dall'URL
        # Format: https://www.sec.gov/Archives/edgar/data/1085041/000108504125000006/0001085041-25-000006-index.htm
        cik = extract_cik_from_link(filing_link)
        
        # Estrai Accession Number (pattern: XXXXXXXXXX-XX-XXXXXX)
        accession_match = re.search(r'(\d{10}-\d{2}-\d{6})', filing_link)
        accession_number = accession_match.group(1) if accession_match else 'N/A'
        
        # Ottieni URL della Information Table
        info_table_url = get_information_table_url(filing_link)
        if not info_table_url:
            logger.warning("Information Table URL non trovata")
            return False
        
        logger.info(f"Trovata Information Table: {info_table_url}")
        
        # Parsa la Information Table
        holdings = parse_information_table(info_table_url)
        if not holdings:
            logger.warning("Nessuna holding trovata nel file")
            return False
        
        # Salva nel CSV (passa anche accession_number)
        success = save_holdings_to_csv(holdings, filer_name, filing_date, cik, accession_number, filing_link)
        
        if success:
            logger.info(f"Holdings processate con successo per {filer_name}")
        
        return success
        
    except Exception as e:
        logger.error(f"Errore processamento holdings: {e}")
        return False

def extract_filer_name_from_title(title: str) -> str:
    """
    Estrae il nome del filer dal titolo dell'entry RSS
    Formato: "13F-HR - FUND NAME (CIK) (Filer)"
    """
    try:
        # Rimuovi "13F-HR - " all'inizio
        if '13F-HR - ' in title:
            name_part = title.split('13F-HR - ', 1)[1]
            # Rimuovi la parte " (CIK...)" alla fine
            if '(' in name_part:
                filer_name = name_part.split('(')[0].strip()
                # Verifica che non sia vuoto
                if filer_name and filer_name != '':
                    return filer_name
        # Se non riesce, prova a estrarre da altri pattern
        # Pattern alternativo: cerca tra parentesi per CIK
        if '(' in title and ')' in title:
            # Estrai tutto prima della prima parentesi
            name_before_paren = title.split('(')[0].strip()
            if name_before_paren and '13F-HR' not in name_before_paren:
                return name_before_paren
            # Altrimenti cerca dopo "13F-HR -"
            if '13F-HR -' in name_before_paren:
                name = name_before_paren.replace('13F-HR -', '').strip()
                if name:
                    return name
        
        return title  # Fallback: ritorna il titolo completo
    except Exception as e:
        logger.debug(f"Errore estrazione filer name: {e}")
        return 'Filer Sconosciuto'

def initialize_csv_tracker():
    """
    Inizializza il CSV tracker se non esiste o è corrotto
    """
    try:
        # Verifica se il file esiste
        if not os.path.exists(REALTIME_HOLDINGS_CSV):
            logger.info(f"Creazione nuovo CSV tracker: {REALTIME_HOLDINGS_CSV}")
            # Crea il file con header
            fieldnames = [
                'Filing Date', 'Fund Name', 'Fund CIK', 'Accession Number', 'Filing URL',
                'Name of Issuer', 'Title of Class', 'CUSIP', 'FIGI',
                'Value ($)', 'Shares/Principal Amount', 'SH/PRN', 'Put/Call',
                'Investment Discretion', 'Other Manager',
                'Other Managers (raw)', 'All Columns (raw)',
                'Voting Authority - Sole', 'Voting Authority - Shared', 'Voting Authority - None'
            ]
            with open(REALTIME_HOLDINGS_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            logger.info(f"CSV tracker creato con successo")
            return True
        
        # Verifica se il file è valido (ha almeno l'header)
        if os.path.getsize(REALTIME_HOLDINGS_CSV) == 0:
            logger.warning(f"CSV tracker vuoto, reinizializzazione...")
            # Ricrea l'header
            fieldnames = [
                'Filing Date', 'Fund Name', 'Fund CIK', 'Accession Number', 'Filing URL',
                'Name of Issuer', 'Title of Class', 'CUSIP', 'FIGI',
                'Value ($)', 'Shares/Principal Amount', 'SH/PRN', 'Put/Call',
                'Investment Discretion', 'Other Manager',
                'Other Managers (raw)', 'All Columns (raw)',
                'Voting Authority - Sole', 'Voting Authority - Shared', 'Voting Authority - None'
            ]
            with open(REALTIME_HOLDINGS_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            logger.info(f"CSV tracker reinizializzato")
            return True
        
        # File esiste ed è valido
        # Conta le righe
        with open(REALTIME_HOLDINGS_CSV, 'r', encoding='utf-8') as f:
            row_count = sum(1 for _ in f) - 1  # -1 per l'header
        logger.info(f"CSV tracker trovato: {row_count} holdings esistenti")
        return True
        
    except Exception as e:
        logger.error(f"Errore inizializzazione CSV tracker: {e}")
        return False

def process_feed(feed: feedparser.FeedParserDict, last_seen_ids: Set[str]) -> tuple[List[str], Dict]:
    """Processa le entry del feed e invia notifiche. Ritorna (new_filings, stats)"""
    new_filings = []

    # Contatori per statistiche
    total_checked = 0
    already_seen = 0
    filtered_out = 0
    matched = 0
    sent_successfully = 0
    send_failed = 0

    for entry in feed.entries:
        try:
            entry_id = entry.id
            total_checked += 1

            # Skip se già visto
            if entry_id in last_seen_ids:
                already_seen += 1
                continue

            # Estrai informazioni
            title = entry.get('title', '')
            filer = extract_filer_name_from_title(title)
            filing_date = entry.get('updated', 'Data N/A')
            link = entry.get('link', '')

            # Log ogni filing per debug
            logger.debug(f"Controllo filing: {filer}")

            # Applica filtro per CIK
            is_match, matched_fund = should_notify(filer, link)
            if not is_match:
                # FIX CRITICO: NON aggiungere a new_filings qui!
                # Traccia solo per daily summary
                cik = extract_cik_from_link(link)
                logger.debug(f"Skippato (filtro CIK): {filer} (CIK: {cik})")
                filtered_out += 1

                # Salva per daily summary
                track_filtered_filing(entry_id, filer, cik, filing_date)
                continue

            # Match trovato!
            matched += 1
            logger.info(f"✓ MATCH: {matched_fund} - {filer}")

            # Formatta messaggio
            message = (
                f"🔔 <b>Nuovo Form 13F-HR Rilevato!</b>\n\n"
                f"📊 <b>Fund:</b> {matched_fund}\n"
                f"🏢 <b>Filer:</b> {filer}\n"
                f"📅 <b>Data:</b> {filing_date}\n"
                f"🔗 <b>Link:</b> <a href='{link}'>Visualizza su EDGAR</a>"
            )

            # Processa holdings e salva nel CSV
            logger.info("Inizio download holdings...")
            holdings_success = process_filing_holdings(link, filer, filing_date)

            if holdings_success:
                # Aggiungi info holdings al messaggio
                message += f"\n\n✅ <b>Holdings salvate nel tracker CSV</b>"
                logger.info("Holdings processate e salvate")
            else:
                logger.warning("Holdings non disponibili o errore nel processamento")

            # Invia notifica
            if send_telegram(message):
                logger.info(f"✓ Notifica Telegram inviata con successo")
                new_filings.append(entry_id)
                sent_successfully += 1
            else:
                logger.error(f"✗ Fallita notifica Telegram")
                send_failed += 1
                # Non aggiungiamo a new_filings per ritentare al prossimo ciclo

        except Exception as e:
            logger.error(f"Errore processamento entry: {e}")

    # Log riepilogo ciclo
    logger.info(f"📊 Riepilogo: {total_checked} totali | {already_seen} già visti | {matched} matched | {sent_successfully} inviati | {filtered_out} filtrati | {send_failed} falliti")

    # Prepara statistiche da ritornare
    stats = {
        'total_checked': total_checked - already_seen,  # Solo nuovi filing
        'matched': matched,
        'filtered': filtered_out
    }

    return new_filings, stats

# ==================== MAIN LOOP ====================

def main():
    """Loop principale del programma"""
    logger.info("=== Avvio 13F Alert System v2.0 ===")
    logger.info(f"Intervallo polling: {POLL_INTERVAL}s ({POLL_INTERVAL/60} minuti)")
    logger.info(f"Filtro attivo: SI - {len(HEDGE_FUNDS_CIK_FILTER)} hedge funds monitorati (filtro per CIK)")
    logger.info(f"Hedge funds: {', '.join([name.split('(')[0].strip() for name in list(HEDGE_FUNDS_CIK_FILTER.values())[:5]])}...")
    
    # Avvia Telegram Viewer (se abilitato)
    if AUTO_LAUNCH_VIEWER:
        logger.info("Avvio Telegram Message Viewer...")
        launch_telegram_viewer()
        time.sleep(2)  # Attendi che il viewer si apra
    else:
        logger.info("Auto-avvio viewer disabilitato (avvia manualmente se necessario)")
    
    # Verifica configurazione
    if BOT_TOKEN == 'YOUR_BOT_TOKEN' or CHAT_ID == 'YOUR_CHAT_ID':
        logger.error("ERRORE: Configura BOT_TOKEN e CHAT_ID!")
        return
    
    if USER_AGENT == 'YourName yourname@email.com':
        logger.warning("WARNING: Configura USER_AGENT con il tuo email!")
    
    # Inizializza CSV tracker
    logger.info("Inizializzazione CSV tracker...")
    if not initialize_csv_tracker():
        logger.error("ERRORE: Impossibile inizializzare CSV tracker!")
        logger.warning("Il programma continuerà, ma potrebbero esserci problemi nel salvataggio")
    
    # Carica cache
    last_seen_ids = load_last_seen()

    # Traccia l'ultima data per il daily summary
    last_summary_date = datetime.now().date()

    # Loop infinito
    try:
        while True:
            cycle_start = datetime.now()
            logger.info(f"\n{'='*60}")
            logger.info(f"Controllo alle {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")

            # Controlla se è un nuovo giorno -> invia daily summary
            current_date = cycle_start.date()
            if current_date > last_summary_date:
                logger.info("📋 Nuovo giorno rilevato - invio daily summary...")
                send_daily_summary()
                last_summary_date = current_date

            # Scarica feed
            feed = fetch_13f_feed()

            if feed.entries:
                # Processa entry
                new_filings, stats = process_feed(feed, last_seen_ids)

                # Aggiorna cache con statistiche
                if new_filings:
                    last_seen_ids.update(new_filings)
                    save_last_seen(last_seen_ids, stats)
                    logger.info(f"Processati {len(new_filings)} nuovi filing")
                else:
                    # Salva statistiche anche se non ci sono nuovi filing matched
                    save_last_seen(last_seen_ids, stats)
                    logger.info("Nessun nuovo filing da notificare")
            else:
                logger.warning("Feed vuoto o non disponibile")

            # Attesa prossimo ciclo
            logger.info(f"Prossimo controllo tra {POLL_INTERVAL/60} minuti")
            time.sleep(POLL_INTERVAL)
            
    except KeyboardInterrupt:
        logger.info("\nArresto programma richiesto dall'utente")
    except Exception as e:
        logger.critical(f"Errore critico: {e}", exc_info=True)
    finally:
        logger.info("=== Fine programma ===")

if __name__ == '__main__':
    main()
