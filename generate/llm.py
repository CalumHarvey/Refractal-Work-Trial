"""Gemini API client: JSON responses, an on-disk cache, throttling, retries and a data guard.

Every request is cached under config `llm.cache_dir` by a hash of (model, system prompt, prompt,
generation settings), so re-running a stage costs nothing and gives the same answers. Calls are
throttled per model to `requests_per_minute`. A 429 with a per-minute quota waits for the server's
retry delay; a daily quota raises QuotaExhausted, so a run stops cleanly and resumes from the cache.

Data guard: callers name the datasets whose content is in the prompt. Datasets with
`include: eval_only` in config/build.yaml (unlicensed: ToolSafe, R-Judge, MCPTox) are refused,
because the free tier lets Google use and read what is sent.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ingest.assembly.config import eval_only_datasets
from ingest.common.paths import ROOT

from .config import generation_config

_LAST_CALL: dict[str, float] = {}
_EXHAUSTED: set[str] = set()  # models whose daily quota ran out in this process


class QuotaExhausted(RuntimeError):
    """Raised when the API reports a daily (or otherwise non-retryable) quota is used up."""


class LLMError(RuntimeError):
    """Raised when a request fails after all retries, or the reply is not usable JSON."""


class ForbiddenData(RuntimeError):
    """Raised when a prompt would carry content from a dataset that must not leave the machine."""


class Overloaded(LLMError):
    """Raised when a model keeps answering 503 (high demand); the caller may fall back to another model."""


def _settings() -> dict:
    """Get the `llm` section of the generation config.

    Returns:
        The settings dict.
    """
    return generation_config()["llm"]


def cache_key(model: str, system: str | None, prompt: str, temperature: float, sample: int = 0) -> str:
    """Hash everything that determines a reply.

    Args:
        model: Model name.
        system: System instruction, or None.
        prompt: User prompt.
        temperature: Sampling temperature.
        sample: Index of an independent sample of the same request (0 = the usual single reply).

    Returns:
        A SHA-256 hex digest.
    """
    request = {"model": model, "system": system, "prompt": prompt, "temperature": temperature, "format": "json"}
    if sample:
        request["sample"] = sample  # sample 0 keeps the key of replies cached before samples existed
    payload = json.dumps(request, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(model: str, key: str):
    """Locate a cached reply.

    Args:
        model: Model name.
        key: The request's cache key.

    Returns:
        `<cache_dir>/<model>/<key[:2]>/<key>.json`.
    """
    return ROOT / _settings()["cache_dir"] / model / key[:2] / f"{key}.json"


def _throttle(model: str) -> None:
    """Wait so that calls to one model stay under the configured requests per minute.

    Args:
        model: Model name.

    Returns:
        None.
    """
    gap = 60.0 / max(1, _settings()["requests_per_minute"])
    wait = _LAST_CALL.get(model, 0.0) + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[model] = time.monotonic()


def _retry_delay(body: dict) -> float | None:
    """Read the server's suggested retry delay from an error body.

    Args:
        body: The parsed error response.

    Returns:
        Seconds to wait, or None if the body gives no delay.
    """
    for detail in (body.get("error") or {}).get("details") or []:
        delay = detail.get("retryDelay")
        if delay:
            match = re.match(r"([\d.]+)s", delay)
            if match:
                return float(match.group(1))
    return None


def _is_daily_quota(body: dict) -> bool:
    """Check whether a 429 error is a per-day quota (no point retrying today).

    Args:
        body: The parsed error response.

    Returns:
        True if any quota violation names a per-day quota.
    """
    for detail in (body.get("error") or {}).get("details") or []:
        for violation in detail.get("violations") or []:
            if "PerDay" in (violation.get("quotaId") or "") or "per_day" in (violation.get("quotaMetric") or ""):
                return True
    return False


def _post(model: str, payload: dict) -> dict:
    """Send one generateContent request, retrying rate limits and server errors.

    Args:
        model: Model name.
        payload: The request body.

    Returns:
        The parsed response body.

    Raises:
        QuotaExhausted: On a daily quota error.
        Overloaded: After `overload_retries` 503 answers in a row.
        LLMError: If the request still fails after `max_retries`.
    """
    settings = _settings()
    overloads = 0
    key = os.environ.get(settings["api_key_env"])
    if not key:
        raise LLMError(f"environment variable {settings['api_key_env']} is not set")
    url = settings["endpoint"].format(model=model)
    data = json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(settings["max_retries"] + 1):
        _throttle(model)
        request = urllib.request.Request(url, data=data, method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(request, timeout=settings["timeout_seconds"]) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = {}
            last_error = f"HTTP {exc.code}: {(body.get('error') or {}).get('message', '')[:300]}"
            if exc.code == 429 and _is_daily_quota(body):
                raise QuotaExhausted(f"{model}: daily quota used up; re-run later to resume ({last_error})") from exc
            if exc.code not in (429, 500, 502, 503, 504):
                raise LLMError(f"{model}: {last_error}") from exc
            if exc.code == 503:
                overloads += 1
                if overloads > settings.get("overload_retries", 2):
                    raise Overloaded(f"{model}: overloaded ({last_error})") from exc
            time.sleep(_retry_delay(body) or min(60.0, 2.0 ** attempt * 2))
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
            time.sleep(min(60.0, 2.0 ** attempt * 2))
    raise LLMError(f"{model}: gave up after {settings['max_retries'] + 1} attempts ({last_error})")


def _reply_text(body: dict) -> str:
    """Extract the answer text from a generateContent response (thought parts skipped).

    Args:
        body: The response body.

    Returns:
        The concatenated text parts of the first candidate.

    Raises:
        LLMError: If the response has no usable candidate (e.g. blocked by a safety filter).
    """
    candidates = body.get("candidates") or []
    if not candidates:
        raise LLMError(f"no candidates (prompt feedback: {body.get('promptFeedback')})")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise LLMError(f"empty reply (finish reason: {candidates[0].get('finishReason')})")
    return text


def parse_json(text: str):
    """Parse a JSON reply, tolerating a Markdown code fence around it.

    Args:
        text: The model's reply.

    Returns:
        The parsed value.

    Raises:
        LLMError: If the reply is not JSON.
    """
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"reply is not JSON: {text[:200]!r}") from exc


def check_datasets(datasets: list[str]) -> None:
    """Refuse prompts that carry content from evaluation-only datasets.

    Args:
        datasets: Datasets whose content is in the prompt.

    Returns:
        None.

    Raises:
        ForbiddenData: If any dataset has `include: eval_only` in config/build.yaml.
    """
    forbidden = sorted(set(datasets) & set(eval_only_datasets()))
    if forbidden:
        raise ForbiddenData(f"content from {forbidden} may not be sent to an external model (eval_only)")


def _generate_one(model: str, prompt: str, system: str | None, temperature: float, sample: int = 0) -> dict:
    """Ask one model for a JSON answer, using the cache when possible.

    Args:
        model: Model name.
        prompt: The user prompt.
        system: Optional system instruction.
        temperature: Sampling temperature.
        sample: Independent-sample index (part of the cache key).

    Returns:
        `{"value", "model", "model_version", "cached", "key"}`.

    Raises:
        QuotaExhausted: On a daily quota error.
        Overloaded: If the model stays overloaded.
        LLMError: If the call fails or the reply is not JSON.
    """
    key = cache_key(model, system, prompt, temperature, sample)
    path = _cache_path(model, key)
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        return {"value": parse_json(cached["text"]), "model": model, "model_version": cached.get("model_version"),
                "cached": True, "key": key}
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    body = _post(model, payload)
    text = _reply_text(body)
    value = parse_json(text)  # only cache replies that parse
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model, "model_version": body.get("modelVersion"), "text": text,
                                "usage": body.get("usageMetadata"),
                                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                               ensure_ascii=False), encoding="utf-8")
    return {"value": value, "model": model, "model_version": body.get("modelVersion"), "cached": False, "key": key}


def generate_json(model: str, prompt: str, *, datasets: list[str], system: str | None = None,
                  temperature: float = 0.7, sample: int = 0) -> dict:
    """Ask a Gemini model for a JSON answer, falling back to the configured models when it is overloaded.

    A cached answer from the primary model is used first; when the primary model stays overloaded
    (503) or its daily quota is used up, each model in config `llm.fallbacks[model]` is tried in
    turn (free-tier quotas are per model). A model whose daily quota ran out is skipped for the rest
    of the process. The model that answered is returned, so records name the model that actually
    produced them.

    Args:
        model: Model name, e.g. "gemini-3.5-flash".
        prompt: The user prompt.
        datasets: Datasets whose content appears in the prompt (checked by `check_datasets`).
        system: Optional system instruction.
        temperature: Sampling temperature.
        sample: Index of an independent sample of the same request; samples are cached separately, so
            one model can give several independent judgements (self-consistency).

    Returns:
        `{"value": parsed JSON, "model": model used, "model_version": str | None, "cached": bool,
        "key": cache key}`.

    Raises:
        ForbiddenData: If the prompt carries evaluation-only data.
        QuotaExhausted: When every candidate model's daily quota is used up.
        LLMError: If every model fails or the reply is not JSON.
    """
    check_datasets(datasets)
    candidates = [model] + list((_settings().get("fallbacks") or {}).get(model) or [])
    last = None
    for name in candidates:
        key = cache_key(name, system, prompt, temperature, sample)
        if name in _EXHAUSTED and not _cache_path(name, key).exists():
            continue
        try:
            return _generate_one(name, prompt, system, temperature, sample)
        except Overloaded as exc:
            last = exc
        except QuotaExhausted as exc:
            _EXHAUSTED.add(name)
            last = exc
    if last is None:
        raise QuotaExhausted(f"daily quota used up for {candidates}; re-run later to resume")
    if isinstance(last, Overloaded) and all(c in _EXHAUSTED for c in candidates[1:]) and candidates[1:]:
        raise QuotaExhausted(f"{model} overloaded and fallbacks out of quota; re-run later to resume")
    raise last
