import os
import sys
from pathlib import Path
import typer
from rich import print as rprint
from dotenv import load_dotenv

from src.pipeline.config import load_pipeline_config
from src.pipeline.run import process_directory


app = typer.Typer(add_completion=False, help="Конвейер TXT → Markdown с обезличиванием и LLM‑постобработкой")


@app.command("process")
def cli_process(
    input: str = typer.Option(None, help="Папка с TXT файлами (по умолчанию из .env INPUT_DIR или ./input)"),
    out: str = typer.Option(None, help="Папка для Markdown результата (по умолчанию из .env OUTPUT_DIR или ./output/md)"),
    config: str = typer.Option("config/pipeline.yaml", help="Конфигурация пайплайна"),
    llm: bool = typer.Option(False, help="Включить LLM‑постобработку"),
    dry_run: bool = typer.Option(False, help="Только отчёт, без записи файлов"),
):
    load_dotenv(override=True)
    config_path = Path(config)
    cfg = load_pipeline_config(config_path)
    # Перекрываем включение LLM из CLI
    if llm is not None:
        cfg["llm"]["enabled"] = bool(llm)

    input_dir_env = os.getenv("INPUT_DIR", "input")
    output_dir_env = os.getenv("OUTPUT_DIR", "output/md")
    input_path = Path(input or input_dir_env)
    out_path = Path(out or output_dir_env)
    out_path.mkdir(parents=True, exist_ok=True)

    rprint(f"[bold green]Запуск обработки[/bold green]: input={input_path} out={out_path} llm={cfg['llm'].get('enabled', False)}")
    stats = process_directory(input_path, out_path, cfg, dry_run=dry_run)
    rprint("[bold]Готово[/bold]", stats)


@app.command("validate")
def cli_validate(out: str = typer.Option("output/md", help="Папка Markdown")):
    out_path = Path(out)
    if not out_path.exists():
        rprint(f"[red]Нет папки[/red]: {out_path}")
        raise typer.Exit(code=1)
    total = 0
    missing_front = 0
    for md_path in out_path.rglob("*.md"):
        total += 1
        with md_path.open("r", encoding="utf-8") as f:
            text = f.read()
        if not text.startswith("---\n"):
            missing_front += 1
    rprint({"total": total, "missing_front_matter": missing_front})


if __name__ == "__main__":
    app()


