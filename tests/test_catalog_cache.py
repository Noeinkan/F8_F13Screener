"""The submissions cache: skippable for a manual refresh, never poisoned by an outage."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest
import requests
from tenacity import wait_none

from src.cli import process_historical_13f as pipeline


def _write_cache(cache_dir, cik, accession, age_seconds=0):
    payload = {
        "last_updated": time.time() - age_seconds,
        "filings": [{"accession_number": accession, "filing_date": "2026-05-15"}],
    }
    (cache_dir / f"{cik}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_fresh_cache_is_used_by_default(tmp_path, monkeypatch):
    _write_cache(tmp_path, "0001067983", "FROM-CACHE")

    def _unexpected_fetch(*args, **kwargs):
        raise AssertionError("SEC must not be contacted when the cache is fresh")

    monkeypatch.setattr(pipeline, "_fetch_13f_filings_from_api", _unexpected_fetch)

    filings = pipeline.get_13f_filings_for_cik(
        "0001067983", "Berkshire", str(tmp_path)
    )

    assert [f["accession_number"] for f in filings] == ["FROM-CACHE"]


def test_fresh_catalog_bypasses_a_still_valid_cache(tmp_path, monkeypatch):
    _write_cache(tmp_path, "0001067983", "FROM-CACHE")
    calls: list[str] = []

    def _fake_fetch(cik, fund_name, start_date, end_date):
        calls.append(cik)
        return [{"accession_number": "FROM-SEC", "filing_date": "2026-08-14"}]

    monkeypatch.setattr(pipeline, "_fetch_13f_filings_from_api", _fake_fetch)

    filings = pipeline.get_13f_filings_for_cik(
        "0001067983", "Berkshire", str(tmp_path), fresh_catalog=True
    )

    assert calls == ["0001067983"]
    assert [f["accession_number"] for f in filings] == ["FROM-SEC"]
    # The refreshed payload must land in the cache for subsequent runs.
    cached = json.loads((tmp_path / "0001067983.json").read_text(encoding="utf-8"))
    assert cached["filings"][0]["accession_number"] == "FROM-SEC"


def test_expired_cache_falls_through_to_sec(tmp_path, monkeypatch):
    _write_cache(tmp_path, "0001067983", "STALE", age_seconds=25 * 3600)
    monkeypatch.setattr(
        pipeline,
        "_fetch_13f_filings_from_api",
        lambda *a, **k: [{"accession_number": "FROM-SEC", "filing_date": "2026-08-14"}],
    )

    filings = pipeline.get_13f_filings_for_cik(
        "0001067983", "Berkshire", str(tmp_path)
    )

    assert [f["accession_number"] for f in filings] == ["FROM-SEC"]


# ---------------------------------------------------------------------------
# A failed fetch must never be cached as "no filings"
# ---------------------------------------------------------------------------


def _sec_down(*args, **kwargs):
    raise requests.exceptions.ConnectionError("SEC down")


def test_failure_without_cache_raises_and_writes_no_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_fetch_13f_filings_from_api", _sec_down)

    with pytest.raises(requests.exceptions.ConnectionError):
        pipeline.get_13f_filings_for_cik("0001067983", "Berkshire", str(tmp_path))

    assert not (tmp_path / "0001067983.json").exists()


def test_stale_cache_is_used_when_sec_fails_and_is_not_overwritten(tmp_path, monkeypatch):
    _write_cache(tmp_path, "0001067983", "STALE", age_seconds=72 * 3600)
    before = (tmp_path / "0001067983.json").read_text(encoding="utf-8")
    monkeypatch.setattr(pipeline, "_fetch_13f_filings_from_api", _sec_down)
    report = {}

    filings = pipeline.get_13f_filings_for_cik(
        "0001067983", "Berkshire", str(tmp_path), fetch_report=report
    )

    assert [f["accession_number"] for f in filings] == ["STALE"]
    assert (tmp_path / "0001067983.json").read_text(encoding="utf-8") == before
    assert report == {"stale_cache": 1}


def test_manual_refresh_falls_back_to_the_cache_when_sec_fails(tmp_path, monkeypatch):
    _write_cache(tmp_path, "0001067983", "CACHED")
    monkeypatch.setattr(pipeline, "_fetch_13f_filings_from_api", _sec_down)

    filings = pipeline.get_13f_filings_for_cik(
        "0001067983", "Berkshire", str(tmp_path), fresh_catalog=True
    )

    assert [f["accession_number"] for f in filings] == ["CACHED"]


def test_an_empty_answer_from_sec_is_still_cached(tmp_path, monkeypatch):
    """SEC answering "no 13F" is a real answer, unlike SEC not answering."""
    monkeypatch.setattr(pipeline, "_fetch_13f_filings_from_api", lambda *a, **k: [])

    assert pipeline.get_13f_filings_for_cik("0001067983", "Berkshire", str(tmp_path)) == []
    cached = json.loads((tmp_path / "0001067983.json").read_text(encoding="utf-8"))
    assert cached["filings"] == []


def _http_response(status, payload=None, content_type="application/json"):
    response = MagicMock()
    response.status_code = status
    response.headers = {"Content-Type": content_type}
    response.json.return_value = payload if payload is not None else {}
    if status >= 400:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status}", response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


SUBMISSIONS = {"filings": {"recent": {
    "form": ["13F-HR"], "filingDate": ["2026-08-14"],
    "accessionNumber": ["0000950123-26-000001"], "primaryDocument": ["doc.xml"],
}}}


def _fetch_without_waiting():
    return pipeline._fetch_13f_filings_from_api.retry_with(wait=wait_none())


def test_transient_errors_now_reach_the_retry_decorator(monkeypatch):
    responses = [requests.exceptions.ConnectionError("blip"), _http_response(503), _http_response(200, SUBMISSIONS)]
    calls = []

    def _get(*args, **kwargs):
        calls.append(args)
        outcome = responses[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(pipeline.requests, "get", _get)
    monkeypatch.setattr(pipeline, "rate_limiter", None)

    filings = _fetch_without_waiting()("0001067983", "Berkshire", "2020-01-01")

    assert len(calls) == 3
    assert [f["accession_number"] for f in filings] == ["0000950123-26-000001"]


@pytest.mark.parametrize("status", [403, 404])
def test_client_errors_are_not_retried(monkeypatch, status):
    get = MagicMock(return_value=_http_response(status))
    monkeypatch.setattr(pipeline.requests, "get", get)
    monkeypatch.setattr(pipeline, "rate_limiter", None)

    with pytest.raises(requests.exceptions.HTTPError):
        _fetch_without_waiting()("0001067983", "Berkshire", "2020-01-01")

    assert get.call_count == 1


def test_html_page_instead_of_json_is_a_failure(monkeypatch):
    get = MagicMock(return_value=_http_response(200, content_type="text/html"))
    monkeypatch.setattr(pipeline.requests, "get", get)
    monkeypatch.setattr(pipeline, "rate_limiter", None)

    with pytest.raises(pipeline.SECFetchError):
        _fetch_without_waiting()("0001067983", "Berkshire", "2020-01-01")

    assert get.call_count == 3


def test_catalog_summary_counts_funds_sec_did_not_answer_for(tmp_path, monkeypatch, capsys):
    funds = {"0000000001": "Alpha", "0000000002": "Beta"}
    monkeypatch.setattr(pipeline, "HEDGE_FUNDS_CIK", funds)
    monkeypatch.setattr(pipeline, "get_total_funds", lambda: len(funds))

    def _fake(cik, fund_name, *args, **kwargs):
        if cik == "0000000001":
            raise requests.exceptions.ConnectionError("SEC down")
        return [{"cik": cik, "fund_name": fund_name, "accession_number": "A-2", "filing_date": "2026-08-14"}]

    monkeypatch.setattr(pipeline, "get_13f_filings_for_cik", _fake)

    filings = pipeline.download_catalog(
        output_file=str(tmp_path / "catalog.json"), incremental=False, quiet=True
    )

    out = capsys.readouterr().out
    assert [f["accession_number"] for f in filings] == ["A-2"]
    assert "Fondi processati con successo: 1/2" in out
    assert "Fondi non letti da SEC (nessuna cache): 1/2" in out
    assert "Alpha" in out