#!/usr/bin/env python3
"""
Debug: analizza le tabelle HTML dell'infotable
"""

import requests
from bs4 import BeautifulSoup

info_url = "https://www.sec.gov/Archives/edgar/data/1776551/000177655125000003/xslForm13F_X02/infotable.xml"
USER_AGENT = 'andrea.aita@libero.it'

headers = {'User-Agent': USER_AGENT}
response = requests.get(info_url, headers=headers, timeout=30)

soup = BeautifulSoup(response.content, 'html.parser')

tables = soup.find_all('table')

print(f"Trovate {len(tables)} tabelle\n")

for i, table in enumerate(tables, 1):
    print("="*80)
    print(f"TABELLA {i}")
    print("="*80)
    
    rows = table.find_all('tr')
    print(f"Righe totali: {len(rows)}\n")
    
    # Mostra prime 5 righe
    for j, row in enumerate(rows[:5], 1):
        cells = row.find_all(['td', 'th'])
        print(f"Riga {j} ({len(cells)} celle):")
        for k, cell in enumerate(cells, 1):
            text = cell.get_text(strip=True)
            if len(text) > 50:
                text = text[:47] + "..."
            print(f"  [{k}] {text}")
        print()
    
    if len(rows) > 5:
        print(f"... e altre {len(rows) - 5} righe\n")
