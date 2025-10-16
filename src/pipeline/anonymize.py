import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_RE = re.compile(r"(?:(?<=\D)|^)\+?\d[\d\s().-]{7,}\d(?=\D|$)")
IP_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
MAC_RE = re.compile(r"\b([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}\b")
LOGIN_RE = re.compile(r"(?i)\b(?:login|user|uid|account|acc|логин|пользователь)[:=]\s*([\w.\-@]+)")
URL_CRED_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s]+:[^\s]+@[^\s]+")
SECRET_RE = re.compile(r"(?i)\b(?:(?:api|access|secret|private|bearer|token|key|pwd|pass(?:word)?)\s*[:=]\s*[A-Za-z0-9._\-]{16,})\b")
TIMESTAMP_RE = re.compile(r"\b\d{4}[-/.]\d{2}[-/.]\d{2}[ T]\d{2}:\d{2}(:\d{2})?\b")
# Русский маркер "пароль: <значение>" — маскируем только значение
PASSWORD_WORD_RE = re.compile(r"(?iu)(пароль\s*(?:[:=\-–—]?\s*))([^<\s]\S*)")


MASKS = {
    "EMAIL": "<EMAIL>",
    "PHONE": "<PHONE>",
    "IP": "<IP>",
    "MAC": "<MAC>",
    "LOGIN": "<LOGIN>",
    "URL_CRED": "<SECRET:URI>",
    "SECRET": "<SECRET:GENERIC>",
    "PASSWORD": "<SECRET:PASSWORD>",
}


@dataclass
class AnonymizeReport:
    counts: Dict[str, int]


def replace_pattern(text: str, pattern: re.Pattern, mask: str) -> Tuple[str, int]:
    def _sub(_):
        return mask

    new_text, n = pattern.subn(_sub, text)
    return new_text, n


def anonymize_text(text: str) -> Tuple[str, AnonymizeReport]:
    counts: Dict[str, int] = {k: 0 for k in MASKS.keys()}
    # Защита временных меток от ложного срабатывания PHONE: заменяем на плейсхолдеры
    protected: List[Tuple[str, str]] = []
    def _protect_timestamps(t: str) -> str:
        idx = 0
        def _sub(m: re.Match) -> str:
            nonlocal idx
            orig = m.group(0)
            token = f"<TS_{idx}>"
            protected.append((token, orig))
            idx += 1
            return token
        return TIMESTAMP_RE.sub(_sub, t)

    def _restore_timestamps(t: str) -> str:
        for token, orig in protected:
            t = t.replace(token, orig)
        return t

    text = _protect_timestamps(text)
    for name, (pattern, mask) in {
        "EMAIL": (EMAIL_RE, MASKS["EMAIL"]),
        "PHONE": (PHONE_RE, MASKS["PHONE"]),
        "IP": (IP_RE, MASKS["IP"]),
        "MAC": (MAC_RE, MASKS["MAC"]),
        "URL_CRED": (URL_CRED_RE, MASKS["URL_CRED"]),
        "SECRET": (SECRET_RE, MASKS["SECRET"]),
    }.items():
        text, n = replace_pattern(text, pattern, mask)
        counts[name] += n
    # PASSWORD (рус.): сохраняем префикс, маскируем только значение
    def _pwd_sub(m: re.Match) -> str:
        return m.group(1) + MASKS["PASSWORD"]
    text, n = PASSWORD_WORD_RE.subn(_pwd_sub, text)
    counts["PASSWORD"] = counts.get("PASSWORD", 0) + n
    # LOGIN: замена только значения после маркера
    text, n = LOGIN_RE.subn(lambda m: m.group(0).split("=")[0].split(":")[0] + ": " + MASKS["LOGIN"], text)
    counts["LOGIN"] += n
    text = _restore_timestamps(text)
    return text, AnonymizeReport(counts=counts)


def detect_residual_pii(text: str) -> Dict[str, int]:
    # Перед подсчётом игнорируем валидные временные метки, чтобы не считать их как PHONE
    sanitized = TIMESTAMP_RE.sub("", text)
    residual = {
        "EMAIL": len(EMAIL_RE.findall(text)),
        "PHONE": len(PHONE_RE.findall(sanitized)),
        "IP": len(IP_RE.findall(text)),
        "MAC": len(MAC_RE.findall(text)),
        "URL_CRED": len(URL_CRED_RE.findall(text)),
        "SECRET": len(SECRET_RE.findall(text)),
    }
    # LOGIN: проверяем наличие шаблонов логина с явным значением
    residual["LOGIN"] = len(LOGIN_RE.findall(text))
    return residual


