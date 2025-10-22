# Test del filtro hedge funds
# Esegui questo per vedere quali nomi passano il filtro

import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Copia la lista dal tuo file principale
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

def should_notify(filer_name: str) -> bool:
    """
    Verifica se il filer corrisponde ai filtri (se presenti).
    Usa matching rigoroso: TUTTE le parole chiave del fund devono essere presenti.
    """
    if not HEDGE_FUNDS_FILTER:
        return True
    
    filer_upper = filer_name.upper()
    
    for fund in HEDGE_FUNDS_FILTER:
        fund_upper = fund.upper()
        stop_words = {'LLC', 'LP', 'LLP', 'INC', 'CORP', 'CORPORATION', 'LIMITED', 'LTD', 'FUND', 'FUNDS'}
        fund_keywords = [word for word in fund_upper.split() if word not in stop_words]
        
        if fund_keywords and all(keyword in filer_upper for keyword in fund_keywords):
            logger.info(f"✓ MATCH: '{filer_name}' → '{fund}'")
            return True
    
    logger.info(f"✗ NO MATCH: '{filer_name}'")
    return False

# Test cases - esempi realistici di nomi che potresti vedere nei filing SEC
test_cases = [
    # Dovrebbero PASSARE (veri hedge funds della tua lista)
    "BAUPOST GROUP LLC",
    "BAUPOST GROUP SECURITIES LLC",
    "SCION ASSET MANAGEMENT LLC",
    "PERSHING SQUARE CAPITAL MANAGEMENT LP",
    "GREENLIGHT CAPITAL INC",
    "THIRD POINT LLC",
    "OAKTREE CAPITAL MANAGEMENT LP",
    "AKRE CAPITAL MANAGEMENT LLC",
    
    # Dovrebbero ESSERE BLOCCATI (falsi positivi)
    "RANDOM CAPITAL MANAGEMENT LLC",
    "THIRD STREET CAPITAL CORP",
    "MANAGEMENT SOLUTIONS INC",
    "ASSET BUILDERS LLC",
    "INVESTMENT PARTNERS LP",
    "CAPITAL GROUP HOLDINGS",
    "POINT INVESTMENTS LLC",
    "SQUARE ONE CAPITAL",
]

print("\n" + "="*70)
print("TEST DEL FILTRO HEDGE FUNDS")
print("="*70 + "\n")

for i, test_name in enumerate(test_cases, 1):
    print(f"\n[Test {i}] {test_name}")
    should_notify(test_name)

print("\n" + "="*70)
print("FINE TEST")
print("="*70 + "\n")
