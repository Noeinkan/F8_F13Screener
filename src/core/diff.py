"""
Portfolio diff engine: compares two quarters of holdings for the same fund.
"""
from typing import Any, Dict, List, Optional


MIN_CHANGE_PCT = 10.0  # only report changes >= this threshold
MAX_ITEMS_PER_SECTION = 5  # keep Telegram messages readable


def _normalize_position_key_part(part: Any) -> str:
    if part is None:
        return ''
    if isinstance(part, float) and part != part:
        return ''

    normalized = str(part).strip()
    return '' if normalized.lower() == 'nan' else normalized


def _compose_position_key(*parts: Optional[str]) -> str:
    return '|'.join(_normalize_position_key_part(part) for part in parts)


def build_position_key(
    cusip: Optional[str],
    issuer_name: Optional[str] = None,
    share_class: Optional[str] = None,
    put_call: Optional[str] = None,
) -> str:
    """Return a stable key for a normalized 13F position."""
    normalized_cusip = _normalize_position_key_part(cusip)
    if normalized_cusip:
        return _compose_position_key(normalized_cusip, share_class, put_call)

    fallback_key = _compose_position_key(issuer_name, share_class, put_call).strip('|')
    return fallback_key or 'UNKNOWN_POSITION'


def _identity_from_holding(position_key: str, holding: Dict[str, Any]) -> Dict[str, Any]:
    normalized_cusip = (holding.get('cusip') or '').strip()
    if not normalized_cusip and '|' not in position_key and position_key != 'UNKNOWN_POSITION':
        normalized_cusip = position_key

    return {
        'position_key': position_key,
        'cusip': normalized_cusip,
        'issuer_name': holding.get('issuer_name') or position_key,
        'share_class': holding.get('share_class'),
        'put_call': holding.get('put_call'),
    }


def _value_pct_change(old_value: Optional[float], new_value: Optional[float]) -> Optional[float]:
    if old_value in (None, 0):
        return None
    return ((new_value or 0) - old_value) / old_value * 100


def compute_detailed_portfolio_diff(
    old: Dict[str, Dict[str, Any]],
    new: Dict[str, Dict[str, Any]],
    min_change_pct: float = MIN_CHANGE_PCT,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Compare two normalized position maps.

    Keys can be CUSIPs or any stable normalized position identifier.
    Each holding can optionally contain: issuer_name, shares, value_usd, share_class, put_call, cusip.
    """
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    new_positions: List[Dict[str, Any]] = []
    for position_key in sorted(new_keys - old_keys):
        holding = new[position_key]
        new_positions.append({
            **_identity_from_holding(position_key, holding),
            'shares': holding.get('shares'),
            'value_usd': holding.get('value_usd'),
        })

    closed_positions: List[Dict[str, Any]] = []
    for position_key in sorted(old_keys - new_keys):
        holding = old[position_key]
        closed_positions.append({
            **_identity_from_holding(position_key, holding),
            'shares': holding.get('shares'),
            'value_usd': holding.get('value_usd'),
        })

    increased: List[Dict[str, Any]] = []
    decreased: List[Dict[str, Any]] = []
    for position_key in old_keys & new_keys:
        old_holding = old[position_key]
        new_holding = new[position_key]
        old_shares = old_holding.get('shares') or 0
        new_shares = new_holding.get('shares') or 0

        if old_shares == 0:
            continue

        pct_change = (new_shares - old_shares) / old_shares * 100
        if pct_change == 0:
            continue
        if abs(pct_change) < min_change_pct:
            continue

        old_value_usd = old_holding.get('value_usd')
        new_value_usd = new_holding.get('value_usd')
        entry = {
            **_identity_from_holding(position_key, new_holding if new_holding.get('issuer_name') else old_holding),
            'old_shares': old_shares,
            'new_shares': new_shares,
            'share_change': new_shares - old_shares,
            'pct_change': pct_change,
            'old_value_usd': old_value_usd,
            'new_value_usd': new_value_usd,
            'value_change': (
                None
                if old_value_usd is None and new_value_usd is None
                else (new_value_usd or 0) - (old_value_usd or 0)
            ),
            'value_pct_change': _value_pct_change(old_value_usd, new_value_usd),
        }

        if pct_change > 0:
            increased.append(entry)
        else:
            decreased.append(entry)

    increased.sort(key=lambda item: item['pct_change'], reverse=True)
    decreased.sort(key=lambda item: item['pct_change'])

    return {
        'new_positions': new_positions,
        'closed_positions': closed_positions,
        'increased': increased,
        'decreased': decreased,
    }


def compute_quarterly_history_transitions(
    snapshots: List[Dict[str, Any]],
    min_change_pct: float = MIN_CHANGE_PCT,
) -> List[Dict[str, Any]]:
    """Compare consecutive quarter snapshots in filing-date order."""
    ordered_snapshots = sorted(
        snapshots,
        key=lambda item: (
            item.get('filing_date') or '',
            item.get('accession_number') or '',
        ),
    )

    transitions: List[Dict[str, Any]] = []
    for previous, current in zip(ordered_snapshots, ordered_snapshots[1:]):
        diff = compute_detailed_portfolio_diff(
            previous.get('positions', {}),
            current.get('positions', {}),
            min_change_pct=min_change_pct,
        )
        transitions.append({
            'from_filing_date': previous.get('filing_date'),
            'to_filing_date': current.get('filing_date'),
            'from_accession_number': previous.get('accession_number'),
            'to_accession_number': current.get('accession_number'),
            'from_label': previous.get('label') or previous.get('filing_date') or previous.get('accession_number'),
            'to_label': current.get('label') or current.get('filing_date') or current.get('accession_number'),
            'new_positions': diff['new_positions'],
            'closed_positions': diff['closed_positions'],
            'increased': diff['increased'],
            'decreased': diff['decreased'],
            'new_count': len(diff['new_positions']),
            'closed_count': len(diff['closed_positions']),
            'increased_count': len(diff['increased']),
            'decreased_count': len(diff['decreased']),
        })

    return transitions


def compute_portfolio_diff(
    old: Dict[str, Dict],
    new: Dict[str, Dict],
) -> Dict:
    """
    Compare two sets of holdings (keyed by CUSIP).

    Each value dict must contain: issuer_name, shares, value_usd.
    Returns a dict with: new_positions, closed_positions, increased, decreased.
    """
    detailed = compute_detailed_portfolio_diff(old, new, min_change_pct=MIN_CHANGE_PCT)

    return {
        'new_positions': [
            {
                'cusip': entry['cusip'] or entry['position_key'],
                'issuer_name': entry['issuer_name'],
                'shares': entry['shares'],
                'value_usd': entry['value_usd'],
            }
            for entry in detailed['new_positions']
        ],
        'closed_positions': [
            {
                'cusip': entry['cusip'] or entry['position_key'],
                'issuer_name': entry['issuer_name'],
                'shares': entry['shares'],
                'value_usd': entry['value_usd'],
            }
            for entry in detailed['closed_positions']
        ],
        'increased': [
            {
                'cusip': entry['cusip'] or entry['position_key'],
                'issuer_name': entry['issuer_name'],
                'old_shares': entry['old_shares'],
                'new_shares': entry['new_shares'],
                'pct_change': entry['pct_change'],
            }
            for entry in detailed['increased']
        ],
        'decreased': [
            {
                'cusip': entry['cusip'] or entry['position_key'],
                'issuer_name': entry['issuer_name'],
                'old_shares': entry['old_shares'],
                'new_shares': entry['new_shares'],
                'pct_change': entry['pct_change'],
            }
            for entry in detailed['decreased']
        ],
    }


def _fmt_value(value_thousands: Optional[int]) -> str:
    """Format a value stored in thousands of USD into a readable string."""
    if not value_thousands:
        return ''
    val = value_thousands * 1000
    if val >= 1_000_000_000:
        return f'${val / 1_000_000_000:.1f}B'
    if val >= 1_000_000:
        return f'${val / 1_000_000:.1f}M'
    if val >= 1_000:
        return f'${val / 1_000:.0f}k'
    return f'${val:,.0f}'


def format_diff_for_telegram(diff: Dict) -> str:
    """Format a portfolio diff dict as HTML suitable for a Telegram message."""
    parts: List[str] = []

    new_pos = diff.get('new_positions', [])
    if new_pos:
        lines = [f'\n\n📈 <b>NUOVE POSIZIONI ({len(new_pos)}):</b>']
        for p in new_pos[:MAX_ITEMS_PER_SECTION]:
            name = p['issuer_name']
            shares = f"{p['shares']:,}" if p['shares'] else 'N/D'
            val = f' ({_fmt_value(p["value_usd"])})' if p['value_usd'] else ''
            lines.append(f'  • {name} — {shares} azioni{val}')
        if len(new_pos) > MAX_ITEMS_PER_SECTION:
            lines.append(f'  <i>...e altre {len(new_pos) - MAX_ITEMS_PER_SECTION}</i>')
        parts.append('\n'.join(lines))

    closed = diff.get('closed_positions', [])
    if closed:
        lines = [f'\n\n📉 <b>POSIZIONI CHIUSE ({len(closed)}):</b>']
        for p in closed[:MAX_ITEMS_PER_SECTION]:
            name = p['issuer_name']
            shares = f"{p['shares']:,}" if p['shares'] else 'N/D'
            lines.append(f'  • {name} — era {shares} azioni')
        if len(closed) > MAX_ITEMS_PER_SECTION:
            lines.append(f'  <i>...e altre {len(closed) - MAX_ITEMS_PER_SECTION}</i>')
        parts.append('\n'.join(lines))

    increased = diff.get('increased', [])
    decreased = diff.get('decreased', [])
    changes = increased[:MAX_ITEMS_PER_SECTION] + decreased[:MAX_ITEMS_PER_SECTION]
    if changes:
        lines = ['\n\n🔄 <b>VARIAZIONI SIGNIFICATIVE:</b>']
        for p in changes:
            name = p['issuer_name']
            arrow = '↑' if p['pct_change'] > 0 else '↓'
            pct = abs(p['pct_change'])
            old_s = f"{p['old_shares']:,}"
            new_s = f"{p['new_shares']:,}"
            lines.append(f'  • {name} {arrow}{pct:.0f}% ({old_s} → {new_s})')
        total_changes = len(increased) + len(decreased)
        if total_changes > MAX_ITEMS_PER_SECTION * 2:
            lines.append(f'  <i>...e altre {total_changes - len(changes)}</i>')
        parts.append('\n'.join(lines))

    return ''.join(parts)
