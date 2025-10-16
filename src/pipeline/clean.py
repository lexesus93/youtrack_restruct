import re
from typing import List


def remove_templates(text: str, templates: List[str]) -> str:
    for pattern in templates:
        text = re.sub(pattern, "", text)
    # Очистка лишних пустых строк после вырезки
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_lists(text: str) -> str:
    # Маркеры списков приводим к '-' и уплотняем пробелы
    text = re.sub(r"(?m)^[\t\s]*[•*·‣▪▶›»\-]\s+", "- ", text)
    text = re.sub(r"(?m)^\s*\d+[\.)]\s+", "1. ", text)
    return text


def filter_user_comments(text: str, users: List[str]) -> str:
    if not users:
        return text
    # Простая эвристика: удаляем блоки комментариев формата "Автор: <user>" до пустой строки/разделителя
    # И/или строки, начинающиеся с "<user>:". Кейс-инсенситив, нормализуем пробелы
    pattern_users = "|".join(re.escape(u) for u in users)
    # Удаление строк "user: ..."
    text = re.sub(rf"(?im)^\s*(?:{pattern_users})\s*:\s*.*$", "", text)
    # Удаление блоков вида "Автор: user" + до следующего пустого раздела (осторожно, минимально)
    text = re.sub(rf"(?is)(?:Автор\s*:\s*(?:{pattern_users}).*?)(?:\n\s*\n|$)", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def wrap_logs(text: str, max_line_length: int = 160) -> str:
    lines = text.split("\n")
    wrapped = []
    for line in lines:
        if len(line) <= max_line_length:
            wrapped.append(line)
            continue
        # Мягкое разбиение длинных строк
        start = 0
        while start < len(line):
            wrapped.append(line[start:start + max_line_length])
            start += max_line_length
    return "\n".join(wrapped)


