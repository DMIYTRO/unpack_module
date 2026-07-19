"""
app.py — Flask веб-интерфейс для unpack_module
Запуск: source ../.venv/bin/activate && python app.py
"""
import sys
import os
import json
import hashlib
import subprocess
import tempfile
import shutil
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect,
    url_for, Response, jsonify, flash, send_file, abort,
)

# Добавляем корень проекта в путь чтобы импортировать db, pipeline_runner
sys.path.insert(0, str(Path(__file__).parent))

import db
import pipeline_runner
import scheduler as sched
import runtime

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Фильтр для парсинга JSON прямо в Jinja2-шаблонах
app.jinja_env.filters["from_json"] = json.loads
app.jinja_env.filters["basename"] = os.path.basename

PROJECT_ROOT = Path(__file__).parent.parent
PREVIEW_CACHE_DIR = Path(tempfile.gettempdir()) / "unpack_module_previews"


def _create_bitmap_preview(source: Path, preview: Path):
    """Create a PNG preview with Linux tools first, then macOS fallbacks."""
    imagemagick = shutil.which("magick") or shutil.which("convert")
    if imagemagick:
        command = [imagemagick]
        if Path(imagemagick).name == "magick":
            command.append("convert")
        command.extend([
            f"{source}[0]",
            "-thumbnail",
            "1600x1600>",
            str(preview),
        ])
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            return
        except subprocess.SubprocessError:
            preview.unlink(missing_ok=True)

    try:
        subprocess.run(
            ["sips", "--setProperty", "format", "png", str(source), "--out", str(preview)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return
    except (FileNotFoundError, subprocess.SubprocessError):
        preview.unlink(missing_ok=True)

    quicklook_dir = PREVIEW_CACHE_DIR / f"quicklook_{preview.stem}"
    try:
        quicklook_dir.mkdir(exist_ok=True)
        subprocess.run(
            ["qlmanage", "-t", "-s", "800", "-o", str(quicklook_dir), str(source)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        generated = next(quicklook_dir.glob("*.png"), None)
        if not generated:
            raise FileNotFoundError("Quick Look did not create a PNG")
        shutil.move(str(generated), str(preview))
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise RuntimeError("No installed preview tool supports this file") from exc
    finally:
        shutil.rmtree(quicklook_dir, ignore_errors=True)


@app.before_request
def setup():
    db.init_db()


# ── Дашборд ─────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    run_id = request.args.get("run_id")
    stats = db.get_stats()
    recent_runs = db.get_recent_runs(6)
    pending = db.get_pending_conflicts()
    config = db.get_schedule()
    manual_paths = db.get_manual_paths()
    is_running = pipeline_runner.is_any_running()
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_runs=recent_runs,
        pending_conflicts=pending,
        active_run_id=run_id,
        is_running=is_running,
        config=config,
        manual_paths=manual_paths,
    )


@app.route("/run", methods=["POST"])
def run_pipeline():
    source_dir = request.form.get("source_dir", "original_archives").strip()
    output_dir = request.form.get("output_dir", "").strip() or source_dir
    db.save_manual_paths(source_dir, output_dir)
    try:
        run_id = pipeline_runner.start_run(source_dir, output_dir, trigger="manual")
        return redirect(url_for("dashboard") + f"?run_id={run_id}")
    except pipeline_runner.PipelineRunningError as e:
        flash(str(e), "error")
        return redirect(url_for("dashboard"))


# ── SSE Стрим ────────────────────────────────────────────────────────────────

@app.route("/stream/<run_id>")
def stream(run_id):
    return Response(
        pipeline_runner.stream_run(run_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── История ──────────────────────────────────────────────────────────────────

@app.route("/history")
def history():
    search = request.args.get("q", "")
    date_from = request.args.get("date_from", "")
    events = db.get_rename_history(limit=500, search=search, date_from=date_from)
    return render_template(
        "history.html", events=events, search=search, date_from=date_from
    )


@app.route("/history/export")
def export_csv():
    events = db.get_rename_history(limit=100_000)

    def generate():
        yield "Дата,Папка,Оригинал,Новое имя,Режим\n"
        for e in events:
            row = f"{e['timestamp']},\"{e['folder_name']}\",\"{e['original']}\",\"{e['new_name']}\",{e['mode']}\n"
            yield row

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=rename_history.csv"},
    )


# ── Конфликты ────────────────────────────────────────────────────────────────

@app.route("/conflicts")
def conflicts():
    pending = db.get_pending_conflicts()
    return render_template("conflicts.html", conflicts=pending)


@app.route("/conflicts/<int:conflict_id>")
def conflict_detail(conflict_id):
    conflict = db.get_conflict(conflict_id)
    if not conflict or conflict["status"] != "pending":
        return redirect(url_for("conflicts"))
    conflict["files"] = json.loads(conflict["files_json"])
    conflict["suborders"] = json.loads(conflict["suborders_json"])
    conflict["mapping"] = json.loads(conflict["mapping_json"])

    # Старые конфликты могли быть сохранены до группировки face/back. Если
    # количество файлов ровно соответствует сторонности, пересобираем только
    # предложение для интерфейса — оператор всё равно подтверждает его вручную.
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from main import build_site_mapping

        folder = Path(conflict["folder_name"])
        rebuilt, per_suborder = build_site_mapping(
            folder,
            [folder / source for source in conflict["files"]],
            conflict["suborders"],
        )
        if len(rebuilt) == len(conflict["files"]) == len(conflict["suborders"]) * per_suborder:
            conflict["mapping"] = [
                [str(source.relative_to(folder)), suborder, new_name]
                for source, suborder, new_name in rebuilt
            ]
    except (ValueError, ImportError):
        pass

    proposed = {item[0]: item[1:] for item in conflict["mapping"]}
    conflict["rows"] = [
        {
            "source": source,
            "suborder": proposed.get(source, [""])[0],
            # Сохраняем подпапку, но оператор редактирует только имя файла.
            "new_name": Path(proposed[source][1]).name if source in proposed else "",
            "is_pdf": source.lower().endswith(".pdf"),
        }
        for source in conflict["files"]
    ]
    return render_template("conflict_detail.html", conflict=conflict)


@app.route("/conflicts/<int:conflict_id>/approve", methods=["POST"])
def approve_conflict(conflict_id):
    sources = request.form.getlist("source")
    names = request.form.getlist("new_name")
    try:
        mapping = pipeline_runner.build_manual_mapping(conflict_id, sources, names)
        pipeline_runner.resolve_conflict(conflict_id, "approve", mapping)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("conflict_detail", conflict_id=conflict_id))
    return redirect(url_for("conflicts"))


@app.route("/conflicts/<int:conflict_id>/reject", methods=["POST"])
def reject_conflict(conflict_id):
    pipeline_runner.resolve_conflict(conflict_id, "reject")
    return redirect(url_for("conflicts"))


@app.route("/conflicts/<int:conflict_id>/preview/<path:relative_path>")
def conflict_preview(conflict_id, relative_path):
    """Безопасно отдаёт оригинал или PNG-превью файла из ожидающего конфликта."""
    conflict = db.get_conflict(conflict_id)
    if not conflict or conflict["status"] != "pending":
        abort(404)

    allowed_files = set(json.loads(conflict["files_json"]))
    if relative_path not in allowed_files:
        abort(404)

    root = Path(conflict["folder_name"]).resolve()
    source = (root / relative_path).resolve()
    if root not in source.parents or not source.is_file():
        abort(404)

    # Современные браузеры показывают эти форматы напрямую.
    if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}:
        return send_file(source, conditional=True)

    # TIFF, Photoshop, Illustrator и CorelDRAW обычно не открываются в браузере.
    # Создаём PNG-копию для просмотра, не изменяя исходный макет.
    if source.suffix.lower() in {".tif", ".tiff", ".psd", ".ai", ".cdr"}:
        PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = f"{source}:{source.stat().st_mtime_ns}:{source.stat().st_size}".encode()
        preview = PREVIEW_CACHE_DIR / f"{hashlib.sha256(stamp).hexdigest()}.png"
        if not preview.exists():
            try:
                _create_bitmap_preview(source, preview)
            except RuntimeError:
                abort(415, "Не удалось создать превью. Для Ubuntu установите ImageMagick/Ghostscript или экспортируйте PDF.")
        return send_file(preview, mimetype="image/png", conditional=True)

    abort(415, "Предпросмотр доступен для PDF, JPG, TIFF, PSD, AI, CDR, PNG, GIF и WebP")


# ── Расписание ───────────────────────────────────────────────────────────────

@app.route("/schedule")
def schedule():
    config = db.get_schedule()
    next_run = sched.get_next_run()
    return render_template("schedule.html", config=config, next_run=next_run)


@app.route("/schedule", methods=["POST"])
def save_schedule():
    cron_expr = request.form.get("cron_expression", "").strip()
    enabled = request.form.get("enabled") == "on"
    target_dir = request.form.get("target_dir", "original_archives").strip()
    output_dir = request.form.get("output_dir", "").strip() or target_dir
    try:
        sched.start_scheduler()
        sched.update_schedule(cron_expr, enabled, target_dir, output_dir)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("schedule"))
    db.save_schedule(cron_expr, enabled, target_dir, output_dir)
    return redirect(url_for("schedule"))


# ── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_stats())


# ── Запуск ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        runtime.start_runtime()
    except ValueError as exc:
        print(f"Расписание отключено: {exc}")
    try:
        app.run(debug=False, port=5050, threaded=True, use_reloader=False)
    finally:
        runtime.shutdown_runtime()
