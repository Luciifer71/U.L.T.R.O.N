import argparse
import json
from pathlib import Path

import pytest

import model_benchmark as benchmark


def response(calls=None, content=''):
    return {'done': True, 'done_reason': 'stop', 'message': {'content': content, 'tool_calls': calls or []},
            'eval_count': 10, 'eval_duration': 1_000_000_000}


def call(name, **args):
    return {'function': {'name': name, 'arguments': args}}


def test_contract_read_does_not_execute_brain(tmp_path):
    path = tmp_path / 'brain.py'
    path.write_text("raise RuntimeError('must not execute')\nTOOLS = [{'function': {'name': 'one'}}]\n"
                    "TOOLS.extend([{'function': {'name': 'two'}}])\n"
                    "class Brain:\n def refresh(self):\n  self.system_prompt = f'Rules{facts_summary}'\n")
    tools, prompt, digest = benchmark.load_contract(path)
    assert len(tools) == 2 and prompt == 'Rules' and len(digest) == 64


def test_actual_contract_contains_resource_tools():
    tools, prompt, _ = benchmark.load_contract()
    names = {t['function']['name'] for t in tools}
    assert {'operate_resource', 'open_application', 'find_resources', 'activate_protocol'} <= names
    assert 'EXECUTION TRUTH' in prompt and 'LOCAL RESOURCES' in prompt


def test_extractor_refuses_dynamic_schema(tmp_path):
    path = tmp_path / 'brain.py'
    path.write_text("TOOLS = make_tools()\n")
    with pytest.raises(ValueError):
        benchmark.load_contract(path)


@pytest.mark.parametrize('host', ['https://localhost:11434', 'http://example.com',
                                  'http://localhost@evil.com', 'http://localhost/private',
                                  'http://localhost?token=secret'])
def test_no_remote_or_credential_endpoint(host):
    with pytest.raises(ValueError):
        benchmark.OllamaHTTP(host, 90)


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf')])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        benchmark.OllamaHTTP('http://localhost:11434', timeout)


def test_target_changes_and_extra_calls_fail():
    expected = call('operate_resource', operation='run_script', target='ultron smoke script')
    case = {'acceptable_calls': [[expected]]}
    assert benchmark.score_response(response([expected]), case)[0]
    changed = call('operate_resource', operation='run_script', target='ultron_smoke_script.py')
    assert not benchmark.score_response(response([changed]), case)[0]
    assert not benchmark.score_response(response([expected, expected]), case)[0]
    assert not benchmark.score_response(response([expected, call('activate_protocol', protocol='gaming_mode')]), case)[0]


def test_multi_app_omission_fails_but_order_does_not_matter():
    calls = [call('open_application', app_name='Notion'), call('open_application', app_name='Notepad')]
    case = {'acceptable_calls': [calls]}
    assert not benchmark.score_response(response(calls[:1]), case)[0]
    assert benchmark.score_response(response(calls[::-1]), case)[0]


@pytest.mark.parametrize('value', [{'done': False}, {'done': True, 'done_reason': 'length'},
                                  response(content=''), response([{'function': {'name': 'x', 'arguments': '{}'}}])])
def test_invalid_or_empty_response_cannot_pass(value):
    assert not benchmark.score_response(value, {'acceptable_calls': [[]]})[0]


def test_negation_requires_no_tool_calls():
    case = {'acceptable_calls': [[]]}
    assert benchmark.score_response(response(content='I will not open it.'), case)[0]
    assert not benchmark.score_response(response([call('open_application', app_name='Calculator')]), case)[0]


class FakeOllama:
    def __init__(self, fail_chat=False, fail_unload=False):
        self.calls = []
        self.fail_chat = fail_chat
        self.fail_unload = fail_unload

    def request(self, route, payload=None):
        self.calls.append((route, payload))
        if route == '/api/show':
            return {'capabilities': ['tools', 'thinking']}
        if route == '/api/ps':
            return {'models': []}
        if route == '/api/generate':
            if self.fail_unload:
                raise OSError('unload failed')
            return {'done': True}
        if self.fail_chat and payload.get('tools'):
            raise TimeoutError('timed out')
        return response(content='Hello')


def settings():
    return argparse.Namespace(thinking='off', context=4096, repeats=1)


def test_benchmark_never_dispatches_proposed_actions_and_controls_thinking():
    client = FakeOllama()
    results = []
    result = benchmark.run_model(client, 'candidate', [{'id': 'hello', 'prompt': 'Hello', 'acceptable_calls': [[]]}],
                                 [{'function': {'name': 'open_application'}}], 'rules', settings(), results.append)
    assert result['summary']['contract_passes'] == 1
    assert result['unload_requested']
    assert all(route in {'/api/show', '/api/chat', '/api/ps', '/api/generate'} for route, _ in client.calls)
    chats = [payload for route, payload in client.calls if route == '/api/chat']
    assert all(payload['think'] is False and payload['options']['num_ctx'] == 4096 for payload in chats)


def test_timeout_preserves_evidence_and_stops_further_cases():
    client = FakeOllama(fail_chat=True)
    saved = []
    case = {'id': 'hello', 'prompt': 'Hello', 'acceptable_calls': [[]]}
    with pytest.raises(RuntimeError):
        benchmark.run_model(client, 'candidate', [case, case], [{'tool': 'stub'}], 'rules', settings(), saved.append)
    assert saved[-1]['rows'][0]['reason'] == 'request_error'
    assert len(saved[-1]['rows']) == 1
    assert saved[-1]['unload_requested']


def test_existing_output_is_not_overwritten(tmp_path):
    output = tmp_path / 'report.json'
    output.write_text('keep this evidence')
    with pytest.raises(SystemExit):
        benchmark.main(['--output', str(output)])
    assert output.read_text() == 'keep this evidence'


def test_missing_model_preflight_has_no_inference(monkeypatch, tmp_path):
    routes = []
    def request(self, route, payload=None):
        routes.append(route)
        return {'models': []} if route == '/api/tags' else {'version': 'test'}
    monkeypatch.setattr(benchmark.OllamaHTTP, 'request', request)
    output = tmp_path / 'report.json'
    assert benchmark.main(['--models', 'missing', '--output', str(output)]) == 2
    report = json.loads(output.read_text())
    assert report['status'] == 'failed' and 'ollama pull missing' in report['error']
    assert '/api/chat' not in routes


def test_fixture_names_unique_and_expected_tools_exist():
    cases = json.loads((benchmark.ROOT / 'evals/model_cases.json').read_text())
    assert len({c['id'] for c in cases}) == len(cases)
    tools, _, _ = benchmark.load_contract()
    names = {t['function']['name'] for t in tools}
    for case in cases:
        assert case['acceptable_calls']
        for variant in case['acceptable_calls']:
            benchmark.calls_key(variant)
            assert all(c['function']['name'] in names for c in variant)
