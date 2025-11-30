#!/usr/bin/env python3
"""
Visualizzatore per 13F filings salvati nella cache
Mostra tutti i 13F scaricati per i 50+ hedge funds monitorati
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from collections import defaultdict

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.core.hedge_funds_config import HEDGE_FUNDS_CIK, get_fund_name_by_cik
from src.core.paths import CACHE_DIR


def load_cached_filing(cache_file: Path) -> Dict:
    """Carica un filing dalla cache"""
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except Exception as e:
        print(f"⚠️  Errore caricamento {cache_file.name}: {e}")
        return None


def get_filing_info(filing_data: Dict) -> Dict:
    """Estrae informazioni chiave dal filing"""
    if not filing_data:
        return None
    
    # Estrai informazioni base
    info = {
        'period_of_report': filing_data.get('coverPage', {}).get('reportCalendarOrQuarter', 'N/A'),
        'filing_date': filing_data.get('filingDate', 'N/A'),
        'filer_name': filing_data.get('coverPage', {}).get('filingManager', {}).get('name', 'N/A'),
        'cik': filing_data.get('cik', 'N/A'),
        'total_value': filing_data.get('summaryPage', {}).get('otherIncludedManagersCount', 0),
        'holdings_count': len(filing_data.get('signatureBlock', {}).get('name', [])) if 'signatureBlock' in filing_data else 0,
    }
    
    # Cerca holdings
    if 'informationTable' in filing_data:
        info['holdings_count'] = len(filing_data['informationTable'])
    
    return info


def view_all_cached_filings(filter_cik: str = None, sort_by: str = 'date'):
    """
    Visualizza tutti i 13F filings nella cache
    
    Args:
        filter_cik: Se specificato, mostra solo i filing di questo CIK
        sort_by: 'date', 'fund', 'holdings'
    """
    print("\n" + "="*80)
    print("📂 13F FILINGS CACHE VIEWER")
    print("="*80)
    
    if not CACHE_DIR.exists():
        print(f"\n⚠️  Directory cache non trovata: {CACHE_DIR}")
        return
    
    # Trova tutti i file JSON nella cache
    cache_files = list(CACHE_DIR.glob("*.json"))
    
    if not cache_files:
        print(f"\n⚠️  Nessun filing trovato nella cache: {CACHE_DIR}")
        return
    
    print(f"\n📊 Trovati {len(cache_files)} file nella cache")
    print(f"📁 Path: {CACHE_DIR}\n")
    
    # Carica e organizza i filing
    filings_by_fund = defaultdict(list)
    all_filings = []
    
    for cache_file in cache_files:
        # Estrai CIK dal nome file (formato: 0001234567.json)
        cik = cache_file.stem.zfill(10)  # Normalizza a 10 cifre
        
        # Filtra per CIK se richiesto
        if filter_cik and cik != filter_cik:
            continue
        
        # Carica il filing
        filing_data = load_cached_filing(cache_file)
        if not filing_data:
            continue
        
        # Estrai info
        info = get_filing_info(filing_data)
        if not info:
            continue
        
        # Aggiungi nome del fund
        fund_name = HEDGE_FUNDS_CIK.get(cik, f"Unknown Fund (CIK: {cik})")
        info['fund_name'] = fund_name
        info['cik'] = cik
        info['file_name'] = cache_file.name
        
        filings_by_fund[fund_name].append(info)
        all_filings.append(info)
    
    if not all_filings:
        print("⚠️  Nessun filing valido trovato nella cache")
        return
    
    # Ordina
    if sort_by == 'date':
        all_filings.sort(key=lambda x: x.get('filing_date', ''), reverse=True)
    elif sort_by == 'fund':
        all_filings.sort(key=lambda x: x.get('fund_name', ''))
    elif sort_by == 'holdings':
        all_filings.sort(key=lambda x: x.get('holdings_count', 0), reverse=True)
    
    # Mostra riepilogo per fund
    print("\n" + "-"*80)
    print("📊 RIEPILOGO PER HEDGE FUND")
    print("-"*80)
    
    for fund_name, filings in sorted(filings_by_fund.items()):
        print(f"\n✓ {fund_name}")
        print(f"  └─ {len(filings)} filing(s) in cache")
        
        for filing in sorted(filings, key=lambda x: x.get('filing_date', ''), reverse=True):
            print(f"     • {filing.get('filing_date', 'N/A')} | Period: {filing.get('period_of_report', 'N/A')} | Holdings: {filing.get('holdings_count', 0)}")
    
    # Mostra dettagli completi
    print("\n" + "-"*80)
    print("📋 DETTAGLI COMPLETI")
    print("-"*80)
    
    for idx, filing in enumerate(all_filings, 1):
        print(f"\n{idx}. {filing.get('fund_name', 'N/A')}")
        print(f"   CIK: {filing.get('cik', 'N/A')}")
        print(f"   Filing Date: {filing.get('filing_date', 'N/A')}")
        print(f"   Report Period: {filing.get('period_of_report', 'N/A')}")
        print(f"   Holdings: {filing.get('holdings_count', 0)}")
        print(f"   Cache File: {filing.get('file_name', 'N/A')}")
    
    # Statistiche finali
    print("\n" + "="*80)
    print("📈 STATISTICHE")
    print("="*80)
    print(f"Totale filing in cache: {len(all_filings)}")
    print(f"Hedge funds rappresentati: {len(filings_by_fund)}")
    print(f"Hedge funds monitorati: {len(HEDGE_FUNDS_CIK)}")
    print(f"Coverage: {len(filings_by_fund)}/{len(HEDGE_FUNDS_CIK)} ({len(filings_by_fund)/len(HEDGE_FUNDS_CIK)*100:.1f}%)")
    
    # Mostra fund senza filing
    funds_with_filings = set(filings_by_fund.keys())
    all_funds = set(HEDGE_FUNDS_CIK.values())
    funds_without_filings = all_funds - funds_with_filings
    
    if funds_without_filings:
        print(f"\n⚠️  Fund senza filing in cache ({len(funds_without_filings)}):")
        for fund in sorted(funds_without_filings):
            print(f"   • {fund}")
    
    print("\n" + "="*80)


def view_fund_filings(fund_name_or_cik: str):
    """Visualizza i filing di un singolo fund"""
    # Cerca per CIK o nome
    cik = None
    if fund_name_or_cik.isdigit():
        cik = fund_name_or_cik.zfill(10)
    else:
        # Cerca per nome
        fund_name_lower = fund_name_or_cik.lower()
        for fund_cik, name in HEDGE_FUNDS_CIK.items():
            if fund_name_lower in name.lower():
                cik = fund_cik
                break
    
    if not cik:
        print(f"\n⚠️  Fund non trovato: {fund_name_or_cik}")
        print("\nUsa uno dei seguenti nomi o CIK:")
        for fund_cik, name in sorted(HEDGE_FUNDS_CIK.items(), key=lambda x: x[1]):
            print(f"  • {name} (CIK: {fund_cik})")
        return
    
    view_all_cached_filings(filter_cik=cik)


def main():
    """Entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Visualizza tutti i 13F filings salvati nella cache",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  # Mostra tutti i filing
  python view_cached_filings.py
  
  # Mostra filing di un fund specifico
  python view_cached_filings.py --fund "Michael Burry"
  python view_cached_filings.py --fund 0001649339
  
  # Ordina per holdings
  python view_cached_filings.py --sort holdings
  
  # Lista tutti i fund monitorati
  python view_cached_filings.py --list-funds
        """
    )
    
    parser.add_argument(
        '--fund',
        help='Mostra solo i filing di un fund specifico (nome o CIK)'
    )
    
    parser.add_argument(
        '--sort',
        choices=['date', 'fund', 'holdings'],
        default='date',
        help='Ordina per: date (default), fund, holdings'
    )
    
    parser.add_argument(
        '--list-funds',
        action='store_true',
        help='Lista tutti gli hedge funds monitorati'
    )
    
    args = parser.parse_args()
    
    # Lista fund
    if args.list_funds:
        print("\n" + "="*80)
        print("📊 HEDGE FUNDS MONITORATI")
        print("="*80)
        print(f"\nTotale: {len(HEDGE_FUNDS_CIK)} fund\n")
        
        for idx, (cik, name) in enumerate(sorted(HEDGE_FUNDS_CIK.items(), key=lambda x: x[1]), 1):
            print(f"{idx:2d}. {name}")
            print(f"    CIK: {cik}")
        
        print("\n" + "="*80)
        return
    
    # Visualizza filing
    if args.fund:
        view_fund_filings(args.fund)
    else:
        view_all_cached_filings(sort_by=args.sort)


if __name__ == '__main__':
    main()
