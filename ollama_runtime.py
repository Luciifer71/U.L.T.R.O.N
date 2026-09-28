from __future__ import annotations

import asyncio
import logging
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

    async def chat(self, **kwargs):
        """Execute a chat request with bounded retries and recovery."""
        await self.wait_until_ready()

        last_error: Exception | None = None

        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                return await asyncio.wait_for(
                    self.client.chat(**kwargs),
                    timeout=self.config.request_timeout_sec,
                )

            except asyncio.CancelledError:
                raise

            except Exception as exc:
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

