"""
Message Bridge - Intercetta e salva i messaggi per il visualizzatore
"""
import json
import os
from datetime import datetime

MESSAGE_LOG_FILE = 'telegram_messages.json'

def save_message_to_viewer(message_html, filer_name=""):
    """Salva il messaggio per il visualizzatore Telegram"""
    try:
        # Carica messaggi esistenti
        if os.path.exists(MESSAGE_LOG_FILE):
            with open(MESSAGE_LOG_FILE, 'r', encoding='utf-8') as f:
                messages = json.load(f)
        else:
            messages = []
        
        # Aggiungi nuovo messaggio
        messages.append({
            'timestamp': datetime.now().isoformat(),
            'filer': filer_name,
            'message': message_html
        })
        
        # Mantieni solo ultimi 100 messaggi
        messages = messages[-100:]
        
        # Salva
        with open(MESSAGE_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
        
        return True
    except Exception as e:
        print(f"Errore salvataggio messaggio per viewer: {e}")
        return False
