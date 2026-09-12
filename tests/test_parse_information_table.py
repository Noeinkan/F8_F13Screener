import os
import re
import tempfile
from pathlib import Path

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
        # Exactly one: the <informationTable> root must not count as a holding.
        assert len(holdings) == 1
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
        assert len(holdings) == 1
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


# ---------------------------------------------------------------------------
# Fixture-based tests: real EDGAR page shapes
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / 'fixtures' / 'infotable'
INDEX_URL = 'https://www.sec.gov/Archives/edgar/data/1649339/000164933924000011/0001649339-24-000011-index.htm'


def _serve(monkeypatch, content: bytes, seen_urls=None):
    class DummyResp:
        status_code = 200

        def __init__(self, body):
            self.content = body

    def fake_get(url, headers=None, timeout=None):
        if seen_urls is not None:
            seen_urls.append(url)
        return DummyResp(content)

    monkeypatch.setattr(requests, 'get', fake_get)


def _index_page(rows):
    """Minimal EDGAR index table; rows are (href, type) pairs."""
    body = ''.join(
        f'<tr><td>1</td><td></td><td><a href="{href}">{href.rsplit("/", 1)[-1]}</a></td><td>{kind}</td><td>100</td></tr>'
        for href, kind in rows
    )
    return f'<html><body><table class="tableFile">{body}</table></body></html>'.encode('utf-8')


def test_get_information_table_url_prefers_raw_xml_over_xslform_rendering(monkeypatch):
    # The xslForm link is listed first on the page, as EDGAR does.
    _serve(monkeypatch, (FIXTURES / 'index_xslform_and_raw.htm').read_bytes())

    result = parser.get_information_table_url(INDEX_URL)

    assert result == 'https://www.sec.gov/Archives/edgar/data/1649339/000164933924000011/infotable.xml'


def test_get_information_table_url_ranks_html_before_xslform_rendering(monkeypatch):
    base = '/Archives/edgar/data/1/000000000124000001'
    _serve(monkeypatch, _index_page([
        (f'{base}/xslForm13F_X02/table.xml', 'INFORMATION TABLE'),
        (f'{base}/table.htm', 'INFORMATION TABLE'),
    ]))

    assert parser.get_information_table_url(INDEX_URL) == f'https://www.sec.gov{base}/table.htm'


def test_get_information_table_url_falls_back_to_xslform_rendering_when_alone(monkeypatch):
    base = '/Archives/edgar/data/1/000000000124000001'
    _serve(monkeypatch, _index_page([
        (f'{base}/xslForm13F_X01/primary_doc.xml', '13F-HR'),
        (f'{base}/XSLFORM13F_X01/Table.XML', 'INFORMATION TABLE'),
    ]))

    assert parser.get_information_table_url(INDEX_URL) == f'https://www.sec.gov{base}/XSLFORM13F_X01/Table.XML'


def test_get_information_table_url_method3_skips_primary_doc_and_prefers_raw(monkeypatch):
    # No INFORMATION TABLE label and no "infotable" in names: method 3.
    base = '/Archives/edgar/data/1/000000000124000001'
    _serve(monkeypatch, _index_page([
        (f'{base}/xslForm13F_X02/primary_doc.xml', '13F-HR'),
        (f'{base}/primary_doc.xml', '13F-HR'),
        (f'{base}/xslForm13F_X02/holdings.xml', ''),
        (f'{base}/holdings.xml', ''),
    ]))

    assert parser.get_information_table_url(INDEX_URL) == f'https://www.sec.gov{base}/holdings.xml'


def test_parse_namespaced_raw_xml_does_not_invent_a_row_from_the_root(monkeypatch):
    _serve(monkeypatch, (FIXTURES / 'infotable_ns_prefixed.xml').read_bytes())

    holdings = parser.parse_information_table('https://www.sec.gov/x/infotable.xml')

    assert len(holdings) == 2
    first, second = holdings
    assert (first['issuer_name'], first['cusip'], first['put_call']) == ('MICROSOFT CORP', '594918104', '')
    assert (second['issuer_name'], second['cusip'], second['put_call']) == ('SPDR S&P 500 ETF TR', '78462F103', 'Put')
    assert first['value'] == 37604000
    assert first['shares'] == 100000
    assert first['sh_prn'] == 'SH'
    assert first['voting_authority_sole'] == 100000
    assert second['voting_authority_sole'] == 0


def test_parse_xml_tolerates_case_variants_of_info_table():
    content = b'''<?xml version="1.0"?>
    <informationtable>
      <INFOTABLE><NAMEOFISSUER>ACME CORP</NAMEOFISSUER><CUSIP>123456789</CUSIP><VALUE>10</VALUE>
        <SHRSORPRN><SSHPRNAMT>5</SSHPRNAMT><SSHPRNAMTTYPE>SH</SSHPRNAMTTYPE></SHRSORPRN></INFOTABLE>
      <infotable><nameofissuer>BETA INC</nameofissuer><cusip>987654321</cusip><value>20</value>
        <shrsorprn><sshprnamttype>PRN</sshprnamttype><sshprnamt>7</sshprnamt></shrsorprn></infotable>
    </informationtable>'''

    holdings = parser.parse_information_table_content(content)

    assert [(h['issuer_name'], h['shares'], h['sh_prn']) for h in holdings] == [
        ('ACME CORP', 5, 'SH'),
        ('BETA INC', 7, 'PRN'),  # amount found even when the type element comes first
    ]


def test_raw_xml_and_its_xslform_rendering_parse_to_identical_holdings():
    """Downstream code and the DB expect one shape, whichever link was picked."""
    from_xml = parser.parse_information_table_content((FIXTURES / 'paired_raw.xml').read_bytes())
    from_html = parser.parse_information_table_content((FIXTURES / 'paired_xsl_rendered.html').read_bytes())

    assert len(from_xml) == 5
    assert from_xml == from_html

    by_cusip = {h['cusip']: h for h in from_xml}
    apple = by_cusip['037833100']
    assert apple['value'] == 174347025280
    assert apple['value_x1000'] == '174347025280'
    assert apple['shares'] == 905560000
    assert apple['shares_raw'] == '905560000'
    assert apple['other_manager'] == '4,8,11'
    assert apple['figi'] == ''
    assert by_cusip['060505104']['figi'] == 'BBG000BCTLF6'
    assert by_cusip['88160R101']['put_call'] == 'Call'
    carvana = by_cusip['146869AJ1']
    assert (carvana['sh_prn'], carvana['share_class']) == ('PRN', 'NOTE 10.250% 5/0')
    att = by_cusip['00206R102']
    assert att['issuer_name'] == 'AT&T INC'
    assert (att['put_call'], att['investment_discretion']) == ('Put', 'OTR')
    assert (att['voting_authority_sole'], att['voting_authority_shared'], att['voting_authority_none']) == (0, 1000, 0)


def test_html_voting_authority_is_integer_like_the_xml_path():
    holdings = parser.parse_information_table_content(SAMPLE_HTML_MULTIROW_VALUE)

    assert len(holdings) == 1
    h = holdings[0]
    assert (h['voting_authority_sole'], h['voting_authority_shared'], h['voting_authority_none']) == (10877, 0, 0)


FILING_BASE = 'https://www.sec.gov/Archives/edgar/data/1649339/000164933924000011'
RAW_URL = f'{FILING_BASE}/infotable.xml'
RENDERED_URL = f'{FILING_BASE}/xslForm13F_X02/infotable.xml'


def _serve_by_url(monkeypatch, pages, seen_urls):
    """Index page plus per-URL bodies; a URL mapped to None answers 404."""
    class DummyResp:
        def __init__(self, body):
            self.status_code = 404 if body is None else 200
            self.content = body or b''

    def fake_get(url, headers=None, timeout=None):
        seen_urls.append(url)
        if url == INDEX_URL:
            return DummyResp((FIXTURES / 'index_xslform_and_raw.htm').read_bytes())
        return DummyResp(pages.get(url))

    monkeypatch.setattr(requests, 'get', fake_get)


def test_parse_filing_holdings_uses_raw_xml_and_never_fetches_the_rendering(monkeypatch):
    seen = []
    raw = b'\n  ' + (FIXTURES / 'paired_raw.xml').read_bytes()  # leading whitespace is not "malformed"
    _serve_by_url(monkeypatch, {RAW_URL: raw}, seen)

    url, holdings = parser.parse_filing_holdings(INDEX_URL)

    assert url == RAW_URL
    assert len(holdings) == 5
    assert RENDERED_URL not in seen


def test_parse_filing_holdings_malformed_raw_xml_falls_back_to_sec_rendering(monkeypatch):
    # Cut mid-document: the lenient XML reader would still return the first rows,
    # and the diff would report the missing ones as closed positions.
    raw = (FIXTURES / 'paired_raw.xml').read_bytes()
    truncated = raw[: len(raw) // 2]
    assert 0 < len(parser.parse_information_table_content(truncated)) < 5
    _serve_by_url(monkeypatch, {
        RAW_URL: truncated,
        RENDERED_URL: (FIXTURES / 'paired_xsl_rendered.html').read_bytes(),
    }, [])

    url, holdings = parser.parse_filing_holdings(INDEX_URL)

    assert url == RENDERED_URL
    assert holdings == parser.parse_information_table_content(raw)


def test_parse_filing_holdings_raw_xml_unavailable_falls_back_to_sec_rendering(monkeypatch):
    _serve_by_url(monkeypatch, {
        RAW_URL: None,
        RENDERED_URL: (FIXTURES / 'paired_xsl_rendered.html').read_bytes(),
    }, [])

    url, holdings = parser.parse_filing_holdings(INDEX_URL)

    assert url == RENDERED_URL
    assert len(holdings) == 5


def test_parse_filing_holdings_prefers_a_link_with_values_over_one_without(monkeypatch):
    no_values = re.sub(rb'<value>[^<]*</value>', b'', (FIXTURES / 'paired_raw.xml').read_bytes())
    _serve_by_url(monkeypatch, {
        RAW_URL: no_values,
        RENDERED_URL: (FIXTURES / 'paired_xsl_rendered.html').read_bytes(),
    }, [])

    url, holdings = parser.parse_filing_holdings(INDEX_URL)

    assert url == RENDERED_URL
    assert all(h['value'] is not None for h in holdings)


def test_parse_filing_holdings_gives_nothing_rather_than_a_partial_portfolio(monkeypatch):
    raw = (FIXTURES / 'paired_raw.xml').read_bytes()
    _serve_by_url(monkeypatch, {
        RAW_URL: raw[: len(raw) // 2],
        RENDERED_URL: b'<html><body>Access Denied</body></html>',
    }, [])

    assert parser.parse_filing_holdings(INDEX_URL) == (None, [])
