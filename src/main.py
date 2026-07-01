"""Unified command entrypoint for local developer workflows."""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Known dashboard ports and the human-readable service they represent.
# Order matters: this is the order printed by `status`.
STATUS_PORTS: tuple[tuple[int, str, str], ...] = (
    (5173, "Web (Vite)", "http://127.0.0.1:5173"),
    (9001, "API (FastAPI)", "http://127.0.0.1:9001"),
    (8501, "Legacy Streamlit (default)", "http://127.0.0.1:8501"),
    (8502, "Legacy Streamlit (restart_dashboard.ps1)", "http://127.0.0.1:8502"),
    (3000, "Fallback port", "http://127.0.0.1:3000"),
)


def _run_web() -> int:
    """Launch FastAPI + Vite dashboard (npm start)."""
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    command = [npm_cmd, "start"]
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


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


def _listening_pids(port: int) -> list[int]:
    """Return PIDs currently LISTENing on `port` on any local address.

    Falls back to `lsof`/`netstat` if a pure-socket approach is not possible.
    """
    # Cross-platform path: try to bind/connect to detect the listener.
    # This only works for "something is bound here"; getting the owning PID
    # without privileges requires a platform tool, so defer to the helpers.
    if sys.platform == "win32":
        return _listening_pids_via_netstat(port)
    return _listening_pids_via_lsof_or_ss(port)


def _listening_pids_via_netstat(port: int) -> list[int]:
    """Windows: parse `netstat -ano` to find LISTEN entries on `port`."""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return []

    pids: set[int] = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        # Format: Proto LocalAddress ForeignAddress State PID
        proto, local, _remote, state, pid_str = parts[0], parts[1], parts[2], parts[3], parts[4]
        if proto.upper() != "TCP" or state.upper() != "LISTENING":
            continue
        if not local.endswith(f":{port}"):
            continue
        try:
            pids.add(int(pid_str))
        except ValueError:
            continue
    return sorted(pids)


def _listening_pids_via_lsof_or_ss(port: int) -> list[int]:
    """POSIX: prefer `lsof`, fall back to `ss`/`netstat`."""
    lsof = shutil.which("lsof")
    if lsof:
        try:
            out = subprocess.run(
                [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            ).stdout
        except subprocess.SubprocessError:
            out = ""
        pids: set[int] = set()
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pids.add(int(line))
            except ValueError:
                continue
        if pids:
            return sorted(pids)

    ss = shutil.which("ss")
    if ss:
        try:
            out = subprocess.run(
                [ss, "-ltnp", f"sport = :{port}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            ).stdout
        except subprocess.SubprocessError:
            out = ""
        pids = set()
        for line in out.splitlines():
            if "pid=" not in line:
                continue
            for token in line.split(","):
                token = token.strip()
                if token.startswith("pid="):
                    try:
                        pids.add(int(token[4:]))
                    except ValueError:
                        pass
        if pids:
            return sorted(pids)

    # Last resort: try to connect; if refused, port is free.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        rc = sock.connect_ex(("127.0.0.1", port))
    except OSError:
        rc = -1
    finally:
        sock.close()
    return [] if rc != 0 else [-1]  # -1 sentinel = "bound, but PID unknown"


def _command_line_for_pid(pid: int) -> str | None:
    """Best-effort retrieval of a process's command line."""
    if pid <= 0:
        return None
    try:
        if sys.platform == "win32":
            return _command_line_windows(pid)
        return _command_line_posix(pid)
    except Exception:
        return None


def _command_line_windows(pid: int) -> str | None:
    """Read the command line for `pid` on Windows.

    Tries `wmic` first (legacy but still present on many installs), then
    falls back to PowerShell's `Get-CimInstance` (always available on
    Windows 10/11). Returns None if both fail.
    """
    wmic = shutil.which("wmic")
    if wmic:
        try:
            out = subprocess.run(
                [wmic, "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/value"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            ).stdout
            for line in out.splitlines():
                if line.lower().startswith("commandline="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        return value
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell:
        try:
            out = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter "
                    f"\"ProcessId={pid}\").CommandLine",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            ).stdout.strip()
            return out or None
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
    return None


def _command_line_posix(pid: int) -> str | None:
    """Read /proc/<pid>/cmdline or fall back to ps -p <pid> -o args=."""
    try:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            data = cmdline_path.read_bytes().decode("utf-8", errors="replace")
            parts = [p for p in data.split("\x00") if p]
            if parts:
                return " ".join(parts)
    except OSError:
        pass

    ps = shutil.which("ps")
    if ps:
        try:
            out = subprocess.run(
                [ps, "-p", str(pid), "-o", "args="],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            ).stdout.strip()
            return out or None
        except subprocess.SubprocessError:
            return None
    return None


def _run_status() -> int:
    """Print which dashboard ports are currently LISTENing and on what PID."""
    print("Dashboard status")
    print("=" * 72)
    header = f"{'PORT':<6}{'SERVICE':<40}{'STATE':<12}PID"
    print(header)
    print("-" * len(header))

    # Aggregate the React+FastAPI summary: web (5173) + api (9001) both up.
    web_pid: int | None = None
    api_pid: int | None = None
    for port, label, url in STATUS_PORTS:
        pids = _listening_pids(port)
        if not pids:
            print(f"{port:<6}{label:<40}{'stopped':<12}-")
            continue
        for pid in pids:
            cmd = _command_line_for_pid(pid)
            state = "running"
            line = f"{port:<6}{label:<40}{state:<12}{pid}"
            print(line)
            if cmd:
                print(f"      cmd: {cmd}")
        if port == 5173 and pids:
            web_pid = pids[0]
        if port == 9001 and pids:
            api_pid = pids[0]

    print("-" * 72)
    if web_pid and api_pid:
        print(f"Dashboard (React+FastAPI): running on http://127.0.0.1:5173 "
              f"(api pid {api_pid}, web pid {web_pid})")
    else:
        parts: list[str] = []
        if web_pid:
            parts.append(f"web pid {web_pid}")
        if api_pid:
            parts.append(f"api pid {api_pid}")
        if parts:
            print(f"Dashboard (React+FastAPI): partial ({', '.join(parts)})")
        else:
            print("Dashboard (React+FastAPI): stopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.main")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("dashboard", help="Start React + FastAPI dashboard (canonical)")
    subparsers.add_parser("web", help="Alias for dashboard (React + FastAPI)")
    subparsers.add_parser("dashboard-streamlit", help="Start legacy Streamlit dashboard")

    subparsers.add_parser("alerts", help="Run realtime 13F alert poller")
    subparsers.add_parser(
        "status",
        help="Print which dashboard ports are LISTENing (diagnostic for 'what is serving?')",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, extra_args = parser.parse_known_args(argv)

    if args.command in {"dashboard", "web"}:
        if extra_args:
            parser.error(f"Unrecognized arguments for {args.command}: {' '.join(extra_args)}")
        return _run_web()
    if args.command == "dashboard-streamlit":
        return _run_dashboard(extra_args)
    if args.command == "alerts":
        if extra_args:
            parser.error(f"Unrecognized arguments for alerts: {' '.join(extra_args)}")
        return _run_alerts()
    if args.command == "status":
        if extra_args:
            parser.error(f"Unrecognized arguments for status: {' '.join(extra_args)}")
        return _run_status()

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())