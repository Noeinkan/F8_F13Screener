import pandas as pd

csv_path = r'D:\03_Coding\F8_F13Screener\src\core\data\historical\holdings\13f_holdings_5years.csv'

print('Caricamento CSV...')
df = pd.read_csv(csv_path, nrows=1000)

print(f'\n{"="*70}')
print(f'ANALISI CSV - Prime 1000 righe')
print(f'{"="*70}')
print(f'\nRighe caricate: {len(df)}')
print(f'Colonne totali: {len(df.columns)}')

print(f'\n{"="*70}')
print('COLONNE PROBLEMATICHE (precedentemente vuote)')
print(f'{"="*70}\n')

cols_to_check = [
    'FIGI',
    'Value ($)',
    'Shares/Principal Amount',
    'SH/PRN',
    'Put/Call',
    'Investment Discretion',
    'Other Manager',
    'Other Managers (raw)'
]

for col in cols_to_check:
    if col in df.columns:
        non_empty = df[col].notna().sum()
        non_empty_non_blank = df[col].fillna('').astype(str).str.strip().ne('').sum()
        pct = (non_empty_non_blank / len(df) * 100)
        
        status = '✅' if pct > 80 else '⚠️' if pct > 20 else '❌'
        
        print(f'{status} {col:32s}: {non_empty_non_blank:4d}/{len(df):4d} ({pct:5.1f}%)')
    else:
        print(f'❓ {col:32s}: COLONNA NON TROVATA')

print(f'\n{"="*70}')
print('ESEMPI DI VALORI (primi 5 non vuoti per colonna)')
print(f'{"="*70}')

for col in cols_to_check:
    if col in df.columns:
        print(f'\n📊 {col}:')
        non_empty = df[df[col].notna() & (df[col].astype(str).str.strip() != '')]
        if len(non_empty) > 0:
            for i, (idx, row) in enumerate(non_empty.head(5).iterrows(), 1):
                val = row[col]
                issuer = row.get('Name of Issuer', 'N/A')[:40]
                print(f'   {i}. {val} (Issuer: {issuer})')
        else:
            print('   ❌ Nessun valore trovato')
    else:
        print(f'\n❓ {col}: COLONNA NON TROVATA NEL CSV')

print(f'\n{"="*70}')
print('RIEPILOGO')
print(f'{"="*70}')
print(f'\nSe le colonne sono ancora vuote, significa che i filing SEC')
print(f'non contengono questi dati nei tag XML/HTML che stiamo parsando.')
print(f'\nPer verificare, controlla un filing specifico su SEC.gov')
