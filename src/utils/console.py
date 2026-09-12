"""
Console output that survives a Windows terminal.

Every message this project prints carries emoji, and the default Windows console
encoding (cp1252) cannot represent them: a plain ``print`` raises
UnicodeEncodeError and takes the command down with it. On the Linux VPS this
never happens, which is exactly why it is easy to ship. Route console output
through here instead.
"""
import sys


def safe_print(msg: str) -> None:
    """Print to stdout, replacing characters the console cannot encode."""
    try:
        print(msg)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or 'ascii'
        print(msg.encode(encoding, errors='replace').decode(encoding, errors='replace'))
