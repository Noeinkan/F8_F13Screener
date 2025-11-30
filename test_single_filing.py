"""
Test parsing di un singolo filing per verificare l'estrazione delle colonne
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from src.core.parser import HoldingsParser
from src.core.sec_client import SECClient
import json

# Setup
USER_AGENT = 'andrea.aita@libero.it'
parser = HoldingsParser(USER_AGENT)
sec_client = SECClient(USER_AGENT)

# Carica un filing dal catalogo
catalog_file = r'D:\03_Coding\F8_F13Screener\src\core\data\historical\catalog\historical_13f_catalog_5years.json'
with open(catalog_file, 'r') as f:
    catalog = json.load(f)

# Test multiple filings (XML and HTML formats)
test_indices = [0, 50, 100, 200]  # Different filings
results = []

for idx in test_indices:
    if idx >= len(catalog['filings']):
        continue
    
    filing = catalog['filings'][idx]
    print(f"\n{'='*80}")
    print(f"Testing filing #{idx}:")
    print(f"  Fund: {filing['fund_name']}")
    print(f"  Date: {filing['filing_date']}")
    print(f"  URL: {filing['filing_url'][:80]}...")
    
    try:
        # Parse
        info_table_url = parser.get_information_table_url(filing['filing_url'])
        if not info_table_url:
            print("  ❌ Could not find information table URL")
            continue
        
        format_type = 'XML' if info_table_url.endswith('.xml') else 'HTML'
        print(f"  Format: {format_type}")
        print(f"  Info Table: {info_table_url[:80]}...")
        
        holdings = parser.parse_information_table(info_table_url)
        if not holdings:
            print("  ❌ No holdings parsed")
            continue
        
        print(f"  ✅ Parsed {len(holdings)} holdings")
        
        # Analyze fields
        fields_to_check = ['figi', 'value_x1000', 'shares_raw', 'sh_prn', 'put_call', 
                           'investment_discretion', 'other_manager']
        
        field_stats = {}
        for field in fields_to_check:
            non_empty = sum(1 for h in holdings if h.get(field))
            pct = (non_empty / len(holdings) * 100) if holdings else 0
            field_stats[field] = (non_empty, pct)
        
        results.append({
            'idx': idx,
            'fund': filing['fund_name'],
            'date': filing['filing_date'],
            'format': format_type,
            'holdings_count': len(holdings),
            'stats': field_stats,
            'first_holding': holdings[0]
        })
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        continue

# Summary
print(f"\n\n{'='*80}")
print("SUMMARY OF ALL TESTED FILINGS")
print(f"{'='*80}\n")

for result in results:
    print(f"Filing #{result['idx']} ({result['format']}) - {result['fund']} - {result['date']}")
    print(f"  Holdings: {result['holdings_count']}")
    for field, (count, pct) in result['stats'].items():
        status = '✅' if pct > 80 else '⚠️' if pct > 20 else '❌'
        print(f"  {status} {field:25s}: {count:3d}/{result['holdings_count']:3d} ({pct:5.1f}%)")
    print()

# Show one complete example
if results:
    print(f"{'='*80}")
    print("EXAMPLE: First holding from first successful filing")
    print(f"{'='*80}\n")
    first = results[0]['first_holding']
    for key, value in first.items():
        if value:
            print(f"{key:30s}: {value}")
