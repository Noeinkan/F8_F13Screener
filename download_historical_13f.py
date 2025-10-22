"""
Script per scaricare filing 13F storici per i 25 hedge funds value investing.
Usa l'API EDGAR per trovare tutti i filing 13F-HR disponibili per ciascun CIK.
FILTRO: SOLO ULTIMI 5 ANNI (2020-2025)
"""

import requests
import json
import time
import os
from datetime import datetime, timedelta
from typing import List, Dict

# Configurazione
USER_AGENT = os.getenv('SEC_USER_AGENT', 'andrea.aita@libero.it')
HEADERS = {'User-Agent': USER_AGENT}

# FILTRO: Solo ultimi 5 anni (dal 2020-01-01)
CUTOFF_DATE = '2020-01-01'

# I tuoi 25 hedge funds con CIK
HEDGE_FUNDS_CIK = {
    '0001061768': 'Baupost Group (Seth Klarman)',
    '0001649339': 'Scion Asset Management (Michael Burry)',
    '0001656456': 'Appaloosa Management (David Tepper)',
    '0000905567': 'Yacktman Asset Management',
    '0001336528': 'Pershing Square Capital (Bill Ackman)',
    '0001079114': 'Greenlight Capital (David Einhorn)',
    '0001056831': 'Fairholme Capital (Bruce Berkowitz)',
    '0000732905': 'Tweedy Browne Company',
    '0001099281': 'Third Avenue Management',
    '0000949509': 'Oaktree Capital Management (Howard Marks)',
    '0001549575': 'Pabrai Investment Funds (Mohnish Pabrai)',
    '0001404599': 'Aquamarine Capital (Guy Spier)',
    '0000860643': 'Gardner Russo & Gardner (Tom Russo)',
    '0000906304': 'Royce Investment Partners (Chuck Royce)',
    '0000807985': 'Southeastern Asset Management',
    '0001351069': 'ValueAct Capital',
    '0001040273': 'Third Point LLC (Dan Loeb)',
    '0001709323': 'Himalaya Capital (Li Lu)',
    '0001568820': 'Arlington Value Capital (Allan Mecham)',
    '0001112520': 'Akre Capital Management (Chuck Akre)',
    '0001641864': 'Giverny Capital',
    '0001360079': 'Wintergreen Advisers',
    '0001218254': 'Boyar Asset Management',
    '0001056823': 'Horizon Kinetics',
    '0001039565': 'Kahn Brothers'
}

def get_13f_filings_for_cik(cik: str, fund_name: str) -> List[Dict]:
    """
    Recupera tutti i filing 13F-HR per un CIK dalla SEC API.
    
    API endpoint: https://data.sec.gov/submissions/CIK{cik}.json
    """
    # Normalizza CIK (10 cifre con padding di zeri)
    cik_padded = cik.zfill(10)
    
    api_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    
    print(f"\n Scaricamento filing per: {fund_name}")
    print(f"   CIK: {cik} | API: {api_url}")
    
    try:
        response = requests.get(api_url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            print(f"    Errore HTTP {response.status_code}")
            return []
        
        data = response.json()
        
        # Estrai tutti i filing
        recent_filings = data.get('filings', {}).get('recent', {})
        
        if not recent_filings:
            print(f"     Nessun filing trovato")
            return []
        
        # Filtra solo 13F-HR
        filings_13f = []
        
        accession_numbers = recent_filings.get('accessionNumber', [])
        filing_dates = recent_filings.get('filingDate', [])
        forms = recent_filings.get('form', [])
        primary_documents = recent_filings.get('primaryDocument', [])
        
        for i in range(len(forms)):
            # Filtra per tipo di form
            if forms[i] not in ['13F-HR', '13F-HR/A']:
                continue
            
            # FILTRO: Solo ultimi 5 anni
            filing_date = filing_dates[i]
            
            # Debug
            if i < 3:  # Stampa primi 3 per debug
                print(f"   DEBUG: Form={forms[i]}, Date={filing_date}, Cutoff={CUTOFF_DATE}, Pass={filing_date >= CUTOFF_DATE}")
            
            if filing_date < CUTOFF_DATE:
                continue
            
            # Costruisci URL del filing index
            accession = accession_numbers[i]
            accession_no_dashes = accession.replace('-', '')
            cik_no_leading = cik.lstrip('0')
            
            # URL pattern: https://www.sec.gov/Archives/edgar/data/{CIK}/{accession_no_dashes}/{accession}-index.htm
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
        
        print(f"    Trovati {len(filings_13f)} filing 13F-HR")
        
        # Mostra le date dei filing
        if filings_13f:
            dates = sorted([f['filing_date'] for f in filings_13f], reverse=True)
            if len(dates) <= 5:
                print(f"    Date: {', '.join(dates)}")
            else:
                print(f"    Dal {dates[-1]} al {dates[0]} ({len(dates)} filing)")
        
        return filings_13f
        
    except requests.exceptions.RequestException as e:
        print(f"    Errore connessione: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"    Errore parsing JSON: {e}")
        return []
    except Exception as e:
        print(f"    Errore: {e}")
        return []

def save_filings_catalog(all_filings: List[Dict], filename: str = 'historical_13f_catalog_5years.json'):
    """
    Salva il catalogo di tutti i filing trovati in un JSON
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'total_filings': len(all_filings),
                'total_funds': len(set([f['cik'] for f in all_filings])),
                'filings': all_filings
            }, f, indent=2, ensure_ascii=False)
        
        print(f"\n Catalogo salvato in: {filename}")
        return True
    except Exception as e:
        print(f"\n Errore salvataggio catalogo: {e}")
        return False

def main():
    print("="*80)
    print("DOWNLOAD FILING 13F-HR ULTIMI 5 ANNI (2020-2025) - 25 HEDGE FUNDS")
    print("="*80)
    print(f"\nObiettivo: Trovare filing 13F-HR dal {CUTOFF_DATE} ad oggi")
    print(f"Hedge funds monitorati: {len(HEDGE_FUNDS_CIK)}")
    print(f"Source: SEC EDGAR API (data.sec.gov)")
    print(f"\nInizio scansione... (rate limit: 10 req/sec, pausa 0.11s tra richieste)\n")
    
    all_filings = []
    successful_funds = 0
    
    for i, (cik, fund_name) in enumerate(HEDGE_FUNDS_CIK.items(), 1):
        print(f"[{i}/{len(HEDGE_FUNDS_CIK)}]", end=" ")
        
        filings = get_13f_filings_for_cik(cik, fund_name)
        
        if filings:
            all_filings.extend(filings)
            successful_funds += 1
        
        # Rate limiting: SEC permette max 10 req/sec
        if i < len(HEDGE_FUNDS_CIK):
            time.sleep(0.11)  # 110ms = ~9 req/sec per essere sicuri
    
    # Risultati finali
    print("\n" + "="*80)
    print("RIEPILOGO SCANSIONE")
    print("="*80)
    print(f" Fondi processati con successo: {successful_funds}/{len(HEDGE_FUNDS_CIK)}")
    print(f" Totale filing 13F-HR trovati: {len(all_filings)}")
    
    if all_filings:
        # Statistiche per fund
        filings_by_fund = {}
        for filing in all_filings:
            fund = filing['fund_name']
            if fund not in filings_by_fund:
                filings_by_fund[fund] = []
            filings_by_fund[fund].append(filing)
        
        print(f"\n TOP 10 FONDI PER NUMERO DI FILING:")
        sorted_funds = sorted(filings_by_fund.items(), key=lambda x: len(x[1]), reverse=True)
        for i, (fund, filings) in enumerate(sorted_funds[:10], 1):
            dates = [f['filing_date'] for f in filings]
            date_range = f"{min(dates)}  {max(dates)}" if len(dates) > 1 else dates[0]
            print(f"   {i:2d}. {fund[:50]:50s} | {len(filings):3d} filing | {date_range}")
        
        # Range temporale
        all_dates = [f['filing_date'] for f in all_filings]
        print(f"\n Range temporale: {min(all_dates)}  {max(all_dates)}")
        
        # Salva catalogo
        save_filings_catalog(all_filings)
        
        print("\n" + "="*80)
        print("PROSSIMI PASSI:")
        print("="*80)
        print("1.  Catalogo salvato in 'historical_13f_catalog.json'")
        print("2.  Usa questo catalogo per scaricare gli holdings specifici")
        print("3.  Ogni URL nel catalogo punta alla pagina index del filing")
        print("4.  Da l puoi estrarre l'Information Table come nel programma principale")
        print("="*80 + "\n")
        
        # Esempio di URL
        if all_filings:
            example = all_filings[0]
            print(" ESEMPIO DI URL FILING:")
            print(f"   Fund: {example['fund_name']}")
            print(f"   Data: {example['filing_date']}")
            print(f"   URL: {example['filing_url']}")
            print()
    else:
        print("\n  NESSUN FILING TROVATO!")
        print("Possibili cause:")
        print("   Problemi di connessione alla SEC API")
        print("   CIK non corretti")
        print("   Rate limiting troppo aggressivo")

if __name__ == '__main__':
    main()

