from __future__ import annotations

from pathlib import Path
from typing import Dict, Callable, Optional, List
from datetime import datetime
from rich import print as rprint
import time

from .io_utils import discover_input_files, read_text_file, write_markdown_file, sha256_of_text, slugify_title
from .normalize import normalize_text
from .clean import remove_templates, normalize_lists, wrap_logs, filter_user_comments
from .anonymize import anonymize_text
## dedup отключён
from .markdown import render_front_matter, render_markdown, FrontMatter, format_markdown
from .llm import postprocess_with_llm
from .images import enrich_text_with_image_explanations
from .metadata import extract_metadata, metadata_section_ru
from .anonymize import detect_residual_pii


class FileResult:
    def __init__(self, input_path: Path, output_path: Optional[Path], doc_id: str, title: str, duplicate: bool):
        self.input_path = input_path
        self.output_path = output_path
        self.doc_id = doc_id
        self.title = title
        self.duplicate = duplicate


def process_directory(
    input_dir: Path,
    output_dir: Path,
    cfg: Dict,
    dry_run: bool = False,
    progress_cb: Optional[Callable[[Dict], None]] = None,
    control: Optional[object] = None,
) -> Dict:
    files: List[Path] = discover_input_files(input_dir)
    state_dir = Path(cfg["io"].get("state_dir", "state"))
    reports_dir = Path(cfg["io"].get("reports_dir", "reports"))
    (reports_dir / "pii").mkdir(parents=True, exist_ok=True)
    (reports_dir / "validation").mkdir(parents=True, exist_ok=True)
    # dedup отключён

    processed = 0
    # skipped_duplicates больше не используется
    results: List[FileResult] = []

    # Загрузка промптов LLM
    system_prompt = Path(cfg["llm"]["system_prompt_path"]).read_text(encoding="utf-8") if cfg.get("llm", {}).get("enabled") else ""
    user_prompt = Path(cfg["llm"]["user_prompt_path"]).read_text(encoding="utf-8") if cfg.get("llm", {}).get("enabled") else ""

    total = len(files)
    for idx, path in enumerate(files, start=1):
        if control:
            if getattr(control, "should_stop", lambda: False)():
                break
            if hasattr(control, "wait_if_paused"):
                control.wait_if_paused()
        if progress_cb:
            progress_cb({"event": "file_start", "file": str(path), "index": idx, "total": total})
        try:
            raw = read_text_file(path)
        except Exception as e:
            if progress_cb:
                progress_cb({"event": "error", "file": str(path), "message": str(e)})
            continue

        # Нормализация
        if progress_cb:
            progress_cb({"event": "stage", "file": str(path), "stage": "normalize"})
        if control:
            if getattr(control, "should_stop", lambda: False)():
                break
            if hasattr(control, "wait_if_paused"):
                control.wait_if_paused()
        text = normalize_text(raw, cfg["formatting"].get("unwrap_broken_lines", True))
        # Очистка
        if progress_cb:
            progress_cb({"event": "stage", "file": str(path), "stage": "clean"})
        if control:
            if getattr(control, "should_stop", lambda: False)():
                break
            if hasattr(control, "wait_if_paused"):
                control.wait_if_paused()
        text = remove_templates(text, cfg["cleaning"].get("remove_templates", []))
        text = normalize_lists(text)
        text = wrap_logs(text, cfg["formatting"].get("max_line_length", 160))
        # Фильтрация комментариев от заданных пользователей
        users_to_filter = (cfg.get("filtering", {}) or {}).get("users_to_filter", [])
        if users_to_filter:
            text = filter_user_comments(text, users_to_filter)
        # Обогащение текстов пояснениями к изображениям
        if (cfg.get("images", {}) or {}).get("enabled", False):
            if progress_cb:
                progress_cb({"event": "stage", "file": str(path), "stage": "images"})
            if control:
                if getattr(control, "should_stop", lambda: False)():
                    break
                if hasattr(control, "wait_if_paused"):
                    control.wait_if_paused()
            try:
                text = enrich_text_with_image_explanations(text, path, cfg)
            except Exception as e:
                if progress_cb:
                    progress_cb({"event": "warn", "file": str(path), "stage": "images", "message": str(e)})
        # Обезличивание (проход 1)
        if progress_cb:
            progress_cb({"event": "stage", "file": str(path), "stage": "anonymize_pass1"})
        if control:
            if getattr(control, "should_stop", lambda: False)():
                break
            if hasattr(control, "wait_if_paused"):
                control.wait_if_paused()
        text, pii_report1 = anonymize_text(text)
        # Извлечение метаданных на основе исходного текста
        if progress_cb:
            progress_cb({"event": "stage", "file": str(path), "stage": "extract_metadata"})
        meta = extract_metadata(text)

        # Идентификатор документа
        doc_id = sha256_of_text(text)

        # Заголовок
        title = _derive_title(text)
        sections = cfg["template"].get("sections_ru", [])

        # Базовый Markdown до LLM
        if progress_cb:
            progress_cb({"event": "stage", "file": str(path), "stage": "build_markdown"})
        body_by_section = {sec: "" for sec in sections}
        body_by_section[sections[0] if sections else "Резюме"] = text
        if "Метаданные" in sections:
            body_by_section["Метаданные"] = metadata_section_ru(meta)
        md = render_markdown(title, sections, body_by_section)

        # LLM постобработка
        if cfg.get("llm", {}).get("enabled"):
            if progress_cb:
                progress_cb({"event": "stage", "file": str(path), "stage": "llm"})
            if control:
                if getattr(control, "should_stop", lambda: False)():
                    break
                if hasattr(control, "wait_if_paused"):
                    control.wait_if_paused()
            md_llm = postprocess_with_llm(md, system_prompt, user_prompt, cfg.get("llm", {}))
            if md_llm:
                md = md_llm

        # Обезличивание (проход 2)
        if progress_cb:
            progress_cb({"event": "stage", "file": str(path), "stage": "anonymize_pass2"})
        if control:
            if getattr(control, "should_stop", lambda: False)():
                break
            if hasattr(control, "wait_if_paused"):
                control.wait_if_paused()
        md, pii_report2 = anonymize_text(md)
        # Валидация на остаточную PII
        if progress_cb:
            progress_cb({"event": "stage", "file": str(path), "stage": "validate"})
        residual = detect_residual_pii(md)
        leakage = sum(residual.values())

        # Front matter
        fm = FrontMatter(
            source="youtrack-export",
            document_id=doc_id,
            title=title,
            language="ru",
            has_pii=False,
            pii_rules_version=str(cfg["pii"].get("ruleset_version", "v1.0.0")),
            cleaning_profile=f"default@{datetime.utcnow().date().isoformat()}",
            dedup_group_id=doc_id,
            source_path=str(path),
            checksum=f"sha256:{sha256_of_text(raw)}",
            llm_postprocess={
                "enabled": bool(cfg.get("llm", {}).get("enabled")),
                "backend": (cfg.get("llm", {}).get("priority") or "ollama"),
            },
            extra={},
        )
        out_text = format_markdown(md)
        if cfg.get("output", {}).get("front_matter", False):
            out_text = render_front_matter(fm) + "\n" + out_text

        # Запись
        if progress_cb:
            progress_cb({"event": "stage", "file": str(path), "stage": "write"})
        if not dry_run:
            # Имя выходного файла формируем из имени исходника с расширением .md
            out_file = output_dir / f"{path.stem}.md"
            write_markdown_file(out_file, out_text)
        else:
            out_file = None

        # Отчёты
        (reports_dir / "pii" / f"{doc_id}.json").write_text(
            __import__("json").dumps({
                "doc_id": doc_id,
                "counts_pass1": pii_report1.counts,
                "counts_pass2": pii_report2.counts,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # dedup отчёты отключены
        if leakage:
            with (reports_dir / "validation" / "residual_pii.jsonl").open("a", encoding="utf-8") as f:
                f.write(__import__("json").dumps({"doc_id": doc_id, "residual": residual}, ensure_ascii=False) + "\n")

        processed += 1
        results.append(FileResult(path, out_file, doc_id, title, False))
        if progress_cb:
            progress_cb({
                "event": "file_end",
                "file": str(path),
                "duplicate": False,
                "index": idx,
                "total": total,
                "output_path": str(out_file) if out_file else None,
            })

    return {"processed": processed, "results": [
        {
            "input_path": str(r.input_path),
            "output_path": str(r.output_path) if r.output_path else None,
            "doc_id": r.doc_id,
            "title": r.title,
            "duplicate": r.duplicate,
        } for r in results
    ]}


def _derive_title(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if len(s) >= 10:
            return s[:120]
    return "Инцидент YouTrack"


