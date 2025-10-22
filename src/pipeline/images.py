from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import base64
import requests
import mimetypes


# Поддерживаемые расширения изображений (легко расширяемо)
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"
}


@dataclass
class ImageExplanation:
    image_path: Path
    explanation: str
    matched_reference: Optional[str]  # буквальный референс, если был найден


def _find_sidecar_images_for_text_file(text_path: Path) -> List[Path]:
    """Для файла file.txt ищем соседнюю папку file/ и изображения внутри неё."""
    folder = text_path.with_suffix("")
    if not folder.exists() or not folder.is_dir():
        return []
    images: List[Path] = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(p)
    return images


def _read_image_as_base64(path: Path) -> str:
    with path.open("rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _guess_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    # Разрешённые типы из документации; остальные маппим на image/png
    if mime in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        return mime
    # Частые дополнительные форматы
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if path.suffix.lower() == ".webp":
        return "image/webp"
    if path.suffix.lower() == ".gif":
        return "image/gif"
    return "image/png"


def _call_openrouter_vision(prompt: str, image_b64: str, cfg: Dict, call_entry: Optional[Dict] = None, mime_type: Optional[str] = None) -> Optional[str]:
    """Вызов vision‑модели через OpenRouter с base64-изображением.

    Ожидает, что модель поддерживает контент вида {type: "image_url", image_url: {url: "data:image/...;base64,..."}}.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = cfg.get("vision_model") or os.getenv("OPENROUTER_VISION_MODEL", "qwen-2.5-7b-instruct")
    timeout = float(os.getenv("OPENROUTER_TIMEOUT", "20"))
    if call_entry is not None:
        call_entry["base_url"] = base_url
        call_entry["model"] = model
        call_entry["timeout_s"] = timeout
    if not api_key:
        if call_entry is not None:
            call_entry["error"] = "no_api_key"
        return None

    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://local-processing",
            "X-Title": "youtrack-md-pipeline-images",
            "Content-Type": "application/json",
        }
        # Используем мультимодальные сообщения (text + image)
        data_url = f"data:{(mime_type or 'image/png')};base64,{image_b64}"
        if call_entry is not None:
            call_entry["mime"] = mime_type or "image/png"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            },
                        },
                    ],
                }
            ],
            "temperature": 0.2,
            "top_p": 0.9,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.ok:
            data = resp.json()
            choices = data.get("choices") or []
            if choices:
                return (choices[0].get("message") or {}).get("content")
        else:
            if call_entry is not None:
                call_entry["http_status"] = resp.status_code
                # Сохраняем часть тела ответа для диагностики
                try:
                    call_entry["response_preview"] = resp.text[:500]
                except Exception:
                    pass
    except Exception:
        if call_entry is not None:
            import traceback
            call_entry["exception"] = traceback.format_exc()[-800:]
        return None
    return None


def _build_vision_prompt_ru() -> str:
    return (
        "Ты — помощник по расшифровке изображений из баг‑репортов. "
        "Определи тип изображения и дай структурированное объяснение.\n\n"
        "Если это скриншот лога: преобразуй его в текст лога (кодовый блок).\n"
        "Если это скриншот интерфейса: опиши окна и элементы управления, что выделено, подписи/маркировки.\n"
        "Краткость и точность. Русский язык."
    )


def explain_images_for_text_file(text_path: Path, cfg: Dict, report: Optional[Dict] = None) -> List[ImageExplanation]:
    images = _find_sidecar_images_for_text_file(text_path)
    if not images:
        if report is not None:
            report.setdefault("events", []).append({
                "type": "discover",
                "status": "no_images",
                "folder": str(text_path.with_suffix("")),
            })
        return []

    prompt = _build_vision_prompt_ru()
    results: List[ImageExplanation] = []
    if report is not None:
        report["images"] = [str(p) for p in images]
        report.setdefault("calls", [])
    retry_count = int((cfg.get("images", {}) or {}).get("retry_count", 0))
    backoff = float((cfg.get("images", {}) or {}).get("retry_backoff_sec", 0))
    fallbacks: List[str] = list((cfg.get("images", {}) or {}).get("fallback_models", []) or [])
    for img in images:
        img_b64 = _read_image_as_base64(img)
        mime = _guess_mime_type(img)
        # Основная попытка + ретраи
        attempts: List[Dict] = []
        def attempt_with_model(model_name: str) -> Optional[str]:
            call = {"image": str(img), "status": "pending"}
            if report is not None:
                attempts.append(call)
            # Временная подмена модели
            cfg_local = {"vision_model": model_name}
            out = _call_openrouter_vision(prompt, img_b64, cfg_local, call_entry=call, mime_type=mime)
            if report is not None:
                call["status"] = "ok" if out else ("error" if call.get("error") or call.get("http_status") or call.get("exception") else "empty")
                if out:
                    call["response_preview"] = (out[:200] + ("…" if len(out) > 200 else ""))
            return out

        # Попытка с основной моделью
        explanation = attempt_with_model((cfg.get("images", {}) or {}).get("vision_model") or os.getenv("OPENROUTER_VISION_MODEL", "qwen-2.5-7b-instruct")) or ""
        # Ретраи при 5xx/исключениях/empty
        if not explanation and retry_count > 0 and attempts:
            from time import sleep
            for i in range(retry_count):
                if backoff:
                    sleep(backoff)
                explanation = attempt_with_model((cfg.get("images", {}) or {}).get("vision_model") or os.getenv("OPENROUTER_VISION_MODEL", "qwen-2.5-7b-instruct")) or ""
                if explanation:
                    break
        # Фолбэк‑модели
        if not explanation and fallbacks:
            from time import sleep
            for fb in fallbacks:
                if backoff:
                    sleep(backoff)
                explanation = attempt_with_model(fb) or ""
                if explanation:
                    break

        if report is not None:
            # Разворачиваем attempts в calls
            report["calls"].extend(attempts)
        if explanation:
            results.append(ImageExplanation(image_path=img, explanation=explanation, matched_reference=None))
    return results


_FILE_REF_RE = re.compile(r"(?i)\b([\w.-]+\.(?:png|jpe?g|gif|bmp|webp|tiff?))\b")


def _find_literal_references(text: str) -> List[Tuple[str, Tuple[int, int]]]:
    """Возвращает список (имя_файла, (start, end)) по буквальным упоминаниям в тексте."""
    out: List[Tuple[str, Tuple[int, int]]] = []
    for m in _FILE_REF_RE.finditer(text):
        out.append((m.group(1), (m.start(), m.end())))
    return out


def _insert_explanation_near(text: str, pos: int, explanation: str) -> str:
    """Вставляет пояснение рядом с позицией pos. Эвристика: после текущего предложения."""
    # Ищем конец предложения после pos
    end = len(text)
    m = re.search(r"[\.!?]\s", text[pos:])
    insert_at = pos + (m.end() if m else 0)
    addition = f"\n\n> Пояснение к изображению:\n\n{explanation}\n\n"
    return text[:insert_at] + addition + text[insert_at:]


def _semantic_reference_candidates(text: str) -> List[Tuple[str, int]]:
    """Грубые семантические маркеры мест, куда можно вставлять пояснение.
    Возвращает список (якорная_фраза, позиция_начала)."""
    anchors = [
        r"(?i)см\.?\s*скриншот",
        r"(?i)см\.?\s*вложение",
        r"(?i)приложен[оы]?\s+изображение",
        r"(?i)смотрите\s+скрин",
        r"(?i)на\s+картинке",
    ]
    out: List[Tuple[str, int]] = []
    for pat in anchors:
        for m in re.finditer(pat, text):
            out.append((m.group(0), m.start()))
    return sorted(out, key=lambda x: x[1])


def _best_image_for_anchor(images: List[ImageExplanation], anchor_text: str) -> Optional[ImageExplanation]:
    if not images:
        return None
    # Простая эвристика: пока берём первое неиспользованное
    for img in images:
        if img.matched_reference is None:
            return img
    return images[0]


def _insert_at_logical_place(text: str, explanation: str) -> str:
    # Если есть разделы, попробуем вставить в "Контекст" или в начало
    candidates = [r"(?im)^##\s*Контекст\s*$", r"(?im)^# .+?$"]
    for pat in candidates:
        m = re.search(pat, text)
        if m:
            pos = m.end()
            return text[:pos] + f"\n\n> Пояснение к изображению:\n\n{explanation}\n\n" + text[pos:]
    # иначе в конец
    return text.rstrip() + f"\n\n> Пояснение к изображению:\n\n{explanation}\n"


def enrich_text_with_image_explanations(text: str, text_path: Path, cfg: Dict) -> str:
    """Главная точка входа: находит изображения, снимает пояснения и встраивает их в текст.

    - Буквальные референсы: вставить рядом с упоминанием
    - Семантические: якоря типа "см. скриншот" → сопоставить подходящее изображение
    - Нет референсов, но есть упоминания вложений → вставить в логичное место
    """
    explanations = explain_images_for_text_file(text_path, cfg)
    if not explanations:
        return text

    # 1) Буквальные референсы
    literals = _find_literal_references(text)
    used: Dict[Path, bool] = {}
    # Идём с конца, чтобы индексы не съезжали при вставках
    for filename, (start, end) in sorted(literals, key=lambda x: x[1][0], reverse=True):
        match = None
        for img in explanations:
            if img.image_path.name.lower() == filename.lower():
                match = img
                break
        if match is not None:
            text = _insert_explanation_near(text, end, match.explanation)
            match.matched_reference = filename
            used[match.image_path] = True

    # 2) Семантические якоря
    anchors = _semantic_reference_candidates(text)
    for _, pos in sorted(anchors, key=lambda x: x[1], reverse=True):
        candidate = _best_image_for_anchor([img for img in explanations if not used.get(img.image_path)], "")
        if candidate is not None:
            text = _insert_explanation_near(text, pos, candidate.explanation)
            used[candidate.image_path] = True

    # 3) Общие упоминания вложений/изображений
    if any(re.search(p, text) for p in [r"(?i)вложени[ея]", r"(?i)приложени[ея]", r"(?i)картинк[аи]", r"(?i)скриншот"]):
        for img in explanations:
            if not used.get(img.image_path):
                text = _insert_at_logical_place(text, img.explanation)
                used[img.image_path] = True

    return text


def enrich_text_with_image_explanations_report(text: str, text_path: Path, cfg: Dict) -> Tuple[str, Dict]:
    """То же, что enrich_text_with_image_explanations, но с подробным отчётом событий."""
    report: Dict = {"input": str(text_path), "events": [], "images": [], "calls": [], "insertions": []}
    explanations = explain_images_for_text_file(text_path, cfg, report=report)
    if not explanations:
        return text, report

    # 1) Буквальные референсы
    literals = _find_literal_references(text)
    used: Dict[Path, bool] = {}
    for filename, (start, end) in sorted(literals, key=lambda x: x[1][0], reverse=True):
        match = None
        for img in explanations:
            if img.image_path.name.lower() == filename.lower():
                match = img
                break
        if match is not None:
            text = _insert_explanation_near(text, end, match.explanation)
            match.matched_reference = filename
            used[match.image_path] = True
            report["insertions"].append({
                "type": "literal",
                "image": str(match.image_path),
                "reference": filename,
                "position": end,
            })

    # 2) Семантические якоря
    anchors = _semantic_reference_candidates(text)
    for anchor_text, pos in sorted(anchors, key=lambda x: x[1], reverse=True):
        candidate = _best_image_for_anchor([img for img in explanations if not used.get(img.image_path)], anchor_text)
        if candidate is not None:
            text = _insert_explanation_near(text, pos, candidate.explanation)
            used[candidate.image_path] = True
            report["insertions"].append({
                "type": "semantic",
                "image": str(candidate.image_path),
                "anchor": anchor_text,
                "position": pos,
            })

    # 3) Общие упоминания вложений/изображений
    if any(re.search(p, text) for p in [r"(?i)вложени[ея]", r"(?i)приложени[ея]", r"(?i)картинк[аи]", r"(?i)скриншот"]):
        for img in explanations:
            if not used.get(img.image_path):
                text = _insert_at_logical_place(text, img.explanation)
                used[img.image_path] = True
                report["insertions"].append({
                    "type": "logical",
                    "image": str(img.image_path),
                })

    if not report["insertions"] and explanations:
        # Нет явных упоминаний, но есть изображения — вставим хотя бы одно в конец
        text = _insert_at_logical_place(text, explanations[0].explanation)
        report["insertions"].append({
            "type": "fallback",
            "image": str(explanations[0].image_path),
        })

    return text, report


