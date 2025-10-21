# 📊 13F Holdings Tracker - Documentazione

## Panoramica

Il sistema ora scarica automaticamente e salva le holdings (partecipazioni azionarie) di ogni hedge fund che presenta un Form 13F-HR, salvando tutto in un unico file CSV tracker.

## Come Funziona

### 1. **Rilevamento Nuovo Filing**
Quando viene rilevato un nuovo Form 13F-HR nel feed RSS SEC:

### 2. **Estrazione Link Filing Detail**
Dal messaggio Telegram viene estratto il link al "Filing Detail" (es. `https://www.sec.gov/Archives/edgar/data/754811/000143774925031428/0001437749-25-031428-index.htm`)

### 3. **Download Information Table**
Il sistema:
- Scarica la pagina index del filing
- Cerca il file HTML della "Information Table" (es. `F13InfoTable_78009.html`)
- Scarica questo file HTML

### 4. **Parsing Holdings**
Il parser estrae da ogni riga della tabella:
- **CUSIP**: Identificativo unico del titolo
- **Issuer Name**: Nome dell'azienda
- **Share Class**: Classe di azioni
- **Value (x$1000)**: Valore della posizione in migliaia di dollari
- **Shares**: Numero di azioni possedute
- **Put/Call**: Se è un'opzione (Put, Call, o vuoto)
- **Investment Discretion**: Tipo di discrezionalità
- **Voting Authority**: Diritti di voto (Sole, Shared, None)

### 5. **Salvataggio CSV**
Tutti i dati vengono salvati in `13f_holdings_tracker.csv` con formato:

```csv
filing_date,cik,fund_name,cusip,issuer_name,share_class,value_x1000,shares,put_call,investment_discretion,other_manager,voting_authority_sole,voting_authority_shared,voting_authority_none
2025-10-22,754811,BERKSHIRE HATHAWAY INC,002824100,ABBOTT LABORATORIES,COM,1234567,10000000,,,,,
```

## Struttura CSV Tracker

| Campo | Descrizione |
|-------|-------------|
| `filing_date` | Data del filing 13F |
| `cik` | CIK del fund (identificativo SEC) |
| `fund_name` | Nome dell'hedge fund |
| `cusip` | CUSIP del titolo |
| `issuer_name` | Nome dell'azienda |
| `share_class` | Classe di azioni |
| `value_x1000` | Valore in migliaia di dollari |
| `shares` | Numero di azioni |
| `put_call` | Put/Call se opzione |
| `investment_discretion` | Discrezionalità investimento |
| `other_manager` | Altri manager |
| `voting_authority_sole` | Voti esclusivi |
| `voting_authority_shared` | Voti condivisi |
| `voting_authority_none` | Nessun voto |

## Utilizzo del CSV

### Analisi con Python/Pandas

```python
import pandas as pd

# Carica il tracker
df = pd.read_csv('13f_holdings_tracker.csv')

# Trova tutte le posizioni di Berkshire Hathaway
berkshire = df[df['fund_name'].str.contains('BERKSHIRE', case=False)]

# Top 10 holdings per valore
top_holdings = df.sort_values('value_x1000', ascending=False).head(10)

# Confronta posizioni tra due fund
fund1 = df[df['fund_name'].str.contains('BERKSHIRE', case=False)]
fund2 = df[df['fund_name'].str.contains('CITADEL', case=False)]

# Trova holdings comuni
common_cusips = set(fund1['cusip']) & set(fund2['cusip'])
common_holdings = df[df['cusip'].isin(common_cusips)]
```

### Analisi con Excel

1. Apri `13f_holdings_tracker.csv` in Excel
2. Usa filtri per analizzare:
   - Holdings per fund specifico
   - Posizioni su un titolo specifico (CUSIP)
   - Confronti temporali tra filings
3. Crea tabelle pivot per aggregazioni

### Query SQL

Se importi il CSV in un database:

```sql
-- Top 10 posizioni più grandi
SELECT fund_name, issuer_name, value_x1000, shares
FROM holdings_tracker
ORDER BY value_x1000 DESC
LIMIT 10;

-- Tutti i fund che possiedono AAPL
SELECT DISTINCT fund_name, shares, value_x1000
FROM holdings_tracker
WHERE issuer_name LIKE '%APPLE%'
ORDER BY value_x1000 DESC;

-- Confronta holdings tra date diverse
SELECT 
    filing_date,
    fund_name,
    COUNT(*) as num_positions,
    SUM(value_x1000) as total_value
FROM holdings_tracker
GROUP BY filing_date, fund_name
ORDER BY filing_date DESC;
```

## Configurazione

### File: `13f_alert.py`

```python
# CSV tracker per holdings
HOLDINGS_CSV = '13f_holdings_tracker.csv'
```

## Log e Debugging

Il sistema logga ogni operazione:

```
📊 Processamento holdings per: BERKSHIRE HATHAWAY INC
📄 Trovata Information Table: https://www.sec.gov/...
Parsate 145 holdings dalla Information Table
✓ Salvate 145 holdings nel CSV tracker
✅ Holdings processate con successo per BERKSHIRE HATHAWAY INC
```

### Possibili Warning

- `⚠️ Information Table URL non trovata` - Il filing potrebbe non avere la tabella HTML
- `⚠️ Nessuna holding trovata nel file` - Il parser non ha trovato dati (formato HTML non standard)

## Note Importanti

1. **Formati HTML Variabili**: I file 13F-HR possono avere formati HTML diversi. Il parser è generico ma potrebbe necessitare aggiustamenti per alcuni casi edge.

2. **Rate Limiting SEC**: Il sistema rispetta i rate limits SEC (User-Agent obbligatorio)

3. **Dimensione CSV**: Il file crescerà nel tempo. Considera di:
   - Archiviare periodicamente i dati vecchi
   - Importare in un database per query più efficienti
   - Usare compressione (gzip) per file storici

4. **Validazione Dati**: Verifica sempre i dati scaricati, specialmente:
   - Valori numerici (shares, value)
   - CUSIP validi (9 caratteri alfanumerici)
   - Date filing corrette

## Troubleshooting

### Il CSV non viene creato
- Verifica i permessi di scrittura nella directory
- Controlla i log per errori di parsing
- Verifica che beautifulsoup4 sia installato: `pip install beautifulsoup4`

### Holdings mancanti
- Alcuni filing potrebbero non avere l'Information Table in HTML
- Verifica manualmente il link EDGAR per confermare
- Controlla i log per vedere quale step fallisce

### Dati incompleti
- Il formato HTML potrebbe variare tra filing
- Potrebbe essere necessario aggiustare il parser per casi specifici
- Segnala filing problematici per migliorare il parser

## Roadmap Futuri Miglioramenti

- [ ] Parser XML come fallback (alcuni filing usano XML invece di HTML)
- [ ] Database SQLite invece di CSV per query più efficienti
- [ ] Dashboard web per visualizzare holdings
- [ ] Alert per cambiamenti significativi nelle posizioni
- [ ] Confronto automatico tra filings dello stesso fund
- [ ] Export in formato Excel con formattazione

## Supporto

Per problemi o domande, controlla i log in `13f_alerts.log` e verifica la struttura del filing EDGAR manualmente.
