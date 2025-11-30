"""
Debug XML structure to understand why value is not extracted
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from src.core.parser import HoldingsParser
import requests
from bs4 import BeautifulSoup

USER_AGENT = 'andrea.aita@libero.it'

# URL del filing di test
info_table_url = "https://www.sec.gov/Archives/edgar/data/1656456/000165645625000006/xslForm13F_X02/primary_doc.xml"

print("Downloading XML...")
response = requests.get(info_table_url, headers={'User-Agent': USER_AGENT}, timeout=30)
content = response.content

print("\nParsing XML...")
soup = BeautifulSoup(content, 'xml')

# Mostra i primi 3000 caratteri del XML
# Parse as HTML
soup_html = BeautifulSoup(content, 'html.parser')

# Find all tables
tables = soup_html.find_all('table')
print(f"\n\nFound {len(tables)} HTML tables")

if tables:
    # Look for the information table (usually has specific headers)
    for i, table in enumerate(tables):
        rows = table.find_all('tr')
        if len(rows) < 2:
            print(f"\nTABLE #{i} - SKIP (only {len(rows)} rows)")
            continue
        
        # Check all rows for CUSIP/ISSUER headers
        has_info_table = False
        for j, row in enumerate(rows[:10]):  # Check first 10 rows
            cells = row.find_all(['td', 'th'])
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            
            if any('CUSIP' in text.upper() for text in cell_texts):
                has_info_table = True
                print(f"\n{'='*80}")
                print(f"✅ TABLE #{i} - INFORMATION TABLE FOUND! - {len(rows)} rows")
                print(f"{'='*80}")
                print(f"Header row ({j}): {cell_texts}")
                
                # Show first data row
                if j + 1 < len(rows):
                    data_row = rows[j + 1]
                    data_cells = data_row.find_all(['td', 'th'])
                    data_texts = [cell.get_text(strip=True) for cell in data_cells]
                    print(f"\nFirst data row ({j+1}):")
                    for k, text in enumerate(data_texts):
                        print(f"  [{k}] {text[:80]}")
                break
        
        if not has_info_table:
            print(f"\nTABLE #{i} - {len(rows)} rows (not info table)")
