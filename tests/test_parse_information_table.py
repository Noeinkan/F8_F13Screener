import os
import tempfile
import requests
import pytest
from bs4 import BeautifulSoup
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# We'll import the function under test
from src.core.parser import HoldingsParser
import os

USER_AGENT = os.getenv('SEC_USER_AGENT', 'test@example.com')
parser = HoldingsParser(USER_AGENT)

SAMPLE_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<informationTable>
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>123456789</cusip>
    <value>1000</value>
    <shrsOrPrn>
      <sshPrnamt>500</sshPrnamt>
    </shrsOrPrn>
    <putCall/>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <otherManager/>
    <votingAuthority>
      <sole>500</sole>
      <shared>0</shared>
      <none>0</none>
    </votingAuthority>
  </infoTable>
</informationTable>
'''

SAMPLE_HTML = '''
<html><body>
<table>
  <tr><th>NAME OF ISSUER</th><th>TITLE OF CLASS</th><th>CUSIP</th><th>VALUE</th><th>SHRS OR PRN AMT</th><th>INVESTMENT DISCRETION</th><th>VOTING AUTH. - SOLE</th></tr>
  <tr><td>ACME CORP</td><td>COM</td><td>123456789</td><td>1,000</td><td>500</td><td>SOLE</td><td>500</td></tr>
</table>
</body></html>
'''

@pytest.fixture()
def write_temp_file():
    files = []
    tmpdir = tempfile.gettempdir()
    xml_path = os.path.join(tmpdir, 'test_infotable.xml')
    html_path = os.path.join(tmpdir, 'test_infotable.html')
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_XML)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_HTML)
    files.append(xml_path)
    files.append(html_path)
    yield files
    try:
        os.remove(xml_path)
        os.remove(html_path)
    except Exception:
        pass


def test_parse_xml(write_temp_file):
    xml_path, html_path = write_temp_file
    url = 'file://' + xml_path
    # parse_information_table uses requests.get; requests supports file:// only via adapters, but we can read file directly by calling function's logic
    # For test purpose, call parse_information_table with a small wrapper: we'll monkeypatch requests.get
    import requests as req_mod

    class DummyResp:
        def __init__(self, content):
            self.content = content
            self.status_code = 200

    def fake_get(url, headers=None, timeout=None):
        with open(xml_path, 'rb') as f:
            return DummyResp(f.read())

    monkey = pytest.MonkeyPatch()
    monkey.setattr(req_mod, 'get', fake_get)
    try:
        holdings = parser.parse_information_table(xml_path)
        assert isinstance(holdings, list)
        assert len(holdings) >= 1
        h = holdings[0]
        assert h.get('issuer_name') == 'ACME CORP'
        assert h.get('cusip') == '123456789'
        assert h.get('value') == 1000
        assert h.get('shares') == 500
    finally:
        monkey.undo()


def test_parse_html(write_temp_file):
    xml_path, html_path = write_temp_file
    import requests as req_mod

    class DummyResp:
        def __init__(self, content):
            self.content = content
            self.status_code = 200

    def fake_get(url, headers=None, timeout=None):
        with open(html_path, 'rb') as f:
            return DummyResp(f.read())

    monkey = pytest.MonkeyPatch()
    monkey.setattr(req_mod, 'get', fake_get)
    try:
        holdings = parser.parse_information_table(html_path)
        assert isinstance(holdings, list)
        assert len(holdings) >= 1
        h = holdings[0]
        assert h.get('issuer_name') == 'ACME CORP'
        assert h.get('cusip') == '123456789'
        assert h.get('value') == 1000
        assert h.get('shares') == 500
    finally:
        monkey.undo()
