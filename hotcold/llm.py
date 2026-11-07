"""Model backends. Every backend exposes `async respond(system, messages, schema) -> (answer | None, meta)`.

Real models go through LangChain (`init_chat_model`), so any provider can be plugged in; the per-model
settings live in MODELS. Answers are constrained with structured outputs (JSON schema with enums), so
there is no free-text parsing and no silent default: a refusal or unparsable answer comes back as None
and the subject is flagged.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re

import openai
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

# Per-model settings. "off" = the closest each model has to answering without extended reasoning.
# Prices: USD per million tokens (input, output, cached input).
MODELS = {
    "anthropic:claude-haiku-5-5": {
        "off": {"thinking": {"type": "disabled"}}, "on": {"thinking": {"type": "adaptive"}},
        "price": (0.10, 0.50, 0.01),
    },
    "anthropic:claude-sonnet-5-5": {
        "off": {"thinking": {"type": "between_tools"}}, "on": {"thinking": {"type": "adaptive"}},
        "price": (2.00, 10.00, 0.20),
    },
    "anthropic:claude-opus-5-5": {  # thinking cannot be turned off
        "off": {}, "on": {"thinking": {"type": "adaptive"}},
        "price": (4.00, 20.00, 0.20),
    },
    "openai:gpt-5-nano": {  # cheapest OpenAI model; reasoning model, "minimal" is its lowest setting
        "off": {"reasoning_effort": "minimal"}, "on": {"reasoning_effort": "medium"},
        "price": (0.05, 0.40, 0.005),
    },
    # Open-weight models served by DeepInfra (prices from its model list, 2026-11-05).
    "deepinfra:deepseek-ai/DeepSeek-V4-Pro": {  # reasons by default; no switch to turn it off
        "off": {}, "on": {},
        "price": (1.30, 2.60, 0.10),
    },
    "deepinfra:Qwen/Qwen3.5-397B-A17B": {
        "off": {"reasoning_effort": "none"}, "on": {"reasoning_effort": "medium"},
        "price": (0.45, 3.00, 0.22),
    },
    "deepinfra:meta-llama/Llama-4-Scout-17B-16E-Instruct": {  # no reasoning mode
        "off": {}, "on": {},
        "price": (0.10, 0.30, 0.10),
    },
    "deepinfra:deepseek-ai/DeepSeek-V4-Flash-0731": {  # reasons by default
        "off": {}, "on": {},
        "price": (0.06, 0.18, 0.015),
    },
    "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507": {  # instruct version: no reasoning mode
        "off": {}, "on": {},
        "price": (0.09, 0.55, 0.09),
    },
    "deepinfra:Qwen/Qwen3.8-Flash": {
        "off": {"reasoning_effort": "none"}, "on": {"reasoning_effort": "medium"},
        "price": (0.113, 0.382, 0.0141),
    },
    "deepinfra:google/gemma-4-31B-it-turbo": {  # reasons by default
        "off": {}, "on": {},
        "price": (0.09, 0.34, 0.05),
    },
    "deepinfra:openai/gpt-oss-120b": {  # lowest reasoning setting is "low"
        "off": {"reasoning_effort": "low"}, "on": {"reasoning_effort": "medium"},
        "price": (0.037, 0.17, 0.037),
    },
}

# Environment variable holding each provider's key. DeepInfra is reached through its OpenAI-compatible endpoint.
API_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "deepinfra": "DEEPINFRA_API_TOKEN"}
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai"
REQUEST_TIMEOUT_S = 120  # per HTTP request; LangChain retries timeouts, rate limits and 5xx with backoff
HARD_TIMEOUT_S = 900  # whole call including those retries


class FatalAPIError(RuntimeError):
    """Wrong or expired key, no permission, no credit: every further call would fail too, so the run stops."""


def is_fatal(e: Exception) -> bool:
    import anthropic

    if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError,
                      anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return True
    status = getattr(e, "status_code", None)
    msg = str(e).lower()
    return status == 402 or "credit balance" in msg or "insufficient_quota" in msg


def cost_usd(model: str, usage: dict) -> float:
    if model not in MODELS:
        return 0.0
    pin, pout, pcache = MODELS[model]["price"]
    return (
        usage.get("input_tokens", 0) * pin
        + usage.get("cache_creation_input_tokens", 0) * pin * 1.25  # Anthropic cache writes
        + usage.get("cache_read_input_tokens", 0) * pcache
        + usage.get("output_tokens", 0) * pout
    ) / 1e6


def request_settings(model: str, thinking: str = "off", max_tokens: int = 1024) -> dict:
    """Everything sent with each request besides the messages (recorded in manifest.json)."""
    provider = model.split(":", 1)[0]
    return {"max_tokens": max(max_tokens, 8000) if thinking == "on" else max_tokens, "max_retries": 6,
            "request_timeout_s": REQUEST_TIMEOUT_S, "hard_timeout_s": HARD_TIMEOUT_S,
            "structured_output": "json_schema" + (", strict" if provider == "openai" else ", native" if provider == "anthropic"
                                                  else ", checked locally + retries"),
            "base_url": DEEPINFRA_URL if provider == "deepinfra" else "provider default",
            "temperature": "provider default (not set)",
            **{k: v for k, v in MODELS.get(model, {}).get(thinking, {}).items()}}


class LangChainModel:
    """Any chat model LangChain supports, addressed as "provider:model" (e.g. "openai:gpt-5-nano")."""

    def __init__(self, model: str, thinking: str = "off", max_tokens: int = 1024):
        if model not in MODELS:
            raise ValueError(f"unknown model {model}; add its settings to MODELS in hotcold/llm.py")
        self.name = model
        self.provider = model.split(":", 1)[0]
        settings = MODELS[model][thinking]
        if thinking == "on":
            max_tokens = max(max_tokens, 8000)
        if self.provider == "deepinfra":
            settings = {**settings, "model_provider": "openai", "base_url": DEEPINFRA_URL,
                        "api_key": os.environ[API_KEYS["deepinfra"]], "use_responses_api": False}
            model = model.split(":", 1)[1]
        self.chat = init_chat_model(model, max_tokens=max_tokens, max_retries=6, timeout=REQUEST_TIMEOUT_S, **settings)

    def _messages(self, system: str, messages: list[dict]):
        out = [SystemMessage(system)]
        for i, m in enumerate(messages):
            if m["role"] == "assistant":
                out.append(AIMessage(m["content"]))
            elif self.provider == "anthropic" and i == len(messages) - 1:
                # Anthropic caches explicitly: mark the end of the prefix; each call extends the previous one.
                out.append(HumanMessage([{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}]))
            else:
                out.append(HumanMessage(m["content"]))  # OpenAI caches long prefixes automatically
        return out

    async def respond(self, system: str, messages: list[dict], schema: dict):
        schema = {"title": "answer", "description": "Answer to the current screen", **schema}
        # Options are enforced while generating where the provider supports it (Anthropic natively; OpenAI with
        # strict=True). DeepInfra models are not forced: their answers are checked locally (subject.invalid) and a
        # malformed answer is asked again, up to FORMAT_RETRIES times.
        kw = {"strict": True} if self.provider == "openai" else {}
        runnable = self.chat.with_structured_output(schema, method="json_schema", include_raw=True, **kw)
        try:
            out = await asyncio.wait_for(runnable.ainvoke(self._messages(system, messages)), HARD_TIMEOUT_S)
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as e:
            # OpenAI-compatible endpoints raise instead of returning a truncated/filtered answer: a technical
            # failure of this request, retried by the caller
            return None, {"stop_reason": type(e).__name__, "text": "", "usage": {}}
        except Exception as e:
            if is_fatal(e):
                raise FatalAPIError(f"{self.name}: {type(e).__name__}: {e}") from e
            raise
        raw, parsed = out["raw"], out["parsed"]
        md = raw.response_metadata or {}
        meta = {
            "stop_reason": md.get("stop_reason") or md.get("finish_reason"),
            "text": json.dumps(parsed) if parsed is not None else _text(raw),
            "usage": _usage(raw.usage_metadata or {}),
            "model_version": md.get("model_name") or md.get("model"),
        }
        if parsed is None or out.get("parsing_error") or set(parsed) != set(schema["properties"]):
            return None, meta
        return parsed, meta


def _text(msg) -> str:
    c = msg.content
    return c if isinstance(c, str) else "".join(b.get("text", "") for b in c if isinstance(b, dict))


def _usage(u: dict) -> dict:
    """LangChain usage -> uncached input, cache writes, cache reads, output (output includes reasoning)."""
    d = u.get("input_token_details", {}) or {}
    read = d.get("cache_read", 0) or 0
    # langchain-anthropic reports cache writes under ephemeral_5m/1h_input_tokens and then sets cache_creation=0
    write = sum(v or 0 for k, v in d.items() if k.startswith("ephemeral_")) or d.get("cache_creation", 0) or 0
    return {
        "input_tokens": (u.get("input_tokens", 0) or 0) - read - write,
        "cache_creation_input_tokens": write,
        "cache_read_input_tokens": read,
        "output_tokens": u.get("output_tokens", 0) or 0,
    }


class ScriptedModel:
    """Offline stand-in for tests and dry runs: answers the quiz (optionally wrong first), then plays a rule.

    rule: "left" | "right" | "random"
    Failure injection for tests: `raise_at` = raise this exception on the n-th request; `bad_first` = the first n
    requests come back unparsable; `age` = what to write in the free-text age field; `delay` = seconds per call.
    """

    name = "scripted"

    def __init__(self, rule: str = "left", wrong_quiz: int = 0, seed: int = 0, raise_at: tuple[int, Exception] | None = None,
                 bad_first: int = 0, age: str = "25", delay: float = 0.0):
        self.rule, self.wrong_quiz, self.rng = rule, wrong_quiz, random.Random(seed)
        self.quiz_seen = 0
        self.raise_at, self.bad_first, self.age, self.delay = raise_at, bad_first, age, delay
        self.n = 0

    async def respond(self, system: str, messages: list[dict], schema: dict):
        self.n += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_at and self.n == self.raise_at[0]:
            raise self.raise_at[1]
        if self.n <= self.bad_first:
            return None, {"stop_reason": "length", "text": '{"choi', "usage": {"input_tokens": 10, "output_tokens": 3}}
        props = schema["properties"]
        text = messages[-1]["content"]
        if "q1_1" in props:
            self.quiz_seen += 1
            ans = {"q1_1": "35", "q1_2": "25", "q1_3": "50", "q1_4": "12", "q2": "False",
                   "q3": "False" if "You have no information about the choice" in _all_user(messages) else "True",
                   "q4": re.search(r"chose IN in phase 1 of the study is equal to (\d+%)", _all_user(messages)).group(1)}
            if self.quiz_seen <= self.wrong_quiz:
                ans["q2"] = "True"
        elif "choice" in props:
            ans = {"choice": {"left": "LEFT", "right": "RIGHT"}.get(self.rule) or self.rng.choice(["LEFT", "RIGHT"])}
        else:
            ans = {k: (v["enum"][0] if "enum" in v else self.age if k == "age" else "") for k, v in props.items()}
        n = len(text) // 4
        return ans, {"stop_reason": "end_turn", "text": json.dumps(ans), "model_version": "scripted",
                     "usage": {"input_tokens": n, "output_tokens": 10}}


def _all_user(messages: list[dict]) -> str:
    return "\n".join(m["content"] for m in messages if m["role"] == "user")
