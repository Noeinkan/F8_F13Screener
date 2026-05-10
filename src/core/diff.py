"""
Portfolio diff engine: compares two quarters of holdings for the same fund.
"""
from typing import Dict, List, Optional


MIN_CHANGE_PCT = 10.0  # only report changes >= this threshold
MAX_ITEMS_PER_SECTION = 5  # keep Telegram messages readable


def compute_portfolio_diff(
    old: Dict[str, Dict],
    new: Dict[str, Dict],
) -> Dict:
    """
    Compare two sets of holdings (keyed by CUSIP).

    Each value dict must contain: issuer_name, shares, value_usd.
    Returns a dict with: new_positions, closed_positions, increased, decreased.
    """
    old_cusips = set(old.keys())
    new_cusips = set(new.keys())

    new_positions: List[Dict] = []
    for cusip in sorted(new_cusips - old_cusips):
        h = new[cusip]
        new_positions.append({
            'cusip': cusip,
            'issuer_name': h.get('issuer_name') or cusip,
            'shares': h.get('shares'),
            'value_usd': h.get('value_usd'),
        })

    closed_positions: List[Dict] = []
    for cusip in sorted(old_cusips - new_cusips):
        h = old[cusip]
        closed_positions.append({
            'cusip': cusip,
            'issuer_name': h.get('issuer_name') or cusip,
            'shares': h.get('shares'),
            'value_usd': h.get('value_usd'),
        })

    increased: List[Dict] = []
    decreased: List[Dict] = []
    for cusip in old_cusips & new_cusips:
        old_shares = old[cusip].get('shares') or 0
        new_shares = new[cusip].get('shares') or 0
        if old_shares == 0:
            continue
        pct = (new_shares - old_shares) / old_shares * 100
        if abs(pct) < MIN_CHANGE_PCT:
            continue
        entry = {
            'cusip': cusip,
            'issuer_name': new[cusip].get('issuer_name') or cusip,
            'old_shares': old_shares,
            'new_shares': new_shares,
            'pct_change': pct,
        }
        if pct > 0:
            increased.append(entry)
        else:
            decreased.append(entry)

    increased.sort(key=lambda x: x['pct_change'], reverse=True)
    decreased.sort(key=lambda x: x['pct_change'])

    return {
        'new_positions': new_positions,
        'closed_positions': closed_positions,
        'increased': increased,
        'decreased': decreased,
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
