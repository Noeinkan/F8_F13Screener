#!/usr/bin/env python3
"""
Script unificato per processare filing 13F-HR storici.

FONTE DATI:
- Lista hedge funds da hedge_funds_config.py (configurazione centralizzata)
- API SEC EDGAR per scoprire filing disponibili
- Parsing HTML SEC per estrarre holdings dettagliate

MODALITÀ:
1. catalog  - Scarica catalogo filing storici da API SEC (veloce, ~5 min per 43 funds)
2. holdings - Estrae holdings dettagliate da filing (lento, ~1 ora per 1000+ filing)
3. full     - Catalogo + Holdings in sequenza (processo completo automatico)

PERIODO: Ultimi 5 anni (dal 2020-01-01 ad oggi)
"""

import requests
import json
import time
import concurrent.futures
import threading
import statistics
from collections import deque
import os
import csv
import re
import argparse
import importlib.util
from datetime import datetime
from typing import List, Dict, Optional
import sys
import logging
import shutil
import multiprocessing
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
class TokenBucketRateLimiter:
    """Token bucket rate limiter per gestire burst di richieste rispettando un limite massimo per secondo."""
    
    def __init__(self, rate: float, capacity: float):
        self.rate = rate  # Richieste per secondo
        self.capacity = capacity  # Capacità massima del bucket
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def _refill(self):
        now = time.time()
        tokens_to_add = (now - self.last_refill) * self.rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now

    def wait(self):
        with self.lock:
            self._refill()
            if self.tokens < 1:
                sleep_time = (1 - self.tokens) / self.rate
                time.sleep(sleep_time)
                self._refill()
            self.tokens -= 1


# Alias per compatibilità
RateLimiter = TokenBucketRateLimiter


# Global rate limiter (inizializzato con valori di default SEC)
rate_limiter = TokenBucketRateLimiter(rate=10, capacity=10)
import os
import csv
import re
import argparse
import importlib.util
from datetime import datetime
from typing import List, Dict, Optional
# Import hedge_funds_config dynamically to avoid editor/linter "could not be resolved" warnings
try:
    spec_h = importlib.util.spec_from_file_location("hedge_config", "hedge_funds_config.py")
    hedge_module = importlib.util.module_from_spec(spec_h)
    spec_h.loader.exec_module(hedge_module)
    HEDGE_FUNDS_CIK = getattr(hedge_module, 'HEDGE_FUNDS_CIK', {})
    get_total_funds = getattr(hedge_module, 'get_total_funds', lambda: len(HEDGE_FUNDS_CIK))
    get_fund_name_by_cik = getattr(hedge_module, 'get_fund_name_by_cik', lambda cik: HEDGE_FUNDS_CIK.get(cik, 'Fund Sconosciuto'))
    get_all_ciks = getattr(hedge_module, 'get_all_ciks', lambda: list(HEDGE_FUNDS_CIK.keys()))
    get_all_fund_names = getattr(hedge_module, 'get_all_fund_names', lambda: list(HEDGE_FUNDS_CIK.values()))
    HAS_HEDGE_CONFIG = True
except Exception as e:
    print(f"⚠️  Modulo hedge_funds_config.py non disponibile: {e}")
    HEDGE_FUNDS_CIK = {}
    def get_total_funds():
        return 0
    def get_fund_name_by_cik(cik: str) -> str:
        return HEDGE_FUNDS_CIK.get(cik, 'Fund Sconosciuto')
    def get_all_ciks() -> list:
        return []
    def get_all_fund_names() -> list:
        return []
    HAS_HEDGE_CONFIG = False
import sys

# Ensure stdout/stderr are UTF-8 to avoid UnicodeEncodeError on Windows consoles
try:
    # Available on Python 3.7+; will raise on unsupported streams/environments
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    # If reconfigure isn't available or fails, ignore and continue
    pass

def validate_hedge_funds_config():
    if not HEDGE_FUNDS_CIK:
        raise ValueError("hedge_funds_config.py è vuoto o non caricato correttamente")
    for cik, name in HEDGE_FUNDS_CIK.items():
        if not re.match(r'^\d+$', cik):
            raise ValueError(f"CIK non valido: {cik}")
        if not name or not isinstance(name, str):
            raise ValueError(f"Nome fondo non valido per CIK {cik}: {name}")

def check_disk_space(path: str, min_space_mb: int = 100):
    total, used, free = shutil.disk_usage(os.path.dirname(path))
    free_mb = free / (1024 * 1024)
    if free_mb < min_space_mb:
        raise RuntimeError(f"Spazio su disco insufficiente: {free_mb:.1f} MB disponibili, richiesto almeno {min_space_mb} MB")

# ==================== CONFIGURAZIONE ====================
USER_AGENT = os.getenv('SEC_USER_AGENT', 'andrea.aita@libero.it')
HEADERS = {'User-Agent': USER_AGENT}
CUTOFF_DATE = '2020-01-01'  # Solo ultimi 5 anni
CATALOG_FILE = 'historical_13f_catalog_5years.json'
HOLDINGS_CSV = '13f_holdings_5years.csv'
PROCESSED_TRACKING_FILE = 'processed_filings_tracking.json'  # Traccia filing già processati
PROCESSING_METRICS_FILE = 'processing_metrics.json'  # Salva avg/median/time samples

# Importa funzioni da 13f_alert.py se disponibile
try:
    spec = importlib.util.spec_from_file_location("alert_module", "13f_alert.py")
    alert_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alert_module)
    process_filing_holdings = alert_module.process_filing_holdings
    HAS_ALERT_MODULE = True
except Exception as e:
    print(f"⚠️  Modulo 13f_alert.py non disponibile: {e}")
    print("   Modalità 'holdings' e 'full' non disponibili.\n")
    HAS_ALERT_MODULE = False

# ==================== MODALITÀ 1: CATALOG ====================

def load_processed_filings() -> Dict[str, set]:
    """
    Carica il tracking dei filing già processati.
    Ritorna un dict: {accession_number: True}
    """
    if not os.path.exists(PROCESSED_TRACKING_FILE):
        return {}
    
    try:
        with open(PROCESSED_TRACKING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('processed_accession_numbers', []))
    except Exception as e:
        print(f"⚠️  Errore caricamento tracking: {e}")
        return set()

def save_processed_filings(processed_set: set) -> None:
    """
    Salva il tracking dei filing processati.
    """
    check_disk_space(PROCESSED_TRACKING_FILE)
    try:
        with open(PROCESSED_TRACKING_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'last_updated': datetime.now().isoformat(),
                'total_processed': len(processed_set),
                'processed_accession_numbers': sorted(list(processed_set))
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️  Errore salvataggio tracking: {e}")

def load_existing_catalog() -> List[Dict]:
    """
    Carica il catalogo esistente se presente.
    """
    if not os.path.exists(CATALOG_FILE):
        return []
    
    try:
        with open(CATALOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('filings', [])
    except Exception as e:
        print(f"⚠️  Errore caricamento catalogo esistente: {e}")
        return []


def load_processing_metrics() -> Dict:
    if not os.path.exists(PROCESSING_METRICS_FILE):
        return {'samples': [], 'avg': None, 'median': None, 'count': 0}
    try:
        with open(PROCESSING_METRICS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'samples': [], 'avg': None, 'median': None, 'count': 0}


def save_processing_metrics(metrics: Dict) -> None:
    try:
        with open(PROCESSING_METRICS_FILE, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️  Errore salvataggio metrics: {e}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.exceptions.RequestException,))
)
def _fetch_13f_filings_from_api(cik: str, fund_name: str, start_date: str = CUTOFF_DATE, end_date: str = None) -> List[Dict]:
    """
    Recupera tutti i filing 13F-HR per un CIK dalla SEC API (senza cache).
    """
    cik_padded = cik.zfill(10)
    api_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    
    print(f"\n 📥 Scaricamento filing per: {fund_name}")
    print(f"   CIK: {cik} | API: {api_url}")
    
    try:
        # Respect global rate limiter if present
        if 'rate_limiter' in globals() and rate_limiter is not None:
            rate_limiter.wait()

        response = requests.get(api_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        recent_filings = data.get('filings', {}).get('recent', {})
        
        if not recent_filings:
            print(f"     ⚠️  Nessun filing trovato")
            return []
        
        filings_13f = []
        
        accession_numbers = recent_filings.get('accessionNumber', [])
        filing_dates = recent_filings.get('filingDate', [])
        forms = recent_filings.get('form', [])
        primary_documents = recent_filings.get('primaryDocument', [])
        
        for i in range(len(forms)):
            if forms[i] not in ['13F-HR', '13F-HR/A']:
                continue
            
            filing_date = filing_dates[i]
            
            if filing_date < start_date:
                continue
            if end_date and filing_date > end_date:
                continue
            
            accession = accession_numbers[i]
            accession_no_dashes = accession.replace('-', '')
            cik_no_leading = cik.lstrip('0')
            
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_leading}/{accession_no_dashes}/{accession}-index.htm"
            
            filings_13f.append({
                'cik': cik,
                'fund_name': fund_name,
                'form': forms[i],
                'filing_date': filing_date,
                'accession_number': accession,
                'primary_document': primary_documents[i] if i < len(primary_documents) else '',
                'filing_url': filing_url
            })
        
        print(f"    ✅ Trovati {len(filings_13f)} filing 13F-HR")
        
        if filings_13f:
            dates = sorted([f['filing_date'] for f in filings_13f], reverse=True)
            if len(dates) <= 5:
                print(f"    📅 Date: {', '.join(dates)}")
            else:
                print(f"    📅 Dal {dates[-1]} al {dates[0]} ({len(dates)} filing)")
        
        return filings_13f
        
    except Exception as e:
        print(f"    ❌ Errore: {e}")
        return []

def get_13f_filings_for_cik(cik: str, fund_name: str, cache_dir: str = "cache", start_date: str = CUTOFF_DATE) -> List[Dict]:
    """
    Recupera tutti i filing 13F-HR per un CIK, con caching locale.
    """
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{cik}.json")
    
    # Prova a caricare dal cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                if cached_data.get('last_updated', 0) > (time.time() - 24*3600):  # Cache valida per 24 ore
                    print(f"    ✅ Caricato da cache: {cache_file}")
                    return cached_data.get('filings', [])
        except Exception as e:
            print(f"    ⚠️ Errore caricamento cache: {e}")
    
    # Scarica da API
    filings = _fetch_13f_filings_from_api(cik, fund_name)
    if filings is not None:  # Anche se vuoto, salva per evitare retry
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'last_updated': time.time(),
                    'filings': filings
                }, f, indent=2, ensure_ascii=False)
            print(f"    💾 Salvato in cache: {cache_file}")
        except Exception as e:
            print(f"    ⚠️ Errore salvataggio cache: {e}")
    return filings

def download_catalog(output_file: str = CATALOG_FILE, incremental: bool = True, quiet: bool = False, start_date: str = CUTOFF_DATE, end_date: str = None) -> List[Dict]:
    """
    MODALITÀ 1: Scarica catalogo completo di filing da API SEC
    Usa la lista hedge funds da hedge_funds_config.py
    Cerca tutti i filing 13F-HR degli ultimi 5 anni
    
    Args:
        output_file: Nome file output
        incremental: Se True, scarica solo filing nuovi non già processati
    """
    print("="*80)
    print("MODALITÀ 1: DOWNLOAD CATALOGO FILING 13F-HR")
    print("="*80)
    print(f"\n📊 Obiettivo: Trovare filing 13F-HR dal {CUTOFF_DATE} ad oggi")
    print(f"🏦 Hedge funds monitorati: {get_total_funds()} (da hedge_funds_config.py)")
    print(f"🌐 Source: SEC EDGAR API (data.sec.gov)")
    
    # Carica tracking filing già processati
    if incremental:
        processed_filings = load_processed_filings()
        existing_catalog = load_existing_catalog()
        print(f"\n♻️  Modalità INCREMENTALE attiva:")
        print(f"   - Filing già catalogati: {len(existing_catalog)}")
        print(f"   - Filing già processati: {len(processed_filings)}")
        print(f"   - Verranno scaricati SOLO i filing nuovi")
    else:
        processed_filings = set()
        existing_catalog = []
        print(f"\n🔄 Modalità COMPLETA: scarica tutti i filing")
    
    print(f"\n⏳ Inizio scansione automatica...")
    print(f"   Rate limit: {rate_limiter.rate} req/sec (token bucket, capacity: {rate_limiter.capacity})")
    print(f"   Tempo stimato: ~{get_total_funds() * (1/rate_limiter.rate) / 60:.1f} minuti\n")
    
    all_filings = existing_catalog.copy()  # Parte dai filing esistenti
    new_filings_count = 0
    skipped_filings_count = 0
    successful_funds = 0
    
    for i, (cik, fund_name) in tqdm(enumerate(HEDGE_FUNDS_CIK.items(), 1), total=get_total_funds(), desc="Downloading catalog", disable=quiet):
        print(f"[{i}/{get_total_funds()}]", end=" ")
        
        filings = get_13f_filings_for_cik(cik, fund_name)
        
        if filings:
            # Filtra solo filing nuovi se in modalità incrementale
            if incremental:
                new_filings = [f for f in filings if f['accession_number'] not in processed_filings]
                skipped = len(filings) - len(new_filings)
                
                if new_filings:
                    all_filings.extend(new_filings)
                    new_filings_count += len(new_filings)
                    print(f"    ✅ {len(new_filings)} NUOVI filing (skipped: {skipped})")
                else:
                    print(f"    ⏭️  Nessun filing nuovo (tutti già processati)")
                
                skipped_filings_count += skipped
            else:
                all_filings.extend(filings)
                new_filings_count += len(filings)
            
            successful_funds += 1
    
    # Salva catalogo aggiornato
    if all_filings:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'total_filings': len(all_filings),
                'new_filings': new_filings_count,
                'skipped_filings': skipped_filings_count,
                'total_funds': len(set([f['cik'] for f in all_filings])),
                'cutoff_date': CUTOFF_DATE,
                'incremental_mode': incremental,
                'filings': all_filings
            }, f, indent=2, ensure_ascii=False)
    
    # Riepilogo
    print("\n" + "="*80)
    print("📊 RIEPILOGO CATALOGO")
    print("="*80)
    print(f"✅ Fondi processati con successo: {successful_funds}/{get_total_funds()}")
    print(f"📄 Totale filing nel catalogo: {len(all_filings)}")
    
    if incremental:
        print(f"🆕 Nuovi filing trovati: {new_filings_count}")
        print(f"⏭️  Filing già esistenti (skipped): {skipped_filings_count}")
    
    if all_filings:
        filings_by_fund = {}
        for filing in all_filings:
            fund = filing['fund_name']
            if fund not in filings_by_fund:
                filings_by_fund[fund] = []
            filings_by_fund[fund].append(filing)
        
        print(f"\n🏆 TOP 10 FONDI PER NUMERO DI FILING:")
        sorted_funds = sorted(filings_by_fund.items(), key=lambda x: len(x[1]), reverse=True)
        for i, (fund, filings) in enumerate(sorted_funds[:10], 1):
            dates = [f['filing_date'] for f in filings]
            date_range = f"{min(dates)} → {max(dates)}" if len(dates) > 1 else dates[0]
            print(f"   {i:2d}. {fund[:45]:45s} | {len(filings):3d} filing | {date_range}")
        
        all_dates = [f['filing_date'] for f in all_filings]
        print(f"\n📅 Range temporale: {min(all_dates)} → {max(all_dates)}")
        print(f"\n💾 Catalogo salvato in: {output_file}")
    
    print("="*80 + "\n")
    
    return all_filings

# ==================== MODALITÀ 2: HOLDINGS ====================

def extract_holdings_from_catalog(catalog_file: str = CATALOG_FILE, workers: Optional[int] = None, auto_confirm: bool = False, use_processes: bool = False, save_interval: int = 5) -> None:
    """
    MODALITÀ 2: Estrae holdings dettagliate da un catalogo esistente
    Processa SOLO i filing non ancora processati (tracking automatico)
    """
    if not HAS_ALERT_MODULE:
        print("❌ Modulo 13f_alert.py non disponibile. Impossibile estrarre holdings.")
        return
    
    print("="*80)
    print("MODALITÀ 2: ESTRAZIONE HOLDINGS DA CATALOGO")
    print("="*80)
    
    # Carica catalogo
    if not os.path.exists(catalog_file):
        print(f"\n❌ File catalogo non trovato: {catalog_file}")
        print("   Esegui prima la modalità 'catalog' o 'full'\n")
        return
    
    with open(catalog_file, 'r', encoding='utf-8') as f:
        catalog_data = json.load(f)
    
    all_filings = catalog_data.get('filings', [])
    
    # Carica tracking filing già processati per holdings
    processed_filings = load_processed_filings()
    
    # Filtra solo filing non ancora processati
    filings_to_process = [f for f in all_filings if f['accession_number'] not in processed_filings]
    already_processed = len(all_filings) - len(filings_to_process)
    
    print(f"\n📊 Filing nel catalogo: {len(all_filings)}")
    print(f"✅ Già processati: {already_processed}")
    print(f"🆕 Da processare: {len(filings_to_process)}")
    print(f"🏦 Da {catalog_data.get('total_funds', 0)} hedge funds")
    print(f"📅 Periodo: dal {catalog_data.get('cutoff_date', 'N/A')}\n")
    
    if len(filings_to_process) == 0:
        print("✅ Tutti i filing sono già stati processati!")
        print("   Nessuna azione necessaria.\n")
        return
    
    print("⚠️  ATTENZIONE: Questo scaricherà holdings dettagliate da SEC.")
    print(f"   Tempo stimato (grezzo): ~{len(filings_to_process) * 0.15 / 60:.1f} minuti con rate limiting.\n")

    # Salta conferma se auto_confirm è abilitato
    if not auto_confirm:
        risposta = input("Vuoi procedere? (s/n): ").lower()
        if risposta != 's':
            print("\n❌ Operazione annullata.")
            return
    else:
        print("✅ Modalità automatica: procedo senza conferma...")

    # Raggruppa filing per fund
    filings_by_fund = {}
    for filing in filings_to_process:
        fund_name = filing.get('fund_name', 'Sconosciuto')
        if fund_name not in filings_by_fund:
            filings_by_fund[fund_name] = []
        filings_by_fund[fund_name].append(filing)
    
    print(f"🏦 Funds da processare: {len(filings_by_fund)}")
    print(f"📄 Filing totali da processare: {len(filings_to_process)}\n")

    # Use workers passed by CLI if provided; default based on CPU and type
    if workers is None:
        workers = min(multiprocessing.cpu_count(), 4) if use_processes else min(multiprocessing.cpu_count() * 2, 8)

    Executor = concurrent.futures.ProcessPoolExecutor if use_processes else concurrent.futures.ThreadPoolExecutor

    print("\n" + "="*80)
    print(f"🔄 INIZIO PROCESSAMENTO (workers={workers}, executor={'processes' if use_processes else 'threads'})")
    print("="*80 + "\n")

    successi = 0
    falliti = 0
    skipped = 0

    # Thread-safe structures
    lock = threading.Lock()

    def worker_process(filing):
        nonlocal successi, falliti, skipped
        local_times = []
        fund_name = filing.get('fund_name', 'Sconosciuto')
        filing_url = filing.get('filing_url', '')
        filing_date = filing.get('filing_date', 'N/A')
        accession_number = filing.get('accession_number', '')

        if not filing_url:
            with lock:
                skipped += 1
            print(f"  ⚠️  Skipped: {fund_name} (URL non trovato)")
            return

        print(f"  📊 {fund_name}")
        print(f"  📅 {filing_date}")
        print(f"  🔗 {filing_url[:60]}...")

        try:
            # Global rate limiter before per-filing processing
            if 'rate_limiter' in globals() and rate_limiter is not None:
                rate_limiter.wait()

            t0 = time.time()
            success = process_filing_holdings(filing_url, fund_name, filing_date)
            t1 = time.time()
            elapsed = t1 - t0
            local_times.append(elapsed)
            with lock:
                if success:
                    print(f"  ✅ Holdings salvate: {accession_number}")
                    successi += 1
                    processed_filings.add(accession_number)
                else:
                    print(f"  ⚠️  Nessuna holding trovata: {accession_number}")
                    falliti += 1
                    processed_filings.add(accession_number)

                # Aggiorna metriche globali ogni filing processato
                if len(local_times) >= 1:
                    try:
                        metrics = load_processing_metrics()
                        samples = metrics.get('samples', [])
                        samples.extend(local_times)
                        samples = samples[-100:]
                        metrics['samples'] = samples
                        if samples:
                            metrics['avg'] = statistics.mean(samples)
                            metrics['median'] = statistics.median(samples)
                        metrics['count'] = metrics.get('count', 0) + len(local_times)
                        save_processing_metrics(metrics)
                    except Exception as e:
                        print(f"⚠️ Errore aggiornamento metrics: {e}")
                    local_times.clear()
        except Exception as e:
            with lock:
                falliti += 1
            print(f"  ❌ Errore processing {accession_number}: {e}")

        # Small sleep to avoid bursting requests (per-worker throttle)
        time.sleep(0.15)

    # Processa per fund invece che per filing individuale
    fund_index = 0
    for fund_name, fund_filings in filings_by_fund.items():
        fund_index += 1
        print(f"\n🏦 [{fund_index}/{len(filings_by_fund)}] Processamento fund: {fund_name}")
        print(f"   📄 Filing da processare: {len(fund_filings)}")
        
        # Parallel execution per fund
        with Executor(max_workers=workers) as executor:
            futures = [executor.submit(worker_process, filing) for filing in fund_filings]
            
            # Wait for all filings of this fund to complete
            for fut in concurrent.futures.as_completed(futures):
                pass  # Just wait for completion
        
        # Salva tracking a intervalli o alla fine
        if fund_index % save_interval == 0 or fund_index == len(filings_by_fund):
            print(f"   💾 Salvataggio tracking intermedio (fund {fund_index}/{len(filings_by_fund)})...")
            with lock:
                save_processed_filings(processed_filings)
            print(f"   ✅ Tracking aggiornato (totale processati: {len(processed_filings)})")
    
    # Salva tracking finale (ridondante ma sicuro)
    save_processed_filings(processed_filings)
    
    # Salva tracking finale
    save_processed_filings(processed_filings)
    
    # Riepilogo finale
    print("\n" + "="*80)
    print("📊 RIEPILOGO FINALE")
    print("="*80)
    print(f"✅ Successi:      {successi}")
    print(f"❌ Falliti:       {falliti}")
    print(f"⚠️  Skipped:       {skipped}")
    print(f"📊 Totale:        {len(filings_to_process)}")
    print(f"💾 Tracking salvato in: {PROCESSED_TRACKING_FILE}")
    print("="*80)
    
    if successi > 0:
        csv_path = alert_module.HOLDINGS_CSV if HAS_ALERT_MODULE else HOLDINGS_CSV
        if os.path.exists(csv_path):
            print(f"\n✅ CSV tracker aggiornato: {csv_path}")
            print(f"   📊 Puoi aprirlo con Excel o Python/Pandas per analizzarlo")
        else:
            print(f"\n⚠️  CSV non trovato (probabilmente nessuna holding valida)")
    
    print("\n🎉 Processamento completato!\n")

# ==================== MODALITÀ 3: FULL ====================

def process_full_pipeline(workers: Optional[int] = None, use_processes: bool = False, save_interval: int = 5, start_date: str = CUTOFF_DATE, end_date: str = None, quiet: bool = False):
    """
    MODALITÀ 3: Esegue tutto il pipeline (catalog + holdings)
    Completamente automatico: usa solo hedge_funds_config.py
    """
    print("="*80)
    print("MODALITÀ 3: PIPELINE COMPLETO (CATALOG + HOLDINGS)")
    print("="*80)
    print("\n🎯 Questo eseguirà AUTOMATICAMENTE:")
    print(f"   1. Download catalogo filing per {get_total_funds()} hedge funds da API SEC")
    print(f"   2. Estrazione holdings dettagliate per ogni filing trovato")
    print(f"\n📋 Fonte dati: hedge_funds_config.py ({get_total_funds()} funds)")
    print(f"📅 Periodo: ultimi 5 anni (dal {CUTOFF_DATE})")
    print(f"\n⏱️  TEMPO STIMATO:")
    print(f"   - Fase 1 (Catalog): ~{get_total_funds() * 0.11 / 60:.1f} minuti")
    print(f"   - Fase 2 (Holdings): variabile (dipende da quanti filing vengono trovati)")
    print(f"   - Totale: ~30-90 minuti per processo completo\n")
    
    risposta = input("Vuoi procedere con il pipeline completo? (s/n): ").lower()
    if risposta != 's':
        print("\n❌ Operazione annullata.")
        return
    
    # Fase 1: Catalog
    print("\n" + "="*80)
    print("FASE 1/2: DOWNLOAD CATALOGO")
    print("="*80 + "\n")
    
    filings = download_catalog()
    
    if not filings:
        print("\n❌ Nessun filing trovato. Pipeline interrotto.")
        return
    
    # Pausa tra le fasi
    print("\n⏸️  Pausa di 2 secondi prima di iniziare l'estrazione holdings...")
    time.sleep(2)
    
    # Fase 2: Holdings
    print("\n" + "="*80)
    print("FASE 2/2: ESTRAZIONE HOLDINGS")
    print("="*80 + "\n")
    
    # Use CLI-provided workers if available via global args (main will call with workers)
    extract_holdings_from_catalog(workers=workers, auto_confirm=True)
    
    print("\n" + "="*80)
    print("🎉 PIPELINE COMPLETO TERMINATO")
    print("="*80 + "\n")

# ==================== MAIN ====================

def main():
    parser = argparse.ArgumentParser(
        description='Script unificato per processare filing 13F-HR storici dagli ultimi 5 anni',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
FONTE DATI:
  - Lista {get_total_funds()} hedge funds da hedge_funds_config.py
  - API SEC EDGAR per scoperta filing
  - Periodo: dal {CUTOFF_DATE} ad oggi (ultimi 5 anni)

MODALITÀ DISPONIBILI:
  catalog   - Scarica catalogo filing da API SEC (veloce, ~5 min per {get_total_funds()} funds)
  holdings  - Estrae holdings dettagliate da filing nel catalogo (lento, ~1-2 ore)
  full      - Esegue catalog + holdings automaticamente (processo completo)

ESEMPI:
  python process_historical_13f.py catalog
  python process_historical_13f.py holdings
  python process_historical_13f.py full

OUTPUT:
  - historical_13f_catalog_5years.json  (modalità catalog/full)
  - 13f_holdings_5years.csv             (modalità holdings/full)

NOTES:
  Lo script usa SOLO hedge_funds_config.py come fonte.
  Non dipende da Telegram o altri file esterni.
  Scarica automaticamente tutti i filing disponibili negli ultimi 5 anni.
        """
    )
    
    parser.add_argument(
        'mode',
        choices=['catalog', 'holdings', 'full', 'benchmark'],
        help='Modalità di esecuzione'
    )
    
    parser.add_argument(
        '--catalog-file',
        default=CATALOG_FILE,
        help=f'File catalogo (default: {CATALOG_FILE})'
    )
    
    parser.add_argument(
        '--full-refresh',
        action='store_true',
        help='Disabilita modalità incrementale e scarica tutto da zero'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='Numero di worker concorrenti per la modalità holdings (default: 1)'
    )

    parser.add_argument(
        '--sample-size',
        dest='sample_size',
        type=int,
        default=5,
        help='Dimensione del campione per la modalità benchmark (default: 5)'
    )

    parser.add_argument(
        '--yes',
        action='store_true',
        help='Salta la conferma interattiva e procedi automaticamente'
    )
    
    parser.add_argument(
        '--rate',
        dest='rate',
        type=float,
        default=10,
        help='Rate limite richieste per secondo (default: 10 per SEC guidelines)'
    )
    
    parser.add_argument(
        '--capacity',
        dest='capacity',
        type=float,
        default=10,
        help='Capacità burst del rate limiter (default: 10)'
    )
    
    parser.add_argument(
        '--use-processes',
        action='store_true',
        help='Usa ProcessPoolExecutor invece di ThreadPoolExecutor per operazioni CPU-intensive'
    )
    
    parser.add_argument(
        '--save-interval',
        type=int,
        default=5,
        help='Salva tracking ogni N fondi processati (default: 5)'
    )
    
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Output minimo (solo errori e riepilogo)'
    )
    
    parser.add_argument(
        '--start-date',
        default=CUTOFF_DATE,
        help='Data di inizio (YYYY-MM-DD, default: 2020-01-01)'
    )
    
    parser.add_argument(
        '--end-date',
        default=datetime.now().strftime('%Y-%m-%d'),
        help='Data di fine (YYYY-MM-DD, default: oggi)'
    )
    
    args = parser.parse_args()
    
    # Banner iniziale
    print("\n" + "="*80)
    print("🏦 PROCESSAMENTO FILING 13F-HR STORICI (ULTIMI 5 ANNI)")
    print("="*80)
    print(f"📅 Periodo: dal {CUTOFF_DATE} ad oggi")
    print(f"🏢 Hedge funds: {get_total_funds()} (da hedge_funds_config.py)")
    print(f"⚙️  Modalità: {args.mode.upper()}")
    print(f"🌐 Fonte: SEC EDGAR API + HTML parsing")
    
    if args.full_refresh:
        print(f"🔄 FULL REFRESH: Scarica tutto da zero (ignora tracking)")
    else:
        print(f"♻️  INCREMENTALE: Scarica solo filing nuovi (tracking attivo)")
    
    print("="*80 + "\n")
    
    # Esegui modalità richiesta
    # Setup global rate limiter
    global rate_limiter
    rate_limiter = TokenBucketRateLimiter(rate=args.rate, capacity=args.capacity)
    if args.mode == 'catalog':
        download_catalog(args.catalog_file, incremental=not args.full_refresh)
    
    elif args.mode == 'holdings':
        # Use the workers provided via CLI
        extract_holdings_from_catalog(args.catalog_file, workers=args.workers, auto_confirm=args.yes)
    
    elif args.mode == 'full':
        process_full_pipeline(workers=args.workers)
    elif args.mode == 'benchmark':
        # Quick benchmark to estimate average time per filing
        def run_benchmark(sample_size: int = args.sample_size):
            if not os.path.exists(args.catalog_file):
                print(f"❌ Catalog file not found: {args.catalog_file}")
                return
            with open(args.catalog_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            filings = data.get('filings', [])
            if not filings:
                print("❌ No filings in catalog to benchmark")
                return

            sample = filings[:sample_size]
            times = []
            print(f"Benchmarking {len(sample)} filings (senza salvare risultati)...")
            for i, filing in enumerate(sample, 1):
                url = filing.get('filing_url')
                fund = filing.get('fund_name')
                date = filing.get('filing_date')
                print(f"[{i}/{len(sample)}] {fund} {date} -> {url[:60]}...")
                t0 = time.time()
                try:
                    # Call process_filing_holdings but don't persist side-effects if possible
                    process_filing_holdings(url, fund, date)
                except Exception as e:
                    print(f"  Errore durante benchmark: {e}")
                t1 = time.time()
                elapsed = t1 - t0
                times.append(elapsed)
                print(f"  Tempo: {elapsed:.1f}s")

            if times:
                avg = statistics.mean(times)
                med = statistics.median(times)
                print(f"\nRisultati benchmark: avg={avg:.1f}s, median={med:.1f}s per filing")
                est_total_seconds = avg * len(filings)
                print(f"Stima basata su avg: ~{est_total_seconds/3600:.1f} ore per {len(filings)} filing")
                # Salva le metriche aggregate
                metrics = load_processing_metrics()
                # Append samples but limit stored samples to last 100
                metrics_samples = metrics.get('samples', [])
                metrics_samples.extend(times)
                metrics_samples = metrics_samples[-100:]
                metrics['samples'] = metrics_samples
                metrics['avg'] = statistics.mean(metrics_samples)
                metrics['median'] = statistics.median(metrics_samples)
                metrics['count'] = metrics.get('count', 0) + len(times)
                save_processing_metrics(metrics)

        run_benchmark()

if __name__ == '__main__':
    main()
