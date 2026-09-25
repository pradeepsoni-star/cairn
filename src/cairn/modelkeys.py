"""Where an API key lives, and how it is handled.

Telling a person to set an environment variable and restart is a developer's
answer to a normal question. This is the box they paste a key into instead.

Three rules, because a key is a credential even when it is only yours.

1. **A key is never sent back out.** Once stored, every reply says whether a
   provider is configured and shows the last four characters so it can be
   told apart from another one - never the key. A screen that redisplays a
   secret is a screen that leaks it to whoever is standing behind you.

2. **A key is never written to the activity log**, which is a plain text file
   the user is encouraged to read and might reasonably paste somewhere.

3. **It is stored in a file, and the interface says so plainly.** The
   operating system's credential store would be better and is the obvious
   next step; pretending a JSON file in your own AppData folder is anything
   more than that would be worse than saying it. Environment variables still
   win if set, so nothing that already worked stops working.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
from pathlib import Path

from cairn.config import data_dir

# Provider -> the environment variables that have always worked. Checked
# BEFORE stored keys, so a machine configured by its owner or its IT
# department keeps behaving the way they set it up.
ENV_NAMES = {
    "anthropic": ("ANTHROPIC_API_KEY", "CAIRN_ANTHROPIC_KEY"),
    "openai": ("OPENAI_API_KEY", "CAIRN_OPENAI_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "CAIRN_GEMINI_KEY"),
}

PROVIDERS = ("anthropic", "openai", "gemini", "ollama")

# Where to get one, shown next to the box. Free tiers first, because the
# commonest question is "which of these can I try without paying".
WHERE_TO_GET = {
    "ollama": "Free and fully offline. Install from ollama.com, then run: ollama pull llama3.2",
    "gemini": "Free tier, no card needed. Get a key at aistudio.google.com/apikey",
    "anthropic": "Paid. console.anthropic.com",
    "openai": "Paid. platform.openai.com/api-keys",
}


def _path() -> Path:
    return data_dir() / "model.json"


def _read() -> dict:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(payload: dict) -> None:
    path = _path()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Owner read/write only. A no-op on Windows, where the user's own AppData
    # folder is already scoped to them, and meaningful everywhere else - a
    # shared Linux box is exactly where this matters.
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def stored_key(provider: str) -> str:
    return str(_read().get("keys", {}).get(provider, "")).strip()


def env_key(provider: str) -> str:
    for name in ENV_NAMES.get(provider, ()):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def key_for(provider: str) -> str:
    """The key to use: whatever the environment says, else what was saved."""
    return env_key(provider) or stored_key(provider)


def set_key(provider: str, key: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    payload = _read()
    keys = payload.setdefault("keys", {})
    key = (key or "").strip()
    if key:
        keys[provider] = key
    else:
        keys.pop(provider, None)
    _write(payload)


def ollama_host() -> str:
    return (
        os.environ.get("OLLAMA_HOST", "").strip()
        or str(_read().get("ollama_host", "")).strip()
        or "http://localhost:11434"
    )


def set_ollama_host(host: str) -> None:
    payload = _read()
    host = (host or "").strip().rstrip("/")
    if host:
        payload["ollama_host"] = host
    else:
        payload.pop("ollama_host", None)
    _write(payload)


def ollama_enabled() -> bool:
    """Ollama needs no key, so 'configured' means the user asked for it."""
    if os.environ.get("OLLAMA_HOST") or os.environ.get("CAIRN_OLLAMA", "").lower() == "on":
        return True
    return bool(_read().get("ollama_host"))


def chosen() -> tuple[str, str]:
    """The provider and model the user picked, or ('auto', '')."""
    payload = _read()
    return str(payload.get("provider", "auto")), str(payload.get("model", ""))


def choose(provider: str, model: str = "") -> None:
    payload = _read()
    payload["provider"] = provider if provider in PROVIDERS or provider == "auto" else "auto"
    payload["model"] = (model or "").strip()
    _write(payload)


def _tail(key: str) -> str:
    """The last four characters, so one key can be told from another.

    Never the key. Four characters identify without revealing - and they are
    the last four, because the first characters of an API key are a fixed,
    guessable prefix.
    """
    return f"...{key[-4:]}" if len(key) >= 8 else "set"


def describe() -> dict:
    """What the interface may know. Contains no key material."""
    from cairn.ai import DEFAULT_MODELS

    provider, model = chosen()
    rows = []
    for name in PROVIDERS:
        if name == "ollama":
            rows.append(
                {
                    "key": name,
                    "needs_key": False,
                    "configured": ollama_enabled(),
                    "source": "environment" if os.environ.get("OLLAMA_HOST") else "saved here",
                    "hint": WHERE_TO_GET[name],
                    "default_model": DEFAULT_MODELS[name],
                    "tail": "",
                }
            )
            continue
        from_env = env_key(name)
        saved = stored_key(name)
        rows.append(
            {
                "key": name,
                "needs_key": True,
                "configured": bool(from_env or saved),
                "source": "environment" if from_env else ("saved here" if saved else ""),
                "hint": WHERE_TO_GET[name],
                "default_model": DEFAULT_MODELS[name],
                "tail": _tail(from_env or saved) if (from_env or saved) else "",
            }
        )
    return {
        "provider": provider,
        "model": model,
        "ollama_host": ollama_host(),
        "stored_in": str(_path()),
        "providers": rows,
    }
