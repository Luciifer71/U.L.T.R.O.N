from __future__ import annotations

import asyncio
import logging
import json
import time
import os
from dataclasses import dataclass

from ollama import AsyncClient


logger = logging.getLogger("ultron.ollama")


@dataclass(frozen=True, slots=True)
class OllamaRuntimeConfig:
    host: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b"
    startup_retry_sec: float = 3.0
    request_timeout_sec: float = 90.0
    retry_attempts: int = 3
    retry_backoff_sec: float = 1.5
    think: bool | None = None
    num_ctx: int | None = None
    temperature: float | None = None
    seed: int | None = None

    def __post_init__(self):
        if self.num_ctx is not None and self.num_ctx < 1:
            raise ValueError('LLM_CONTEXT must be positive')
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError('LLM_TEMPERATURE must be between 0 and 2')

    @classmethod
    def from_env(cls, **kwargs):
        thinking = os.getenv('LLM_THINKING', 'default').strip().lower()
        if thinking not in {'default', 'off', 'on'}:
            raise ValueError('LLM_THINKING must be default, off, or on')
        context = os.getenv('LLM_CONTEXT', '').strip()
        temperature = os.getenv('LLM_TEMPERATURE', '').strip()
        seed = os.getenv('LLM_SEED', '').strip()
        return cls(**kwargs, think={'default': None, 'off': False, 'on': True}[thinking],
                   num_ctx=int(context) if context else None,
                   temperature=float(temperature) if temperature else None,
                   seed=int(seed) if seed else None)


class OllamaRuntime:
    """Production runtime boundary for ULTRON's Ollama dependency."""

    def __init__(self, config: OllamaRuntimeConfig) -> None:
        if config.retry_attempts < 1:
            raise ValueError("retry_attempts must be >= 1")
        if config.request_timeout_sec <= 0:
            raise ValueError("request_timeout_sec must be > 0")

        self.config = config
        self.client = AsyncClient(host=config.host)

        self._ready = False
        self._ready_lock = asyncio.Lock()
        self._last_error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def health_check(self) -> None:
        """Verify Ollama is reachable and the required model exists."""
        response = await asyncio.wait_for(
            self.client.list(),
            timeout=self.config.request_timeout_sec,
        )

        models = getattr(response, "models", []) or []
        available_models = {
            str(getattr(model, "model", "")).strip()
            for model in models
            if getattr(model, "model", None)
        }

        if self.config.model not in available_models:
            raise RuntimeError(
                f"Required Ollama model '{self.config.model}' is unavailable. "
                f"Available models: {sorted(available_models) or ['<none>']}. "
                f"Run: ollama pull {self.config.model}"
            )

    async def wait_until_ready(self) -> None:
        """Block startup until Ollama and the required model are available."""
        if self._ready:
            return

        async with self._ready_lock:
            if self._ready:
                return

            while not self._ready:
                try:
                    await self.health_check()
                    self._ready = True
                    self._last_error = None

                    logger.info(
                        "Ollama ready: host=%s model=%s",
                        self.config.host,
                        self.config.model,
                    )
                    return

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    self._ready = False
                    self._last_error = str(exc)

                    logger.warning(
                        "Ollama unavailable: %s | retrying in %.1fs",
                        exc,
                        self.config.startup_retry_sec,
                    )

                    await asyncio.sleep(self.config.startup_retry_sec)

    async def chat(self, *, diagnostic_task_id=None, diagnostic_phase="chat", **kwargs):
        """Execute a chat request with bounded retries and recovery."""
        # A configured trial profile applies to every brain request, including
        # retries and follow-up summaries. Never mutate a caller's options.
        kwargs = dict(kwargs)
        options = dict(kwargs.get('options') or {})
        for key, value in (('num_ctx', self.config.num_ctx),
                           ('temperature', self.config.temperature),
                           ('seed', self.config.seed)):
            if value is not None:
                options[key] = value
        if options:
            kwargs['options'] = options
        if self.config.think is not None:
            kwargs['think'] = self.config.think
        request_started = time.perf_counter()
        await self.wait_until_ready()
        ready_seconds = time.perf_counter() - request_started

        def report(outcome, attempt, started, response=None):
            row = {
                "task_id": diagnostic_task_id, "phase": diagnostic_phase,
                "outcome": outcome, "attempt": attempt,
                "ready_seconds": round(ready_seconds, 3),
                "attempt_seconds": round(time.perf_counter() - started, 3),
                "request_seconds": round(time.perf_counter() - request_started, 3),
            }
            # Only numerical performance metadata: never log message content.
            for field in ("total_duration", "load_duration", "prompt_eval_duration",
                          "eval_duration", "prompt_eval_count", "eval_count"):
                value = response.get(field) if isinstance(response, dict) else getattr(response, field, None)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if field.endswith("_duration"):
                        row[field.replace("_duration", "_seconds")] = round(value / 1e9, 3)
                    else:
                        row[field] = value
            print("[OLLAMA TIMING] " + json.dumps(row), flush=True)

        last_error: Exception | None = None

        for attempt in range(1, self.config.retry_attempts + 1):
            started = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    self.client.chat(**kwargs),
                    timeout=self.config.request_timeout_sec,
                )
                report("ok", attempt, started, response)
                return response

            except asyncio.CancelledError:
                report("cancelled", attempt, started)
                raise

            except Exception as exc:
                report(type(exc).__name__, attempt, started)
                last_error = exc
                self._ready = False
                self._last_error = str(exc)

                logger.warning(
                    "Ollama chat attempt %d/%d failed: %s",
                    attempt,
                    self.config.retry_attempts,
                    exc,
                )

                if attempt >= self.config.retry_attempts:
                    break

                delay = self.config.retry_backoff_sec * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
                await self.wait_until_ready()

        raise RuntimeError(
            f"Ollama chat failed after {self.config.retry_attempts} attempts: "
            f"{last_error}"
        )

