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

SAMPLE_HTML_MULTIROW_VALUE = '''
<html><body>
<table>
    <tr><th colspan="4">COLUMN 1</th><th>VALUE</th><th colspan="2">SHRS OR PRN AMT</th><th></th><th>INVESTMENT</th><th>OTHER</th><th colspan="3">VOTING AUTHORITY</th></tr>
    <tr><th>NAME OF ISSUER</th><th>TITLE OF CLASS</th><th>CUSIP</th><th>FIGI</th><th>(to the nearest dollar)</th><th>PRN AMT</th><th>PRN</th><th>CALL</th><th>DISCRETION</th><th>MANAGER</th><th>SOLE</th><th>SHARED</th><th>NONE</th></tr>
    <tr><td>ACUSHNET HLDGS CORP</td><td>COM</td><td>005098108</td><td>BBG00D5L3ST3</td><td>1,016,782</td><td>10,877</td><td>SH</td><td></td><td>SOLE</td><td></td><td>10,877</td><td>0</td><td>0</td></tr>
</table>
</body></html>
'''

SAMPLE_HTML_X1000_VALUE = '''
<html><body>
<table>
    <tr><th>NAME OF ISSUER</th><th>TITLE OF CLASS</th><th>CUSIP</th><th>(x$1000)</th><th>PRN AMT</th><th>PRN</th><th>CALL</th><th>DISCRETION</th><th>MANAGER</th><th>SOLE</th><th>SHARED</th><th>NONE</th></tr>
    <tr><td>1847 GOEDEKER INC</td><td>W EXP 06/02/202</td><td>28252C117</td><td>5</td><td>37,752</td><td>SH</td><td></td><td>DFND</td><td>1</td><td>4,719</td><td>0</td><td>0</td></tr>
</table>
</body></html>
'''

SAMPLE_INDEX_WITH_INFORMATION_TABLE = '''
<html><body>
<table>
    <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
    <tr><td>1</td><td></td><td><a href="primary_doc.xml">primary_doc.xml</a></td><td>13F-HR</td></tr>
    <tr><td>2</td><td></td><td><a href="salp13fq1xml.html">salp13fq1xml.html</a></td><td>INFORMATION TABLE</td></tr>
    <tr><td>2</td><td></td><td><a href="salp13fq1xml.xml">salp13fq1xml.xml</a></td><td>INFORMATION TABLE</td></tr>
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


def test_parse_html_multiline_value_header():
    import requests as req_mod

    class DummyResp:
        def __init__(self, content):
            self.content = content
            self.status_code = 200

    def fake_get(url, headers=None, timeout=None):
        return DummyResp(SAMPLE_HTML_MULTIROW_VALUE.encode('utf-8'))

    monkey = pytest.MonkeyPatch()
    monkey.setattr(req_mod, 'get', fake_get)
    try:
        holdings = parser.parse_information_table('https://example.com/infotable.xml')
        assert len(holdings) == 1
        h = holdings[0]
        assert h.get('issuer_name') == 'ACUSHNET HLDGS CORP'
        assert h.get('cusip') == '005098108'
        assert h.get('value_x1000') == '1016782'
        assert h.get('value') == 1016782
        assert h.get('shares') == 10877
    finally:
        monkey.undo()


def test_parse_html_x1000_value_header():
    import requests as req_mod

    class DummyResp:
        def __init__(self, content):
            self.content = content
            self.status_code = 200

    def fake_get(url, headers=None, timeout=None):
        return DummyResp(SAMPLE_HTML_X1000_VALUE.encode('utf-8'))

    monkey = pytest.MonkeyPatch()
    monkey.setattr(req_mod, 'get', fake_get)
    try:
        holdings = parser.parse_information_table('https://example.com/form13fhr-infoTable.xml')
        assert len(holdings) == 1
        h = holdings[0]
        assert h.get('issuer_name') == '1847 GOEDEKER INC'
        assert h.get('cusip') == '28252C117'
        assert h.get('value_x1000') == '5'
        assert h.get('value') == 5
        assert h.get('shares') == 37752
    finally:
        monkey.undo()


def test_get_information_table_url_prefers_explicit_information_table_xml():
    import requests as req_mod

    class DummyResp:
        def __init__(self, content):
            self.content = content
            self.status_code = 200

    def fake_get(url, headers=None, timeout=None):
        return DummyResp(SAMPLE_INDEX_WITH_INFORMATION_TABLE.encode('utf-8'))

    monkey = pytest.MonkeyPatch()
    monkey.setattr(req_mod, 'get', fake_get)
    try:
        result = parser.get_information_table_url(
            'https://www.sec.gov/Archives/edgar/data/2045724/000204572426000008/0002045724-26-000008-index.htm'
        )
        assert result is not None
        assert result.endswith('/salp13fq1xml.xml')
        assert not result.endswith('/primary_doc.xml')
    finally:
        monkey.undo()
