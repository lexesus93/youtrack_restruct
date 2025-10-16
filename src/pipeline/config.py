from pathlib import Path
from typing import Any, Dict
from ruamel.yaml import YAML


def load_pipeline_config(path: Path) -> Dict[str, Any]:
    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f) or {}
    # Минимальные значения по умолчанию
    data.setdefault("io", {})
    data.setdefault("formatting", {})
    data.setdefault("cleaning", {})
    data.setdefault("metadata", {})
    data.setdefault("pii", {"enabled": True})
    data.setdefault("secrets", {"detect_secrets": {"enabled": True}})
    data.setdefault("dedup", {"policy": "drop"})
    data.setdefault("template", {"sections_ru": [
        "Резюме", "Контекст", "Шаги воспроизведения", "Ожидалось vs Фактически",
        "Логи", "Причина", "Исправление / Обходной путь", "Ссылки"
    ]})
    data.setdefault("llm", {"enabled": False})
    data.setdefault("validation", {})
    return data


