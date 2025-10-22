"""
Analizza il CSV tracker per trovare filing storici dei tuoi hedge funds
"""

import csv
from collections import defaultdict
from datetime import datetime

HEDGE_FUNDS_FILTER = [
    'BAUPOST GROUP',
    'SCION ASSET MANAGEMENT',
    'APPALOOSA MANAGEMENT',
    'YACKTMAN ASSET MANAGEMENT',
    'PERSHING SQUARE',
    'GREENLIGHT CAPITAL',
    'FAIRHOLME CAPITAL',
    'TWEEDY BROWNE',
    'THIRD AVENUE MANAGEMENT',
    'OAKTREE CAPITAL MANAGEMENT',
    'PABRAI INVESTMENT',
    'AQUAMARINE CAPITAL',
    'GARDNER RUSSO',
    'ROYCE INVESTMENT PARTNERS',
    'SOUTHEASTERN ASSET MANAGEMENT',
    'VALUEACT CAPITAL',
    'THIRD POINT',
    'HIMALAYA CAPITAL',
    'ARLINGTON VALUE CAPITAL',
    'AKRE CAPITAL MANAGEMENT',
    'GIVERNY CAPITAL',
    'WINTERGREEN ADVISERS',
    'BOYAR ASSET MANAGEMENT',
    'HORIZON KINETICS',
    'KAHN BROTHERS'
]

def should_match(fund_name: str) -> tuple[bool, str]:
    """
    Verifica se il nome del fund corrisponde alla lista.
    Ritorna (match, matched_fund)
    """
    fund_upper = fund_name.upper()
    
    for filter_fund in HEDGE_FUNDS_FILTER:
        filter_upper = filter_fund.upper()
        stop_words = {'LLC', 'LP', 'LLP', 'INC', 'CORP', 'CORPORATION', 'LIMITED', 'LTD', 'FUND', 'FUNDS'}
        filter_keywords = [word for word in filter_upper.split() if word not in stop_words]
        
        if filter_keywords and all(keyword in fund_upper for keyword in filter_keywords):
            return True, filter_fund
    
    return False, ""

# Leggi il CSV
print("="*80)
print("ANALISI FILING STORICI NEL CSV TRACKER")
print("="*80)
print("\nLettura del file 13f_holdings_tracker.csv...")

try:
    with open('13f_holdings_tracker.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        # Raggruppa per fund
        filings_by_fund = defaultdict(lambda: {
            'dates': set(),
            'holdings_count': 0,
            'accession_numbers': set()
        })
        
        unique_funds_in_csv = set()
        total_rows = 0
        
        for row in reader:
            total_rows += 1
            fund_name = row.get('Fund Name', '')
            filing_date = row.get('Filing Date', '')
            accession = row.get('Accession Number', '')
            
            unique_funds_in_csv.add(fund_name)
            
            # Controlla se corrisponde alla lista
            is_match, matched_fund = should_match(fund_name)
            
            if is_match:
                filings_by_fund[fund_name]['dates'].add(filing_date)
                filings_by_fund[fund_name]['holdings_count'] += 1
                filings_by_fund[fund_name]['accession_numbers'].add(accession)
                filings_by_fund[fund_name]['matched_filter'] = matched_fund
        
        print(f"✓ Letti {total_rows:,} record da {len(unique_funds_in_csv)} fondi diversi\n")
        
        # Stampa risultati
        print("="*80)
        print(f"HEDGE FUNDS DELLA TUA LISTA TROVATI NEL CSV: {len(filings_by_fund)}")
        print("="*80)
        
        if filings_by_fund:
            # Ordina per numero di holdings (dal maggiore al minore)
            sorted_funds = sorted(
                filings_by_fund.items(), 
                key=lambda x: x[1]['holdings_count'], 
                reverse=True
            )
            
            for fund_name, data in sorted_funds:
                print(f"\n📊 {fund_name}")
                print(f"   Match con filtro: {data['matched_filter']}")
                print(f"   Filing trovati: {len(data['dates'])} date diverse")
                print(f"   Accession Numbers: {len(data['accession_numbers'])}")
                print(f"   Totale holdings: {data['holdings_count']:,}")
                
                # Mostra le date (ordinate)
                dates_sorted = sorted(list(data['dates']))
                if len(dates_sorted) <= 5:
                    print(f"   Date: {', '.join(dates_sorted)}")
                else:
                    print(f"   Date: {dates_sorted[0]} → {dates_sorted[-1]} ({len(dates_sorted)} filing)")
            
            print("\n" + "="*80)
            print("RIEPILOGO:")
            print("="*80)
            print(f"✅ Hedge funds monitorati trovati: {len(filings_by_fund)}/{len(HEDGE_FUNDS_FILTER)}")
            print(f"📈 Totale holdings dei tuoi funds: {sum(d['holdings_count'] for d in filings_by_fund.values()):,}")
            
            # Quali mancano?
            found_filters = {data['matched_filter'] for data in filings_by_fund.values()}
            missing = set(HEDGE_FUNDS_FILTER) - found_filters
            
            if missing:
                print(f"\n⚠️  Hedge funds NON trovati nel CSV ({len(missing)}):")
                for fund in sorted(missing):
                    print(f"   • {fund}")
                print("\n   → Questi fondi potrebbero non aver mai depositato, o usano nomi diversi")
            
        else:
            print("\n❌ NESSUNO dei tuoi hedge funds è stato trovato nel CSV!")
            print("\nPossibili cause:")
            print("1. I nomi nel CSV sono diversi da quelli nella lista filtro")
            print("2. Questi fondi non hanno depositato di recente")
            print("3. Il CSV contiene solo filing di altri fondi")
            
            print("\n📋 Primi 20 fondi presenti nel CSV:")
            for i, fund in enumerate(sorted(list(unique_funds_in_csv))[:20], 1):
                print(f"   {i}. {fund}")
        
        print("\n" + "="*80 + "\n")
        
except FileNotFoundError:
    print("❌ ERRORE: File 13f_holdings_tracker.csv non trovato!")
    print("   Il CSV deve essere nella stessa directory dello script.")
except Exception as e:
    print(f"❌ ERRORE durante la lettura del CSV: {e}")
