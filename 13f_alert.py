import requests
import feedparser
import json
import time
import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import Set, List, Dict
from message_bridge import save_message_to_viewer  # Per visualizzatore locale

# ==================== CONFIGURAZIONE ====================
# IMPORTANTE: Sostituisci questi valori o usa variabili d'ambiente
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8045079991:AAFKUyI0SAjs3m_W8lpCBbbCYJregPCFkuw')  # ← INSERISCI IL TUO TOKEN QUI
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '1434044631')  # ← INSERISCI IL TUO CHAT_ID QUI
USER_AGENT = os.getenv('SEC_USER_AGENT', 'andrea.aita@libero.it')  # ← INSERISCI IL TUO EMAIL QUI

# Configurazioni avanzate
RSS_URL = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=13F-HR&count=100&output=atom'  # 10 per TEST, 100 per PRODUZIONE
LAST_CHECK_FILE = 'last_13f_check_v2.json'
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
POLL_INTERVAL = 30  # 30 secondi per TEST (cambia in 900 per produzione = 15 minuti)
MAX_RETRIES = 3
RETRY_DELAY = 60  # secondi

# Auto-avvio viewer (True = avvia automaticamente, False = solo programma principale)
AUTO_LAUNCH_VIEWER = True  # Cambia in False per disabilitare l'auto-avvio

# Filtro opzionale: aggiungi hedge fund da monitorare (vuoto = tutti)
HEDGE_FUNDS_FILTER = [
    # 'BERKSHIRE HATHAWAY',
    # 'CITADEL',
    # 'RENAISSANCE TECHNOLOGIES',
    # 'BRIDGEWATER'
]

# ==================== SETUP LOGGING ====================
# Gestione logging con fallback se il file è bloccato
log_handlers = [logging.StreamHandler()]

try:
    # Prova ad aprire il file log principale
    log_handlers.append(logging.FileHandler('13f_alerts.log', encoding='utf-8'))
except PermissionError:
    # Se bloccato, usa un file con timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    fallback_log = f'13f_alerts_{timestamp}.log'
    log_handlers.append(logging.FileHandler(fallback_log, encoding='utf-8'))
    print(f"⚠️ File log principale bloccato, uso: {fallback_log}")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

# ==================== FUNZIONI CORE ====================

def launch_telegram_viewer():
    """Avvia il visualizzatore Telegram in una finestra separata"""
    try:
        viewer_path = os.path.join(os.path.dirname(__file__), 'telegram_viewer.py')
        
        if os.path.exists(viewer_path):
            # Avvia in processo separato e COMPLETAMENTE INDIPENDENTE
            if sys.platform == 'win32':
                # Usa pythonw per evitare console extra, o python normale
                # CREATE_NEW_PROCESS_GROUP rende il processo indipendente
                subprocess.Popen(
                    [sys.executable, viewer_path],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    close_fds=True
                )
            else:
                subprocess.Popen(
                    [sys.executable, viewer_path],
                    close_fds=True
                )
            
            logger.info("📱 Telegram Viewer avviato con successo!")
            return True
        else:
            logger.warning(f"⚠️ File {viewer_path} non trovato")
            return False
    except Exception as e:
        logger.error(f"❌ Errore avvio Telegram Viewer: {e}")
        return False

def load_last_seen() -> Set[str]:
    """Carica gli ID dei filing già processati"""
    try:
        with open(LAST_CHECK_FILE, 'r') as f:
            data = json.load(f)
            logger.info(f"Caricati {len(data.get('last_ids', []))} ID dalla cache")
            return set(data.get('last_ids', []))
    except FileNotFoundError:
        logger.warning(f"File {LAST_CHECK_FILE} non trovato, creazione nuovo")
        return set()
    except json.JSONDecodeError:
        logger.error("Errore parsing JSON cache, reset cache")
        return set()

def save_last_seen(last_ids: Set[str]) -> None:
    """Salva gli ID processati (mantiene ultimi 500)"""
    try:
        # Mantieni solo ultimi 500 per evitare file troppo grandi
        ids_to_save = list(last_ids)[-500:] if len(last_ids) > 500 else list(last_ids)
        with open(LAST_CHECK_FILE, 'w') as f:
            json.dump({
                'last_ids': ids_to_save,
                'last_update': datetime.now().isoformat()
            }, f, indent=2)
        logger.info(f"Cache salvata con {len(ids_to_save)} ID")
    except Exception as e:
        logger.error(f"Errore salvataggio cache: {e}")

def send_telegram(message: str, retries: int = MAX_RETRIES) -> bool:
    """Invia notifica Telegram con retry automatico"""
    payload = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    
    for attempt in range(retries):
        try:
            response = requests.post(TELEGRAM_URL, data=payload, timeout=10)
            if response.status_code == 200:
                logger.info("Notifica Telegram inviata con successo")
                return True
            else:
                logger.warning(f"Errore Telegram (tentativo {attempt+1}/{retries}): {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Eccezione Telegram (tentativo {attempt+1}/{retries}): {e}")
        
        if attempt < retries - 1:
            time.sleep(RETRY_DELAY)
    
    logger.error("Fallito invio notifica Telegram dopo tutti i tentativi")
    return False

def fetch_13f_feed(retries: int = MAX_RETRIES) -> feedparser.FeedParserDict:
    """Scarica feed RSS SEC con retry"""
    headers = {'User-Agent': USER_AGENT}
    
    for attempt in range(retries):
        try:
            logger.info(f"Scaricamento feed SEC (tentativo {attempt+1}/{retries})...")
            response = requests.get(RSS_URL, headers=headers, timeout=30)
            
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                logger.info(f"Feed scaricato: {len(feed.entries)} entry trovate")
                return feed
            else:
                logger.warning(f"Errore SEC HTTP {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Eccezione scaricamento feed: {e}")
        
        if attempt < retries - 1:
            time.sleep(RETRY_DELAY)
    
    logger.error("Fallito scaricamento feed dopo tutti i tentativi")
    return feedparser.FeedParserDict()

def should_notify(filer_name: str) -> bool:
    """Verifica se il filer corrisponde ai filtri (se presenti)"""
    if not HEDGE_FUNDS_FILTER:
        return True  # Nessun filtro, notifica tutto
    
    filer_upper = filer_name.upper()
    return any(fund.upper() in filer_upper for fund in HEDGE_FUNDS_FILTER)

def process_feed(feed: feedparser.FeedParserDict, last_seen_ids: Set[str]) -> List[str]:
    """Processa le entry del feed e invia notifiche"""
    new_filings = []
    
    for entry in feed.entries:
        try:
            entry_id = entry.id
            
            # Skip se già visto
            if entry_id in last_seen_ids:
                continue
            
            # Estrai informazioni
            filer = entry.get('author', 'Filer Sconosciuto')
            filing_date = entry.get('updated', 'Data N/A')
            link = entry.get('link', '')
            title = entry.get('title', '')
            
            # Applica filtro
            if not should_notify(filer):
                logger.debug(f"Skippato (filtro): {filer}")
                new_filings.append(entry_id)
                continue
            
            # Formatta messaggio
            message = (
                f"🔔 <b>Nuovo Form 13F-HR Rilevato!</b>\n\n"
                f"📊 <b>Filer:</b> {filer}\n"
                f"📅 <b>Data:</b> {filing_date}\n"
                f"📄 <b>Titolo:</b> {title}\n"
                f"🔗 <b>Link:</b> <a href='{link}'>Visualizza su EDGAR</a>"
            )
            
            # Stampa nel terminal (senza tag HTML per leggibilità)
            console_message = (
                f"\n{'='*60}\n"
                f"🔔 NUOVO FORM 13F-HR RILEVATO!\n"
                f"{'='*60}\n"
                f"📊 Filer: {filer}\n"
                f"📅 Data: {filing_date}\n"
                f"📄 Titolo: {title}\n"
                f"🔗 Link: {link}\n"
                f"{'='*60}"
            )
            logger.info(console_message)
            
            # Salva messaggio per visualizzatore locale
            save_message_to_viewer(message, filer)
            
            # Invia notifica
            if send_telegram(message):
                logger.info(f"✓ Notifica Telegram inviata con successo")
                new_filings.append(entry_id)
            else:
                logger.error(f"✗ Fallita notifica Telegram")
                # Non aggiungiamo a new_filings per ritentare al prossimo ciclo
                
        except Exception as e:
            logger.error(f"Errore processamento entry: {e}")
    
    return new_filings

# ==================== MAIN LOOP ====================

def main():
    """Loop principale del programma"""
    logger.info("=== Avvio 13F Alert System v2.0 ===")
    logger.info(f"Intervallo polling: {POLL_INTERVAL}s ({POLL_INTERVAL/60} minuti)")
    logger.info(f"Filtro attivo: {'SI' if HEDGE_FUNDS_FILTER else 'NO (tutti i filing)'}")
    
    # Avvia Telegram Viewer (se abilitato)
    if AUTO_LAUNCH_VIEWER:
        logger.info("🚀 Avvio Telegram Message Viewer...")
        launch_telegram_viewer()
        time.sleep(2)  # Attendi che il viewer si apra
    else:
        logger.info("ℹ️ Auto-avvio viewer disabilitato (avvia manualmente se necessario)")
    
    # Verifica configurazione
    if BOT_TOKEN == 'YOUR_BOT_TOKEN' or CHAT_ID == 'YOUR_CHAT_ID':
        logger.error("❌ ERRORE: Configura BOT_TOKEN e CHAT_ID!")
        return
    
    if USER_AGENT == 'YourName yourname@email.com':
        logger.warning("⚠️ WARNING: Configura USER_AGENT con il tuo email!")
    
    # Carica cache
    last_seen_ids = load_last_seen()
    
    # Loop infinito
    try:
        while True:
            cycle_start = datetime.now()
            logger.info(f"\n{'='*60}")
            logger.info(f"🔍 Controllo alle {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Scarica feed
            feed = fetch_13f_feed()
            
            if feed.entries:
                # Processa entry
                new_filings = process_feed(feed, last_seen_ids)
                
                # Aggiorna cache
                if new_filings:
                    last_seen_ids.update(new_filings)
                    save_last_seen(last_seen_ids)
                    logger.info(f"📥 Processati {len(new_filings)} nuovi filing")
                else:
                    logger.info("✓ Nessun nuovo filing da notificare")
            else:
                logger.warning("Feed vuoto o non disponibile")
            
            # Attesa prossimo ciclo
            logger.info(f"💤 Prossimo controllo tra {POLL_INTERVAL/60} minuti")
            time.sleep(POLL_INTERVAL)
            
    except KeyboardInterrupt:
        logger.info("\n👋 Arresto programma richiesto dall'utente")
    except Exception as e:
        logger.critical(f"💥 Errore critico: {e}", exc_info=True)
    finally:
        logger.info("=== Fine programma ===")

if __name__ == '__main__':
    main()
