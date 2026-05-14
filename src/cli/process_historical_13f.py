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
import sqlite3
from collections import deque
import os
import csv
import re
import argparse
import importlib.util
from datetime import datetime
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, cast
import sys
import logging
import shutil
import multiprocessing
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from tqdm import tqdm
from src.core.paths import (
    CATALOG_FILE,
    HISTORICAL_HOLDINGS_CSV,
    PROCESSED_TRACKING_FILE,
    PROCESSING_METRICS_FILE,
    PROCESSING_CHECKPOINT_FILE,
    FILING_CACHE_DIR,
    HOLDINGS_DB_FILE,
)
from src.core.parser import HoldingsParser
from src.core.sec_client import SECClient
from src.core.storage import Storage

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
csv_write_lock = threading.Lock()


FundLookup = Callable[[str], str]
FundListLookup = Callable[[], List[str]]
FundCountLookup = Callable[[], int]
HEDGE_FUNDS_CIK: Dict[str, str] = {}


def _default_get_total_funds() -> int:
    return len(HEDGE_FUNDS_CIK)


def _default_get_fund_name_by_cik(cik: str) -> str:
    return HEDGE_FUNDS_CIK.get(cik, 'Fund Sconosciuto')


def _default_get_all_ciks() -> List[str]:
    return list(HEDGE_FUNDS_CIK.keys())


def _default_get_all_fund_names() -> List[str]:
    return list(HEDGE_FUNDS_CIK.values())


get_total_funds: FundCountLookup = _default_get_total_funds
get_fund_name_by_cik: FundLookup = _default_get_fund_name_by_cik
get_all_ciks: FundListLookup = _default_get_all_ciks
get_all_fund_names: FundListLookup = _default_get_all_fund_names


# Import hedge_funds_config dynamically to avoid editor/linter "could not be resolved" warnings
try:
    spec_h = importlib.util.spec_from_file_location("hedge_config", "src/core/hedge_funds_config.py")
    if spec_h is None or spec_h.loader is None:
        raise ImportError("Impossibile caricare hedge_funds_config.py")

    hedge_module = importlib.util.module_from_spec(spec_h)
    spec_h.loader.exec_module(hedge_module)
    typed_hedge_module = cast(ModuleType, hedge_module)

    HEDGE_FUNDS_CIK = cast(Dict[str, str], getattr(typed_hedge_module, 'HEDGE_FUNDS_CIK', {}))
    get_total_funds = cast(
        FundCountLookup,
        getattr(typed_hedge_module, 'get_total_funds', _default_get_total_funds),
    )
    get_fund_name_by_cik = cast(
        FundLookup,
        getattr(typed_hedge_module, 'get_fund_name_by_cik', _default_get_fund_name_by_cik),
    )
    get_all_ciks = cast(
        FundListLookup,
        getattr(typed_hedge_module, 'get_all_ciks', _default_get_all_ciks),
    )
    get_all_fund_names = cast(
        FundListLookup,
        getattr(typed_hedge_module, 'get_all_fund_names', _default_get_all_fund_names),
    )
    HAS_HEDGE_CONFIG = True
except Exception as e:
    print(f"⚠️  Modulo hedge_funds_config.py non disponibile: {e}")
    HEDGE_FUNDS_CIK = {}
    HAS_HEDGE_CONFIG = False

# Ensure stdout/stderr are UTF-8 to avoid UnicodeEncodeError on Windows consoles
try:
    # Available on Python 3.7+; will raise on unsupported streams/environments
    stdout_reconfigure = cast(Any, getattr(sys.stdout, 'reconfigure', None))
    stderr_reconfigure = cast(Any, getattr(sys.stderr, 'reconfigure', None))
    if callable(stdout_reconfigure):
        stdout_reconfigure(encoding='utf-8')
    if callable(stderr_reconfigure):
        stderr_reconfigure(encoding='utf-8')
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
    dir_path = os.path.dirname(path) or "."
    total, used, free = shutil.disk_usage(dir_path)
    free_mb = free / (1024 * 1024)
    if free_mb < min_space_mb:
        raise RuntimeError(f"Spazio su disco insufficiente: {free_mb:.1f} MB disponibili, richiesto almeno {min_space_mb} MB")

# ==================== CONFIGURAZIONE ====================
USER_AGENT = os.getenv('SEC_USER_AGENT', 'andrea.aita@libero.it')
HEADERS = {'User-Agent': USER_AGENT}
CUTOFF_DATE = '2020-01-01'  # Solo ultimi 5 anni
# CATALOG_FILE, HISTORICAL_HOLDINGS_CSV, PROCESSED_TRACKING_FILE, PROCESSING_METRICS_FILE imported from paths.py

# Initialize parser and SEC client
parser = HoldingsParser(USER_AGENT)
sec_client = SECClient(USER_AGENT)

def save_holdings_to_csv(holdings: List[Dict], fund_name: str, filing_date: str, cik: str, accession_number: str, filing_url: str) -> bool:
    """Save holdings to CSV tracker"""
    try:
        filing_date_clean = filing_date.split('T')[0] if 'T' in filing_date else filing_date
        
        fieldnames = [
            'Filing Date', 'Fund Name', 'Fund CIK', 'Accession Number', 'Filing URL',
            'Name of Issuer', 'Title of Class', 'CUSIP', 'FIGI',
            'Value ($)', 'Shares/Principal Amount', 'SH/PRN', 'Put/Call',
            'Investment Discretion', 'Other Manager',
            'Other Managers (raw)', 'All Columns (raw)',
            'Voting Authority - Sole', 'Voting Authority - Shared', 'Voting Authority - None'
        ]
        
        with csv_write_lock:
            file_exists = os.path.exists(HISTORICAL_HOLDINGS_CSV)
            with open(HISTORICAL_HOLDINGS_CSV, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                if not file_exists or os.path.getsize(HISTORICAL_HOLDINGS_CSV) == 0:
                    writer.writeheader()

                for holding in holdings:
                    row = {
                        'Filing Date': filing_date_clean,
                        'Fund Name': fund_name,
                        'Fund CIK': cik,
                        'Accession Number': accession_number,
                        'Filing URL': filing_url,
                        'Name of Issuer': holding.get('issuer_name', ''),
                        'Title of Class': holding.get('share_class', ''),
                        'CUSIP': holding.get('cusip', ''),
                        'FIGI': holding.get('figi', ''),
                        'Value ($)': holding.get('value_x1000', ''),
                        'Shares/Principal Amount': holding.get('shares_raw', '') or holding.get('shares', ''),
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
        
        return True
    except Exception as e:
        print(f"Error saving CSV: {e}")
        return False

def reset_holdings_outputs() -> None:
    """Remove historical holdings artifacts so a full refresh can rebuild them."""
    for file_path in (HISTORICAL_HOLDINGS_CSV, PROCESSED_TRACKING_FILE):
        if os.path.exists(file_path):
            os.remove(file_path)


def process_filing_holdings(
    filing_url: str,
    fund_name: str,
    filing_date: str,
    storage: Optional[Storage] = None,
    persist_csv: bool = True,
    persist_db: bool = False,
) -> bool:
    """Process a filing: download, parse and save holdings"""
    try:
        # Extract CIK and Accession Number
        cik = sec_client.extract_cik_from_link(filing_url)
        accession_number = sec_client.extract_accession_number(filing_url)
        
        # Get Information Table URL
        info_table_url = parser.get_information_table_url(filing_url)
        if not info_table_url:
            return False
        
        # Parse holdings
        holdings = parser.parse_information_table(info_table_url)
        if not holdings:
            return False

        persisted = False

        if persist_csv:
            persisted = save_holdings_to_csv(
                holdings,
                fund_name,
                filing_date,
                cik,
                accession_number,
                filing_url,
            ) or persisted

        if persist_db:
            db_storage = storage or Storage(Path(HOLDINGS_DB_FILE))
            saved_count = db_storage.save_holdings(
                holdings,
                fund_name,
                cik,
                filing_date,
                accession_number,
                filing_url,
            )
            persisted = saved_count > 0 or persisted

        return persisted
        
    except Exception as e:
        print(f"Error processing holdings: {e}")
        return False

# ==================== MODALITÀ 1: CATALOG ====================

def load_processed_filings() -> set:
    """
    Carica il tracking dei filing già processati.
    Ritorna un set di accession numbers.
    
    Se il CSV non esiste ma il tracking sì, resetta il tracking
    per forzare la ricreazione del CSV da zero.
    """
    # Se il CSV non esiste, ignora il tracking esistente
    if not os.path.exists(HISTORICAL_HOLDINGS_CSV):
        if os.path.exists(PROCESSED_TRACKING_FILE):
            print(f"⚠️  CSV non trovato ma tracking esiste - verrà resettato")
            print(f"   CSV atteso: {HISTORICAL_HOLDINGS_CSV}")
            print(f"   Il CSV verrà ricreato da zero\n")
        return set()
    
    if not os.path.exists(PROCESSED_TRACKING_FILE):
        return set()
    
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
def _fetch_13f_filings_from_api(
    cik: str,
    fund_name: str,
    start_date: str = CUTOFF_DATE,
    end_date: Optional[str] = None,
) -> List[Dict]:
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

def get_13f_filings_for_cik(
    cik: str,
    fund_name: str,
    cache_dir: Optional[str] = None,
    start_date: str = CUTOFF_DATE,
    end_date: Optional[str] = None,
) -> List[Dict]:
    if cache_dir is None:
        cache_dir = FILING_CACHE_DIR
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
    filings = _fetch_13f_filings_from_api(cik, fund_name, start_date, end_date)
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

def download_catalog(
    output_file: str = CATALOG_FILE,
    incremental: bool = True,
    quiet: bool = False,
    start_date: str = CUTOFF_DATE,
    end_date: Optional[str] = None,
) -> List[Dict]:
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
        
        filings = get_13f_filings_for_cik(cik, fund_name, "cache", start_date, end_date)
        
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

def extract_holdings_from_catalog(
    catalog_file: str = CATALOG_FILE,
    workers: Optional[int] = None,
    auto_confirm: bool = False,
    use_processes: bool = False,
    save_interval: int = 5,
    incremental: bool = True,
    save_db: bool = False,
) -> None:
    """
    MODALITÀ 2: Estrae holdings dettagliate da un catalogo esistente
    Processa SOLO i filing non ancora processati (tracking automatico)
    """
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
    
    if incremental:
        processed_filings = load_processed_filings()
    else:
        reset_holdings_outputs()
        processed_filings = set()
    
    # Filtra solo filing non ancora processati
    filings_to_process = [f for f in all_filings if f['accession_number'] not in processed_filings]
    already_processed = len(all_filings) - len(filings_to_process)
    
    print(f"\n📊 Filing nel catalogo: {len(all_filings)}")
    print(f"✅ Già processati: {already_processed}")
    print(f"🆕 Da processare: {len(filings_to_process)}")
    print(f"🏦 Da {catalog_data.get('total_funds', 0)} hedge funds")
    print(f"📅 Periodo: dal {catalog_data.get('cutoff_date', 'N/A')}\n")

    if not incremental:
        print("🔄 Full refresh holdings: tracking e CSV storico ricreati da zero")

    storage: Optional[Storage] = Storage(Path(HOLDINGS_DB_FILE)) if save_db else None
    if storage is not None:
        if not incremental:
            deleted_rows = storage.clear_holdings()
            print(f"🧹 SQLite holdings azzerate: {deleted_rows:,} righe rimosse")
        print(f"🗄️  Salvataggio SQLite attivo: {HOLDINGS_DB_FILE}")
    
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
            success = process_filing_holdings(
                filing_url,
                fund_name,
                filing_date,
                storage=storage,
                persist_csv=True,
                persist_db=save_db,
            )
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
        if os.path.exists(HISTORICAL_HOLDINGS_CSV):
            print(f"\n✅ CSV tracker aggiornato: {HISTORICAL_HOLDINGS_CSV}")
            print(f"   📊 Puoi aprirlo con Excel o Python/Pandas per analizzarlo")
        else:
            print(f"\n⚠️  CSV non trovato (probabilmente nessuna holding valida)")
    
    print("\n🎉 Processamento completato!\n")

# ==================== MODALITÀ 3: FULL ====================

def process_full_pipeline(
    workers: Optional[int] = None,
    use_processes: bool = False,
    save_interval: int = 5,
    start_date: str = CUTOFF_DATE,
    end_date: Optional[str] = None,
    quiet: bool = False,
    auto_confirm: bool = False,
    incremental: bool = True,
    save_db: bool = False,
):
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
    
    # Salta conferma se auto_confirm è abilitato
    if not auto_confirm:
        risposta = input("Vuoi procedere con il pipeline completo? (s/n): ").lower()
        if risposta != 's':
            print("\n❌ Operazione annullata.")
            return
    else:
        print("✅ Modalità automatica: procedo senza conferma...")
    
    # Fase 1: Catalog
    print("\n" + "="*80)
    print("FASE 1/2: DOWNLOAD CATALOGO")
    print("="*80 + "\n")
    
    filings = download_catalog(
        incremental=incremental,
        quiet=quiet,
        start_date=start_date,
        end_date=end_date,
    )
    
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
    extract_holdings_from_catalog(
        workers=workers,
        auto_confirm=True,
        use_processes=use_processes,
        save_interval=save_interval,
        incremental=incremental,
        save_db=save_db,
    )
    
    print("\n" + "="*80)
    print("🎉 PIPELINE COMPLETO TERMINATO")
    print("="*80 + "\n")


def export_dashboard_csvs(output_dir: str, scope: str = 'both') -> int:
    """Export SQLite-backed CSV files for server-side use and dashboard downloads."""
    db_path = Path(HOLDINGS_DB_FILE)
    if not db_path.exists():
        print(f"❌ Database non trovato: {db_path}")
        print("   Esegui prima la modalità 'holdings' o 'full' con --save-db.\n")
        return 1

    storage = Storage(db_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("="*80)
    print("MODALITÀ EXPORT: CSV DAL DATABASE SQLITE")
    print("="*80)
    print(f"🗄️  Database: {db_path}")
    print(f"📁 Output directory: {output_path}")
    print(f"📦 Scope: {scope}")

    exports = []
    if scope in ('all', 'both'):
        full_path = output_path / 'f8_13f_all_holdings.csv'
        full_rows = storage.export_holdings_to_csv(full_path)
        exports.append((full_path, full_rows, 'holdings completi'))

    if scope in ('latest', 'both'):
        latest_path = output_path / 'f8_13f_latest_snapshot.csv'
        latest_rows = storage.export_latest_snapshot_to_csv(latest_path)
        exports.append((latest_path, latest_rows, 'ultimo snapshot per fondo'))

    wrote_any = False
    for file_path, row_count, label in exports:
        if row_count > 0:
            wrote_any = True
            print(f"✅ {label}: {row_count:,} righe -> {file_path}")
        else:
            print(f"⚠️  Nessun dato esportato per {label}")

    if not wrote_any:
        print("\n⚠️  Il database esiste ma non contiene ancora holdings esportabili.\n")
        return 1

    print("\n🎉 Export completato.\n")
    return 0


def get_missing_value_filings(limit: Optional[int] = None) -> List[Dict[str, str]]:
    """Return one row per accession whose saved holdings still have no market values."""
    db_path = Path(HOLDINGS_DB_FILE)
    if not db_path.exists():
        return []

    query = """
        SELECT
            accession_number,
            MAX(fund_name) AS fund_name,
            MAX(filing_date) AS filing_date,
            MAX(filing_url) AS filing_url,
            COUNT(*) AS row_count
        FROM holdings
        WHERE TRIM(COALESCE(accession_number, '')) <> ''
          AND TRIM(COALESCE(filing_url, '')) <> ''
        GROUP BY accession_number
        HAVING SUM(
            CASE
                WHEN value_usd IS NOT NULL OR TRIM(COALESCE(value_x1000, '')) <> '' THEN 1
                ELSE 0
            END
        ) = 0
        ORDER BY MAX(filing_date) DESC, MAX(fund_name)
    """

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()

    filings = [dict(row) for row in rows]
    return filings[:limit] if limit is not None else filings


def backfill_missing_values_in_db(
    workers: int = 1,
    auto_confirm: bool = False,
    limit: Optional[int] = None,
) -> int:
    """Re-parse existing accessions whose holdings were saved without value fields."""
    db_path = Path(HOLDINGS_DB_FILE)
    if not db_path.exists():
        print(f"❌ Database non trovato: {db_path}")
        return 1

    filings_to_process = get_missing_value_filings(limit=limit)
    total_missing = len(get_missing_value_filings()) if limit is not None else len(filings_to_process)

    print("="*80)
    print("MODALITÀ BACKFILL VALUES")
    print("="*80)
    print(f"🗄️  Database: {db_path}")
    print(f"🔎 Filing con valori mancanti trovati: {total_missing}")
    if limit is not None:
        print(f"📌 Limite esecuzione corrente: {len(filings_to_process)}")

    if not filings_to_process:
        print("✅ Nessun filing da correggere.\n")
        return 0

    if not auto_confirm:
        risposta = input("Vuoi procedere con il backfill dei valori mancanti? (s/n): ").lower()
        if risposta != 's':
            print("\n❌ Operazione annullata.")
            return 1
    else:
        print("✅ Modalità automatica: procedo senza conferma...")

    storage = Storage(db_path)
    successi = 0
    falliti = 0
    lock = threading.Lock()

    def worker_process(filing: Dict[str, str]) -> None:
        nonlocal successi, falliti
        accession_number = filing['accession_number']
        fund_name = filing['fund_name']
        filing_date = filing['filing_date']
        filing_url = filing['filing_url']

        try:
            if 'rate_limiter' in globals() and rate_limiter is not None:
                rate_limiter.wait()

            success = process_filing_holdings(
                filing_url,
                fund_name,
                filing_date,
                storage=storage,
                persist_csv=False,
                persist_db=True,
            )
            with lock:
                if success:
                    successi += 1
                    print(f"  ✅ Backfilled: {accession_number} | {fund_name}")
                else:
                    falliti += 1
                    print(f"  ⚠️  Nessuna holding salvata: {accession_number} | {fund_name}")
        except Exception as e:
            with lock:
                falliti += 1
            print(f"  ❌ Errore backfill {accession_number}: {e}")

        time.sleep(0.15)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(worker_process, filing) for filing in filings_to_process]
        for fut in concurrent.futures.as_completed(futures):
            fut.result()

    remaining_missing = len(get_missing_value_filings())

    print("\n" + "="*80)
    print("📊 RIEPILOGO BACKFILL VALUES")
    print("="*80)
    print(f"✅ Successi: {successi}")
    print(f"❌ Falliti:  {falliti}")
    print(f"🔎 Filing ancora senza valori: {remaining_missing}")
    print("="*80 + "\n")
    return 0 if falliti == 0 else 1

# ==================== MAIN ====================

def setup_logging(quiet=False):
    """Setup logging configuration"""
    if quiet:
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    parser = argparse.ArgumentParser(
        description='Script unificato per processare filing 13F-HR storici dagli ultimi 5 anni',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
FONTE DATI:
  - Lista {get_total_funds()} hedge funds da hedge_funds_config.py
  - API SEC EDGAR per scoperta filing
  - Periodo: ultimi 5 anni (dal 2020-01-01 ad oggi)

MODALITÀ DISPONIBILI:
  catalog   - Scarica catalogo filing da API SEC (veloce, ~5 min per {get_total_funds()} funds)
  holdings  - Estrae holdings dettagliate da filing nel catalogo (lento, ~1-2 ore)
  full      - Esegue catalog + holdings automaticamente (processo completo)
    export    - Esporta CSV dal database SQLite usato dal dashboard
    backfill-values - Ricarica nel DB i filing già salvati senza colonna value

ESEMPI:
  python process_historical_13f.py catalog
  python process_historical_13f.py holdings
  python process_historical_13f.py full
    python process_historical_13f.py export --export-scope both
    python process_historical_13f.py backfill-values --yes --workers 2

OUTPUT:
  - historical_13f_catalog_5years.json  (modalità catalog/full)
  - 13f_holdings_5years.csv             (modalità holdings/full)
    - 13f_holdings.db                     (opzionale, con --save-db per il dashboard)
    - f8_13f_all_holdings.csv             (modalità export)
    - f8_13f_latest_snapshot.csv          (modalità export)

NOTES:
  Lo script usa SOLO hedge_funds_config.py come fonte.
  Non dipende da Telegram o altri file esterni.
  Scarica automaticamente tutti i filing disponibili negli ultimi 5 anni.
        """
    )
    
    parser.add_argument(
        'mode',
        choices=['catalog', 'holdings', 'full', 'benchmark', 'export', 'backfill-values'],
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
        '--save-db',
        action='store_true',
        help='Salva holdings anche nel database SQLite usato dal dashboard'
    )

    parser.add_argument(
        '--output-dir',
        default=os.path.dirname(HISTORICAL_HOLDINGS_CSV),
        help='Directory di output per la modalità export'
    )

    parser.add_argument(
        '--export-scope',
        choices=['all', 'latest', 'both'],
        default='both',
        help='Tipologia di export per la modalità export (default: both)'
    )

    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limita il numero di filing da processare nella modalità backfill-values'
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
        default='2020-01-01',
        help='Data di inizio (YYYY-MM-DD, default: 2020-01-01)'
    )
    
    parser.add_argument(
        '--end-date',
        default=datetime.now().strftime('%Y-%m-%d'),
        help='Data di fine (YYYY-MM-DD, default: oggi)'
    )
    
    args = parser.parse_args()
    
    # Setup
    validate_hedge_funds_config()
    setup_logging(quiet=args.quiet)
    CUTOFF_DATE = args.start_date
    
    # Banner iniziale
    print("\n" + "="*80)
    print("🏦 PROCESSAMENTO FILING 13F-HR STORICI")
    print("="*80)
    print(f"📅 Periodo: dal {args.start_date} al {args.end_date}")
    print(f"🏢 Hedge funds: {get_total_funds()} (da hedge_funds_config.py)")
    print(f"⚙️  Modalità: {args.mode.upper()}")
    print(f"🌐 Fonte: SEC EDGAR API + HTML parsing")
    print(f"🗄️  Seed dashboard DB: {'SI' if args.save_db else 'NO'}")
    
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
        download_catalog(args.catalog_file, incremental=not args.full_refresh, quiet=args.quiet, start_date=args.start_date, end_date=args.end_date)
    
    elif args.mode == 'holdings':
        # Use the workers provided via CLI
        extract_holdings_from_catalog(
            args.catalog_file,
            workers=args.workers,
            auto_confirm=args.yes,
            use_processes=args.use_processes,
            save_interval=args.save_interval,
            incremental=not args.full_refresh,
            save_db=args.save_db,
        )
    
    elif args.mode == 'full':
        process_full_pipeline(
            workers=args.workers,
            use_processes=args.use_processes,
            save_interval=args.save_interval,
            start_date=args.start_date,
            end_date=args.end_date,
            quiet=args.quiet,
            auto_confirm=args.yes,
            incremental=not args.full_refresh,
            save_db=args.save_db,
        )
    elif args.mode == 'export':
        raise SystemExit(export_dashboard_csvs(args.output_dir, scope=args.export_scope))
    elif args.mode == 'backfill-values':
        raise SystemExit(
            backfill_missing_values_in_db(
                workers=args.workers,
                auto_confirm=args.yes,
                limit=args.limit,
            )
        )
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
                    process_filing_holdings(url, fund, date, persist_csv=False, persist_db=False)
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
