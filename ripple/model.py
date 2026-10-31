import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_SECONDS = 40
# Free tiers count tokens per minute, so a refused request is asked again once the minute has turned.
RATE_LIMIT_WAITS = (0, 20, 40)
# Any OpenAI-compatible endpoint works; these are the free tiers Ripple knows the address of.
# Models after the first are spares, tried when the one before is rate limited.
PROVIDERS = {
    "EXPERIENTIAL_API_KEY": ("https://api.experientiallabs.ai/v1", "deepseek-v4-flash"),
    "GROQ_API_KEY": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"),
    "MISTRAL_API_KEY": ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "ZAI_API_KEY": ("https://api.z.ai/api/paas/v4", "glm-4.7-flash"),
    "GEMINI_API_KEY": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "CEREBRAS_API_KEY": ("https://api.cerebras.ai/v1", "gpt-oss-120b"),
    "OPENROUTER_API_KEY": ("https://openrouter.ai/api/v1", "openai/gpt-oss-120b:free"),
}


class ModelUnavailable(RuntimeError):
    """No model is configured, or the provider did not return a usable reply."""


class RateLimited(ModelUnavailable):
    pass


def _load_env_file() -> None:
    file = Path(__file__).resolve().parent.parent / ".env"
    for line in file.read_text().splitlines() if file.exists() else []:
        name, found, value = line.partition("=")
        if found and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip("'\""))


_load_env_file()


def settings(routing: bool = False) -> dict | None:
    """Address, key and model name of the configured model, or None when Ripple runs without one.

    With routing=True the model is RIPPLE_ROUTER_MODEL when set: a cheaper one that only has to pick a query."""
    router = os.getenv("RIPPLE_ROUTER_MODEL") if routing else None
    if os.getenv("RIPPLE_MODEL_KEY") and os.getenv("RIPPLE_MODEL_URL") and os.getenv("RIPPLE_MODEL"):
        return {"url": os.environ["RIPPLE_MODEL_URL"], "key": os.environ["RIPPLE_MODEL_KEY"], "model": router or os.environ["RIPPLE_MODEL"]}
    for variable, (url, model, *spares) in PROVIDERS.items():
        if os.getenv(variable):
            return {"url": url, "key": os.environ[variable], "model": router or os.getenv("RIPPLE_MODEL", model), "spares": spares}
    return None


def name() -> str | None:
    found = settings()
    return found["model"] if found else None


# Models swap in typographic quotes, hyphens and spaces, which breaks verbatim checks against the source text.
PLAIN = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u2011": "-", "\u202f": " ", "\u00a0": " "})


def chat(messages: list[dict], tools: list[dict] | None = None, json_reply: bool = False, must_call: bool = True, routing: bool = False) -> dict:
    """One chat completion. Returns the assistant message plus the model that wrote it; raises ModelUnavailable on any failure."""
    found = settings(routing) if routing else settings()
    if found is None:
        raise ModelUnavailable("no model key is configured")
    spares = [spare for spare in found.get("spares", ()) if spare != found["model"]]
    for wait in RATE_LIMIT_WAITS:
        time.sleep(wait)
        for attempt in [found["model"], *spares]:
            try:
                return _complete(found | {"model": attempt}, messages, tools, json_reply, must_call)
            except RateLimited as problem:
                limited = problem
    raise limited


def _complete(found: dict, messages: list[dict], tools: list[dict] | None, json_reply: bool, must_call: bool) -> dict:
    body = {"model": found["model"], "messages": messages, "temperature": 0}
    if tools:
        body |= {"tools": tools, "tool_choice": "required" if must_call else "auto"}
    if json_reply:
        body["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        f"{found['url'].rstrip('/')}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {found['key']}", "Content-Type": "application/json", "User-Agent": "ripple"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            message = json.load(response)["choices"][0]["message"]
            return message | {"model": found["model"], "content": (message.get("content") or "").rsplit("</think>", 1)[-1].translate(PLAIN)}
    except urllib.error.HTTPError as problem:
        raise (RateLimited if problem.code == 429 else ModelUnavailable)(f"{found['model']} answered {problem.code}: {problem.read().decode(errors='replace')[:300]}") from problem
    except (OSError, KeyError, IndexError, ValueError) as problem:
        raise ModelUnavailable(f"{found['model']} could not be reached: {problem}") from problem
