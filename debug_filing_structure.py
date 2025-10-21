#!/usr/bin/env python3
"""
Debug script per analizzare la struttura di una pagina filing SEC
"""

import requests
from bs4 import BeautifulSoup

filing_url = "https://www.sec.gov/Archives/edgar/data/1776551/000177655125000003/0001776551-25-000003-index.htm"
USER_AGENT = 'andrea.aita@libero.it'

print(f"Scaricamento: {filing_url}\n")

headers = {'User-Agent': USER_AGENT}
response = requests.get(filing_url, headers=headers, timeout=30)

if response.status_code != 200:
    print(f"Errore HTTP: {response.status_code}")
    exit(1)

soup = BeautifulSoup(response.content, 'html.parser')

print("="*80)
print("TABELLE TROVATE NELLA PAGINA:")
print("="*80)

tables = soup.find_all('table')
print(f"\nNumero totale di tabelle: {len(tables)}\n")

for i, table in enumerate(tables, 1):
    print(f"\n--- TABELLA {i} ---")
    
    # Stampa header se presente
    headers_row = table.find('tr')
    if headers_row:
        headers = headers_row.find_all(['th', 'td'])
        if headers:
            print("Header:", [h.get_text(strip=True) for h in headers])
    
    # Stampa prime 3 righe
    rows = table.find_all('tr')[:3]
    for j, row in enumerate(rows, 1):
        cells = row.find_all(['td', 'th'])
        print(f"  Riga {j}:", [cell.get_text(strip=True)[:50] for cell in cells])
    
    print(f"  (Totale righe: {len(table.find_all('tr'))})")

print("\n" + "="*80)
print("LINK AI FILE:")
print("="*80)

# Cerca tutti i link nella pagina
links = soup.find_all('a', href=True)
for link in links:
    href = link['href']
    text = link.get_text(strip=True)
    
    # Filtra solo file .htm, .html, .xml
    if any(ext in href.lower() for ext in ['.htm', '.html', '.xml']):
        print(f"\n{text}")
        print(f"  -> {href}")
