# 📊 Sistema Completo per Download Filing 13F Storici

## 🎯 Panoramica

Hai ora un sistema completo per:
1. ✅ **Monitorare** i nuovi filing 13F in tempo reale (25 hedge funds value)
2. ✅ **Scaricare** tutti i filing 13F storici (1,933 filing trovati dal 1999 ad oggi!)
3. ✅ **Estrarre** tutte le holdings da ogni filing

---

## 📁 File del Sistema

### File Principali:
- `13f_alert.py` - Monitoraggio real-time con filtro CIK
- `download_historical_13f.py` - Trova tutti i filing storici via SEC API
- `process_historical_holdings.py` - Scarica holdings da tutti i filing storici

### File di Supporto:
- `test_cik_filter.py` - Test del filtro CIK
- `check_recent_filings.py` - Verifica filing nel feed RSS
- `check_historical_filings.py` - Analizza CSV storico

### File di Output:
- `historical_13f_catalog.json` - Catalogo completo di 1,933 filing (✅ GIÀ GENERATO)
- `13f_holdings_historical_complete.csv` - Holdings complete da tutti i filing storici
- `13f_holdings_tracker.csv` - Holdings da monitoraggio real-time
- `last_13f_check_v2.json` - Cache del monitoraggio

---

## 🚀 Come Usare il Sistema

### **STEP 1: Monitoraggio Real-Time** ⏰

Avvia il monitoraggio continuo per i nuovi filing:

```powershell
python 13f_alert.py
```

**Cosa fa:**
- ✅ Controlla il feed SEC ogni 30 secondi (cambia `POLL_INTERVAL` per produzione)
- ✅ Filtra SOLO i 25 hedge funds tramite CIK (nessun falso positivo)
- ✅ Invia notifiche Telegram quando trova match
- ✅ Scarica automaticamente le holdings e le salva in `13f_holdings_tracker.csv`
- ✅ Avvia il Telegram Viewer per visualizzare i messaggi localmente

**Quando usarlo:**
- Per ricevere notifiche in tempo reale dei nuovi filing Q3 2025 (in arrivo entro 14 novembre)
- Per monitoraggio continuo nel tempo

---

### **STEP 2: Download Filing Storici** 📥

**GIÀ FATTO!** Hai già il catalogo con 1,933 filing in `historical_13f_catalog.json`

Se vuoi rigenerarlo:

```powershell
python download_historical_13f.py
```

**Output:**
- ✅ `historical_13f_catalog.json` con metadata di tutti i filing
- ✅ Include: CIK, nome fund, data filing, accession number, URL diretto

**Statistiche trovate:**
- 📊 **1,933 filing totali** dal 1999-05-12 al 2025-08-14
- 🏆 **Top fund**: Oaktree Capital (169 filing in 26 anni!)
- 📅 **Range**: Oltre 26 anni di storia completa

---

### **STEP 3: Estrazione Holdings Storiche** 💾

**ATTENZIONE:** Questo processo scarica **1,933 filing** dalla SEC!

```powershell
python process_historical_holdings.py
```

**Cosa fa:**
1. Legge il catalogo `historical_13f_catalog.json`
2. Per ogni filing:
   - Scarica la pagina index
   - Trova l'Information Table
   - Estrae tutte le holdings (nome, CUSIP, shares, value, etc.)
   - Salva tutto in `13f_holdings_historical_complete.csv`
3. Rate limiting automatico (5 req/sec per non sovraccaricare SEC)

**Stima tempo:** ~65 minuti (con rate limit conservativo di 0.2s/filing)

**Output finale:**
- ✅ CSV gigante con TUTTE le holdings storiche
- ✅ Formato identico a quello del monitoraggio real-time
- ✅ Pronto per analisi in Excel, Python, Power BI, etc.

**Dimensione stimata:**
- ~500,000 - 1,000,000+ righe (dipende dalle holdings per filing)
- ~100-200 MB di dati

---

## 📊 I Tuoi 25 Hedge Funds Monitorati

| # | CIK | Hedge Fund | Filing Storici |
|---|-----|------------|----------------|
| 1 | 0001061768 | Baupost Group (Seth Klarman) | 105 |
| 2 | 0001649339 | Scion Asset Management (Michael Burry) | 32 |
| 3 | 0001656456 | Appaloosa Management (David Tepper) | 38 |
| 4 | 0000905567 | Yacktman Asset Management | 109 |
| 5 | 0001336528 | Pershing Square Capital (Bill Ackman) | 94 |
| 6 | 0001079114 | Greenlight Capital (David Einhorn) | 105 |
| 7 | 0001056831 | Fairholme Capital (Bruce Berkowitz) | 111 |
| 8 | 0000732905 | Tweedy Browne Company | 111 |
| 9 | 0001099281 | Third Avenue Management | 93 |
| 10 | 0000949509 | Oaktree Capital Management (Howard Marks) | 169 |
| 11 | 0001549575 | Pabrai Investment Funds (Mohnish Pabrai) | 55 |
| 12 | 0001404599 | Aquamarine Capital (Guy Spier) | 32 |
| 13 | 0000860643 | Gardner Russo & Gardner (Tom Russo) | 113 |
| 14 | 0000906304 | Royce Investment Partners (Chuck Royce) | 37 |
| 15 | 0000807985 | Southeastern Asset Management | 100 |
| 16 | 0001351069 | ValueAct Capital | 7 |
| 17 | 0001040273 | Third Point LLC (Dan Loeb) | 114 |
| 18 | 0001709323 | Himalaya Capital (Li Lu) | 31 |
| 19 | 0001568820 | Arlington Value Capital (Allan Mecham) | 30 |
| 20 | 0001112520 | Akre Capital Management (Chuck Akre) | 121 |
| 21 | 0001641864 | Giverny Capital | 50 |
| 22 | 0001360079 | Wintergreen Advisers | 51 |
| 23 | 0001218254 | Boyar Asset Management | 92 |
| 24 | 0001056823 | Horizon Kinetics | 17 |
| 25 | 0001039565 | Kahn Brothers | 116 |

**TOTALE: 1,933 filing dal 1999 ad oggi**

---

## 🔍 Formato URL EDGAR

Gli URL dei filing seguono questo pattern:

```
https://www.sec.gov/Archives/edgar/data/{filer_CIK}/{accession_no_dashes}/{accession_with_dashes}-index.htm
```

**Esempio:**
```
https://www.sec.gov/Archives/edgar/data/1061768/000106176825000005/0001061768-25-000005-index.htm
```

**Dove:**
- `1061768` = CIK del filer (Baupost Group)
- `000106176825000005` = Accession number senza trattini
- `0001061768-25-000005` = Accession number con trattini
- `-index.htm` = Pagina index del filing

---

## 📈 Possibili Analisi

Con i dati storici completi puoi fare analisi tipo:

### 1. **Portfolio Evolution**
Vedi come le holdings di un fund cambiano nel tempo:
- Quando Burry ha comprato/venduto
- Posizioni top di Ackman nei vari trimestri
- Concentrazione del portfolio di Pabrai

### 2. **Consensus Picks**
Trova azioni detenute da più hedge funds:
- "Quali titoli hanno in comune Buffett-style investors?"
- Best ideas condivise

### 3. **Performance Backtest**
Confronta le scelte dei value investors con il mercato:
- Stocks picked in 2020 vs performance 2020-2025
- Hit rate dei vari fund managers

### 4. **Sector Allocation**
Analizza esposizione settoriale:
- Tech vs Value vs Energy
- Come cambia nel tempo

### 5. **New Positions**
Identifica nuove posizioni appena aperte:
- Confronta Q3 vs Q2
- Trova i "13F whales" che comprano nuove azioni

---

## ⚙️ Configurazione Avanzata

### Rate Limiting

SEC permette max **10 req/sec**. Il sistema usa:
- `download_historical_13f.py`: 0.11s delay (9 req/sec)
- `process_historical_holdings.py`: 0.2s delay (5 req/sec) - conservativo

### Filtri Personalizzati

Per aggiungere/rimuovere hedge funds, modifica in `13f_alert.py`:

```python
HEDGE_FUNDS_CIK_FILTER = {
    '0001061768': 'Baupost Group (Seth Klarman)',
    # Aggiungi qui altri CIK...
}
```

### Intervallo Polling

Per produzione, cambia in `13f_alert.py`:

```python
POLL_INTERVAL = 900  # 15 minuti invece di 30 secondi
```

---

## 🎓 Note Tecniche

### Perché Filtro per CIK è Meglio

**PRIMA (filtro per nome):**
- ❌ "CAPITAL" matchava "RANDOM CAPITAL CORP"
- ❌ "THIRD POINT" matchava "THIRD STREET CAPITAL"
- ❌ Falsi positivi continui

**ADESSO (filtro per CIK):**
- ✅ CIK è univoco e immutabile
- ✅ Zero falsi positivi
- ✅ Non dipende da variazioni del nome legale

### Struttura Accession Number

Formato: `{submitter_CIK_10_digit}-{YY}-{sequence}`

**Esempio:** `0001172661-25-003151`
- `0001172661` = CIK del filing agent (Adviser Compliance Associates)
- `25` = Anno 2025
- `003151` = Numero sequenziale

**Nota:** Il submitter CIK può essere diverso dal filer CIK se usa un agent!

---

## 🚨 Prossime Scadenze

| Trimestre | Fine Periodo | Scadenza Filing | Status |
|-----------|--------------|-----------------|--------|
| Q1 2025 | 31 Marzo | 15 Maggio | ✅ Completato |
| Q2 2025 | 30 Giugno | 14 Agosto | ✅ Completato |
| **Q3 2025** | **30 Settembre** | **14 Novembre 2025** | ⏳ **IN ARRIVO** |
| Q4 2025 | 31 Dicembre | 14 Febbraio 2026 | - |

**Il tuo sistema è pronto per catturare i filing Q3 quando arriveranno!**

---

## 📞 Supporto

**File di Log:**
- `13f_alerts.log` - Log del monitoraggio real-time

**File di Test:**
- `test_cik_filter.py` - Verifica che il filtro CIK funzioni
- `check_recent_filings.py` - Vedi cosa c'è nel feed RSS ora

**Backup:**
- Sempre salvato automaticamente prima di cancellare CSV

---

## ✅ Checklist Finale

Prima di processare gli storici:

- [x] Catalogo generato (`historical_13f_catalog.json` con 1,933 filing)
- [x] Filtro CIK testato e funzionante
- [x] Sistema di rate limiting configurato
- [x] Spazio su disco sufficiente (~200MB per CSV finale)
- [ ] **PRONTO PER STEP 3**: Esegui `process_historical_holdings.py`

---

**Creato:** 22 Ottobre 2025  
**Sistema:** 13F Alert & Historical Download v2.0  
**Hedge Funds:** 25 Value Investing Icons  
**Filing Disponibili:** 1,933 (1999-2025)
