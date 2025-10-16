from __future__ import annotations

import os
from typing import Optional, Tuple
import requests
import re


def postprocess_with_llm(markdown_text: str, system_prompt: str, user_prompt: str, cfg: dict) -> Optional[str]:
    if not cfg.get("enabled", False):
        return markdown_text

    priority = (cfg.get("priority") or "ollama").lower()
    if priority == "ollama":
        out = _try_ollama(markdown_text, system_prompt, user_prompt)
        if out is not None:
            return _sanitize_think(out)
        out2 = _try_openrouter(markdown_text, system_prompt, user_prompt)
        return _sanitize_think(out2) if out2 is not None else None
    else:
        out = _try_openrouter(markdown_text, system_prompt, user_prompt)
        if out is not None:
            return _sanitize_think(out)
        out2 = _try_ollama(markdown_text, system_prompt, user_prompt)
        return _sanitize_think(out2) if out2 is not None else None


def _try_ollama(text: str, system_prompt: str, user_prompt: str) -> Optional[str]:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    timeout = float(os.getenv("OLLAMA_TIMEOUT", "10"))
    url = f"{host.rstrip('/')}/api/chat"
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{user_prompt}\n\nТекст для обработки:\n\n{text}"},
            ],
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
            },
        }
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.ok:
            data = resp.json()
            return data.get("message", {}).get("content")
    except Exception:
        return None
    return None


def _try_openrouter(text: str, system_prompt: str, user_prompt: str) -> Optional[str]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.getenv("OPENROUTER_MODEL", "qwen-2.5-7b-instruct")
    timeout = float(os.getenv("OPENROUTER_TIMEOUT", "10"))
    if not api_key:
        return None
    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://local-processing",
            "X-Title": "youtrack-md-pipeline",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{user_prompt}\n\nТекст для обработки:\n\n{text}"},
            ],
            "temperature": 0.2,
            "top_p": 0.9,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.ok:
            data = resp.json()
            choices = data.get("choices") or []
            if choices:
                return choices[0].get("message", {}).get("content")
    except Exception:
        return None
    return None


_THINK_BLOCK_RE = re.compile(r"(?is)<think>\s*[\s\S]*?\s*</think>")


def _sanitize_think(content: Optional[str]) -> Optional[str]:
    if content is None:
        return None
    # Удаляем любые блоки <think>...</think> вместе с содержимым
    cleaned = _THINK_BLOCK_RE.sub("", content)
    # Сжимаем лишние пустые строки
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def check_llm_ready(cfg: dict) -> Tuple[bool, str, str]:
    priority = (cfg.get("priority") or "ollama").lower()
    if priority == "ollama":
        ok, reason = _probe_ollama()
        if ok:
            return True, "ollama", "ok"
        ok2, reason2 = _probe_openrouter()
        if ok2:
            return True, "openrouter", "ok"
        return False, "none", f"ollama:{reason}; openrouter:{reason2}"
    else:
        ok, reason = _probe_openrouter()
        if ok:
            return True, "openrouter", "ok"
        ok2, reason2 = _probe_ollama()
        if ok2:
            return True, "ollama", "ok"
        return False, "none", f"openrouter:{reason}; ollama:{reason2}"


def _probe_ollama() -> Tuple[bool, str]:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    try:
        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=3)
        if resp.ok:
            return True, "ok"
        return False, f"http {resp.status_code}"
    except Exception as e:
        return False, str(e)


def _probe_openrouter() -> Tuple[bool, str]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    if not api_key:
        return False, "no_api_key"
    try:
        # лёгкий запрос к моделям
        resp = requests.get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=3)
        if resp.ok:
            return True, "ok"
        return False, f"http {resp.status_code}"
    except Exception as e:
        return False, str(e)


