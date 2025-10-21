#!/usr/bin/env python3
"""
Test script per verificare il download e parsing delle holdings
"""

import sys
import os
import importlib.util

# Carica il modulo 13f_alert
spec = importlib.util.spec_from_file_location("alert_module", os.path.join(os.path.dirname(__file__), "13f_alert.py"))
alert_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alert_module)

get_information_table_url = alert_module.get_information_table_url
parse_information_table = alert_module.parse_information_table
save_holdings_to_csv = alert_module.save_holdings_to_csv
logger = alert_module.logger

def test_filing(filing_url: str, fund_name: str = "TEST FUND"):
    """
    Testa il download e parsing di un filing
    """
    print(f"\n{'='*70}")
    print(f"TEST: {fund_name}")
    print(f"URL: {filing_url}")
    print(f"{'='*70}\n")
    
    # Step 1: Trova Information Table URL
    print("📥 Step 1: Ricerca Information Table URL...")
    info_table_url = get_information_table_url(filing_url)
    
    if not info_table_url:
        print("❌ ERRORE: Information Table URL non trovata!")
        return False
    
    print(f"✅ Trovata: {info_table_url}\n")
    
    # Step 2: Parsa holdings
    print("📊 Step 2: Parsing holdings...")
    holdings = parse_information_table(info_table_url)
    
    if not holdings:
        print("❌ ERRORE: Nessuna holding parsata!")
        return False
    
    print(f"✅ Parsate {len(holdings)} holdings\n")
    
    # Step 3: Mostra prime 5 holdings
    print("📋 Prime 5 holdings:")
    print("-" * 70)
    for i, holding in enumerate(holdings[:5], 1):
        print(f"{i}. {holding.get('issuer_name', 'N/A')}")
        print(f"   CUSIP: {holding.get('cusip', 'N/A')}")
        print(f"   Shares: {holding.get('shares', 'N/A')}")
        print(f"   Value: ${holding.get('value_x1000', 'N/A')}k")
        print()
    
    if len(holdings) > 5:
        print(f"... e altre {len(holdings) - 5} holdings\n")
    
    # Step 4: Salva CSV
    print("💾 Step 4: Salvataggio CSV (test)...")
    test_csv = "test_holdings.csv"
    # Usa una funzione temporanea per test
    import csv
    with open(test_csv, 'w', newline='', encoding='utf-8') as f:
        if holdings:
            writer = csv.DictWriter(f, fieldnames=list(holdings[0].keys()))
            writer.writeheader()
            writer.writerows(holdings)
    print(f"✅ Salvato in {test_csv}\n")
    
    print(f"{'='*70}")
    print("✅ TEST COMPLETATO CON SUCCESSO!")
    print(f"{'='*70}\n")
    
    return True

if __name__ == "__main__":
    # Test con un filing reale dall'elenco
    # Puoi modificare questo URL con qualsiasi filing detail che vuoi testare
    
    # Esempio 1: Charles Schwab Trust Bank
    test_url = "https://www.sec.gov/Archives/edgar/data/1776551/000177655125000003/0001776551-25-000003-index.htm"
    
    print("\n🧪 AVVIO TEST HOLDINGS PARSER\n")
    
    success = test_filing(test_url, "Charles Schwab Trust Bank")
    
    if success:
        print("\n✅ Tutti i test superati!")
        sys.exit(0)
    else:
        print("\n❌ Test falliti - controlla i log sopra")
        sys.exit(1)
