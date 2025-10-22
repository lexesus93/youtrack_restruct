import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import os
import re
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QLineEdit, QTextEdit, QCheckBox, QProgressBar, QListWidget,
    QListWidgetItem, QTabWidget, QSplitter, QDialog, QDialogButtonBox
)
from PySide6.QtGui import QTextOption, QDesktopServices, QColor, QTextCursor, QTextCharFormat
from markdown_it import MarkdownIt

from src.pipeline.config import load_pipeline_config
from src.pipeline.run import process_directory
from src.pipeline.llm import check_llm_ready
from pathlib import Path


class Worker(QThread):
    progress = Signal(dict)
    finished = Signal(dict)

    def __init__(self, input_dir: Path, output_dir: Path, cfg: dict, dry_run: bool = False):
        super().__init__()
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.cfg = cfg
        self.dry_run = dry_run
        self._paused = False
        self._stop = False

    def run(self):
        def cb(evt: dict):
            self.progress.emit(evt)
        class Control:
            def should_stop(inner_self):
                return self._stop
            def wait_if_paused(inner_self):
                while self._paused and not self._stop:
                    self.msleep(100)
        stats = process_directory(self.input_dir, self.output_dir, self.cfg, dry_run=self.dry_run, progress_cb=cb, control=Control())
        self.finished.emit(stats)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._stop = True


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TXT → Markdown (RU)")
        self.resize(800, 600)
        # Подхват .env до построения UI, чтобы пути применились по умолчанию
        load_dotenv(override=False)
        self._build_ui()
        self.worker = None
        self._items_by_input = {}
        self._image_logs: dict = {}

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Ввод/вывод
        io_row = QHBoxLayout()
        self.input_edit = QLineEdit(str(Path(os.getenv("INPUT_DIR", "input")).absolute()))
        btn_in = QPushButton("Выбрать входную папку")
        btn_in.clicked.connect(self._choose_input)
        self.output_edit = QLineEdit(str(Path(os.getenv("OUTPUT_DIR", "output/md")).absolute()))
        btn_out = QPushButton("Выбрать выходную папку")
        btn_out.clicked.connect(self._choose_output)
        io_row.addWidget(QLabel("Вход:"))
        io_row.addWidget(self.input_edit)
        io_row.addWidget(btn_in)
        io_row.addWidget(QLabel("Выход:"))
        io_row.addWidget(self.output_edit)
        io_row.addWidget(btn_out)
        layout.addLayout(io_row)

        # Конфиг и LLM
        cfg_row = QHBoxLayout()
        self.config_edit = QLineEdit(str(Path("config/pipeline.yaml").absolute()))
        self.llm_checkbox = QCheckBox("Включить LLM‑постобработку")
        self.llm_checkbox.setChecked(True)
        cfg_row.addWidget(QLabel("Конфиг:"))
        cfg_row.addWidget(self.config_edit)
        cfg_row.addWidget(self.llm_checkbox)
        layout.addLayout(cfg_row)

        # Кнопка управления промптом (модальное окно) и открытие отчётов
        prompt_row = QHBoxLayout()
        self.prompt_btn = QPushButton("Промпт…")
        self.prompt_btn.clicked.connect(self._open_prompt_dialog)
        self.open_reports_btn = QPushButton("Открыть папку отчётов")
        self.open_reports_btn.clicked.connect(self._open_reports)
        prompt_row.addWidget(self.prompt_btn)
        prompt_row.addWidget(self.open_reports_btn)
        prompt_row.addStretch(1)
        layout.addLayout(prompt_row)
        self._custom_prompt_text: str = ""

        # Прогресс
        prog_row = QHBoxLayout()
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        self.status_lbl = QLabel("Готов"); self.status_lbl.setMinimumWidth(140)
        prog_row.addWidget(self.progress, 1)
        prog_row.addWidget(self.status_lbl, 0)
        layout.addLayout(prog_row)

        # Список и предпросмотр (2/3 на предпросмотр)
        self.file_list = QListWidget()
        self.tabs = QTabWidget()
        self.src_view = QTextEdit(); self.src_view.setReadOnly(True); self.src_view.setWordWrapMode(QTextOption.NoWrap)
        self.out_view = QTextEdit(); self.out_view.setReadOnly(True); self.out_view.setWordWrapMode(QTextOption.NoWrap)
        self.src_view.setLineWrapMode(QTextEdit.NoWrap)
        self.out_view.setLineWrapMode(QTextEdit.NoWrap)
        self.src_view.setMinimumHeight(300)
        self.out_view.setMinimumHeight(300)
        self.tabs.addTab(self.src_view, "Исходник")
        self.tabs.addTab(self.out_view, "Результат")
        # Вкладка логов изображений
        self.images_log_view = QTextEdit(); self.images_log_view.setReadOnly(True); self.images_log_view.setWordWrapMode(QTextOption.NoWrap)
        self.tabs.addTab(self.images_log_view, "Логи изображений")
        # Переключатель режимов предпросмотра (Текст/Markdown)
        mode_row = QHBoxLayout()
        self.mode_text_btn = QPushButton("Текст"); self.mode_text_btn.setCheckable(True); self.mode_text_btn.setChecked(True)
        self.mode_md_btn = QPushButton("Markdown"); self.mode_md_btn.setCheckable(True)
        self.mode_text_btn.clicked.connect(lambda: self._set_preview_mode("text"))
        self.mode_md_btn.clicked.connect(lambda: self._set_preview_mode("md"))
        mode_row.addWidget(QLabel("Предпросмотр:"))
        mode_row.addWidget(self.mode_text_btn)
        mode_row.addWidget(self.mode_md_btn)
        mode_row.addStretch(1)
        splitter = QSplitter()
        splitter.addWidget(self.file_list)
        right_panel = QWidget(); rp_layout = QVBoxLayout(right_panel); rp_layout.setContentsMargins(0,0,0,0); rp_layout.setSpacing(4)
        rp_layout.addLayout(mode_row)
        rp_layout.addWidget(self.tabs)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        # начальные размеры ~1/3 : 2/3
        try:
            splitter.setSizes([self.width() // 3, self.width() * 2 // 3])
        except Exception:
            pass
        layout.addWidget(splitter, 1)

        # Кнопки
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.run_btn = QPushButton("Запустить")
        self.run_btn.clicked.connect(self._run)
        btn_row.addWidget(self.run_btn)
        self.pause_btn = QPushButton("Пауза")
        self.pause_btn.clicked.connect(self._pause)
        btn_row.addWidget(self.pause_btn)
        self.resume_btn = QPushButton("Возобновить")
        self.resume_btn.clicked.connect(self._resume)
        btn_row.addWidget(self.resume_btn)
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)
        # Drag & Drop поддержка
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if path.is_dir():
            # Если курсор над полем ввода — в него, иначе в поле вывода
            if self.input_edit.underMouse():
                self.input_edit.setText(str(path))
            elif self.output_edit.underMouse():
                self.output_edit.setText(str(path))
            else:
                # По умолчанию как вход
                self.input_edit.setText(str(path))
        event.acceptProposedAction()

    def _choose_input(self):
        d = QFileDialog.getExistingDirectory(self, "Выберите входную папку")
        if d:
            self.input_edit.setText(d)

    def _choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Выберите выходную папку")
        if d:
            self.output_edit.setText(d)

    def _run(self):
        load_dotenv(override=True)
        cfg = load_pipeline_config(Path(self.config_edit.text()))
        cfg["llm"]["enabled"] = self.llm_checkbox.isChecked()
        # Проверка готовности LLM (если включено), чтобы не зависать на долгих таймаутах
        if cfg["llm"].get("enabled"):
            ok, backend, reason = check_llm_ready(cfg.get("llm", {}))
            if not ok:
                self.status_lbl.setText(f"LLM недоступен: {reason}. Продолжаем без LLM.")
                cfg["llm"]["enabled"] = False
        # Если задан пользовательский промпт (через модальный диалог) — сохраняем во временный файл
        user_prompt = (self._custom_prompt_text or "").strip()
        if user_prompt:
            tmp_prompt = Path("config/prompts/_runtime_prompt.md")
            tmp_prompt.parent.mkdir(parents=True, exist_ok=True)
            tmp_prompt.write_text(user_prompt, encoding="utf-8")
            cfg["llm"]["user_prompt_path"] = str(tmp_prompt)
        self.worker = Worker(Path(self.input_edit.text()), Path(self.output_edit.text()), cfg, dry_run=False)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.run_btn.setEnabled(False)
        self.worker.start()

    def _pause(self):
        if self.worker and self.worker.isRunning():
            self.worker.pause()
            self.status_lbl.setText("Пауза")

    def _resume(self):
        if self.worker and self.worker.isRunning():
            self.worker.resume()
            self.status_lbl.setText("Возобновлено")

    def _stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status_lbl.setText("Остановка...")

    def closeEvent(self, event):
        # Корректное завершение фонового треда
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(2000)
        return super().closeEvent(event)

    def _on_progress(self, evt: dict):
        if evt.get("event") == "file_start":
            idx, total = evt.get("index", 0), evt.get("total", 1)
            self.progress.setValue(int((idx - 1) / max(total, 1) * 100))
            self.status_lbl.setText(f"Файл {idx}/{total}: {evt.get('file')}")
            # Добавляем файл в очередь сразу
            in_path = evt.get('file')
            if in_path and in_path not in self._items_by_input:
                label = f"{Path(in_path).name}"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, {"input_path": in_path, "output_path": None})
                self.file_list.addItem(item)
                self._items_by_input[in_path] = item
                if not hasattr(self, "_list_connected"):
                    self.file_list.itemClicked.connect(self._on_item_clicked)
                    self._list_connected = True
        elif evt.get("event") == "stage":
            self.status_lbl.setText(f"{evt.get('file')} — {evt.get('stage')}")
            # Обновляем лог при стадии images: пытаемся прочитать отчёт по текущему doc_id, если он уже записан
            if evt.get("stage") == "write":
                # На стадии write doc_id уже вычислен, отчёт записывается позже; отрисуем логи при завершении файла
                pass
        elif evt.get("event") == "file_end":
            idx = evt.get("index")
            total = evt.get("total") or max(1, self.file_list.count())
            if idx and total:
                self.progress.setValue(int(idx / total * 100))
            self.status_lbl.setText(f"Готов: {evt.get('file')}")
            # Обновляем запись очереди, добавляя путь результата
            in_path = evt.get('file')
            out_path = evt.get('output_path')
            item = self._items_by_input.get(in_path)
            if item is None and in_path:
                # Фоллбэк: если по какой-то причине элемент не добавился на file_start — добавим его сейчас
                item = QListWidgetItem(Path(in_path).name)
                item.setData(Qt.UserRole, {"input_path": in_path, "output_path": out_path})
                self.file_list.addItem(item)
                self._items_by_input[in_path] = item
            if item is not None:
                label = f"{Path(in_path).name} → {Path(out_path).name if out_path else '(нет)'}"
                item.setText(label)
                data = item.data(Qt.UserRole) or {}
                data["output_path"] = out_path
                item.setData(Qt.UserRole, data)
            # Подгружаем логи изображений из reports/images/<doc_id>.json
            try:
                reports_dir = Path(os.getenv("REPORTS_DIR", "reports"))
                doc_id = None
                # Попытаемся восстановить doc_id из пути отчёта PII (известен формат), иначе из исходника не получить напрямую
                # Для простоты: сканируем reports/images по времени и берём последний созданный
                images_dir = reports_dir / "images"
                latest = None
                if images_dir.exists():
                    latest = max(images_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, default=None)
                if latest:
                    log_text = latest.read_text(encoding="utf-8", errors="ignore")
                    self._image_logs[in_path] = log_text
                    # Если выбран именно этот элемент — отрисуем сразу
                    current = self.file_list.currentItem()
                    if current and (current.data(Qt.UserRole) or {}).get("input_path") == in_path:
                        self._render_preview()
            except Exception:
                pass
        elif evt.get("event") == "error":
            self.status_lbl.setText(f"Ошибка: {evt.get('file')} — {evt.get('message')}")
            # ошибки не добавляем в список файлов, чтобы не ломать соответствие

    def _on_finished(self, stats: dict):
        self.progress.setValue(100)
        self.run_btn.setEnabled(True)
        # Список уже наполнен по мере обработки

    def _on_item_clicked(self, item):
        r = item.data(Qt.UserRole) or {}
        self._show_result(r)

    def _show_result(self, item: dict):
        # Читаем исходник/результат
        inp = Path(item.get("input_path", ""))
        out = item.get("output_path")
        try:
            self._last_src_text = inp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            self._last_src_text = ""
        if out:
            try:
                self._last_out_text = Path(out).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                self._last_out_text = ""
        else:
            self._last_out_text = ""
        self._render_preview()

    def _set_preview_mode(self, mode: str):
        if mode == "text":
            self.mode_text_btn.setChecked(True)
            self.mode_md_btn.setChecked(False)
        else:
            self.mode_text_btn.setChecked(False)
            self.mode_md_btn.setChecked(True)
        self._render_preview()

    def _render_preview(self):
        if getattr(self, 'mode_text_btn', None) and self.mode_text_btn.isChecked():
            self.src_view.setPlainText(getattr(self, '_last_src_text', ""))
            self.out_view.setPlainText(getattr(self, '_last_out_text', ""))
            # Подсветка в текстовом режиме: выделяем строки с маркером пояснения
            try:
                self._apply_text_highlight()
            except Exception:
                self.out_view.setExtraSelections([])
        else:
            md = MarkdownIt()
            src_html = md.render(getattr(self, '_last_src_text', ""))
            out_html = md.render(getattr(self, '_last_out_text', ""))
            # Подсветка в Markdown: оборачиваем маркер пояснения видимым стилем
            try:
                out_html = re.sub(
                    r"Пояснение\s+к\s+изображению\s*:",
                    '<span style="background-color:#fff3bf;padding:1px 3px;border-radius:2px;">Пояснение к изображению:</span>',
                    out_html,
                    flags=re.I,
                )
            except Exception:
                pass
            self.src_view.setHtml(src_html)
            self.out_view.setHtml(out_html)
            # В HTML-режиме дополнительные выделения не нужны
            self.out_view.setExtraSelections([])
        # Логи изображений: показываем JSON как текст
        try:
            current = self.file_list.currentItem()
            inp = (current.data(Qt.UserRole) or {}).get("input_path") if current else None
            log_text = self._image_logs.get(inp or "") or "(нет логов изображений)"
            self.images_log_view.setPlainText(log_text)
        except Exception:
            self.images_log_view.setPlainText("(нет логов изображений)")

    def _apply_text_highlight(self):
        # Ищем в out_view все вхождения маркера и подсвечиваем фон
        text = self.out_view.toPlainText()
        if not text:
            self.out_view.setExtraSelections([])
            return
        pattern = re.compile(r"Пояснение\s+к\s+изображению\s*:", re.I)
        selections = []
        for m in pattern.finditer(text):
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#fff3bf"))
            sel.format = fmt
            cursor = self.out_view.textCursor()
            cursor.setPosition(m.start())
            cursor.setPosition(m.end(), QTextCursor.KeepAnchor)
            sel.cursor = cursor
            selections.append(sel)
        self.out_view.setExtraSelections(selections)

    def _open_reports(self):
        # Открываем папку отчётов (REPORTS_DIR или по умолчанию ./reports)
        base = os.getenv("REPORTS_DIR", "reports")
        p = Path(base).absolute()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _open_prompt_dialog(self):
        # Определяем текущий эффективный промпт: пользовательский или из конфига
        current_text = (self._custom_prompt_text or "").strip()
        if not current_text:
            try:
                from ruamel.yaml import YAML
                yaml = YAML(typ="safe")
                cfg_path = Path(self.config_edit.text())
                with cfg_path.open("r", encoding="utf-8") as f:
                    cfg = yaml.load(f) or {}
                user_prompt_path = (cfg.get("llm", {}) or {}).get("user_prompt_path") or "config/prompts/rewrite.md"
                current_text = Path(user_prompt_path).read_text(encoding="utf-8") if Path(user_prompt_path).exists() else ""
            except Exception:
                current_text = ""

        dlg = QDialog(self)
        dlg.setWindowTitle("Промпт LLM")
        v = QVBoxLayout(dlg)
        info = QLabel("Текущий промпт. Измените при необходимости и нажмите Сохранить.")
        v.addWidget(info)
        edit = QTextEdit()
        edit.setPlainText(current_text)
        v.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        v.addWidget(btns)

        def on_save():
            self._custom_prompt_text = edit.toPlainText()
            dlg.accept()

        def on_cancel():
            dlg.reject()

        btns.accepted.connect(on_save)
        btns.rejected.connect(on_cancel)
        dlg.exec()


def main():
    app = QApplication([])
    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()


