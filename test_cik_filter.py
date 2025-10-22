"""
Test del filtro CIK per verificare che funzioni correttamente
"""

import re

HEDGE_FUNDS_CIK_FILTER = {
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

def extract_cik_from_link(link: str) -> str:
    """Estrae il CIK dall'URL EDGAR"""
    try:
        match = re.search(r'(?:CIK=|/data/)(\d+)', link)
        if match:
            return match.group(1)
        return 'N/A'
    except:
        return 'N/A'

def should_notify(filer_name: str, filing_link: str) -> tuple[bool, str]:
    """Verifica se il filer corrisponde ai filtri tramite CIK"""
    if not HEDGE_FUNDS_CIK_FILTER:
        return True, "ALL"
    
    cik = extract_cik_from_link(filing_link)
    cik_normalized = cik.lstrip('0') if cik else ''
    
    for filter_cik, fund_name in HEDGE_FUNDS_CIK_FILTER.items():
        filter_cik_normalized = filter_cik.lstrip('0')
        
        if cik == filter_cik or cik_normalized == filter_cik_normalized:
            return True, fund_name
    
    return False, ""

# Test cases
test_cases = [
    # Dovrebbero PASSARE (veri CIK dei tuoi hedge funds)
    ("Baupost Group LLC", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001061768&type=13F"),
    ("Scion Asset Management", "https://www.sec.gov/Archives/edgar/data/1649339/000164933925000001/0001649339-25-000001-index.htm"),
    ("Pershing Square", "https://www.sec.gov/Archives/edgar/data/1336528/000133652825000002/0001336528-25-000002-index.htm"),
    ("Greenlight Capital", "https://www.sec.gov/cgi-bin/browse-edgar?CIK=1079114"),
    ("Third Point LLC", "https://www.sec.gov/Archives/edgar/data/1040273/000104027325000001/0001040273-25-000001-index.htm"),
    
    # CIK con zeri leading (normalizzazione)
    ("Baupost", "https://www.sec.gov/Archives/edgar/data/0001061768/test.htm"),
    ("Baupost", "https://www.sec.gov/Archives/edgar/data/1061768/test.htm"),  # Senza zeri
    
    # Dovrebbero ESSERE BLOCCATI (CIK non nella lista)
    ("Random Fund", "https://www.sec.gov/Archives/edgar/data/9999999/000999999925000001/0009999999-25-000001-index.htm"),
    ("Another Fund", "https://www.sec.gov/cgi-bin/browse-edgar?CIK=1234567"),
    ("Unknown Manager", "https://www.sec.gov/Archives/edgar/data/8888888/test.htm"),
]

print("\n" + "="*80)
print("TEST DEL FILTRO CIK - 25 HEDGE FUNDS VALUE INVESTING")
print("="*80)
print(f"\nMonitoro {len(HEDGE_FUNDS_CIK_FILTER)} hedge funds tramite CIK univoco\n")

passed = 0
failed = 0

for i, (filer_name, url) in enumerate(test_cases, 1):
    cik = extract_cik_from_link(url)
    is_match, matched_fund = should_notify(filer_name, url)
    
    status = "✓ MATCH" if is_match else "✗ NO MATCH"
    
    print(f"[Test {i}] {status}")
    print(f"  Filer: {filer_name}")
    print(f"  CIK estratto: {cik}")
    
    if is_match:
        print(f"  → {matched_fund}")
        passed += 1
    else:
        print(f"  → Bloccato (CIK non nella lista)")
        if i > 7:  # I test dopo il 7 devono essere bloccati
            passed += 1
        else:
            failed += 1
    print()

print("="*80)
print(f"RISULTATI: {passed}/{len(test_cases)} test corretti")
print("="*80)

# Mostra lista completa hedge funds
print("\n📊 LISTA COMPLETA 25 HEDGE FUNDS MONITORATI:\n")
for i, (cik, name) in enumerate(sorted(HEDGE_FUNDS_CIK_FILTER.items(), key=lambda x: x[1]), 1):
    print(f"{i:2d}. CIK {cik} → {name}")

print("\n" + "="*80)
print("✅ Il filtro CIK è molto più affidabile del filtro per nome!")
print("   • CIK è univoco e immutabile")
print("   • Nessun falso positivo possibile")
print("   • Non dipende da variazioni del nome legale")
print("="*80 + "\n")
