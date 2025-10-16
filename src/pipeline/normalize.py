import re


def normalize_text(text: str, unwrap_broken_lines: bool = True) -> str:
    # Удаление невидимых и управление пробелами
    text = re.sub(r"\u200b|\ufeff", "", text)
    # Сокращение множественных пустых строк
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Разворачивание разорванных строк по простым эвристикам
    if unwrap_broken_lines:
        text = re.sub(r"(?<![.:;\-])\n(?!\n)", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


