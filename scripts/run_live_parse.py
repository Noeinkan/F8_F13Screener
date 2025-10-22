import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util
from pathlib import Path

MOD_PATH = Path(__file__).resolve().parents[1] / '13f_alert.py'
spec = importlib.util.spec_from_file_location('thirteen_alert', str(MOD_PATH))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

parse_information_table = mod.parse_information_table
save_holdings_to_csv = mod.save_holdings_to_csv

URLS = [
    'https://www.sec.gov/Archives/edgar/data/1350694/000117266125003151/xslForm13F_X02/infotable.xml'
]

OUT_CSV = '13f_holdings_test_output.csv'

all_holdings = []
for url in URLS:
    print(f"Processing: {url}")
    holdings = parse_information_table(url)
    print(f"  -> Parsed {len(holdings)} holdings")
    # Save per-file with a dummy filer name and date
    if holdings:
        save_holdings_to_csv(holdings, filer_name='TEST FUND', filing_date='2025-10-22', cik='1350694', accession_number='N/A', filing_url=url)
    all_holdings.extend(holdings)

print(f"Total holdings parsed: {len(all_holdings)}")
print(f"CSV saved (appended) to current dir: {OUT_CSV} (note: function uses HOLDINGS_CSV constant by default)")
