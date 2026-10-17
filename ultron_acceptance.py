"""One-command acceptance report and support ZIP; live app checks are opt-in."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from collect_ultron_report import make_bundle
from ultron_diagnostics import build_report
from ultron_control.request_planning import explicit_launch_plan, validate_application_targets, PlanClarification

ROOT = Path(__file__).resolve().parent


def application_call(name):
    return {'function': {'name': 'open_application', 'arguments': {'app_name': name}}}


def planning_checks():
    rows = []
    for prompt, expected in [
        ('Open calculator.', ['Calculator']),
        ('Open the calculator and file explorer for me.', ['Calculator', 'File Explorer']),
        ('Open file, explorer and calculator.', ['File Explorer', 'Calculator']),
        ('Okay then, can you open calculator and notion for me?', ['Calculator', 'Notion']),
    ]:
        started = time.perf_counter()
        calls = explicit_launch_plan(prompt)
        passed = calls == [application_call(name) for name in expected] and validate_application_targets(prompt, calls) is None
        rows.append({'prompt': prompt, 'expected': expected, 'passed': passed,
                     'seconds': round(time.perf_counter() - started, 6)})
    for prompt in [
        'Annual pull, file explorer, calculator and two things.',
        'I like Calculator.', 'Do not open Calculator.',
        'If I finish studying, open Calculator.', 'Explain how to open Calculator.',
        '"Open Calculator."', 'Search youtube for how to open Calculator.',
    ]:
        rejection = validate_application_targets(prompt, [application_call('Calculator')])
        rows.append({'prompt': prompt, 'expected': 'reject proposed launch', 'passed': bool(rejection)})
    for prompt in ['Open calculator and mysteryapp.', 'Open file, explorer and calculator,']:
        try:
            explicit_launch_plan(prompt)
            rejected = False
        except PlanClarification:
            rejected = True
        rows.append({'prompt': prompt, 'expected': 'clarify entire list', 'passed': rejected})
    return rows


async def live_checks():
    # Fixed, visible smoke actions only. Never replay arbitrary support-log text.
    from send_intent import send_command
    rows = []
    for prompt, expected in [
        ('What is my uptime?', 'System uptime:'),
        ('Open file, explorer and calculator.', 'Opened and verified: File Explorer, Calculator.'),
    ]:
        started = time.perf_counter()
        try:
            response = await send_command(prompt, timeout=45)
            passed = response.get('execution', {}).get('success') is True and expected in response.get('text', '')
            rows.append({'prompt': prompt, 'passed': passed, 'response': response,
                         'seconds': round(time.perf_counter() - started, 3)})
        except Exception as exc:
            rows.append({'prompt': prompt, 'passed': False, 'error': type(exc).__name__,
                         'note': 'Stopped without retrying; an issued command may still be running.'})
            break
    return rows


def run_regressions(output):
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
                             *sorted(p.name for p in ROOT.glob('test_*.py')),
                             '--junitxml', str(output)], cwd=ROOT, capture_output=True,
                            text=True, errors='replace', timeout=180)
    counts = {}
    if output.exists():
        suites = ET.parse(output).getroot()
        counts = {key: sum(int(s.get(key, '0')) for s in suites.iter('testsuite'))
                  for key in ('tests', 'failures', 'errors', 'skipped')}
    return {'status': 'passed' if result.returncode == 0 else 'failed',
            'exit_code': result.returncode, 'counts': counts}, result.stdout + '\n' + result.stderr


def main(argv=None):
    from dotenv import load_dotenv
    from ollama_runtime import OllamaRuntimeConfig
    load_dotenv(ROOT / '.env', override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-apps', action='store_true', help='Requires a running brain; opens Calculator and File Explorer')
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = ROOT / 'runtime' / 'acceptance'
    directory.mkdir(parents=True, exist_ok=True)
    config = OllamaRuntimeConfig.from_env()
    report = {'schema_version': 1, 'observed_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'Regression tests and deterministic planning contracts; optional fixed live app checks. No live model benchmark or microphone/speaker certification.',
              'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                for name in ('brain_agent.py', 'ultron_control/request_planning.py', 'ultron_acceptance.py')},
              'model': config.model, 'planning': planning_checks(),
              'live': {'status': 'not_run'}, 'manual_audio': 'unverified'}
    console = ''
    try:
        report['regression'], console = run_regressions(directory / (stamp + '.xml'))
    except subprocess.TimeoutExpired:
        report['regression'] = {'status': 'timed_out'}
    offline_ok = report['regression']['status'] == 'passed' and all(r['passed'] for r in report['planning'])
    if args.live_apps and offline_ok:
        rows = asyncio.run(live_checks())
        report['live'] = {'status': 'passed' if len(rows) == 2 and all(r['passed'] for r in rows) else 'failed', 'rows': rows}
    elif args.live_apps:
        report['live'] = {'status': 'blocked_by_offline_failure'}
    report['status'] = 'passed' if offline_ok and (not args.live_apps or report['live']['status'] == 'passed') else 'failed'
    path = directory / (stamp + '.json')
    serialized = json.dumps(report, indent=2) + '\n'
    path.write_text(serialized, encoding='utf-8')
    (directory / 'latest.json').write_text(serialized, encoding='utf-8')
    diagnostic_path = directory / (stamp + '-diagnostics.json')
    diagnostic_path.write_text(json.dumps(build_report(config.model), indent=2), encoding='utf-8')
    bundle = ROOT / 'runtime' / 'support' / ('ultron-acceptance-' + stamp + '.zip')
    make_bundle(ROOT, diagnostic_path, bundle, console, acceptance=path)
    print(json.dumps({'status': report['status'], 'regression': report['regression'],
                      'planning_passes': sum(r['passed'] for r in report['planning']),
                      'planning_cases': len(report['planning']), 'live': report['live']['status'],
                      'audio': 'unverified', 'bundle': str(bundle)}, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
