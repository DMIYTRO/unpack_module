"""
app.py — Flask веб-интерфейс для unpack_module
Запуск: source ../.venv/bin/activate && python app.py
"""
import sys
import os
import json
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect,
    url_for, Response, jsonify, flash,
)

# Добавляем корень проекта в путь чтобы импортировать db, pipeline_runner
sys.path.insert(0, str(Path(__file__).parent))

import db
import pipeline_runner
import scheduler as sched

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Фильтр для парсинга JSON прямо в Jinja2-шаблонах
app.jinja_env.filters["from_json"] = json.loads

PROJECT_ROOT = Path(__file__).parent.parent


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
    is_running = pipeline_runner.is_any_running()
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_runs=recent_runs,
        pending_conflicts=pending,
        active_run_id=run_id,
        is_running=is_running,
    )


@app.route("/run", methods=["POST"])
def run_pipeline():
    target_dir = request.form.get("target_dir", "original_archives").strip()
    try:
        run_id = pipeline_runner.start_run(target_dir, trigger="manual")
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
    return render_template("conflict_detail.html", conflict=conflict)


@app.route("/conflicts/<int:conflict_id>/approve", methods=["POST"])
def approve_conflict(conflict_id):
    pipeline_runner.resolve_conflict(conflict_id, "approve")
    return redirect(url_for("conflicts"))


@app.route("/conflicts/<int:conflict_id>/reject", methods=["POST"])
def reject_conflict(conflict_id):
    pipeline_runner.resolve_conflict(conflict_id, "reject")
    return redirect(url_for("conflicts"))


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
    db.save_schedule(cron_expr, enabled, target_dir)
    sched.update_schedule(cron_expr, enabled, target_dir)
    return redirect(url_for("schedule"))


# ── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_stats())


# ── Запуск ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    # Восстановить расписание из БД при старте
    config = db.get_schedule()
    if config.get("enabled"):
        sched.update_schedule(
            config["cron_expression"],
            True,
            config["target_dir"],
        )
    app.run(debug=False, port=5050, threaded=True, use_reloader=False)
