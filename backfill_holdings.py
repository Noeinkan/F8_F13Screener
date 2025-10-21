#!/usr/bin/env python3
"""
Script per processare retroattivamente i filing già rilevati
e popolare il CSV tracker con le loro holdings
"""

import json
import re
import time
import importlib.util
import os
from typing import Optional

# Carica il modulo 13f_alert
spec = importlib.util.spec_from_file_location("alert_module", "13f_alert.py")
alert_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alert_module)

process_filing_holdings = alert_module.process_filing_holdings
extract_cik_from_link = alert_module.extract_cik_from_link
logger = alert_module.logger

def extract_link_from_message(message: str) -> Optional[str]:
    """Estrae l'URL del filing dal messaggio HTML"""
    match = re.search(r"href='([^']+)'", message)
    if match:
        return match.group(1)
    return None

def extract_date_from_message(message: str) -> str:
    """Estrae la data dal messaggio"""
    match = re.search(r'<b>Data:</b> ([^<\n]+)', message)
    if match:
        return match.group(1).split('T')[0]  # Solo la data, non l'ora
    return "N/A"

def main():
    print("="*80)
    print("PROCESSAMENTO RETROATTIVO FILING 13F-HR")
    print("="*80)
    print("\nQuesto script processa tutti i filing già rilevati e salva")
    print("le loro holdings nel CSV tracker.\n")
    
    # Carica messaggi salvati
    if not os.path.exists('telegram_messages.json'):
        print("❌ File telegram_messages.json non trovato!")
        return
    
    with open('telegram_messages.json', 'r', encoding='utf-8') as f:
        messages = json.load(f)
    
    print(f"📨 Trovati {len(messages)} messaggi salvati\n")
    
    # Chiedi conferma
    print("⚠️  ATTENZIONE: Questo scaricherà holdings da SEC per tutti i filing.")
    print("   Potrebbero volerci diversi minuti e molte richieste HTTP.\n")
    
    risposta = input("Vuoi procedere? (s/n): ").lower()
    if risposta != 's':
        print("\n❌ Operazione annullata.")
        return
    
    print("\n" + "="*80)
    print("INIZIO PROCESSAMENTO")
    print("="*80 + "\n")
    
    successi = 0
    falliti = 0
    skipped = 0
    
    for i, msg_data in enumerate(messages, 1):
        print(f"\n[{i}/{len(messages)}] Processamento...")
        
        message = msg_data.get('message', '')
        filer = msg_data.get('filer', 'Filer Sconosciuto')
        
        # Estrai URL
        filing_url = extract_link_from_message(message)
        if not filing_url:
            print(f"  ⚠️  Skipped: {filer} (URL non trovato)")
            skipped += 1
            continue
        
        # Estrai data
        filing_date = extract_date_from_message(message)
        
        print(f"  📊 {filer}")
        print(f"  📅 {filing_date}")
        print(f"  🔗 {filing_url[:60]}...")
        
        # Processa holdings
        try:
            success = process_filing_holdings(filing_url, filer, filing_date)
            if success:
                print(f"  ✅ Holdings salvate")
                successi += 1
            else:
                print(f"  ⚠️  Nessuna holding trovata")
                falliti += 1
        except Exception as e:
            print(f"  ❌ Errore: {e}")
            falliti += 1
        
        # Rate limiting SEC (max 10 req/sec)
        if i < len(messages):
            time.sleep(0.15)  # ~6-7 req/sec per sicurezza
    
    # Riepilogo
    print("\n" + "="*80)
    print("RIEPILOGO FINALE")
    print("="*80)
    print(f"✅ Successi:      {successi}")
    print(f"❌ Falliti:       {falliti}")
    print(f"⚠️  Skipped:       {skipped}")
    print(f"📊 Totale:        {len(messages)}")
    print("="*80)
    
    if successi > 0:
        csv_path = alert_module.HOLDINGS_CSV
        if os.path.exists(csv_path):
            print(f"\n✅ CSV tracker creato: {csv_path}")
            print(f"   Puoi aprirlo con Excel o Python/Pandas per analizzarlo")
        else:
            print(f"\n⚠️  CSV non trovato (probabilmente nessuna holding valida)")
    
    print("\n🎉 Processamento completato!\n")

if __name__ == '__main__':
    main()
