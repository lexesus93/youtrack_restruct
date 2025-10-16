from __future__ import annotations

import re
from typing import Dict, List


ISSUE_RE = re.compile(r"\b([A-Z]{2,10}-\d{1,7})\b")
ENV_RE = re.compile(r"\b(prod|production|stage|staging|dev|test|qa)\b", re.I)
SEMVER_RE = re.compile(r"\b(v?\d+\.\d+\.\d+(?:[-+][\w.]+)?)\b")
HTTP_CODE_RE = re.compile(r"\bHTTP\/?1\.?1?\s+(\d{3})\b", re.I)
LINK_RE = re.compile(r"https?://\S+", re.I)
TIMESTAMP_RE = re.compile(r"\b\d{4}[-/.]\d{2}[-/.]\d{2}[ T]\d{2}:\d{2}(:\d{2})?\b")


def extract_metadata(text: str) -> Dict:
    issue_ids = list(dict.fromkeys(m.group(1) for m in ISSUE_RE.finditer(text)))
    envs = list(dict.fromkeys(m.group(1).lower() for m in ENV_RE.finditer(text)))
    versions = list(dict.fromkeys(m.group(1) for m in SEMVER_RE.finditer(text)))
    http_codes = list(dict.fromkeys(m.group(1) for m in HTTP_CODE_RE.finditer(text)))
    links = list(dict.fromkeys(m.group(0) for m in LINK_RE.finditer(text)))
    timestamps = list(dict.fromkeys(m.group(0) for m in TIMESTAMP_RE.finditer(text)))

    return {
        "issue_ids": issue_ids,
        "envs": envs,
        "versions": versions,
        "http_codes": http_codes,
        "links": links,
        "timestamps": timestamps,
    }


def metadata_section_ru(md: Dict) -> str:
    lines: List[str] = []
    if md.get("issue_ids"):
        lines.append(f"- **Тикеты**: {', '.join(md['issue_ids'])}")
    if md.get("envs"):
        lines.append(f"- **Среды**: {', '.join(md['envs'])}")
    if md.get("versions"):
        lines.append(f"- **Версии**: {', '.join(md['versions'])}")
    if md.get("http_codes"):
        lines.append(f"- **HTTP коды**: {', '.join(md['http_codes'])}")
    if md.get("links"):
        lines.append("- **Ссылки**:")
        for link in md["links"][:20]:
            lines.append(f"  - {link}")
    if md.get("timestamps"):
        lines.append(f"- **Метки времени**: {', '.join(md['timestamps'][:10])}")
    return "\n".join(lines) or ""


