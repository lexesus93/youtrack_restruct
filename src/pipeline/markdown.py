from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from ruamel.yaml import YAML
import mdformat


yaml = YAML()
yaml.indent(mapping=2, sequence=2, offset=2)


@dataclass
class FrontMatter:
    source: str
    document_id: str
    title: str
    language: str
    has_pii: bool
    pii_rules_version: str
    cleaning_profile: str
    dedup_group_id: str
    source_path: str
    checksum: str
    llm_postprocess: Dict
    extra: Dict


def render_front_matter(fm: FrontMatter) -> str:
    base = {
        "source": fm.source,
        "document_id": fm.document_id,
        "title": fm.title,
        "language": fm.language,
        "has_pii": fm.has_pii,
        "pii_rules_version": fm.pii_rules_version,
        "cleaning_profile": fm.cleaning_profile,
        "dedup_group_id": fm.dedup_group_id,
        "source_path": fm.source_path,
        "checksum": fm.checksum,
        "llm_postprocess": fm.llm_postprocess,
    }
    base.update(fm.extra or {})
    from io import StringIO
    buf = StringIO()
    yaml.dump(base, buf)
    return f"---\n{buf.getvalue()}---\n"


def render_markdown(title: str, sections: List[str], body_by_section: Dict[str, str]) -> str:
    lines: List[str] = []
    lines.append(f"# {title}\n")
    for sec in sections:
        lines.append(f"## {sec}\n")
        content = (body_by_section.get(sec) or "").strip()
        if content:
            lines.append(content + "\n")
        else:
            lines.append("\n")
    return "\n".join(lines)


def format_markdown(content: str) -> str:
    try:
        return mdformat.text(content)
    except Exception:
        return content


