"""Shared model factory for pydantic-ai agents.

Every LLM knob is .env-overridable, globally and per-agent:
- Backend: `{AGENT_NAME}_LLM_BACKEND` (e.g. `AFFO_LLM_BACKEND=gemini`)
  overrides just that agent; `LLM_BACKEND` sets the global default.
  Values: "ollama" (default) | "gemini".
- Model name: `{AGENT_NAME}_GEMINI_MODEL` / `{AGENT_NAME}_OLLAMA_MODEL`
  overrides just that agent's model (whichever backend it resolved to);
  `GEMINI_MODEL` / `OLLAMA_MODEL` set the global defaults.
Agent name is whatever string is passed to `get_model(agent_name)` —
matches the specialist's key in orchestration.py's SPECIALISTS.
"""

import asyncio
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings

from agentic.config import settings


class _SlidingWindowRateLimiter:
    """Caps calls to `max_calls` per rolling `period` seconds, sleeping as
    needed rather than raising — callers just see a slower call.
    """

    def __init__(self, max_calls: int, period: float) -> None:
        self.max_calls = max_calls
        self.period = period
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            self._evict_expired()
            if len(self._timestamps) >= self.max_calls:
                wait = self.period - (time.monotonic() - self._timestamps[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                self._evict_expired()
            self._timestamps.append(time.monotonic())

    def _evict_expired(self) -> None:
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] >= self.period:
            self._timestamps.popleft()


# Gemini free tier hit a hard 429 at 5 requests/minute per project+model
# (observed live). Shared across every agent using the Gemini backend —
# module-level singleton, since the quota itself is shared, not per-agent.
_gemini_rate_limiter = _SlidingWindowRateLimiter(max_calls=5, period=60.0)


class _RateLimitedGoogleModel(GoogleModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        await _gemini_rate_limiter.acquire()
        return await super().request(messages, model_settings, model_request_parameters)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ):
        await _gemini_rate_limiter.acquire()
        async with super().request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            yield stream

# Local CPU/consumer-GPU inference on longer contexts (e.g. a specialist with
# a RAG tool in its loop) can take well past the client's default timeout —
# seen firsthand as an httpx.ReadTimeout mid-Phase-3. Generous but finite.
_OLLAMA_TIMEOUT_SECONDS = 600.0

# NOTE on context window: Ollama's default is only 4096 tokens, and (as of
# this Ollama version) num_ctx passed via the OpenAI-compatible endpoint
# (`options` in the request body, or ModelSettings.extra_body) is silently
# ignored — confirmed by comparing `ollama ps` before/after. Only the native
# /api/chat endpoint respects a per-request num_ctx. Since OllamaModel talks
# to the OpenAI-compatible endpoint, the fix is a *model* baked with a larger
# window: see Modelfile.qwen3.5-4b-16k (`ollama create qwen3.5-4b-16k -f
# Modelfile.qwen3.5-4b-16k`), which OLLAMA_MODEL defaults to below.
#
# Started at 8192 (on qwen2.5:14b) after a single RAG tool response (~4-5K
# tokens) overflowed 4096 and hung for 50+ minutes; even 8192 wasn't enough
# once the orchestrator aggregates all specialists' full reports in its own
# context — bumped to 16384. Ollama trickles response bytes during these
# hangs, so the http client's read-timeout never trips either; see
# _OLLAMA_TIMEOUT_SECONDS below (passed to the http client in get_model())
# for the actual backstop against this recurring.
#
# NOTE on model choice: qwen2.5:14b-instruct repeatedly dropped tool-result
# fields into null in structured output; mistral:7b was worse — it
# fabricated plausible-looking wrong numbers instead of nulling them.
# qwen3.5:4b (smaller, newer generation) was the only one that transcribed
# every field correctly across repeated tests — not a general "smaller is
# better" claim, just what this empirical comparison found.


def _agent_env(agent_name: str, suffix: str, default: str) -> str:
    """`{AGENT}_{SUFFIX}` env override, falling back to `default` (itself
    already resolved from settings/.env) when unset or empty. Used for
    every per-agent LLM knob — backend choice and which model each agent
    uses, independently.
    """
    if not agent_name:
        return default
    return os.getenv(f"{agent_name.upper()}_{suffix}", "") or default


# Which specialist names (plus "orchestrator", the cross-signal step) call
# an LLM at all — the rest are pure Python, so `get_model_info` reports
# `None` for them rather than resolving a backend/model that's never
# actually used.
LLM_USING_AGENTS = frozenset(
    {"affo", "earnings_call", "sentiment", "disruption", "valuation", "orchestrator"}
)


def get_model_info(agent_name: str) -> dict | None:
    """Static, read-only reflection of what `get_model(agent_name)` would
    resolve to (backend + model name), without constructing an actual
    provider/client — for surfacing "which model runs this" in the UI.
    """
    if agent_name not in LLM_USING_AGENTS:
        return None
    backend = _agent_env(agent_name, "LLM_BACKEND", settings.llm_backend).lower()
    if backend == "gemini":
        model_name = _agent_env(agent_name, "GEMINI_MODEL", settings.gemini_model)
    else:
        model_name = _agent_env(agent_name, "OLLAMA_MODEL", settings.ollama_model)
    return {"backend": backend, "model": model_name}


def get_model(agent_name: str = ""):
    backend = _agent_env(agent_name, "LLM_BACKEND", settings.llm_backend).lower()

    if backend == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set but a gemini backend was requested "
                f"(agent={agent_name or 'default'})"
            )
        model_name = _agent_env(agent_name, "GEMINI_MODEL", settings.gemini_model)
        return _RateLimitedGoogleModel(
            model_name,
            provider=GoogleProvider(api_key=settings.gemini_api_key),
        )

    model_name = _agent_env(agent_name, "OLLAMA_MODEL", settings.ollama_model)
    return OllamaModel(
        model_name,
        provider=OllamaProvider(
            base_url=settings.ollama_base_url,
            http_client=httpx2.AsyncClient(timeout=_OLLAMA_TIMEOUT_SECONDS),
        ),
    )
