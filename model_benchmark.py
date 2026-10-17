"""Offline-action Ollama tool-planning benchmark; no proposed tool is executed."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
MAX_RESPONSE = 4 * 1024 * 1024


def load_contract(path=ROOT / 'brain_agent.py'):
    """Read literal tools and fact-free system prompt without importing the brain."""
    source = path.read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    tools = None
    prompt = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'TOOLS' for t in node.targets):
            tools = ast.literal_eval(node.value)
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == 'TOOLS'):
            if node.value.func.attr != 'extend' or tools is None or len(node.value.args) != 1:
                raise ValueError('Unsupported TOOLS construction; update the benchmark extractor.')
            tools.extend(ast.literal_eval(node.value.args[0]))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
            and t.value.id == 'self' and t.attr == 'system_prompt' for t in node.targets
        ):
            if isinstance(node.value, ast.Constant):
                prompt = ast.literal_eval(node.value)
            elif isinstance(node.value, ast.JoinedStr):
                parts = []
                for part in node.value.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        parts.append(part.value)
                    elif (isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name)
                          and part.value.id == 'facts_summary' and part.format_spec is None):
                        parts.append('')  # Never read personal memory for synthetic evaluation.
                    else:
                        raise ValueError('Unsupported system prompt expression.')
                prompt = ''.join(parts)
            else:
                raise ValueError('Unsupported system prompt construction.')
    if not tools or not isinstance(prompt, str) or not prompt:
        raise ValueError('Could not extract current tool contract and system prompt.')
    return tools, prompt, hashlib.sha256(source.encode()).hexdigest()


class OllamaHTTP:
    def __init__(self, host, timeout):
        url = urllib.parse.urlsplit(host)
        if (url.scheme != 'http' or url.hostname not in {'localhost', '127.0.0.1', '::1'}
                or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment):
            raise ValueError('Benchmark requires a local http://localhost:port Ollama URL.')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Timeout must be finite and positive.')
        self.host = host.rstrip('/')
        self.timeout = timeout
        # Never route synthetic local inference through environment HTTP proxies.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, route, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.host + route, data=data, headers={'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=self.timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('Ollama response exceeded benchmark size limit.')
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('error'):
            raise ValueError('Invalid Ollama response: ' + str(value)[:400])
        return value


def canonical(value):
    # Preserve punctuation, extensions, word order, argument keys and duplicates.
    if isinstance(value, str):
        return ' '.join(value.casefold().split())
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    return value


def calls_key(calls):
    if not isinstance(calls, list):
        raise ValueError('tool_calls must be a list.')
    result = []
    for call in calls:
        function = call['function']
        name, arguments = function['name'], function['arguments']
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError('Tool name/arguments have invalid types.')
        result.append(json.dumps(canonical({'name': name, 'arguments': arguments}), sort_keys=True))
    return sorted(result)


def score_response(response, case):
    if response.get('done') is not True or response.get('done_reason') == 'length':
        return False, 'incomplete_response'
    message = response.get('message')
    if not isinstance(message, dict):
        return False, 'missing_message'
    try:
        actual = calls_key(message.get('tool_calls', []))
        matched = any(actual == calls_key(choice) for choice in case['acceptable_calls'])
    except (KeyError, TypeError, ValueError):
        return False, 'malformed_tool_calls'
    if not actual and not str(message.get('content') or '').strip():
        return False, 'empty_response'
    return matched, 'contract_match' if matched else 'tool_or_target_mismatch'


def run_model(client, model, cases, tools, prompt, args, checkpoint):
    info = client.request('/api/show', {'model': model})
    caps = info.get('capabilities', [])
    if 'tools' not in caps:
        raise ValueError(f'{model}: Ollama does not advertise tool support. Check model and Ollama version.')
    thinking = None if 'thinking' not in caps or args.thinking == 'default' else args.thinking == 'on'
    common = {'model': model, 'stream': False, 'keep_alive': '5m',
              'options': {'num_ctx': args.context, 'num_predict': 256, 'temperature': 0, 'seed': 42}}
    if thinking is not None:
        common['think'] = thinking
    result = {'model': model, 'capabilities': caps, 'details': info.get('details'),
              'effective_think': thinking, 'rows': [], 'status': 'running'}
    checkpoint(result)
    try:
        start = time.perf_counter()
        warmup = client.request('/api/chat', {**common, 'messages': [{'role': 'user', 'content': 'Reply with OK.'}]})
        if warmup.get('done') is not True or not isinstance(warmup.get('message'), dict):
            raise ValueError('Warmup did not return a completed message.')
        result['warmup_wall_seconds'] = round(time.perf_counter() - start, 3)
        result['warmup_load_seconds'] = warmup.get('load_duration', 0) / 1e9
        for repeat in range(args.repeats):
            for case in cases:
                row = {'case': case['id'], 'repeat': repeat + 1, 'prompt': case['prompt']}
                start = time.perf_counter()
                try:
                    response = client.request('/api/chat', {
                        **common, 'tools': tools,
                        'messages': [{'role': 'system', 'content': prompt},
                                     *case.get('history', []), {'role': 'user', 'content': case['prompt']}],
                    })
                    row['contract_pass'], row['reason'] = score_response(response, case)
                    row['response'] = response
                    duration = response.get('eval_duration', 0)
                    row['tokens_per_second'] = response.get('eval_count', 0) / (duration / 1e9) if duration else None
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    row.update(contract_pass=False, reason='request_error', error=str(exc)[:500])
                row['wall_seconds'] = round(time.perf_counter() - start, 3)
                result['rows'].append(row)
                checkpoint(result)
                print(f"{model}: {case['id']} {row['reason']} ({row['wall_seconds']}s)", flush=True)
                # A timeout can leave server-side generation running. Stop rather than
                # queue additional requests or pretend recovery/cancellation is proven.
                if row['reason'] == 'request_error':
                    raise RuntimeError('Request failed; benchmark stopped. Check Ollama before retrying.')
        result['residency_snapshot'] = client.request('/api/ps')
        values = sorted(row['wall_seconds'] for row in result['rows'])
        result['summary'] = {
            'contract_passes': sum(row['contract_pass'] for row in result['rows']),
            'requests': len(values), 'median_wall_seconds': statistics.median(values),
            'p95_wall_seconds': values[math.ceil(.95 * len(values)) - 1],
            'manual_response_review_required': True,
        }
        result['status'] = 'completed'
    except (Exception, KeyboardInterrupt):
        result['status'] = 'failed_or_interrupted'
        raise
    finally:
        try:
            client.request('/api/generate', {'model': model, 'keep_alive': 0, 'stream': False})
            result['unload_requested'] = True
        except (OSError, ValueError) as exc:
            result['unload_error'] = str(exc)[:500]
        checkpoint(result)
    if result.get('unload_error'):
        raise RuntimeError('Model unload failed; stop Ollama generation before continuing.')
    if client.request('/api/ps').get('models'):
        raise RuntimeError('Ollama still has loaded models; stop them before continuing the comparison.')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', default=['qwen2.5:7b', 'qwen3.5:4b', 'qwen3:8b'])
    parser.add_argument('--host', default='http://127.0.0.1:11434')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--context', type=int, default=4096)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--thinking', choices=['off', 'on', 'default'], default='off')
    parser.add_argument('--label', default='brain-only', help='Describe workload, e.g. whisper-loaded; does not start speech.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 20 or not 2048 <= args.context <= 32768:
        parser.error('Use repeats 1..20 and context 2048..32768.')
    output = args.output or ROOT / 'runtime' / 'benchmarks' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    if output.exists():
        parser.error('Output already exists; choose a new file to preserve earlier evidence.')
    report = {'schema_version': 1, 'status': 'preflight', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Model-only synthetic tool planning; no actions, parser, memory, audio or readiness verification.',
              'configuration': {k: v for k, v in vars(args).items() if k not in {'output', 'host'}}, 'models': []}

    def save(result=None):
        if result is not None and not any(r is result for r in report['models']):
            report['models'].append(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + '.tmp')
        temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, output)

    try:
        client = OllamaHTTP(args.host, args.timeout)
        tools, prompt, source_hash = load_contract()
        case_bytes = (ROOT / 'evals' / 'model_cases.json').read_bytes()
        cases = json.loads(case_bytes)
        if not cases:
            raise ValueError('Evaluation set is empty.')
        report['brain_source_sha256'] = source_hash
        report['cases_sha256'] = hashlib.sha256(case_bytes).hexdigest()
        report['ollama_version'] = client.request('/api/version')
        inventory = client.request('/api/tags').get('models', [])
        report['model_inventory'] = [{k: m.get(k) for k in ('name', 'digest', 'size', 'details')} for m in inventory]
        available = {m['name'] for m in inventory}
        missing = [m for m in args.models if m not in available]
        if missing:
            raise ValueError('Missing models. Download explicitly first: ' + '; '.join('ollama pull ' + m for m in missing))
        loaded = client.request('/api/ps').get('models', [])
        if loaded:
            raise ValueError('Stop Ultron brain and unload running Ollama models first: ' + ', '.join(m['name'] for m in loaded))
        report['status'] = 'running'
        save()
        for model in dict.fromkeys(args.models):
            result = run_model(client, model, cases, tools, prompt, args, save)
            print(json.dumps({'model': model, **result['summary']}, indent=2), flush=True)
        report['status'] = 'completed'
        save()
        print(f'Report: {output}\nReview accuracy and latency; no model has been promoted or project setting changed.')
        # Contract misses are evidence, not a failed benchmark process.
        return 0
    except KeyboardInterrupt:
        report.update(status='interrupted', error='User interrupted; verify Ollama has stopped generation.')
        save()
        print(f'Interrupted; partial report: {output}')
        return 130
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        report.update(status='failed', error=str(exc)[:1000])
        save()
        print(f'Benchmark stopped: {exc}\nReport: {output}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
