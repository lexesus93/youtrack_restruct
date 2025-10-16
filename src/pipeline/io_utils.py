from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple
from charset_normalizer import from_path
import hashlib
import ftfy


def discover_input_files(input_root: Path) -> List[Path]:
    if input_root.is_file() and input_root.suffix.lower() == ".txt":
        return [input_root]
    return sorted([p for p in input_root.rglob("*.txt") if p.is_file()])


def read_text_file(path: Path) -> str:
    result = from_path(str(path)).best()
    if result is None:
        raise ValueError(f"Не удалось определить кодировку: {path}")
    text = str(result)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = ftfy.fix_text(text)
    return text


def write_markdown_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify_title(title: str) -> str:
    # Простейшая безопасная слагация
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in title)
    safe = " ".join(safe.split())
    return safe.replace(" ", "-").lower().strip("-")


