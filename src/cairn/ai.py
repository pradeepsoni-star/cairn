"""The optional layer: asking questions of your own documents.

Everything else in Cairn works offline and forever. This file is the one
place that talks to the internet, and it is off unless the user turns it on
and has a key. That ordering is the product decision, not a limitation: a
tool that stops working when a subscription lapses is not a tool you put
your working life into.

What it does is narrow on purpose. It retrieves passages from your own index
and asks a model to answer FROM THOSE PASSAGES, citing them. It is not a
chatbot with your files bolted on. If the passages do not contain the
answer, the correct output is "your documents do not say", and the prompt
below says so in as many words - because the failure mode that destroys
trust is a confident answer assembled from nothing.

Privacy, stated plainly so it can be checked rather than believed: only the
retrieved passages and your question leave the machine, only when you press
ask, and only to the provider whose key you supplied.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

PROMPT = """You are answering a question using only the passages below, which come from the user's own files.

Rules:
- Answer from the passages. Do not add facts from your own knowledge.
- If the passages do not contain the answer, say exactly what is missing. Do not guess.
- Cite the file name in brackets after each claim, like [budget-2026.xlsx].
- Be brief. Three sentences is usually enough.

PASSAGES
{context}

QUESTION
{question}"""

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "ollama": "llama3.1",
}

_KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY", "CAIRN_ANTHROPIC_KEY"),
    "openai": ("OPENAI_API_KEY", "CAIRN_OPENAI_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "CAIRN_GEMINI_KEY"),
}


class NotConfigured(Exception):
    """No usable provider. The message explains exactly what to do about it."""


@dataclass
class Provider:
    name: str
    key: str
    model: str


def _key_for(provider: str) -> str:
    for variable in _KEYS.get(provider, ()):
        value = os.environ.get(variable, "").strip()
        if value:
            return value
    return ""


def available() -> list[str]:
    """Providers this machine could use right now."""
    found = [name for name in _KEYS if _key_for(name)]
    if os.environ.get("OLLAMA_HOST") or os.environ.get("CAIRN_OLLAMA", "").lower() == "on":
        found.append("ollama")
    return found


def resolve(preferred: str = "auto", model: str = "") -> Provider:
    """Pick a provider, or explain precisely why none can be picked."""
    if preferred and preferred != "auto":
        key = _key_for(preferred)
        if not key and preferred != "ollama":
            raise NotConfigured(
                f"{preferred} is selected but {_KEYS[preferred][0]} is not set in this environment."
            )
        return Provider(preferred, key, model or DEFAULT_MODELS.get(preferred, ""))

    for name in ("anthropic", "openai", "gemini", "ollama"):
        if name == "ollama":
            if os.environ.get("OLLAMA_HOST") or os.environ.get("CAIRN_OLLAMA", "").lower() == "on":
                return Provider(name, "", model or DEFAULT_MODELS[name])
            continue
        key = _key_for(name)
        if key:
            return Provider(name, key, model or DEFAULT_MODELS[name])

    raise NotConfigured(
        "Answering needs a model. Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY or "
        "GEMINI_API_KEY, or run Ollama locally and set OLLAMA_HOST. "
        "Search, commitments, notes and the brief all work without this."
    )


def _call(provider: Provider, prompt: str, timeout: float = 60.0) -> str:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        raise NotConfigured("Answering needs httpx: pip install 'cairn-desk[ai]'") from exc

    if provider.name == "anthropic":
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": provider.key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": provider.model,
                "max_tokens": 900,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        blocks = response.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

    if provider.name == "openai":
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {provider.key}"},
            json={
                "model": provider.model,
                "max_tokens": 900,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    if provider.name == "gemini":
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{provider.model}:generateContent",
            headers={"x-goog-api-key": provider.key, "content-type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=timeout,
        )
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    response = httpx.post(
        f"{host}/api/generate",
        json={"model": provider.model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("response", "").strip()


def ask(conn, question: str, preferred: str = "auto", model: str = "") -> dict:
    """Answer a question from the user's own indexed documents."""
    from pathlib import Path

    from cairn.permissions import Permission, Permissions, record
    from cairn.search import context_for_question

    # Before anything is retrieved, let alone sent. A refused permission here
    # must not even reveal which of the user's files matched.
    Permissions.load().require(Permission.SEND_TO_AI)

    passages = context_for_question(conn, question)
    if not passages:
        return {
            "answer": "Nothing in your indexed files matches that. Try different words, "
            "or add the folder those documents live in.",
            "sources": [],
            "provider": "",
        }

    provider = resolve(preferred, model)
    context = "\n\n".join(
        f"--- {Path(p['path']).name} ---\n{p['body']}" for p in passages
    )
    # Written down before the request goes out, so the log is honest even if
    # the call then fails or the machine loses power mid-request.
    record(
        Permission.SEND_TO_AI,
        "sent",
        f"{len(passages)} passage(s) from {len({p['path'] for p in passages})} file(s) "
        f"to {provider.name} ({provider.model})",
    )
    answer = _call(provider, PROMPT.format(context=context, question=question))

    seen: list[str] = []
    for passage in passages:
        if passage["path"] not in seen:
            seen.append(passage["path"])
    return {
        "answer": answer or "The model returned nothing.",
        "sources": [{"path": p, "name": Path(p).name} for p in seen],
        "provider": f"{provider.name}/{provider.model}",
    }
