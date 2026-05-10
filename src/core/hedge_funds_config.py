"""
Configurazione centralizzata per i hedge funds monitorati (value investing e growth).
Questo file contiene la lista completa con CIK e nomi dei fund managers.
"""

# Lista completa dei hedge funds con CIK
# Nota: I fund con CIK "N/A" sono commentati e possono essere aggiunti quando disponibili
HEDGE_FUNDS_CIK = {
    # === VALUE INVESTING (25 funds) ===
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
    '0001039565': 'Kahn Brothers',
    '0000921669': 'Icahn Capital (Carl Icahn)',
    '0001067983': 'Berkshire Hathaway (Warren Buffett)',

    # === GROWTH & TECH FOCUSED (18 funds) ===
    '0001840735': 'Greenoaks Capital Partners',
    '0001697591': 'CAS Investment Partners (Clifford Sosin)',
    '0000872573': 'Caxton (Bruce Kovner)',
    '0001766596': 'RV Capital AG (Rob Vinall)',
    # '': 'Ratan Capital Management (Nehal Chopra)',  # CIK N/A
    '0001536411': 'Duquesne Family Office (Stanley Druckenmiller)',
    '0001387322': 'Whale Rock Capital Management (Alex Sacerdote)',
    '0001592413': 'Strategy Capital',
    '0001135730': 'Coatue Management (Philippe Laffont)',
    # '': 'Magnetar Financial (Alec Litowitz)',  # CIK N/A
    '0001891904': 'Octahedron Capital Management',
    '0001389234': 'Symmetry Peak Management (Quint Slattery)',
    '0001050464': 'Peconic Partners (William Harnisch)',
    '0001589624': '3G Capital Partners (Jorge Paulo Lemann)',
    '0001172661': 'Jericho Capital Asset Management (Josh Resnick)',
    '0001104329': 'Crosslink Capital (Seymour Kaufman)',
    '0001103887': 'Nwi Management (Hari Hariharan)',
    '0001462245': 'Shannon River Fund Management (Spencer Waxman)',
    '0001448793': 'Prime Capital Management (Liu Yijun)',
    '0001037389': 'Renaissance Technologies (Jim Simons)',
    '0001167483': 'Tiger Global Management (Chase Coleman)',
    '0002045724': 'Situational Awareness LP (Leopold Aschenbrenner)',
    '0001963565': 'Value Aligned Research Advisors (Ben Hoskin & David Field)',
    '0001541617': 'Altimeter Capital Management (Brad Gerstner)',
    '0001061165': 'Lone Pine Capital (Stephen Mandel)',

    # === MEGA FUNDS & QUANT (10 funds) ===
    '0001423053': 'Citadel (Kenneth Griffin)',
    '0001350694': 'Bridgewater Associates (Ray Dalio)',
    '0001167557': 'AQR Capital Management (Cliff Asness)',
    '0001009268': 'D.E. Shaw (David E. Shaw)',
    '0001317684': 'Two Sigma Investments (John Overdeck & David Siegel)',
    '0001791786': 'Elliott Investment Management (Paul Singer)',
    '0000909661': 'Farallon Capital Management (Thomas Steyer)',
    # '': 'Man Group Ltd.',  # CIK N/A
    '0001426859': 'Ruffer Investment Co.',
    '0001603466': 'Point72 Asset Management (Steve Cohen)',
    '0001273087': 'Millennium Management (Israel Englander)',
    '0001218710': 'Balyasny Asset Management',
}

# Funzioni di utilità
def get_fund_name_by_cik(cik: str) -> str:
    """Restituisce il nome del fund dato il CIK"""
    return HEDGE_FUNDS_CIK.get(cik, "Fund Sconosciuto")

def get_cik_by_fund_name(fund_name: str) -> str:
    """Restituisce il CIK dato il nome del fund (ricerca parziale)"""
    fund_name_lower = fund_name.lower()
    for cik, name in HEDGE_FUNDS_CIK.items():
        if fund_name_lower in name.lower():
            return cik
    return None

def get_total_funds() -> int:
    """Restituisce il numero totale di fund monitorati"""
    return len(HEDGE_FUNDS_CIK)

def get_all_ciks() -> list:
    """Restituisce la lista di tutti i CIK"""
    return list(HEDGE_FUNDS_CIK.keys())

def get_all_fund_names() -> list:
    """Restituisce la lista di tutti i nomi dei fund"""
    return list(HEDGE_FUNDS_CIK.values())
