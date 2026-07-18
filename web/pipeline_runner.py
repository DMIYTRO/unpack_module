"""
pipeline_runner.py
Запускает main.py как подпроцесс, транслирует stdout через SSE,
обрабатывает конфликты через stdin/stdout протокол.
"""
import os
import sys
import re
import json
import uuid
import threading
import subprocess
from queue import Queue, Empty
from pathlib import Path

# PROJECT_ROOT — корень unpack_module (родитель папки web/)
PROJECT_ROOT = Path(__file__).parent.parent

# Глобальные хранилища (живут пока Flask-процесс работает)
run_queues: dict[str, Queue] = {}          # run_id → очередь строк лога
run_processes: dict[str, object] = {}      # run_id → subprocess.Popen
conflict_responses: dict[int, Queue] = {}  # conflict_id → Queue('APPROVE'|'REJECT')


def start_run(target_dir: str, trigger: str = "manual") -> str:
    """Запустить пайплайн в фоновом потоке. Вернуть run_id."""
    import db

    run_id = str(uuid.uuid4())
    q: Queue = Queue()
    run_queues[run_id] = q
    db.log_run(run_id, trigger)

    threading.Thread(
        target=_worker,
        args=(run_id, target_dir),
        daemon=True,
    ).start()

    return run_id


def _worker(run_id: str, target_dir: str):
    """Фоновый поток: запускает main.py, читает stdout, обрабатывает конфликты."""
    import db

    q = run_queues[run_id]
    env = {**os.environ, "WEB_MODE": "1", "RUN_ID": run_id}

    try:
        proc = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "main.py"), target_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        run_processes[run_id] = proc

        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")

            # ── Конфликт: main.py выслал данные ─────────────────────────
            if line.startswith("CONFLICT_DATA:"):
                try:
                    data = json.loads(line[14:])
                    conflict_id = db.save_conflict(
                        run_id,
                        data["folder"],
                        data["files"],
                        data["suborders"],
                        data["mapping"],
                    )
                    q.put(
                        f"⏸ КОНФЛИКТ #{conflict_id}: {data['folder']} — "
                        f"ожидает решения оператора"
                    )
                    resp_q: Queue = Queue()
                    conflict_responses[conflict_id] = resp_q
                    # Блокируем поток до ответа оператора (макс. 1 час)
                    response = resp_q.get(timeout=3600)
                    proc.stdin.write(f"{response}\n")
                    proc.stdin.flush()
                    q.put(f"→ Конфликт #{conflict_id}: {response}")
                except Exception as exc:
                    q.put(f"❌ Ошибка обработки конфликта: {exc}")
                    proc.stdin.write("REJECT\n")
                    proc.stdin.flush()
                continue

            # ── Парсинг переименований для БД ───────────────────────────
            _try_log_rename(run_id, line)

            q.put(line)

        proc.wait()
        status = "done" if proc.returncode == 0 else "error"

    except Exception as exc:
        status = "error"
        q.put(f"❌ Критическая ошибка запуска: {exc}")

    finally:
        db.finish_run(run_id, status)
        q.put(None)  # Sentinel — SSE-стрим завершён
        run_processes.pop(run_id, None)


# Паттерны для парсинга строк из stdout main.py / renamer.py
_RE_LOCAL = re.compile(r"^\[(?:FACE|BACK)\] (.+?)\s+-{3}>\s+(.+)$")
_RE_SITE  = re.compile(r"^\s+\[SITE\] (.+?)\s+-{3}>\s+(.+)$")
_RE_FOLDER= re.compile(r"^---\s+Переименование в папке:\s+(.+?)\s+---$")
_current_folder: dict[str, str] = {}  # run_id → текущая папка


def _try_log_rename(run_id: str, line: str):
    import db

    m_folder = _RE_FOLDER.match(line)
    if m_folder:
        _current_folder[run_id] = m_folder.group(1)
        return

    folder = _current_folder.get(run_id, "")

    m = _RE_LOCAL.match(line)
    if m:
        db.log_rename(run_id, folder, m.group(1).strip(), m.group(2).strip(), "local")
        return

    m = _RE_SITE.match(line)
    if m:
        db.log_rename(run_id, folder, m.group(1).strip(), m.group(2).strip(), "site")


# ── SSE streaming ────────────────────────────────────────────────────────────

def stream_run(run_id: str):
    """Генератор для Flask SSE-ответа."""
    q = run_queues.get(run_id)
    if not q:
        yield "data: [ERROR] Запуск не найден\n\n"
        return

    while True:
        try:
            line = q.get(timeout=25)
            if line is None:
                yield "data: [DONE]\n\n"
                break
            # Экранируем переносы строк (SSE не поддерживает многострочные data)
            safe = line.replace("\n", " ").replace("\r", "")
            yield f"data: {safe}\n\n"
        except Empty:
            yield "data: [PING]\n\n"


# ── Conflict resolution ──────────────────────────────────────────────────────

def resolve_conflict(conflict_id: int, action: str):
    """Вызывается Flask-роутом когда оператор нажимает кнопку."""
    import db

    db.resolve_conflict(conflict_id, action)
    resp_q = conflict_responses.get(conflict_id)
    if resp_q:
        resp_q.put("APPROVE" if action == "approve" else "REJECT")
        conflict_responses.pop(conflict_id, None)
