from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Optional
import hashlib


def canonicalize(text: str) -> str:
    text = text.lower()
    # удаляем очевидные переменные части (временные метки, числа > 6 знаков)
    text = re.sub(r"\b\d{6,}\b", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def simhash_value(text: str) -> int:
    """Безопасный 64-битный simhash для текста.
    Токены приводятся к md5, используем нижние 64 бита, агрегируем по битам.
    """
    tokens = text.split()
    if not tokens:
        return 0
    bits = [0] * 64
    for t in tokens:
        h128 = int(hashlib.md5(t.encode('utf-8', errors='ignore')).hexdigest(), 16)
        h = h128 & ((1 << 64) - 1)
        for i in range(64):
            if (h >> i) & 1:
                bits[i] += 1
            else:
                bits[i] -= 1
    fingerprint = 0
    for i, v in enumerate(bits):
        if v >= 0:
            fingerprint |= (1 << i)
    return fingerprint


@dataclass
class DedupDecision:
    is_duplicate: bool
    canonical_id: Optional[str]


class DedupIndex:
    def __init__(self, state_dir: Path):
        self.db_path = state_dir / "fingerprints.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self):
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS documents (doc_id TEXT PRIMARY KEY, simhash TEXT, path TEXT)"
            )
            # Простейшая миграция: гарантировать, что столбцы соответствуют ожиданиям
            # (если старая схема, создаем временную таблицу и переносим данные)
        finally:
            con.close()

    def check_and_add(self, doc_id: str, text: str, policy: str = "drop") -> DedupDecision:
        canon = canonicalize(text)
        sh = simhash_value(canon)
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute("SELECT doc_id, simhash FROM documents")
            for row in cur.fetchall():
                try:
                    other_id = row[0]
                    other_sh = row[1]
                except Exception:
                    continue
                try:
                    other_sh_int = int(other_sh)
                except Exception:
                    continue
                if hamming_distance(sh, other_sh_int) <= 4:  # порог из конфига можно добавить
                    return DedupDecision(True, other_id)
            con.execute(
                "INSERT OR REPLACE INTO documents(doc_id, simhash, path) VALUES(?,?,?)",
                (doc_id, str(int(sh)), ""),
            )
            con.commit()
            return DedupDecision(False, doc_id)
        finally:
            con.close()


def hamming_distance(a: int, b: int) -> int:
    x = a ^ b
    count = 0
    while x:
        x &= x - 1
        count += 1
    return count


