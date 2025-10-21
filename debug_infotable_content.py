#!/usr/bin/env python3
"""
Debug: scarica e mostra il contenuto dell'infotable
"""

import requests
from bs4 import BeautifulSoup

info_url = "https://www.sec.gov/Archives/edgar/data/1776551/000177655125000003/xslForm13F_X02/infotable.xml"
USER_AGENT = 'andrea.aita@libero.it'

print(f"Scaricamento: {info_url}\n")

headers = {'User-Agent': USER_AGENT}
response = requests.get(info_url, headers=headers, timeout=30)

print(f"Status: {response.status_code}")
print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
print(f"Dimensione: {len(response.content)} bytes\n")

# Mostra primi 2000 caratteri
print("="*80)
print("CONTENUTO (primi 2000 caratteri):")
print("="*80)
print(response.text[:2000])
print("="*80)

# Prova a parsare come HTML
soup = BeautifulSoup(response.content, 'html.parser')

# Cerca tabelle
tables = soup.find_all('table')
print(f"\nTabelle HTML trovate: {len(tables)}")

# Cerca elementi infoTable (XML)
info_tables = soup.find_all('infotable')
print(f"Elementi infoTable (XML) trovati: {len(info_tables)}")

# Cerca shrsOrPrnAmt (tipico tag XML dei 13F)
shares_tags = soup.find_all(['shrsorprnamt', 'shrsOrPrnAmt'])
print(f"Tag shares (XML) trovati: {len(shares_tags)}")

if shares_tags:
    print("\nPrimo share tag:")
    print(shares_tags[0].prettify()[:500])
