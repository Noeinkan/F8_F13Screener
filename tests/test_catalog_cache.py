"""The submissions cache must be skippable so a manual refresh reaches SEC."""

from __future__ import annotations

import json
import time

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
