#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-instance launcher for Financial Metric Resolver v6.1.

Only terminates processes after validating that the PID command line belongs to
this application. No global `taskkill python.exe` is used.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
from data_home import resolve_data_home, ensure_data_home  # noqa: E402

from version import APP_VERSION as VERSION
DEFAULT_PORT = 8501


def _paths():
    data_home = resolve_data_home(APP_DIR)
    paths = ensure_data_home(data_home, APP_DIR / "metric_aliases.json")
    runtime = paths["runtime"]
    runtime.mkdir(parents=True, exist_ok=True)
    return paths, runtime


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True,
        )
        return proc.returncode == 0 and str(pid) in proc.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def process_command_line(pid: int) -> str:
    if os.name == "nt":
        cmd = (
            "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" -ErrorAction SilentlyContinue;"
            "if($p){$p.CommandLine}" % pid
        )
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
        return proc.stdout.strip()
    path = Path(f"/proc/{pid}/cmdline")
    if path.exists():
        try:
            return path.read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except Exception:
            return ""
    return ""


def is_our_streamlit(pid: int, expected_code_home: Optional[str] = None) -> bool:
    if not pid_alive(pid):
        return False
    cmd = process_command_line(pid).lower().replace("\\", "/")
    if "streamlit" not in cmd or "app.py" not in cmd:
        return False
    if expected_code_home:
        home = str(expected_code_home).lower().replace("\\", "/")
        if home not in cmd and "financial_metric_resolver" not in cmd:
            return False
    elif "financial_metric_resolver" not in cmd:
        # Never terminate an unrelated Streamlit app merely because it owns 8501.
        return False
    return True


def terminate_streamlit(pid: int, expected_code_home: Optional[str] = None, timeout: float = 6.0) -> bool:
    if not is_our_streamlit(pid, expected_code_home):
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    return not pid_alive(pid)


def request_old_launcher_shutdown(runtime: Path, active: dict[str, Any]) -> bool:
    token = str(active.get("instance_token") or "")
    launcher_pid = int(active.get("launcher_pid") or 0)
    streamlit_pid = int(active.get("streamlit_pid") or 0)
    if not token:
        return False
    control = runtime / "control.json"
    _write_json(control, {"action": "shutdown", "instance_token": token, "requested_by": VERSION, "requested_at": time.time()})
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if (not pid_alive(launcher_pid)) and (not pid_alive(streamlit_pid)):
            control.unlink(missing_ok=True)
            return True
        time.sleep(0.25)
    return False


def pid_listening_on_port(port: int) -> int:
    if os.name == "nt":
        cmd = (
            f"$c=Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty OwningProcess; if($c){$c}"
        )
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
        try:
            return int(proc.stdout.strip().splitlines()[0])
        except Exception:
            return 0
    # Linux/macOS best-effort; do not kill when ownership cannot be proven.
    for cmd in (["lsof", "-ti", f"tcp:{int(port)}"], ["fuser", f"{int(port)}/tcp"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            tokens = (proc.stdout + " " + proc.stderr).strip().split()
            for token in tokens:
                if token.isdigit():
                    return int(token)
        except Exception:
            continue
    return 0


def prepare_port(port: int) -> int:
    """Close a proven old FinancialMetricResolver listener, otherwise choose a free port."""
    owner = pid_listening_on_port(port)
    if not owner:
        return port
    if is_our_streamlit(owner, None):
        terminate_streamlit(owner, None)
        time.sleep(0.5)
        if not pid_listening_on_port(port):
            return port
    # Never kill unrelated software. Find another port.
    for candidate in range(port + 1, port + 20):
        if not pid_listening_on_port(candidate):
            return candidate
    raise RuntimeError("No free Streamlit port found in safe range")


def stop_previous_instance(runtime: Path) -> None:
    active_path = runtime / "active_instance.json"
    active = _read_json(active_path)
    if not active:
        return
    old_streamlit = int(active.get("streamlit_pid") or 0)
    old_launcher = int(active.get("launcher_pid") or 0)
    if old_launcher == os.getpid():
        return

    # First ask the old launcher to shut down gracefully.
    request_old_launcher_shutdown(runtime, active)

    # Fallback: only kill a PID after validating it is our Streamlit process.
    if old_streamlit and pid_alive(old_streamlit):
        terminate_streamlit(old_streamlit, active.get("code_home"))
    active_path.unlink(missing_ok=True)


def start_streamlit(port: int, token: str) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(APP_DIR / "app.py"),
        "--server.port", str(port),
        "--server.headless", "false",
    ]
    env = os.environ.copy()
    env["FIN_METRIC_INSTANCE_TOKEN"] = token
    kwargs: dict[str, Any] = {"cwd": str(APP_DIR), "env": env}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def main() -> int:
    _, runtime = _paths()
    active_path = runtime / "active_instance.json"
    control_path = runtime / "control.json"
    control_path.unlink(missing_ok=True)
    stop_previous_instance(runtime)

    token = uuid.uuid4().hex
    requested_port = int(os.environ.get("FIN_METRIC_PORT") or DEFAULT_PORT)
    port = prepare_port(requested_port)

    while True:
        child = start_streamlit(port, token)
        record = {
            "product": "FinancialMetricResolver",
            "version": VERSION,
            "instance_token": token,
            "launcher_pid": os.getpid(),
            "streamlit_pid": child.pid,
            "port": port,
            "code_home": str(APP_DIR),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _write_json(active_path, record)
        print(f"Financial Metric Resolver {VERSION} running at http://localhost:{port}")

        restart = False
        while child.poll() is None:
            request = _read_json(control_path)
            if request and request.get("instance_token") == token:
                action = str(request.get("action") or "").lower()
                control_path.unlink(missing_ok=True)
                if action in {"shutdown", "restart"}:
                    terminate_streamlit(child.pid, str(APP_DIR))
                    restart = action == "restart"
                    break
            time.sleep(0.5)

        try:
            child.wait(timeout=5)
        except Exception:
            pass

        if restart:
            token = uuid.uuid4().hex
            continue
        break

    active = _read_json(active_path)
    if active.get("launcher_pid") == os.getpid():
        active_path.unlink(missing_ok=True)
    control_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
