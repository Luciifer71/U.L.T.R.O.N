import asyncio

import pytest

from ultron.core.ollama_runtime import OllamaRuntime, OllamaRuntimeConfig


@pytest.fixture(autouse=True)
def clean_profile(monkeypatch):
    for key in ('LLM_THINKING', 'LLM_CONTEXT', 'LLM_TEMPERATURE', 'LLM_SEED'):
        monkeypatch.delenv(key, raising=False)


def test_explicit_legacy_model_preserves_existing_request(monkeypatch):
    received = []
    class Client:
        async def chat(self, **kwargs):
            received.append(kwargs)
            return {'message': {'content': 'ok'}}
    monkeypatch.setattr('ultron.core.ollama_runtime.AsyncClient', lambda **kwargs: Client())
    runtime = OllamaRuntime(OllamaRuntimeConfig.from_env(model="qwen2.5:7b"))
    runtime._ready = True
    request = {'model': 'qwen2.5:7b', 'messages': [], 'options': {'temperature': 0.2}}
    asyncio.run(runtime.chat(**request))
    assert received == [request]
    assert 'think' not in received[0]


def test_trial_profile_applies_to_every_request_without_mutation(monkeypatch):
    for key, value in {'LLM_THINKING': 'off', 'LLM_CONTEXT': '4096',
                       'LLM_TEMPERATURE': '0', 'LLM_SEED': '42'}.items():
        monkeypatch.setenv(key, value)
    received = []
    class Client:
        async def chat(self, **kwargs):
            received.append(kwargs)
            return {'message': {'content': 'ok'}}
    monkeypatch.setattr('ultron.core.ollama_runtime.AsyncClient', lambda **kwargs: Client())
    runtime = OllamaRuntime(OllamaRuntimeConfig.from_env(model='qwen3:8b'))
    runtime._ready = True
    options = {'temperature': 0.2, 'num_predict': 256}
    async def run():
        await runtime.chat(model='qwen3:8b', messages=[], options=options)
        await runtime.chat(model='qwen3:8b', messages=[], keep_alive='2m')
    asyncio.run(run())
    for request in received:
        assert request['think'] is False
        assert request['options']['num_ctx'] == 4096
        assert request['options']['temperature'] == 0
        assert request['options']['seed'] == 42
    assert received[0]['keep_alive'] == '10m'
    assert received[1]['keep_alive'] == '2m'
    assert received[0]['options']['num_predict'] == 256
    assert options == {'temperature': 0.2, 'num_predict': 256}


@pytest.mark.parametrize('key,value', [
    ('LLM_THINKING', 'maybe'), ('LLM_CONTEXT', 'zero'),
    ('LLM_CONTEXT', '0'), ('LLM_TEMPERATURE', 'nan'),
    ('LLM_TEMPERATURE', '-1'), ('LLM_SEED', 'forty'),
])
def test_invalid_profile_fails_before_client_creation(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    def forbidden_client(**kwargs):
        pytest.fail('Invalid profile must fail before client creation')
    monkeypatch.setattr('ultron.core.ollama_runtime.AsyncClient', forbidden_client)
    with pytest.raises(ValueError):
        OllamaRuntime(OllamaRuntimeConfig.from_env())


@pytest.mark.parametrize('shape', ['dict', 'object', 'missing'])
def test_timing_metadata_preserves_response_and_excludes_content(monkeypatch, capsys, shape):
    import json
    from types import SimpleNamespace
    metadata = {'load_duration': 2_000_000_000, 'prompt_eval_duration': 3_000_000_000,
                'eval_duration': 4_000_000_000, 'total_duration': 9_000_000_000,
                'prompt_eval_count': 100, 'eval_count': 20,
                'message': {'content': 'private response'}}
    response = (metadata if shape == 'dict' else SimpleNamespace(**metadata)
                if shape == 'object' else {'message': {'content': 'private response'}})
    received = []
    clock = [0.0]
    monkeypatch.setattr('ultron.core.ollama_runtime.time.perf_counter', lambda: clock[0])
    class Client:
        async def chat(self, **kwargs):
            received.append(kwargs)
            clock[0] += 9
            return response
    monkeypatch.setattr('ultron.core.ollama_runtime.AsyncClient', lambda **kwargs: Client())
    runtime = OllamaRuntime(OllamaRuntimeConfig())
    async def ready():
        clock[0] += 2
    monkeypatch.setattr(runtime, 'wait_until_ready', ready)
    result = asyncio.run(runtime.chat(diagnostic_task_id='task-1', diagnostic_phase='plan',
                                     messages=[{'role': 'user', 'content': 'private prompt'}]))
    assert result is response
    assert set(received[0]) == {'messages', 'keep_alive'}
    assert received[0]['keep_alive'] == '10m'
    output = capsys.readouterr().out
    assert 'private' not in output
    row = json.loads(output.split('[OLLAMA TIMING] ')[1])
    assert row['task_id'] == 'task-1' and row['phase'] == 'plan'
    assert row['ready_seconds'] == 2 and row['attempt_seconds'] == 9
    assert row['request_seconds'] == 11
    if shape == 'missing':
        assert 'load_seconds' not in row
    else:
        assert row['load_seconds'] == 2 and row['prompt_eval_seconds'] == 3
        assert row['eval_seconds'] == 4 and row['eval_count'] == 20


def test_timing_reports_failed_attempt_and_recovery(monkeypatch, capsys):
    import json
    calls = []
    class Client:
        async def chat(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise OSError('temporary failure')
            return {'message': {'content': 'ok'}}
    monkeypatch.setattr('ultron.core.ollama_runtime.AsyncClient', lambda **kwargs: Client())
    runtime = OllamaRuntime(OllamaRuntimeConfig(retry_attempts=2, retry_backoff_sec=0))
    async def ready():
        pass
    monkeypatch.setattr(runtime, 'wait_until_ready', ready)
    result = asyncio.run(runtime.chat(messages=[]))
    assert result['message']['content'] == 'ok'
    rows = [json.loads(line.split('[OLLAMA TIMING] ')[1])
            for line in capsys.readouterr().out.splitlines()]
    assert [(row['attempt'], row['outcome']) for row in rows] == [(1, 'OSError'), (2, 'ok')]


def test_qwen3_default_profile_and_explicit_override(monkeypatch):
    monkeypatch.delenv('LLM_MODEL', raising=False)
    config = OllamaRuntimeConfig.from_env()
    assert (config.model, config.think, config.num_ctx, config.temperature, config.seed) == ('qwen3:8b', False, 4096, 0, 42)
    monkeypatch.setenv('LLM_MODEL', 'another-model')
    config = OllamaRuntimeConfig.from_env()
    assert config.model == 'another-model' and config.think is None
    monkeypatch.setenv('LLM_MODEL', 'qwen3:8b')
    monkeypatch.setenv('LLM_THINKING', 'on')
    monkeypatch.setenv('LLM_CONTEXT', '8192')
    config = OllamaRuntimeConfig.from_env()
    assert config.think is True and config.num_ctx == 8192
