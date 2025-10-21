# 13F Alert System v2.0 - Notifiche Telegram per Form 13F

Sistema automatico di monitoraggio per i filing Form 13F-HR della SEC con notifiche in tempo reale su Telegram.

## 📋 Caratteristiche

- ✅ Monitoraggio globale feed RSS SEC ufficiale
- ✅ Notifiche Telegram istantanee
- ✅ Sistema anti-duplicati con cache persistente
- ✅ Retry automatico per robustezza
- ✅ Logging dettagliato
- ✅ Filtro opzionale per hedge fund specifici
- ✅ Rate limiting SEC-compliant

## 🚀 Installazione

### 1. Requisiti
- Python 3.7 o superiore
- Connessione internet
- Account Telegram

### 2. Installa le dipendenze
```powershell
pip install -r requirements.txt
```

### 3. Configura il Bot Telegram

#### a) Crea il Bot
1. Apri Telegram e cerca `@BotFather`
2. Invia `/newbot` e segui le istruzioni
3. Salva il **Token** che ricevi (es. `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

#### b) Ottieni il Chat ID

**Metodo Semplice (Consigliato):**
1. Apri Telegram e cerca il tuo bot appena creato
2. Clicca "Start" o invia un messaggio (es. `/start`)
3. Cerca `@userinfobot` su Telegram
4. Avvia una conversazione con @userinfobot
5. Ti mostrerà il tuo **Chat ID** (es. `123456789`)

**Metodo Alternativo (Browser):**
1. Avvia una conversazione con il tuo bot e invia un messaggio
2. Visita: `https://api.telegram.org/bot<TUO_TOKEN>/getUpdates`
   - Sostituisci `<TUO_TOKEN>` con il token completo (senza `<>`)
3. Cerca `"chat":{"id":123456789}` nel JSON
4. Salva questo numero come **Chat ID**

### 4. Configura le credenziali

**Opzione A - Nel codice (semplice):**
Modifica `13f_alert_v2.py` alle righe 11-13:
```python
BOT_TOKEN = 'il_tuo_token_del_bot'
CHAT_ID = 'il_tuo_chat_id'
USER_AGENT = 'TuoNome tuo@email.com'
```

**Opzione B - Variabili d'ambiente (più sicuro):**
```powershell
# PowerShell
$env:TELEGRAM_BOT_TOKEN="il_tuo_token"
$env:TELEGRAM_CHAT_ID="il_tuo_chat_id"
$env:SEC_USER_AGENT="TuoNome tuo@email.com"
```

## 🎯 Utilizzo

### Esecuzione Standard (con Visualizzatore Telegram)
Il programma **avvia automaticamente** il visualizzatore Telegram in una finestra separata:

```powershell
# Metodo 1: File batch (doppio click)
start_13f_monitor.bat

# Metodo 2: Python diretto
python 13f_alert.py
```

**Cosa succede:**
1. ✅ Si apre una finestra con il **Telegram Message Viewer** (simula Telegram)
2. ✅ Il programma principale inizia a monitorare nel terminal
3. ✅ Ogni nuovo Form 13F viene mostrato **sia su Telegram che nel viewer locale**

### Solo Visualizzatore (senza monitoraggio)
Se vuoi solo vedere i messaggi salvati in precedenza:
```powershell
python telegram_viewer.py
```

### Esecuzione in Background (Windows)
```powershell
# Senza finestra console
pythonw 13f_alert_v2.py

# Con Task Scheduler (consigliato per avvio automatico)
# 1. Apri Task Scheduler
# 2. Crea Attività Base
# 3. Trigger: All'avvio del sistema
# 4. Azione: Avvia programma -> python.exe
# 5. Argomenti: percorso_completo\13f_alert_v2.py
```

### Fermare il Programma
Premi `Ctrl+C` nel terminale

## ⚙️ Configurazione Avanzata

### Filtrare Hedge Fund Specifici
Modifica la lista `HEDGE_FUNDS_FILTER` nel file (righe 22-27):
```python
HEDGE_FUNDS_FILTER = [
    'BERKSHIRE HATHAWAY',
    'CITADEL',
    'RENAISSANCE TECHNOLOGIES',
    'BRIDGEWATER'
]
```

### Modificare Intervallo di Controllo
```python
POLL_INTERVAL = 900  # 15 minuti (in secondi)
# Esempio: 600 = 10 minuti, 1800 = 30 minuti
```

## 📁 File Generati

- `13f_alerts.log` - Log dettagliato delle operazioni
- `last_13f_check_v2.json` - Cache dei filing già processati

## 🔍 Esempio Output

Quando viene rilevato un nuovo Form 13F, riceverai su Telegram:

```
🔔 Nuovo Form 13F-HR Rilevato!

📊 Filer: BERKSHIRE HATHAWAY INC
📅 Data: 2025-10-21T16:30:00-04:00
📄 Titolo: 13F-HR - BERKSHIRE HATHAWAY INC
🔗 Link: Visualizza su EDGAR
```

## 🛠️ Troubleshooting

### Errore "Configura BOT_TOKEN e CHAT_ID"
- Hai dimenticato di sostituire i placeholder nel codice

### Nessuna notifica ricevuta
1. Verifica che hai avviato una chat con il bot
2. Controlla il file `13f_alerts.log` per errori
3. Testa manualmente: `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=Test`

### Errore "SEC Rate Limit"
- Il programma ha già un delay di 15 minuti (conforme SEC)
- Verifica di aver configurato un USER_AGENT valido con email

### Il programma si chiude inaspettatamente
- Controlla `13f_alerts.log` per l'errore specifico
- Verifica la connessione internet
- Assicurati che le dipendenze siano installate

## 📊 Specifiche SEC

- **Form 13F-HR**: Rapporto trimestrale obbligatorio per investitori istituzionali con >$100M in asset
- **Deadline**: 45 giorni dalla fine di ogni trimestre (Q1: 15 Mag, Q2: 14 Ago, Q3: 14 Nov, Q4: 14 Feb)
- **Feed RSS**: Aggiornato in tempo reale dalla SEC, mostra ultimi 100 filing

## 📝 Note Legali

- Questo software è solo per uso informativo
- I dati provengono da fonti pubbliche SEC (EDGAR)
- Rispetta i Terms of Service SEC: max 10 richieste/secondo
- Non garantito per decisioni di trading

## 🆘 Supporto

Per problemi o domande:
1. Controlla il file `13f_alerts.log`
2. Verifica la documentazione SEC EDGAR
3. Testa la configurazione Telegram manualmente

## 📅 Versione

**v2.0** - Ottobre 2025
- Monitoraggio globale RSS feed
- Sistema retry avanzato
- Logging completo
- Filtri personalizzabili

---

**Buon monitoraggio! 📈**
