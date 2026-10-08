import asyncio

import pytest

from ollama_runtime import OllamaRuntime, OllamaRuntimeConfig


@pytest.fixture(autouse=True)
def clean_profile(monkeypatch):
    for key in ('LLM_THINKING', 'LLM_CONTEXT', 'LLM_TEMPERATURE', 'LLM_SEED'):
        monkeypatch.delenv(key, raising=False)


def test_default_profile_preserves_existing_request(monkeypatch):
    received = []
    class Client:
        async def chat(self, **kwargs):
            received.append(kwargs)
            return {'message': {'content': 'ok'}}
    monkeypatch.setattr('ollama_runtime.AsyncClient', lambda **kwargs: Client())
    runtime = OllamaRuntime(OllamaRuntimeConfig.from_env())
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
    monkeypatch.setattr('ollama_runtime.AsyncClient', lambda **kwargs: Client())
    runtime = OllamaRuntime(OllamaRuntimeConfig.from_env(model='qwen3:8b'))
    runtime._ready = True
    options = {'temperature': 0.2, 'num_predict': 256}
    async def run():
        await runtime.chat(model='qwen3:8b', messages=[], options=options)
        await runtime.chat(model='qwen3:8b', messages=[])
    asyncio.run(run())
    for request in received:
        assert request['think'] is False
        assert request['options']['num_ctx'] == 4096
        assert request['options']['temperature'] == 0
        assert request['options']['seed'] == 42
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
    monkeypatch.setattr('ollama_runtime.AsyncClient', forbidden_client)
    with pytest.raises(ValueError):
        OllamaRuntime(OllamaRuntimeConfig.from_env())
