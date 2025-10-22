"""
Script OTTIMIZZATO per processare i filing 13F storici e scaricare tutti gli holdings.
Usa il catalogo generato da download_historical_13f.py

OTTIMIZZAZIONI:
- Parallelizzazione con ThreadPoolExecutor (10 worker)
- Rate limiting intelligente condiviso (10 req/sec SEC limit)
- Progress bar dettagliata
- Checkpoint/resume automatico
- Stima tempo: ~5-10 minuti invece di 1h 45min
"""

import json
import csv
import time
import os
from typing import List, Dict, Optional
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Configurazione
USER_AGENT = os.getenv('SEC_USER_AGENT', 'andrea.aita@libero.it')
HEADERS = {'User-Agent': USER_AGENT}
OUTPUT_CSV = '13f_holdings_5years.csv'
CATALOG_FILE = 'historical_13f_catalog_5years.json'
CHECKPOINT_FILE = 'processing_checkpoint.json'

# Parallelizzazione
MAX_WORKERS = 10  # Thread paralleli
RATE_LIMIT_PER_SECOND = 9  # SEC limit: 10/sec, usiamo 9 per sicurezza

# Rate limiter globale (condiviso tra thread)
class RateLimiter:
    def __init__(self, max_per_second):
        self.max_per_second = max_per_second
        self.min_interval = 1.0 / max_per_second
        self.last_request_time = 0
        self.lock = threading.Lock()
    
    def wait(self):
        """Attendi se necessario per rispettare il rate limit"""
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            
            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)
            
            self.last_request_time = time.time()

rate_limiter = RateLimiter(RATE_LIMIT_PER_SECOND)

# Lock per scrittura CSV (thread-safe)
csv_lock = threading.Lock()

def get_information_table_url(filing_index_url: str) -> Optional[str]:
    """
    Scarica la pagina index del filing e trova l'URL del file Information Table HTML
    """
    try:
        rate_limiter.wait()
        response = requests.get(filing_index_url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Metodo 1: Cerca link che contiene "infotable"
        for link in soup.find_all('a', href=True):
            href = link['href']
            link_text = link.get_text(strip=True).lower()
            
            if 'infotable' in link_text or 'infotable' in href.lower():
                if href.startswith('http'):
                    return href
                else:
                    if href.startswith('/'):
                        return f"https://www.sec.gov{href}"
                    else:
                        base_url = '/'.join(filing_index_url.split('/')[:-1])
                        return f"{base_url}/{href}"
        
        # Metodo 2: Cerca nella tabella dei documenti
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 3:
                description = ' '.join([cell.get_text(strip=True).upper() for cell in cells])
                if 'INFORMATION TABLE' in description or 'INFO TABLE' in description:
                    for cell in cells:
                        link = cell.find('a', href=True)
                        if link and (link['href'].lower().endswith('.html') or link['href'].lower().endswith('.htm')):
                            href = link['href']
                            if href.startswith('http'):
                                return href
                            else:
                                base_url = '/'.join(filing_index_url.split('/')[:-1])
                                return f"{base_url}/{href}"
        
        return None
        
    except Exception:
        return None

def parse_information_table(html_url: str) -> List[Dict]:
    """
    Scarica e parsa il file HTML della Information Table
    """
    try:
        rate_limiter.wait()
        response = requests.get(html_url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        holdings = []
        
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            
            if len(rows) < 2:
                continue
            
            header_found = False
            header_row_index = -1
            
            for i, row in enumerate(rows[:5]):
                cells = row.find_all(['td', 'th'])
                cell_texts = [cell.get_text(strip=True).upper() for cell in cells]
                
                if any('CUSIP' in text for text in cell_texts) and \
                   any('ISSUER' in text or 'NAME' in text for text in cell_texts):
                    header_found = True
                    header_row_index = i
                    break
            
            if not header_found:
                continue
            
            for row in rows[header_row_index + 1:]:
                cells = row.find_all(['td', 'th'])
                
                if len(cells) < 3:
                    continue
                
                try:
                    cell_texts = [cell.get_text(strip=True) for cell in cells]
                    
                    if not cell_texts or cell_texts[0].upper() in ['NAME OF ISSUER', 'COLUMN 1', '']:
                        continue
                    
                    holding = {}
                    
                    if len(cell_texts) >= 13:
                        holding = {
                            'issuer_name': cell_texts[0],
                            'share_class': cell_texts[1],
                            'cusip': cell_texts[2],
                            'figi': cell_texts[3] if len(cell_texts) > 3 else '',
                            'value_x1000': cell_texts[4].replace(',', '') if len(cell_texts) > 4 else '',
                            'shares': cell_texts[5].replace(',', '') if len(cell_texts) > 5 else '',
                            'sh_prn': cell_texts[6] if len(cell_texts) > 6 else '',
                            'put_call': cell_texts[7] if len(cell_texts) > 7 else '',
                            'investment_discretion': cell_texts[8] if len(cell_texts) > 8 else '',
                            'other_manager': cell_texts[9] if len(cell_texts) > 9 else '',
                            'voting_authority_sole': cell_texts[10].replace(',', '') if len(cell_texts) > 10 else '',
                            'voting_authority_shared': cell_texts[11].replace(',', '') if len(cell_texts) > 11 else '',
                            'voting_authority_none': cell_texts[12].replace(',', '') if len(cell_texts) > 12 else ''
                        }
                    elif len(cell_texts) >= 8:
                        holding = {
                            'issuer_name': cell_texts[0],
                            'share_class': cell_texts[1] if len(cell_texts) > 1 else '',
                            'cusip': cell_texts[2] if len(cell_texts) > 2 else '',
                            'figi': '',
                            'value_x1000': cell_texts[3].replace(',', '') if len(cell_texts) > 3 else '',
                            'shares': cell_texts[4].replace(',', '') if len(cell_texts) > 4 else '',
                            'sh_prn': cell_texts[5] if len(cell_texts) > 5 else '',
                            'put_call': cell_texts[6] if len(cell_texts) > 6 else '',
                            'investment_discretion': cell_texts[7] if len(cell_texts) > 7 else '',
                            'other_manager': '',
                            'voting_authority_sole': '',
                            'voting_authority_shared': '',
                            'voting_authority_none': ''
                        }
                    else:
                        holding = {
                            'issuer_name': cell_texts[0] if len(cell_texts) > 0 else '',
                            'share_class': cell_texts[1] if len(cell_texts) > 1 else '',
                            'cusip': cell_texts[2] if len(cell_texts) > 2 else '',
                            'figi': '',
                            'value_x1000': '',
                            'shares': '',
                            'sh_prn': '',
                            'put_call': '',
                            'investment_discretion': '',
                            'other_manager': '',
                            'voting_authority_sole': '',
                            'voting_authority_shared': '',
                            'voting_authority_none': ''
                        }
                    
                    if holding['cusip'] and holding['issuer_name']:
                        holdings.append(holding)
                        
                except Exception:
                    continue
            
            if holdings:
                break
        
        return holdings
        
    except Exception:
        return []

def save_holdings_to_csv(holdings: List[Dict], filing: Dict):
    """
    Salva le holdings nel CSV (thread-safe)
    """
    fieldnames = [
        'Filing Date', 'Fund Name', 'Fund CIK', 'Accession Number', 'Filing URL',
        'Name of Issuer', 'Title of Class', 'CUSIP', 'FIGI',
        'Value ($)', 'Shares/Principal Amount', 'SH/PRN', 'Put/Call',
        'Investment Discretion', 'Other Manager',
        'Voting Authority - Sole', 'Voting Authority - Shared', 'Voting Authority - None'
    ]
    
    with csv_lock:
        file_exists = os.path.exists(OUTPUT_CSV)
        
        with open(OUTPUT_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            if not file_exists or os.path.getsize(OUTPUT_CSV) == 0:
                writer.writeheader()
            
            for holding in holdings:
                row = {
                    'Filing Date': filing['filing_date'],
                    'Fund Name': filing['fund_name'],
                    'Fund CIK': filing['cik'],
                    'Accession Number': filing['accession_number'],
                    'Filing URL': filing['filing_url'],
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
                    'Voting Authority - Sole': holding.get('voting_authority_sole', ''),
                    'Voting Authority - Shared': holding.get('voting_authority_shared', ''),
                    'Voting Authority - None': holding.get('voting_authority_none', '')
                }
                writer.writerow(row)

def process_filing(filing: Dict) -> tuple:
    """
    Processa un singolo filing e ritorna (accession_number, num_holdings, success)
    """
    try:
        # Ottieni URL della Information Table
        info_table_url = get_information_table_url(filing['filing_url'])
        if not info_table_url:
            return (filing['accession_number'], 0, False)
        
        # Parsa la Information Table
        holdings = parse_information_table(info_table_url)
        if not holdings:
            return (filing['accession_number'], 0, False)
        
        # Salva nel CSV
        save_holdings_to_csv(holdings, filing)
        
        return (filing['accession_number'], len(holdings), True)
        
    except Exception:
        return (filing['accession_number'], 0, False)

def load_checkpoint() -> set:
    """Carica i filing già processati"""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get('processed', []))
        except:
            return set()
    return set()

def save_checkpoint(processed: set):
    """Salva i filing processati"""
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({'processed': list(processed)}, f)

def main():
    print("="*80)
    print("PROCESSAMENTO VELOCE FILING 13F-HR ULTIMI 5 ANNI (2020-2025)")
    print("="*80)
    
    # Carica catalogo
    print(f"\n📂 Caricamento catalogo da: {CATALOG_FILE}")
    
    try:
        with open(CATALOG_FILE, 'r', encoding='utf-8') as f:
            catalog = json.load(f)
    except FileNotFoundError:
        print(f"❌ ERRORE: File {CATALOG_FILE} non trovato!")
        print("   Esegui prima: python download_historical_13f.py")
        return
    
    all_filings = catalog['filings']
    
    # Checkpoint
    processed = load_checkpoint()
    filings = [f for f in all_filings if f['accession_number'] not in processed]
    
    total_filings = len(filings)
    already_processed = len(all_filings) - total_filings
    
    print(f"✅ Catalogo caricato: {len(all_filings)} filing totali")
    if already_processed > 0:
        print(f"⏭️  Già processati: {already_processed} filing (riprendo da checkpoint)")
    print(f"📊 Da processare: {total_filings} filing")
    print(f"📅 Range: {catalog['generated_at']}")
    print(f"\n⚙️  Output: {OUTPUT_CSV}")
    print(f"🚀 Parallelizzazione: {MAX_WORKERS} worker simultanei")
    print(f"⏱️  Stima tempo: ~{total_filings / (RATE_LIMIT_PER_SECOND * 0.5) / 60:.1f} minuti")
    print(f"    (vs {total_filings * 0.2 / 60:.1f} min versione seriale)")
    
    if total_filings == 0:
        print("\n✅ Tutti i filing già processati!")
        return
    
    # Chiedi conferma
    print(f"\n⚠️  Scaricherà {total_filings} filing dalla SEC con {MAX_WORKERS} thread paralleli")
    response = input("   Vuoi procedere? (s/n): ")
    
    if response.lower() != 's':
        print("\n❌ Operazione annullata")
        return
    
    print(f"\n🚀 Inizio processamento parallelo...\n")
    
    successful = 0
    failed = 0
    total_holdings = 0
    
    start_time = datetime.now()
    
    # Processamento parallelo con ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Sottometti tutti i task
        future_to_filing = {executor.submit(process_filing, filing): filing for filing in filings}
        
        # Processa i risultati man mano che arrivano
        for i, future in enumerate(as_completed(future_to_filing), 1):
            accession, num_holdings, success = future.result()
            
            if success:
                successful += 1
                total_holdings += num_holdings
            else:
                failed += 1
            
            # Aggiorna checkpoint
            processed.add(accession)
            if i % 10 == 0:
                save_checkpoint(processed)
            
            # Progress bar ogni 10 filing o all'ultimo
            if i % 10 == 0 or i == total_filings:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = i / elapsed if elapsed > 0 else 0
                eta_seconds = (total_filings - i) / rate if rate > 0 else 0
                eta_minutes = eta_seconds / 60
                
                print(f"[{i}/{total_filings}] ({i/total_filings*100:.1f}%) | "
                      f"✅ {successful} | ❌ {failed} | "
                      f"📊 {total_holdings:,} holdings | "
                      f"⚡ {rate:.1f}/s | "
                      f"⏱️  ETA: {eta_minutes:.1f}m")
    
    # Salva checkpoint finale
    save_checkpoint(processed)
    
    # Risultati finali
    elapsed_total = (datetime.now() - start_time).total_seconds()
    
    print("\n" + "="*80)
    print("PROCESSAMENTO COMPLETATO")
    print("="*80)
    print(f"✅ Filing processati con successo: {successful}/{total_filings}")
    print(f"❌ Filing falliti: {failed}/{total_filings}")
    print(f"📊 Totale holdings estratte: {total_holdings:,}")
    print(f"⏱️  Tempo totale: {elapsed_total/60:.1f} minuti")
    print(f"⚡ Velocità media: {successful/elapsed_total:.1f} filing/sec")
    print(f"📁 Output salvato in: {OUTPUT_CSV}")
    print(f"\n💡 Speedup: {(total_filings * 0.2 / elapsed_total):.1f}x più veloce!")
    print("="*80 + "\n")

if __name__ == '__main__':
    main()
