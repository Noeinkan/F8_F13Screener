"""
Message Bridge - Intercetta e salva i messaggi per il visualizzatore
"""
import json
import os
from datetime import datetime
from src.core.paths import MESSAGE_LOG_FILE

def save_message_to_viewer(message_html, filer_name=""):
    """Salva il messaggio per il visualizzatore Telegram"""
    try:
        # Carica messaggi esistenti
        messages = []
        if os.path.exists(MESSAGE_LOG_FILE):
            try:
                # Prova a leggere con un timeout breve
                import time
                for attempt in range(3):
                    try:
                        with open(MESSAGE_LOG_FILE, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                            if content:  # Solo se il file non è vuoto
                                messages = json.loads(content)
                            else:
                                messages = []
                        break  # Successo, esci dal loop
                    except PermissionError:
                        if attempt < 2:
                            time.sleep(0.1)  # Aspetta 100ms e riprova
                        else:
                            raise  # Ultima tentativo fallito
            except (json.JSONDecodeError, ValueError):
                # Se il file è corrotto, ricomincia da zero
                messages = []
            except PermissionError:
                # File bloccato, salta questo salvataggio
                print("⚠️ File messaggi temporaneamente bloccato, messaggio salvato su Telegram")
                return False
        
        # Aggiungi nuovo messaggio
        messages.append({
            'timestamp': datetime.now().isoformat(),
            'filer': filer_name,
            'message': message_html
        })
        
        # Mantieni solo ultimi 100 messaggi
        messages = messages[-100:]
        
        # Salva con retry
        import time
        for attempt in range(3):
            try:
                with open(MESSAGE_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(messages, f, indent=2, ensure_ascii=False)
                return True
            except PermissionError:
                if attempt < 2:
                    time.sleep(0.1)  # Aspetta 100ms e riprova
                else:
                    print("⚠️ Impossibile salvare messaggio nel viewer (file bloccato)")
                    return False
        
        return True
    except Exception as e:
        print(f"Errore salvataggio messaggio per viewer: {e}")
        return False
