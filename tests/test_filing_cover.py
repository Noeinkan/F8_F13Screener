from pathlib import Path

import pytest
import requests

from src.core.filing_cover import (
    CoverPage,
    cover_page_url,
    fetch_cover_page,
    parse_cover_page,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'cover'


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parse_original_filing():
    cover = parse_cover_page(_fixture('primary_doc_original.xml'))

    assert cover == CoverPage(
        submission_type='13F-HR',
        period_of_report='2025-12-31',
        is_amendment=False,
        amendment_type=None,
        table_entry_total=27,
        table_value_total=4312345678,
    )


def test_parse_restatement_amendment_normalises_case():
    cover = parse_cover_page(_fixture('primary_doc_restatement.xml'))

    assert cover.submission_type == '13F-HR/A'
    assert cover.period_of_report == '2025-06-30'
    assert cover.is_amendment is True
    assert cover.amendment_type == 'RESTATEMENT'
    assert (cover.table_entry_total, cover.table_value_total) == (13, 529912345)


def test_parse_new_holdings_amendment_with_prefixed_namespace_and_messy_spacing():
    cover = parse_cover_page(_fixture('primary_doc_new_holdings.xml'))

    assert cover.submission_type == '13F-HR/A'
    assert cover.period_of_report == '2024-09-30'
    assert cover.is_amendment is True
    assert cover.amendment_type == 'NEW HOLDINGS'
    assert (cover.table_entry_total, cover.table_value_total) == (1, 84512000)


def test_parse_without_summary_page_leaves_totals_empty():
    cover = parse_cover_page(_fixture('primary_doc_no_summary.xml'))

    assert cover.submission_type == '13F-HR'
    assert cover.period_of_report == '2021-03-31'
    assert cover.is_amendment is False
    assert cover.table_entry_total is None
    assert cover.table_value_total is None


def test_parse_accepts_str_with_bom_and_encoding_declaration():
    text = '﻿\n' + _fixture('primary_doc_original.xml').decode('utf-8')

    assert parse_cover_page(text).period_of_report == '2025-12-31'


def test_amendment_detected_from_submission_type_when_flag_missing():
    xml = b'''<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
      <headerData><submissionType>13F-HR/A</submissionType></headerData>
      <formData><coverPage><reportCalendarOrQuarter>03-31-2024</reportCalendarOrQuarter>
        <amendmentInfo><amendmentType>NEW_HOLDINGS</amendmentType></amendmentInfo>
      </coverPage></formData></edgarSubmission>'''

    cover = parse_cover_page(xml)

    assert cover.is_amendment is True
    assert cover.amendment_type == 'NEW HOLDINGS'
    assert cover.period_of_report == '2024-03-31'  # falls back to reportCalendarOrQuarter


def test_unknown_amendment_type_becomes_none():
    xml = b'''<edgarSubmission><headerData><submissionType>13F-HR/A</submissionType>
      <filerInfo><periodOfReport>12-31-2023</periodOfReport></filerInfo></headerData>
      <formData><coverPage><isAmendment>true</isAmendment>
        <amendmentInfo><amendmentType>SOMETHING ELSE</amendmentType></amendmentInfo>
      </coverPage><summaryPage><tableEntryTotal>n/a</tableEntryTotal>
      <tableValueTotal>1,234.00</tableValueTotal></summaryPage></formData></edgarSubmission>'''

    cover = parse_cover_page(xml)

    assert cover.is_amendment is True
    assert cover.amendment_type is None
    assert cover.table_entry_total is None
    assert cover.table_value_total == 1234


@pytest.mark.parametrize('content', [
    b'<!DOCTYPE html><html><head><meta charset="utf-8"><title>13F</title></head><body><p>rendered</p></body></html>',
    b'<html><body><table><tr><td>FORM 13F</td></tr></table></body></html>',
    b'',
])
def test_parse_rejects_non_cover_content(content):
    with pytest.raises(ValueError):
        parse_cover_page(content)


@pytest.mark.parametrize('cik, accession, primary, expected', [
    ('0001061768', '0001061768-26-000005', 'xslForm13F_X02/primary_doc.xml',
     'https://www.sec.gov/Archives/edgar/data/1061768/000106176826000005/primary_doc.xml'),
    ('1061768', '0001061768-26-000005', None,
     'https://www.sec.gov/Archives/edgar/data/1061768/000106176826000005/primary_doc.xml'),
    ('0001649339', '0001567619-22-010747', 'XSLFORM13F_X01/cover.xml',
     'https://www.sec.gov/Archives/edgar/data/1649339/000156761922010747/cover.xml'),
    ('0001649339', '0001567619-22-010747', '',
     'https://www.sec.gov/Archives/edgar/data/1649339/000156761922010747/primary_doc.xml'),
])
def test_cover_page_url(cik, accession, primary, expected):
    assert cover_page_url(cik, accession, primary) == expected


class _Response:
    def __init__(self, status_code=200, content=b''):
        self.status_code = status_code
        self.content = content


class _Session:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers, timeout))
        if self.error:
            raise self.error
        return self.response


def test_fetch_cover_page_sends_user_agent_and_parses():
    session = _Session(_Response(200, _fixture('primary_doc_restatement.xml')))

    cover = fetch_cover_page(session, 'https://www.sec.gov/x/primary_doc.xml', 'Jane Doe jane@example.com', timeout=5)

    assert cover is not None and cover.amendment_type == 'RESTATEMENT'
    assert session.calls == [
        ('https://www.sec.gov/x/primary_doc.xml', {'User-Agent': 'Jane Doe jane@example.com'}, 5)
    ]


def test_fetch_cover_page_returns_none_on_http_error(caplog):
    session = _Session(_Response(404, b'Not Found'))

    assert fetch_cover_page(session, 'https://www.sec.gov/x/primary_doc.xml', 'ua') is None
    assert 'HTTP 404' in caplog.text
    assert len(session.calls) == 1  # no retries


def test_fetch_cover_page_returns_none_on_parse_failure(caplog):
    session = _Session(_Response(200, b'<html><body>rendered</body></html>'))

    assert fetch_cover_page(session, 'https://www.sec.gov/x/primary_doc.xml', 'ua') is None
    assert 'unreadable' in caplog.text


def test_fetch_cover_page_returns_none_on_network_error(caplog):
    session = _Session(error=requests.ConnectionError('boom'))

    assert fetch_cover_page(session, 'https://www.sec.gov/x/primary_doc.xml', 'ua') is None
    assert 'request failed' in caplog.text
