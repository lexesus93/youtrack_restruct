## Конвейер TXT → Markdown (RU) с обезличиванием, удалением дублей и LLM‑постобработкой

### Кратко
- Вход: папка с `.txt`.
- Выход: папка с `.md` (русские заголовки), YAML front matter, кастомные разделы.
- Обязательно: нормализация, очистка, обезличивание, удаление дубликатов.
- Опционально: LLM‑постобработка через Ollama (локально) с фолбэком на OpenRouter (по `.env`).

### Быстрый старт
1. Установите зависимости:
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```
2. Настройте окружение:
```bash
cp .env.example .env
# отредактируйте значения при необходимости
```
3. Отредактируйте `config/pipeline.yaml` под ваши нужды (русские разделы по умолчанию уже заданы).
4. Запуск GUI:
```bash
python -m src.gui.app
```
5. Запуск CLI:
```bash
python -m src.cli process --input ./input --out ./output/md --config ./config/pipeline.yaml --llm
```

### Переменные окружения (.env)
См. `.env.example`. Все ключи/URL берутся из `.env`. Если `LLM_ENABLED=false` — постобработка выключена.

### Структура
```
config/
  pipeline.yaml
  prompts/
    guardrails.md
    rewrite.md
input/
output/
  md/
reports/
  pii/
  dedup/
  validation/
state/
  fingerprints.sqlite
src/
  cli.py
  gui/app.py
  pipeline/
    __init__.py
    config.py
    io_utils.py
    normalize.py
    clean.py
    anonymize.py
    dedup.py
    markdown.py
    llm.py
    run.py
```

### Кроссплатформенность
- Проект проверен для запуска на macOS, Linux и Windows (Python 3.11+). GUI на PySide6.

### Примечание по обезличиванию
- По умолчанию используются регулярные выражения (email/phone/IP/MAC/URI/логины/секреты). Для RU‑имен можно подключить `natasha` (опционально).


