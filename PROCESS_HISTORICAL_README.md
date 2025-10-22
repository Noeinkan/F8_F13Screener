# 📊 Process Historical 13F - Guida Completa

## 🎯 Obiettivo

Script unificato per **scaricare automaticamente** tutti i filing 13F-HR degli ultimi 5 anni per i tuoi hedge funds monitorati.

## 🔧 Caratteristiche

✅ **Completamente automatico** - Non serve Telegram o input manuale  
✅ **Usa configurazione centralizzata** - Lista funds da `hedge_funds_config.py`  
✅ **Periodo fisso** - Ultimi 5 anni (dal 2020-01-01 ad oggi)  
✅ **3 modalità** - Catalog, Holdings, o Full pipeline  
✅ **Rate limiting integrato** - Rispetta limiti SEC (10 req/sec)  
✅ **Progress tracking** - Statistiche dettagliate in tempo reale  

---

## 📋 Prerequisiti

### File richiesti:
- `hedge_funds_config.py` - Lista hedge funds con CIK
- `13f_alert.py` - Per estrazione holdings (solo modalità holdings/full)

### Hedge funds monitorati:
Attualmente: **43 hedge funds** (25 value + 18 growth/tech)

---

## 🚀 Uso

### 1️⃣ Modalità CATALOG (veloce)
Scarica solo la lista dei filing disponibili (metadati).

```bash
python process_historical_13f.py catalog
```

**Output:** `historical_13f_catalog_5years.json`  
**Tempo:** ~5 minuti per 43 funds  
**Contenuto:** Lista filing con CIK, date, URL, accession number  

### 2️⃣ Modalità HOLDINGS (lento)
Estrae holdings dettagliate da un catalogo esistente.

```bash
python process_historical_13f.py holdings
```

**Prerequisiti:** Deve esistere `historical_13f_catalog_5years.json`  
**Output:** `13f_holdings_5years.csv`  
**Tempo:** ~1-2 ore (dipende da quanti filing ci sono)  
**Contenuto:** CSV con ticker, shares, value, filing date, fund name  

### 3️⃣ Modalità FULL (automatico)
Esegue catalog + holdings in sequenza senza interruzioni.

```bash
python process_historical_13f.py full
```

**Output:** Entrambi i file sopra  
**Tempo:** ~30-90 minuti totali  
**Ideale per:** Prima esecuzione o refresh completo  

---

## 📂 Output Files

### 📄 `historical_13f_catalog_5years.json`
```json
{
  "generated_at": "2025-10-22T21:27:27.404731",
  "total_filings": 1200,
  "total_funds": 43,
  "cutoff_date": "2020-01-01",
  "filings": [
    {
      "cik": "0001061768",
      "fund_name": "Baupost Group (Seth Klarman)",
      "form": "13F-HR",
      "filing_date": "2025-02-14",
      "accession_number": "0001061768-25-000005",
      "filing_url": "https://www.sec.gov/Archives/edgar/data/..."
    }
  ]
}
```

### 📊 `13f_holdings_5years.csv`
```csv
filing_date,fund_name,cik,ticker,cusip,shares,value,percentage
2025-02-14,Baupost Group,0001061768,AAPL,037833100,5000000,850000000,2.5
2025-02-14,Baupost Group,0001061768,GOOGL,02079K305,1200000,450000000,1.3
...
```

---

## 🔄 Workflow Tipico

### Prima Volta (Setup Iniziale)
```bash
# Scarica tutto in automatico
python process_historical_13f.py full
```

### Aggiornamento Periodico
```bash
# Solo catalog (veloce) per vedere nuovi filing
python process_historical_13f.py catalog

# Poi holdings se ci sono nuovi filing interessanti
python process_historical_13f.py holdings
```

---

## ⚙️ Configurazione

### Modificare il periodo temporale
Apri `process_historical_13f.py` e modifica:

```python
CUTOFF_DATE = '2020-01-01'  # Cambia questa data
```

Esempi:
- `'2023-01-01'` - Solo ultimi 2 anni
- `'2018-01-01'` - Ultimi 7 anni
- `'2015-01-01'` - Ultimi 10 anni

### Aggiungere/rimuovere hedge funds
Modifica `hedge_funds_config.py`:

```python
HEDGE_FUNDS_CIK = {
    '0001234567': 'Nuovo Fund (Manager Name)',
    # ...
}
```

---

## 📊 Statistiche Tipiche

### Per 43 hedge funds, ultimi 5 anni:

| Metrica | Valore Tipico |
|---------|---------------|
| Filing totali | ~1000-1500 |
| Holdings totali | ~50,000-100,000 |
| Top fund per filing | ~80-100 filing |
| Ticker unici | ~3,000-5,000 |

### Rate Limiting:
- **API SEC:** 10 req/sec → pausa 0.11s
- **HTML Parsing:** 6-7 req/sec → pausa 0.15s

---

## 🐛 Troubleshooting

### ❌ "Modulo 13f_alert.py non disponibile"
**Soluzione:** Modalità `holdings` e `full` richiedono `13f_alert.py`. Usa solo `catalog` se non disponibile.

### ❌ "File catalogo non trovato"
**Soluzione:** Per modalità `holdings`, esegui prima `catalog`.

### ❌ "HTTP 403 Forbidden"
**Soluzione:** Controlla `SEC_USER_AGENT` nelle variabili d'ambiente o in `process_historical_13f.py`.

### ⚠️ Holdings vuote per alcuni filing
**Normale:** Alcuni filing potrebbero non avere Information Table accessibile o formato diverso.

---

## 🎓 Analisi Dati

### Con Python/Pandas:
```python
import pandas as pd

# Carica holdings
df = pd.read_csv('13f_holdings_5years.csv')

# Analisi
print(f"Total holdings: {len(df)}")
print(f"Unique tickers: {df['ticker'].nunique()}")
print(f"Unique funds: {df['fund_name'].nunique()}")

# Top 10 posizioni per valore
top_holdings = df.nlargest(10, 'value')
print(top_holdings[['fund_name', 'ticker', 'shares', 'value']])

# Holdings per fund
by_fund = df.groupby('fund_name')['value'].sum().sort_values(ascending=False)
print(by_fund)
```

### Con Excel:
1. Apri `13f_holdings_5years.csv` in Excel
2. Usa Tabelle Pivot per analizzare
3. Filtra per ticker, fund, o data

---

## 🔗 File Correlati

| File | Scopo |
|------|-------|
| `hedge_funds_config.py` | Lista hedge funds (configurazione) |
| `13f_alert.py` | Monitoraggio real-time + parsing holdings |
| `download_historical_13f.py` | Script vecchio (deprecato) |
| `backfill_holdings.py` | Script vecchio (deprecato) |

---

## ✨ Vantaggi vs Script Vecchi

| Feature | Script Vecchi | process_historical_13f.py |
|---------|---------------|---------------------------|
| Dipendenze | Telegram messages | Solo hedge_funds_config.py |
| Modalità | Separate | 3 in 1 |
| Workflow | Manuale | Automatico |
| Statistiche | Basiche | Dettagliate |
| Help | Nessuno | `--help` integrato |
| Progress | Minimo | Real-time con emoji |

---

## 📞 Support

Per problemi o domande:
1. Controlla la sezione Troubleshooting
2. Verifica i log di output dello script
3. Controlla che `hedge_funds_config.py` sia aggiornato

---

**🎉 Buona analisi dei filing 13F-HR!**
