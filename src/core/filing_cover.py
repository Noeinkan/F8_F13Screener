"""
13F cover page (``primary_doc.xml``) reader.

Every 13F-HR filing carries, next to its Information Table, a cover page with
what the holdings alone cannot tell: the quarter the report is for, whether it
is an amendment and of which kind, and the filer's own count and total of the
table rows. An amendment is either a RESTATEMENT (it replaces the quarter's
holdings) or NEW HOLDINGS (it adds rows to them), so without this page an
amendment cannot be folded into the right quarter.

``parse_cover_page`` is pure; ``fetch_cover_page`` is the only function that
touches the network.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

import requests

logger = logging.getLogger(__name__)

SEC_ARCHIVES_BASE_URL = 'https://www.sec.gov/Archives/edgar/data'
DEFAULT_PRIMARY_DOCUMENT = 'primary_doc.xml'
AMENDMENT_TYPES = ('RESTATEMENT', 'NEW HOLDINGS')

_TRUE_VALUES = {'true', '1', 'y', 'yes'}


@dataclass
class CoverPage:
    submission_type: Optional[str]
    period_of_report: Optional[str]
    is_amendment: bool
    amendment_type: Optional[str]
    table_entry_total: Optional[int]
    table_value_total: Optional[int]


def _local_name(tag: object) -> str:
    """``{http://ns}periodOfReport`` or ``ns1:periodOfReport`` -> ``periodofreport``."""
    if not isinstance(tag, str):  # comments and processing instructions
        return ''
    return tag.rsplit('}', 1)[-1].rsplit(':', 1)[-1].lower()


def _find(element: ET.Element, *path: str) -> Optional[ET.Element]:
    """Follow ``path`` by local name; each step searches all descendants of the previous match."""
    current: Optional[ET.Element] = element
    for step in path:
        if current is None:
            return None
        wanted = step.lower()
        current = next(
            (node for node in current.iter() if node is not current and _local_name(node.tag) == wanted),
            None,
        )
    return current


def _text(element: ET.Element, *path: str) -> Optional[str]:
    node = _find(element, *path)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _first_text(element: ET.Element, paths: Iterable[tuple]) -> Optional[str]:
    for path in paths:
        value = _text(element, *path)
        if value:
            return value
    return None


def _normalise_date(raw: Optional[str]) -> Optional[str]:
    """EDGAR writes ``MM-DD-YYYY``; store ISO ``YYYY-MM-DD``."""
    if not raw:
        return None
    for fmt in ('%m-%d-%Y', '%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    logger.warning("Cover page: unrecognised periodOfReport %r", raw)
    return None


def _normalise_amendment_type(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = re.sub(r'[\s_-]+', ' ', raw).strip().upper()
    if value in AMENDMENT_TYPES:
        return value
    logger.warning("Cover page: unrecognised amendmentType %r", raw)
    return None


def _to_int(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        return int(Decimal(raw.replace(',', '').replace(' ', '')))
    except (InvalidOperation, ValueError, OverflowError):
        logger.warning("Cover page: non-numeric total %r", raw)
        return None


def parse_cover_page(content: bytes | str) -> CoverPage:
    """Parse a 13F ``primary_doc.xml``.

    Tolerates a default namespace, prefixed namespaces and tag-case variants.
    Raises ``ValueError`` when the content is not XML or is not a 13F cover
    page (for example SEC's HTML rendering of it).
    """
    if isinstance(content, bytes):
        content = content.lstrip(b'\xef\xbb\xbf').lstrip()
    else:
        content = content.lstrip('﻿').lstrip()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"cover page is not well-formed XML: {exc}") from exc

    submission_type = _text(root, 'headerData', 'submissionType') or _text(root, 'submissionType')
    raw_period = _first_text(root, [
        ('headerData', 'periodOfReport'),
        ('coverPage', 'periodOfReport'),
        ('coverPage', 'reportCalendarOrQuarter'),
        ('periodOfReport',),
    ])
    if not submission_type and not raw_period:
        raise ValueError(
            f"not a 13F cover page (root element <{_local_name(root.tag)}>, "
            "no submissionType or periodOfReport)"
        )

    amendment_flag = (_text(root, 'coverPage', 'isAmendment') or '').lower()
    is_amendment = amendment_flag in _TRUE_VALUES or bool(
        submission_type and submission_type.upper().endswith('/A')
    )
    amendment_type = (
        _normalise_amendment_type(_text(root, 'coverPage', 'amendmentInfo', 'amendmentType'))
        if is_amendment
        else None
    )

    return CoverPage(
        submission_type=submission_type,
        period_of_report=_normalise_date(raw_period),
        is_amendment=is_amendment,
        amendment_type=amendment_type,
        table_entry_total=_to_int(_text(root, 'summaryPage', 'tableEntryTotal')),
        table_value_total=_to_int(_text(root, 'summaryPage', 'tableValueTotal')),
    )


def cover_page_url(fund_cik: str, accession_number: str, primary_document: str | None = None) -> str:
    """URL of the raw cover page XML inside the filing's archive folder.

    The catalog's ``primary_document`` points at SEC's HTML rendering
    (``xslForm13F_X02/primary_doc.xml``); the raw file is the same name one
    directory up.
    """
    cik = int(str(fund_cik).strip())
    folder = str(accession_number).strip().replace('-', '')
    parts = [part for part in (primary_document or '').strip().strip('/').split('/') if part]
    while parts and parts[0].lower().startswith('xslform'):
        parts.pop(0)
    document = '/'.join(parts) or DEFAULT_PRIMARY_DOCUMENT
    return f"{SEC_ARCHIVES_BASE_URL}/{cik}/{folder}/{document}"


def fetch_cover_page(session, url: str, user_agent: str, timeout: float = 30) -> CoverPage | None:
    """Download and parse one cover page. ``None`` (with a log line) on any failure; no retries."""
    try:
        response = session.get(url, headers={'User-Agent': user_agent}, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("Cover page request failed for %s: %s", url, exc)
        return None

    if response.status_code != 200:
        logger.warning("Cover page HTTP %s for %s", response.status_code, url)
        return None

    try:
        return parse_cover_page(response.content)
    except ValueError as exc:
        logger.warning("Cover page unreadable at %s: %s", url, exc)
        return None
