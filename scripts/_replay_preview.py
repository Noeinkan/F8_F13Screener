import sqlite3
conn = sqlite3.connect(r'C:\Users\andre\Downloads\F8_F13Screener\src\core\data\13f_holdings.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

rows = cur.execute("""
    SELECT entry_id, filer_name, cik, filing_date, acceptance_datetime
    FROM seen_filings
    WHERE matched = 1
      AND cik IS NOT NULL AND cik != ''
      AND filing_date >= date('now', '-60 day')
    ORDER BY filing_date ASC
""").fetchall()

# Derive accession = last ':' segment of entry_id (always 'NNNNNNNNNN-NN-NNNNNN').
def accession_of(eid: str) -> str:
    return eid.rsplit(':', 1)[-1] if eid else ''

with_h = []
no_h = []
for r in rows:
    acc = accession_of(r['entry_id'])
    has = cur.execute("SELECT COUNT(*) FROM holdings WHERE accession_number = ?", (acc,)).fetchone()[0]
    if has:
        with_h.append((r['filing_date'], r['cik'], r['filer_name'], acc, has))
    else:
        no_h.append((r['filing_date'], r['cik'], r['filer_name'], acc))

print('=== With-holdings (will include portfolio diff) ===')
for fd, cik, fn, acc, n in with_h:
    print(f'  {fd} | {cik} | {fn:<40} | acc={acc} | rows={n}')
print(f'  count: {len(with_h)}')

print()
print('=== Without-holdings (filing-detected only) ===')
for fd, cik, fn, acc in no_h:
    print(f'  {fd} | {cik} | {fn:<40} | acc={acc}')
print(f'  count: {len(no_h)}')

print()
print(f'TOTAL candidates: {len(rows)}  (with-holdings: {len(with_h)} | without-holdings: {len(no_h)})')
