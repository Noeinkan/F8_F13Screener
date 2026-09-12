import json
from pathlib import Path

import pytest

from src.cli import backfill_filing_metadata as backfill
from src.cli.backfill_filing_metadata import RateLimiter, run_backfill

COVER_FIXTURES = Path(__file__).parent / 'fixtures' / 'cover'
USER_AGENT = 'Test Runner test@example.com'


def _row(accession, fund_name='Baupost Group (Seth Klarman)', fund_cik='0001061768', form_type=None):
    return {
        'accession_number': accession,
        'fund_name': fund_name,
        'fund_cik': fund_cik,
        'filing_date': '2026-02-13',
        'filing_url': f"https://www.sec.gov/Archives/edgar/data/{int(fund_cik or '1')}/{accession.replace('-', '')}/{accession}-index.htm",
        'form_type': form_type,
        'period_of_report': None,
        'amendment_type': None,
    }


class FakeStorage:
    """Codes against the signatures the dashboard storage is adding, not its implementation."""

    def __init__(self, rows, mismatches=None, has_mismatch_method=True):
        self.rows = rows
        self.limits_requested = []
        self.batches = []
        self._mismatches = mismatches or []
        if not has_mismatch_method:
            self.get_entry_count_mismatches = None

    def get_filings_missing_metadata(self, limit=None):
        self.limits_requested.append(limit)
        return self.rows[:limit] if limit is not None else list(self.rows)

    def upsert_filing_metadata_many(self, records):
        self.batches.append([dict(record) for record in records])
        return len(records)

    def get_entry_count_mismatches(self):
        return self._mismatches

    @property
    def written(self):
        return [record for batch in self.batches for record in batch]


class FakeResponse:
    def __init__(self, status_code, content=b''):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, responses):
        self.responses = responses  # url -> FakeResponse
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({'url': url, 'headers': headers, 'timeout': timeout})
        return self.responses.get(url, FakeResponse(404, b'Not Found'))


class NoWaitLimiter:
    def __init__(self):
        self.calls = 0

    def wait(self):
        self.calls += 1


def _cover(name):
    return FakeResponse(200, (COVER_FIXTURES / name).read_bytes())


def _url(cik, accession):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/primary_doc.xml"


@pytest.fixture()
def catalog_file(tmp_path):
    def write(entries):
        path = tmp_path / 'catalog.json'
        path.write_text(json.dumps({'generated_at': '2026-07-02', 'filings': entries}), encoding='utf-8')
        return path
    return write


def _catalog_entry(accession, cik='0001061768', form='13F-HR'):
    return {
        'cik': cik,
        'fund_name': 'Baupost Group (Seth Klarman)',
        'form': form,
        'filing_date': '2026-02-13',
        'accession_number': accession,
        'primary_document': 'xslForm13F_X02/primary_doc.xml',
        'filing_url': 'unused',
    }


def test_fetches_each_cover_page_and_writes_metadata(catalog_file):
    original, restated = '0001061768-26-000005', '0001649339-25-000009'
    storage = FakeStorage([
        _row(original),
        _row(restated, fund_name='Scion Asset Management', fund_cik='0001649339'),
    ])
    session = FakeSession({
        _url('0001061768', original): _cover('primary_doc_original.xml'),
        _url('0001649339', restated): _cover('primary_doc_restatement.xml'),
    })
    limiter = NoWaitLimiter()
    lines = []

    summary = run_backfill(
        storage,
        session=session,
        user_agent=USER_AGENT,
        catalog_path=catalog_file([_catalog_entry(original)]),
        rate_limiter=limiter,
        out=lines.append,
    )

    assert (summary.fetched, summary.failed) == (2, 0)
    assert limiter.calls == 2
    assert all(call['headers'] == {'User-Agent': USER_AGENT} for call in session.calls)
    # The xslForm directory from the catalog is stripped: the raw XML is fetched.
    assert [call['url'] for call in session.calls] == [_url('0001061768', original), _url('0001649339', restated)]

    offline_batch, online_batch = storage.batches
    assert offline_batch == [{'accession_number': original, 'form_type': '13F-HR'}]
    assert online_batch == [
        {
            'accession_number': original,
            'form_type': '13F-HR',
            'period_of_report': '2025-12-31',
            'table_entry_total': 27,
            'table_value_total': 4312345678,
        },
        {
            'accession_number': restated,
            'form_type': '13F-HR/A',
            'period_of_report': '2025-06-30',
            'amendment_type': 'RESTATEMENT',
            'table_entry_total': 13,
            'table_value_total': 529912345,
        },
    ]
    assert summary.updated == 2
    assert summary.offline_updated == 1
    assert summary.amendments == {'RESTATEMENT': 1}
    output = '\n'.join(lines)
    assert 'amendments:      RESTATEMENT=1' in output
    assert 'entry-count mismatches: 0' in output


def test_failures_are_counted_and_do_not_stop_the_run(catalog_file):
    ok, missing, no_cik = '0001061768-26-000005', '0001061768-25-000007', '0009999999-25-000001'
    bad_row = _row(no_cik, fund_cik=None)
    bad_row['filing_url'] = ''
    storage = FakeStorage([_row(missing), bad_row, _row(ok)])
    session = FakeSession({_url('0001061768', ok): _cover('primary_doc_new_holdings.xml')})

    summary = run_backfill(
        storage, session=session, user_agent=USER_AGENT,
        catalog_path=catalog_file([]), rate_limiter=NoWaitLimiter(), out=lambda _line: None,
    )

    assert (summary.fetched, summary.failed, summary.updated) == (1, 2, 1)
    assert summary.failed_accessions == [missing, no_cik]
    assert len(session.calls) == 2  # the row without a CIK never reaches SEC
    assert storage.written == [{
        'accession_number': ok,
        'form_type': '13F-HR/A',
        'period_of_report': '2024-09-30',
        'amendment_type': 'NEW HOLDINGS',
        'table_entry_total': 1,
        'table_value_total': 84512000,
    }]
    assert summary.amendments == {'NEW HOLDINGS': 1}


def test_cik_falls_back_to_catalog_then_filing_url(catalog_file):
    from_catalog, from_url = '0001649339-25-000009', '0001167483-21-000003'
    row_a = _row(from_catalog, fund_cik=None)
    row_b = _row(from_url, fund_cik='')
    row_b['filing_url'] = 'https://www.sec.gov/Archives/edgar/data/1167483/000116748321000003/0001167483-21-000003-index.htm'
    storage = FakeStorage([row_a, row_b])
    session = FakeSession({
        _url('1649339', from_catalog): _cover('primary_doc_restatement.xml'),
        _url('1167483', from_url): _cover('primary_doc_no_summary.xml'),
    })

    summary = run_backfill(
        storage, session=session, user_agent=USER_AGENT,
        catalog_path=catalog_file([_catalog_entry(from_catalog, cik='0001649339', form='13F-HR/A')]),
        rate_limiter=NoWaitLimiter(), out=lambda _line: None,
    )

    assert (summary.fetched, summary.failed) == (2, 0)
    no_summary = storage.written[-1]
    assert no_summary == {'accession_number': from_url, 'form_type': '13F-HR', 'period_of_report': '2021-03-31'}


def test_dry_run_fetches_and_prints_but_writes_nothing(catalog_file):
    accession = '0001061768-26-000005'
    storage = FakeStorage([_row(accession)])
    session = FakeSession({_url('0001061768', accession): _cover('primary_doc_original.xml')})
    lines = []

    summary = run_backfill(
        storage, session=session, user_agent=USER_AGENT, dry_run=True,
        catalog_path=catalog_file([_catalog_entry(accession)]), rate_limiter=NoWaitLimiter(), out=lines.append,
    )

    assert storage.batches == []
    assert summary.fetched == 1 and summary.updated == 0
    output = '\n'.join(lines)
    assert f'[dry-run] {accession} form_type=13F-HR' in output
    assert 'period_of_report=2025-12-31' in output
    assert 'dry run, nothing written' in output


def test_offline_only_makes_no_requests_and_only_fills_missing_form_types(catalog_file):
    known, unknown, in_catalog_only = '0001-26-1', '0001-26-2', '0001-26-3'
    storage = FakeStorage([_row(known, form_type='13F-HR'), _row(unknown), _row(in_catalog_only)])
    session = FakeSession({})

    summary = run_backfill(
        storage, session=session, user_agent=None, offline_only=True,
        catalog_path=catalog_file([
            _catalog_entry(known, form='13F-HR/A'),  # row already has a form type: left alone
            _catalog_entry(in_catalog_only, form='13F-HR/A'),
        ]),
        out=lambda _line: None,
    )

    assert session.calls == []
    assert storage.written == [{'accession_number': in_catalog_only, 'form_type': '13F-HR/A'}]
    assert (summary.catalog_matched, summary.offline_updated, summary.fetched) == (2, 1, 0)


def test_missing_catalog_is_not_fatal(tmp_path):
    storage = FakeStorage([_row('0001-26-1')])

    summary = run_backfill(
        storage, offline_only=True, catalog_path=tmp_path / 'nope.json', out=lambda _line: None,
    )

    assert summary.catalog_matched == 0 and storage.batches == []


def test_fund_filter_applies_before_the_limit(catalog_file):
    rows = [
        _row('A-1', fund_name='Baupost Group'),
        _row('B-1', fund_name='Scion Asset Management', fund_cik='0001649339'),
        _row('B-2', fund_name='SCION ASSET MANAGEMENT', fund_cik='0001649339'),
        _row('B-3', fund_name='Scion Asset Management', fund_cik='0001649339'),
    ]
    storage = FakeStorage(rows)

    summary = run_backfill(
        storage, offline_only=True, fund='scion', limit=2,
        catalog_path=catalog_file([]), out=lambda _line: None,
    )

    assert storage.limits_requested == [None]
    assert summary.selected == 2

    storage_no_fund = FakeStorage(rows)
    run_backfill(storage_no_fund, offline_only=True, limit=3, catalog_path=catalog_file([]), out=lambda _l: None)
    assert storage_no_fund.limits_requested == [3]


def test_writes_in_batches(catalog_file):
    accessions = [f'0001061768-26-00000{i}' for i in range(5)]
    storage = FakeStorage([_row(acc) for acc in accessions])
    session = FakeSession({_url('0001061768', acc): _cover('primary_doc_original.xml') for acc in accessions})

    summary = run_backfill(
        storage, session=session, user_agent=USER_AGENT, batch_size=2,
        catalog_path=catalog_file([]), rate_limiter=NoWaitLimiter(), out=lambda _line: None,
    )

    assert [len(batch) for batch in storage.batches] == [2, 2, 1]
    assert summary.updated == 5


def test_progress_already_downloaded_is_written_when_interrupted(catalog_file):
    accessions = ['0001061768-26-000001', '0001061768-26-000002']
    storage = FakeStorage([_row(acc) for acc in accessions])
    responses = {_url('0001061768', accessions[0]): _cover('primary_doc_original.xml')}

    class InterruptingSession(FakeSession):
        def get(self, url, headers=None, timeout=None):
            if url == _url('0001061768', accessions[1]):
                raise KeyboardInterrupt
            return super().get(url, headers, timeout)

    with pytest.raises(KeyboardInterrupt):
        run_backfill(
            storage, session=InterruptingSession(responses), user_agent=USER_AGENT,
            catalog_path=catalog_file([]), rate_limiter=NoWaitLimiter(), out=lambda _line: None,
        )

    assert [record['accession_number'] for record in storage.written] == [accessions[0]]


def test_mismatches_are_reported_and_missing_method_tolerated(catalog_file):
    mismatch = {'accession_number': '0001-26-1', 'fund_name': 'Baupost', 'table_entry_total': 27, 'stored_rows': 26}
    lines = []
    run_backfill(
        FakeStorage([], mismatches=[mismatch]), offline_only=True,
        catalog_path=catalog_file([]), out=lines.append,
    )
    assert '  entry-count mismatches: 1' in lines
    assert any('table_entry_total=27' in line and 'stored_rows=26' in line for line in lines)

    lines = []
    summary = run_backfill(
        FakeStorage([], has_mismatch_method=False), offline_only=True,
        catalog_path=catalog_file([]), out=lines.append,
    )
    assert summary.mismatches is None
    assert any('not available' in line for line in lines)


def test_network_step_requires_session_and_user_agent(catalog_file):
    with pytest.raises(ValueError):
        run_backfill(FakeStorage([_row('0001-26-1')]), catalog_path=catalog_file([]), out=lambda _line: None)


def test_rate_limiter_spaces_requests_at_most_five_per_second():
    clock = {'now': 100.0}
    sleeps = []

    def sleep(seconds):
        sleeps.append(round(seconds, 6))
        clock['now'] += seconds

    limiter = RateLimiter(max_per_second=5, clock=lambda: clock['now'], sleep=sleep)
    starts = []
    for _ in range(6):
        limiter.wait()
        starts.append(clock['now'])
        clock['now'] += 0.05  # the request itself takes 50 ms

    assert sleeps == [0.15] * 5
    gaps = [round(b - a, 6) for a, b in zip(starts, starts[1:])]
    assert all(gap >= 0.2 for gap in gaps)


def test_rate_limiter_does_not_sleep_when_requests_are_slow():
    clock = {'now': 0.0}
    sleeps = []
    limiter = RateLimiter(max_per_second=5, clock=lambda: clock['now'], sleep=sleeps.append)
    for _ in range(3):
        limiter.wait()
        clock['now'] += 1.0
    assert sleeps == []


def test_main_wires_storage_session_and_flags(monkeypatch, capsys):
    created = {}

    class StubStorage(FakeStorage):
        def __init__(self, db_path):
            super().__init__([])
            created['db_path'] = db_path

    monkeypatch.setattr(backfill, 'DashboardStorage', StubStorage)
    monkeypatch.setattr(backfill, 'resolve_user_agent', lambda: USER_AGENT)
    captured = {}

    def fake_run(storage, **kwargs):
        captured.update(kwargs)
        return backfill.BackfillSummary()

    monkeypatch.setattr(backfill, 'run_backfill', fake_run)

    exit_code = backfill.main(['--limit', '7', '--fund', 'Scion', '--dry-run'])

    assert exit_code == 0
    assert Path(created['db_path']) == Path(backfill.DASHBOARD_DB_FILE)
    assert captured['limit'] == 7 and captured['fund'] == 'Scion' and captured['dry_run'] is True
    assert captured['user_agent'] == USER_AGENT
    assert captured['session'] is not None


def test_main_refuses_to_hit_sec_without_user_agent(monkeypatch, capsys):
    monkeypatch.setattr(backfill, 'resolve_user_agent', lambda: None)
    monkeypatch.setattr(backfill, 'DashboardStorage', lambda _path: pytest.fail('storage must not be opened'))

    assert backfill.main([]) == 2
    assert 'SEC_USER_AGENT' in capsys.readouterr().err
