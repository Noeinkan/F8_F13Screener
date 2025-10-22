"""
Script di diagnostica per verificare quali 13F sono nel feed SEC
e quali corrispondono ai tuoi hedge funds filtrati
"""

import requests
import feedparser
import re

USER_AGENT = 'andrea.aita@libero.it'
RSS_URL = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=13F-HR&count=100&output=atom'

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

def extract_filer_name_from_title(title: str) -> str:
    """Estrae il nome del filer dal titolo"""
    try:
        if '13F-HR - ' in title:
            name_part = title.split('13F-HR - ', 1)[1]
            if '(' in name_part:
                filer_name = name_part.split('(')[0].strip()
                if filer_name and filer_name != '':
                    return filer_name
        if '(' in title and ')' in title:
            name_before_paren = title.split('(')[0].strip()
            if name_before_paren and '13F-HR' not in name_before_paren:
                return name_before_paren
            if '13F-HR -' in name_before_paren:
                name = name_before_paren.replace('13F-HR -', '').strip()
                if name:
                    return name
        return title
    except Exception as e:
        return 'Filer Sconosciuto'

def should_notify(filer_name: str) -> tuple[bool, str]:
    """
    Verifica se il filer corrisponde ai filtri.
    Ritorna (match, fund_matched)
    """
    if not HEDGE_FUNDS_FILTER:
        return True, "ALL"
    
    filer_upper = filer_name.upper()
    
    for fund in HEDGE_FUNDS_FILTER:
        fund_upper = fund.upper()
        stop_words = {'LLC', 'LP', 'LLP', 'INC', 'CORP', 'CORPORATION', 'LIMITED', 'LTD', 'FUND', 'FUNDS'}
        fund_keywords = [word for word in fund_upper.split() if word not in stop_words]
        
        if fund_keywords and all(keyword in filer_upper for keyword in fund_keywords):
            return True, fund
    
    return False, ""

# Scarica il feed
print("="*80)
print("DIAGNOSTICA 13F FILINGS - CONTROLLO FEED SEC")
print("="*80)
print(f"\nScaricamento ultimi 100 filing 13F-HR dalla SEC...")

headers = {'User-Agent': USER_AGENT}
response = requests.get(RSS_URL, headers=headers, timeout=30)

if response.status_code != 200:
    print(f"ERRORE: HTTP {response.status_code}")
    exit(1)

feed = feedparser.parse(response.content)
print(f"✓ Feed scaricato: {len(feed.entries)} filing trovati\n")

# Analizza
matches = []
no_matches = []

for entry in feed.entries:
    title = entry.get('title', '')
    filer = extract_filer_name_from_title(title)
    filing_date = entry.get('updated', 'N/A')[:10]  # Solo data
    
    is_match, matched_fund = should_notify(filer)
    
    if is_match:
        matches.append({
            'filer': filer,
            'matched_fund': matched_fund,
            'date': filing_date,
            'title': title
        })
    else:
        no_matches.append({
            'filer': filer,
            'date': filing_date
        })

# Stampa risultati
print("="*80)
print(f"RISULTATI: {len(matches)} MATCH TROVATI / {len(feed.entries)} TOTALI")
print("="*80)

if matches:
    print(f"\n✅ FILING CHE CORRISPONDONO AI TUOI HEDGE FUNDS ({len(matches)}):\n")
    for i, match in enumerate(matches, 1):
        print(f"{i}. [{match['date']}] {match['filer']}")
        print(f"   → Match con: {match['matched_fund']}")
        print()
else:
    print("\n❌ NESSUN FILING CORRISPONDE AI TUOI HEDGE FUNDS NELLA LISTA!")
    print("\nPossibili motivi:")
    print("1. I tuoi hedge funds non hanno depositato 13F di recente")
    print("2. I nomi nel feed SEC sono diversi da quelli nella tua lista")
    print("3. Il filtro è troppo restrittivo")

print("\n" + "="*80)
print(f"FILING NON CORRISPONDENTI (primi 20 di {len(no_matches)}):")
print("="*80 + "\n")

for i, item in enumerate(no_matches[:20], 1):
    print(f"{i}. [{item['date']}] {item['filer']}")

if len(no_matches) > 20:
    print(f"\n... e altri {len(no_matches) - 20} filing")

print("\n" + "="*80)
print("SUGGERIMENTI:")
print("="*80)
print("• Se vedi nomi simili ai tuoi hedge funds ma non fanno match,")
print("  potrebbe essere necessario aggiustare i nomi nella lista HEDGE_FUNDS_FILTER")
print("• I filing 13F vengono depositati trimestralmente (45 giorni dopo fine trimestre)")
print("• Controlla su EDGAR se i tuoi hedge funds hanno depositato di recente")
print("="*80 + "\n")
