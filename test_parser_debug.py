#!/usr/bin/env python3
"""
Script di debug per testare il parser su un filing specifico
"""
import sys
import os
import logging

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.core.parser import HoldingsParser

# Enable DEBUG logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Test con un URL di esempio
USER_AGENT = 'test@example.com'
parser = HoldingsParser(USER_AGENT)

# Prendi un URL dalla tua lista (sostituisci con uno che sta fallendo)
test_url = input("Inserisci l'URL del filing index da testare: ").strip()

if not test_url:
    # URL di test di default
    test_url = "https://www.sec.gov/Archives/edgar/data/1649339/000164933925000007/0001649339-25-000007-index.htm"
    print(f"Usando URL di default: {test_url}")

print(f"\n{'='*80}")
print(f"Testing parser su: {test_url}")
print(f"{'='*80}\n")

# Step 1: Get Information Table URL
print("\n[1] Cercando Information Table URL...")
info_table_url = parser.get_information_table_url(test_url)

if info_table_url:
    print(f"✅ Information Table trovata: {info_table_url}")
    
    # Step 2: Parse holdings
    print("\n[2] Parsing holdings...")
    holdings = parser.parse_information_table(info_table_url)
    
    if holdings:
        print(f"✅ Trovate {len(holdings)} holdings")
        print("\nPrime 3 holdings:")
        for i, h in enumerate(holdings[:3], 1):
            print(f"\n  {i}. {h.get('issuer_name', 'N/A')}")
            print(f"     CUSIP: {h.get('cusip', 'N/A')}")
            print(f"     Shares: {h.get('shares', 'N/A')}")
            print(f"     Value: {h.get('value', 'N/A')}")
    else:
        print("❌ Nessuna holding trovata")
else:
    print("❌ Information Table URL non trovata")
    print("\nProva a visitare manualmente l'URL e cerca il file 'Information Table' o XML")

print(f"\n{'='*80}\n")
