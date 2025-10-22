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
import os
import csv
import re
import argparse
import importlib.util
from datetime import datetime
from typing import List, Dict, Optional
from hedge_funds_config import HEDGE_FUNDS_CIK, get_total_funds, get_fund_name_by_cik

# ==================== CONFIGURAZIONE ====================
USER_AGENT = os.getenv('SEC_USER_AGENT', 'andrea.aita@libero.it')
HEADERS = {'User-Agent': USER_AGENT}
CUTOFF_DATE = '2020-01-01'  # Solo ultimi 5 anni
CATALOG_FILE = 'historical_13f_catalog_5years.json'
HOLDINGS_CSV = '13f_holdings_5years.csv'

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

def get_13f_filings_for_cik(cik: str, fund_name: str) -> List[Dict]:
    """
    Recupera tutti i filing 13F-HR per un CIK dalla SEC API.
    """
    cik_padded = cik.zfill(10)
    api_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    
    print(f"\n 📥 Scaricamento filing per: {fund_name}")
    print(f"   CIK: {cik} | API: {api_url}")
    
    try:
        response = requests.get(api_url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            print(f"    ❌ Errore HTTP {response.status_code}")
            return []
        
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
            
            if filing_date < CUTOFF_DATE:
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

def download_catalog(output_file: str = CATALOG_FILE) -> List[Dict]:
    """
    MODALITÀ 1: Scarica catalogo completo di filing da API SEC
    Usa la lista hedge funds da hedge_funds_config.py
    Cerca tutti i filing 13F-HR degli ultimi 5 anni
    """
    print("="*80)
    print("MODALITÀ 1: DOWNLOAD CATALOGO FILING 13F-HR")
    print("="*80)
    print(f"\n📊 Obiettivo: Trovare filing 13F-HR dal {CUTOFF_DATE} ad oggi")
    print(f"🏦 Hedge funds monitorati: {get_total_funds()} (da hedge_funds_config.py)")
    print(f"🌐 Source: SEC EDGAR API (data.sec.gov)")
    print(f"\n⏳ Inizio scansione automatica...")
    print(f"   Rate limit: 10 req/sec → pausa 0.11s tra richieste")
    print(f"   Tempo stimato: ~{get_total_funds() * 0.11 / 60:.1f} minuti\n")
    
    all_filings = []
    successful_funds = 0
    
    for i, (cik, fund_name) in enumerate(HEDGE_FUNDS_CIK.items(), 1):
        print(f"[{i}/{get_total_funds()}]", end=" ")
        
        filings = get_13f_filings_for_cik(cik, fund_name)
        
        if filings:
            all_filings.extend(filings)
            successful_funds += 1
        
        if i < get_total_funds():
            time.sleep(0.11)  # Rate limiting SEC
    
    # Salva catalogo
    if all_filings:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'total_filings': len(all_filings),
                'total_funds': len(set([f['cik'] for f in all_filings])),
                'cutoff_date': CUTOFF_DATE,
                'filings': all_filings
            }, f, indent=2, ensure_ascii=False)
    
    # Riepilogo
    print("\n" + "="*80)
    print("📊 RIEPILOGO CATALOGO")
    print("="*80)
    print(f"✅ Fondi processati con successo: {successful_funds}/{get_total_funds()}")
    print(f"📄 Totale filing 13F-HR trovati: {len(all_filings)}")
    
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

def extract_holdings_from_catalog(catalog_file: str = CATALOG_FILE) -> None:
    """
    MODALITÀ 2: Estrae holdings dettagliate da un catalogo esistente
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
    
    filings = catalog_data.get('filings', [])
    
    print(f"\n📊 Trovati {len(filings)} filing nel catalogo")
    print(f"🏦 Da {catalog_data.get('total_funds', 0)} hedge funds")
    print(f"📅 Periodo: dal {catalog_data.get('cutoff_date', 'N/A')}\n")
    
    print("⚠️  ATTENZIONE: Questo scaricherà holdings dettagliate da SEC per ogni filing.")
    print(f"   Potrebbero volerci {len(filings) * 0.15 / 60:.1f} minuti con rate limiting.\n")
    
    risposta = input("Vuoi procedere? (s/n): ").lower()
    if risposta != 's':
        print("\n❌ Operazione annullata.")
        return
    
    print("\n" + "="*80)
    print("🔄 INIZIO PROCESSAMENTO")
    print("="*80 + "\n")
    
    successi = 0
    falliti = 0
    skipped = 0
    
    for i, filing in enumerate(filings, 1):
        print(f"\n[{i}/{len(filings)}] Processamento...")
        
        fund_name = filing.get('fund_name', 'Sconosciuto')
        filing_url = filing.get('filing_url', '')
        filing_date = filing.get('filing_date', 'N/A')
        
        if not filing_url:
            print(f"  ⚠️  Skipped: {fund_name} (URL non trovato)")
            skipped += 1
            continue
        
        print(f"  📊 {fund_name}")
        print(f"  📅 {filing_date}")
        print(f"  🔗 {filing_url[:60]}...")
        
        try:
            success = process_filing_holdings(filing_url, fund_name, filing_date)
            if success:
                print(f"  ✅ Holdings salvate")
                successi += 1
            else:
                print(f"  ⚠️  Nessuna holding trovata")
                falliti += 1
        except Exception as e:
            print(f"  ❌ Errore: {e}")
            falliti += 1
        
        # Rate limiting SEC (max 10 req/sec)
        if i < len(filings):
            time.sleep(0.15)  # ~6-7 req/sec per sicurezza
    
    # Riepilogo finale
    print("\n" + "="*80)
    print("📊 RIEPILOGO FINALE")
    print("="*80)
    print(f"✅ Successi:      {successi}")
    print(f"❌ Falliti:       {falliti}")
    print(f"⚠️  Skipped:       {skipped}")
    print(f"📊 Totale:        {len(filings)}")
    print("="*80)
    
    if successi > 0:
        csv_path = alert_module.HOLDINGS_CSV if HAS_ALERT_MODULE else HOLDINGS_CSV
        if os.path.exists(csv_path):
            print(f"\n✅ CSV tracker creato: {csv_path}")
            print(f"   📊 Puoi aprirlo con Excel o Python/Pandas per analizzarlo")
        else:
            print(f"\n⚠️  CSV non trovato (probabilmente nessuna holding valida)")
    
    print("\n🎉 Processamento completato!\n")

# ==================== MODALITÀ 3: FULL ====================

def process_full_pipeline():
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
    
    extract_holdings_from_catalog()
    
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
        choices=['catalog', 'holdings', 'full'],
        help='Modalità di esecuzione'
    )
    
    parser.add_argument(
        '--catalog-file',
        default=CATALOG_FILE,
        help=f'File catalogo (default: {CATALOG_FILE})'
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
    print("="*80 + "\n")
    
    # Esegui modalità richiesta
    if args.mode == 'catalog':
        download_catalog(args.catalog_file)
    
    elif args.mode == 'holdings':
        extract_holdings_from_catalog(args.catalog_file)
    
    elif args.mode == 'full':
        process_full_pipeline()

if __name__ == '__main__':
    main()
