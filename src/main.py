"""Unified command entrypoint for local developer workflows."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_dashboard(raw_args: list[str]) -> int:
    """Launch the Streamlit dashboard using the existing restart script on Windows."""
    if sys.platform == "win32":
        script = REPO_ROOT / "scripts" / "restart_dashboard.ps1"
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *raw_args,
        ]
        return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "src/web/dashboard.py",
        *raw_args,
    ]
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


def _run_alerts() -> int:
    """Run the realtime filings poller."""
    command = [sys.executable, "-m", "src.cli.main"]
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.main")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("dashboard", help="Start Streamlit dashboard")

    subparsers.add_parser("alerts", help="Run realtime 13F alert poller")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, extra_args = parser.parse_known_args(argv)

    if args.command == "dashboard":
        return _run_dashboard(extra_args)
    if args.command == "alerts":
        if extra_args:
            parser.error(f"Unrecognized arguments for alerts: {' '.join(extra_args)}")
        return _run_alerts()

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())