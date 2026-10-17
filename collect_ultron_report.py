"""Collect a local support ZIP. Nothing is uploaded automatically."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
COMPONENTS = ('brain_agent', 'voice_listener', 'action_daemon')
LIMIT = 2 * 1024 * 1024


def redact(text):
    # Best effort: reports still contain user commands, filenames and responses.
    text = re.sub(r'(?i)([?&](?:token|key|api_key|TrustedClientToken|ConnectionId|Sec-MS-GEC)\s*=)[^&\s\"\']+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(\b(?:api[_-]?key|access[_-]?token|password|secret|authorization)\b[\"\']?\s*[:=]\s*)[^\r\n,;]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(https?://|nats://)[^\s/@:]+:[^\s/@]+@', r'\1[REDACTED]@', text)
    text = re.sub(r'(?i)C:\\Users\\[^\\\s]+', r'C:\\Users\\[USER]', text)
    return text


def make_bundle(root, report, output, diagnostic_output="", acceptance=None):
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'files': [], 'missing': [],
                'privacy': 'Contains transcripts, responses and resource names. Redaction is best effort; review before sharing.',
                'scope': 'Launcher-managed Python logs only. Ollama/Docker native logs and audio recordings are not captured.'}
    paths = [report]
    acceptance = acceptance or root / 'runtime' / 'acceptance' / 'latest.json'
    if acceptance.is_file() and not acceptance.is_symlink():
        paths.append(acceptance)
    for component in COMPONENTS:
        current = root / 'runtime' / 'logs' / f'{component}.log'
        if not current.is_file():
            manifest['missing'].append(current.name + ': restart using the updated launcher to enable capture')
        for path in (current.with_suffix('.log.1'), current):
            if path.is_file():
                paths.append(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            # Bound reads even if a component is still writing.
            with path.open('rb') as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - LIMIT))
                data = stream.read(LIMIT).decode('utf-8', errors='replace')
            name = 'diagnostics.json' if path == report else 'acceptance.json' if path == acceptance else 'logs/' + path.name
            archive.writestr(name, redact(data))
            manifest['files'].append({'name': name, 'modified_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), 'truncated': size > LIMIT})
        if diagnostic_output:
            archive.writestr('diagnostic-console.txt', redact(diagnostic_output[-500000:]))
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
        archive.writestr('READ_ME.txt', 'Review before sharing: logs include spoken commands and responses. Credentials are redacted on a best-effort basis. No environment files, databases, audio, or arbitrary project files are collected. Check manifest.json for missing/stale logs.\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', help='Model inventory to check (e.g. qwen3:8b)')
    parser.add_argument('--tests', action='store_true', help='Also run the regression suite')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = ROOT / 'runtime' / 'diagnostics' / (stamp + '.json')
    command = [sys.executable, str(ROOT / 'ultron_diagnostics.py'), '--output', str(report)]
    if args.model:
        command += ['--model', args.model]
    if args.tests:
        command += ['--tests']
    diagnostic_output = ""
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, errors='replace', timeout=210)
        status = result.returncode
        diagnostic_output = result.stdout + "\n" + result.stderr
        if not report.is_file():
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({'diagnostics_failed': True, 'exit_code': status, 'stderr': redact(result.stderr[-8000:])}), encoding='utf-8')
    except subprocess.TimeoutExpired:
        status = 1
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'diagnostics_failed': True, 'reason': 'Timed out after 210 seconds'}), encoding='utf-8')
    output = ROOT / 'runtime' / 'support' / f'ultron-support-{stamp}.zip'
    manifest = make_bundle(ROOT, report, output, diagnostic_output)
    for missing in manifest['missing']:
        print('Missing log:', missing)
    print('Review the ZIP before sharing: it includes command transcripts and responses.')
    print(f'Diagnostic exit code: {status}. See diagnostics.json for service and test results.')
    print(f'Upload this one file: {output}')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
