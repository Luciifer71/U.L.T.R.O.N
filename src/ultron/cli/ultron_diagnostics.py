"""Read-only local checks; never start services, load models or execute proposed tools."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

from ultron.paths import project_root

ROOT = project_root()


def local_endpoint(value, default_port):
    parsed = urlsplit(value)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Only loopback services are probed")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Credential-bearing endpoints are not probed")
    return parsed.hostname, parsed.port or default_port


def check_ollama(host, model):
    try:
        local_endpoint(host, 11434)
        if urlsplit(host).scheme != "http":
            raise ValueError("Expected local HTTP")
        with urlopen(host.rstrip("/") + "/api/tags", timeout=3) as response:
            payload = json.load(response)
        names = {entry.get("name") for entry in payload["models"]}
        installed = model in names or (":" not in model and model + ":latest" in names)
        return {"status": "ok" if installed else "warning", "reachable": True,
                "configured_model_installed": installed,
                "scope": "Model inventory only; inference and GPU placement not tested"}
    except Exception as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}


def check_nats(url):
    try:
        host, port = local_endpoint(url, 4222)
        with socket.create_connection((host, port), timeout=3) as connection:
            connection.settimeout(3)
            greeting = connection.recv(4096)
        if not greeting.startswith(b"INFO "):
            return {"status": "unavailable", "reason": "No NATS greeting"}
        return {"status": "ok", "scope": "NATS greeting only; authentication and subscribers not tested"}
    except Exception as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}


def collect_process_memory(limit=10):
    """Read names and RSS only, never command lines, paths or environment."""
    import psutil
    rows = []
    skipped = 0
    try:
        for process in psutil.process_iter(["pid", "name", "memory_info"], ad_value=None):
            try:
                info = process.info
                memory = info.get("memory_info")
                if memory is None:
                    skipped += 1
                    continue
                rows.append({"pid": info["pid"], "name": info.get("name"),
                             "rss_bytes": memory.rss})
            except (psutil.Error, OSError):
                skipped += 1
    except (psutil.Error, OSError) as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}
    rows.sort(key=lambda row: row["rss_bytes"], reverse=True)
    return {"status": "ok", "top_processes": rows[:limit], "skipped": skipped,
            "scope": "RSS snapshot; shared pages can be counted in multiple processes. Not GPU memory or total system RAM attribution. Names and PIDs only; no paths or command lines."}



def check_google():
    """Isolate live account checks so a stalled provider cannot hang a support bundle."""
    root = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'Ultron' / 'google'
    if not (root / 'enabled').exists():
        return {'status': 'not_configured'}
    try:
        result = subprocess.run([sys.executable, str(ROOT / 'run_ultron.py'), 'google', 'doctor'],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
        report = json.loads(result.stdout)
        if not isinstance(report, dict) or 'connection' not in report:
            return {'status': 'diagnostic_failed'}
        return report
    except subprocess.TimeoutExpired:
        return {'status': 'timed_out', 'scope': 'Google check exceeded 60 seconds; no authorization conclusion.'}
    except (OSError, ValueError):
        return {'status': 'diagnostic_failed'}


def build_report(model):
    packages = {}
    for name in ("psutil", "ollama", "nats-py", "faster-whisper", "ctranslate2", "sounddevice", "edge-tts", "pytest",
                 "google-auth", "google-api-python-client", "google-auth-oauthlib", "google-auth-httplib2", "keyring"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    try:
        from ultron.control.system_info import collect_telemetry
        telemetry = collect_telemetry()
    except Exception as exc:
        telemetry = {"unavailable": type(exc).__name__}
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {"os": platform.system(), "python": platform.python_version()},
        "configured_model": model,
        "packages": packages,
        "telemetry": telemetry,
        "process_memory": collect_process_memory(),
        "google": check_google(),
        "services": {
            "ollama": check_ollama(os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"), model),
            "nats": check_nats(os.getenv("NATS_URL", "nats://127.0.0.1:4222")),
        },
        "regression_tests": {"status": "not_run"},
        "manual_checks": ["Wake word and full command recognized", "Spoken reply audible",
                          "Requested application visibly opened"],
        "scope": "No microphone recording, speech synthesis, model inference or application actions. No full-system health claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Model to check, e.g. qwen3:8b for the trial launcher")
    parser.add_argument("--tests", action="store_true", help="Also run verify_ultron.py with a 180-second limit")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    report = build_report(args.model or os.getenv("LLM_MODEL", "qwen3:8b"))
    if args.tests:
        started = time.monotonic()
        try:
            result = subprocess.run([sys.executable, str(ROOT / "verify_ultron.py")],
                                    cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=180)
            report["regression_tests"] = {"status": "passed" if result.returncode == 0 else "failed",
                                          "exit_code": result.returncode}
            # Show test output locally; do not copy arbitrary logs into the shareable report.
            print(result.stdout)
            if result.returncode:
                print(result.stderr)
        except subprocess.TimeoutExpired:
            report["regression_tests"] = {"status": "timed_out"}
        report["regression_tests"]["seconds"] = round(time.monotonic() - started, 3)
    output = args.output or ROOT / "runtime" / "diagnostics" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Report: {output}")
    return 1 if report["regression_tests"]["status"] in {"failed", "timed_out"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
