from src.core.parser import HoldingsParser
import json

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
filing_url = 'https://www.sec.gov/Archives/edgar/data/2045724/000204572426000008/0002045724-26-000008-index.htm'

try:
    parser = HoldingsParser(USER_AGENT)
    print(f'Finding info table URL for: {filing_url}')
    info_table_url = parser.get_information_table_url(filing_url)
    if not info_table_url:
        print('Failed to find Information Table URL')
        exit(1)
    
    print(f'Parsing info table: {info_table_url}')
    holdings = parser.parse_information_table(info_table_url)
    print(f'SUCCESS: Parsed {len(holdings)} holdings.')
except Exception as e:
    print(f'EXCEPTION: {str(e)}')
    import traceback
    traceback.print_exc()
