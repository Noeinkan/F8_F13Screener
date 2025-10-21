#!/usr/bin/env python3
"""
Script per forzare il re-processing di N filing recenti
"""

import json
import importlib.util
import os
import sys

# Numero di filing da re-processare
NUM_FILINGS = int(sys.argv[1]) if len(sys.argv) > 1 else 5

print(f"🔄 Rimozione ultimi {NUM_FILINGS} filing dalla cache...")

# Carica cache
with open('last_13f_check_v2.json', 'r') as f:
    data = json.load(f)

last_ids = data.get('last_ids', [])
print(f"📊 ID in cache: {len(last_ids)}")

# Rimuovi ultimi N
if len(last_ids) >= NUM_FILINGS:
    removed = last_ids[-NUM_FILINGS:]
    last_ids = last_ids[:-NUM_FILINGS]
    
    # Salva cache aggiornata
    data['last_ids'] = last_ids
    with open('last_13f_check_v2.json', 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Rimossi {len(removed)} ID dalla cache")
    print(f"📊 ID rimanenti: {len(last_ids)}")
    print(f"\n🚀 Ora esegui: python 13f_alert.py")
    print(f"   I filing rimossi verranno ri-processati e il CSV verrà creato!")
else:
    print(f"⚠️  Cache ha solo {len(last_ids)} ID, impossibile rimuovere {NUM_FILINGS}")
