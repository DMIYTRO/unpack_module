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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from atomic_rename import atomic_rename_many

CONFLICT_MARKER = ".conflict_pending"

# Глобальные хранилища (живут пока Flask-процесс работает)
run_queues: dict[str, Queue] = {}          # run_id → очередь строк лога
run_processes: dict[str, object] = {}      # run_id → subprocess.Popen
conflict_responses: dict[int, Queue] = {}  # conflict_id → Queue('APPROVE'|'REJECT')
_runs_lock = threading.Lock()
_active_run_ids: set[str] = set()


class PipelineRunningError(Exception):
    """Выбрасывается, если пайплайн уже запущен."""
    pass


def is_any_running() -> bool:
    """Проверяет, есть ли активные процессы переименования."""
    with _runs_lock:
        return bool(_active_run_ids)


def start_run(source_dir: str, output_dir: str | None = None, trigger: str = "manual") -> str:
    """Запустить пайплайн в фоновом потоке. Вернуть run_id."""
    import db

    run_id = str(uuid.uuid4())
    with _runs_lock:
        if _active_run_ids:
            raise PipelineRunningError("Пайплайн уже выполняется. Пожалуйста, подождите завершения текущего запуска.")
        _active_run_ids.add(run_id)

    q: Queue = Queue()
    run_queues[run_id] = q
    try:
        db.log_run(run_id, trigger)
        threading.Thread(
            target=_worker,
            args=(run_id, source_dir, output_dir or source_dir),
            daemon=True,
        ).start()
    except Exception:
        run_queues.pop(run_id, None)
        with _runs_lock:
            _active_run_ids.discard(run_id)
        raise

    return run_id


def _worker(run_id: str, source_dir: str, output_dir: str):
    """Фоновый поток: запускает main.py, читает stdout, обрабатывает конфликты."""
    import db

    q = run_queues[run_id]
    env = {**os.environ, "WEB_MODE": "1", "RUN_ID": run_id, "PYTHONUNBUFFERED": "1"}

    protocol_error = False
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(PROJECT_ROOT / "main.py"), source_dir, output_dir],
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
                        data["folder_path"],  # Сохраняем полный путь в БД
                        data["files"],
                        data["suborders"],
                        data["mapping"],
                        data.get("archive_dir"),
                    )
                    folder_path = Path(data["folder_path"])
                    (folder_path / CONFLICT_MARKER).write_text(
                        f"Конфликт #{conflict_id} ожидает решения оператора.\n",
                        encoding="utf-8",
                    )
                    q.put(
                        f"⏸ КОНФЛИКТ #{conflict_id}: {data['folder_name']} — "
                        f"отложен для решения в веб-интерфейсе"
                    )
                except Exception as exc:
                    q.put(f"❌ Ошибка сохранения конфликта: {exc}")
                    protocol_error = True
                continue

            # ── Парсинг переименований для БД ───────────────────────────
            _try_log_rename(run_id, line)

            q.put(line)

        proc.wait()
        status = "done" if proc.returncode == 0 and not protocol_error else "error"

    except Exception as exc:
        status = "error"
        q.put(f"❌ Критическая ошибка запуска: {exc}")

    finally:
        db.finish_run(run_id, status)
        q.put(None)  # Sentinel — SSE-стрим завершён
        run_processes.pop(run_id, None)
        _current_folder.pop(run_id, None)
        with _runs_lock:
            _active_run_ids.discard(run_id)


# Паттерны для парсинга строк из stdout main.py / renamer.py
_RE_LOCAL = re.compile(r"^\[(?:FACE|BACK)\] (.+?)\s+(?:-{3}>|→)\s+(.+)$")
_RE_SITE  = re.compile(r"^\s+\[SITE\] (.+?)\s+(?:-{3}>|→)\s+(.+)$")
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

def _safe_relative_path(value: str) -> Path:
    """Проверяет, что путь остаётся внутри папки заказа."""
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("Недопустимый путь к файлу")
    return path


def build_manual_mapping(conflict_id: int, sources: list[str], new_names: list[str]) -> list[list[str]]:
    """Проверяет ручные имена и строит безопасную карту переименования."""
    import db

    conflict = db.get_conflict(conflict_id)
    if not conflict or conflict["status"] != "pending":
        raise ValueError("Конфликт уже обработан или не найден")
    if len(sources) != len(new_names):
        raise ValueError("Не удалось прочитать все строки переименования")

    allowed_sources = set(json.loads(conflict["files_json"]))
    if set(sources) != allowed_sources or len(set(sources)) != len(sources):
        raise ValueError("Список файлов был изменён. Обновите страницу и повторите попытку")

    root = Path(conflict["folder_name"]).resolve()
    destinations = set()
    mapping = []
    for source_text, new_name in zip(sources, new_names):
        source_rel = _safe_relative_path(source_text)
        clean_name = new_name.strip()
        if not clean_name or Path(clean_name).name != clean_name or clean_name in {".", ".."}:
            raise ValueError(f"Для файла {source_text} укажите только новое имя файла, без пути")

        source = (root / source_rel).resolve()
        if root not in source.parents or not source.is_file():
            raise ValueError(f"Исходный файл не найден: {source_text}")
        destination = source.with_name(clean_name)
        if destination in destinations:
            raise ValueError(f"Два файла получают одно имя: {clean_name}")
        if destination.exists() and destination != source:
            raise ValueError(f"Файл с именем {clean_name} уже существует рядом с {source_text}")
        destinations.add(destination)
        mapping.append([str(source_rel), "manual", str(destination.relative_to(root))])

    return mapping


def resolve_conflict(conflict_id: int, action: str, mapping: list[list[str]] | None = None):
    """Вызывается Flask-роутом когда оператор нажимает кнопку."""
    import db
    import shutil
    from datetime import datetime
    from pathlib import Path

    conflict = db.get_conflict(conflict_id)
    if not conflict or conflict["status"] != "pending":
        return

    folder_path = Path(conflict["folder_name"])
    conflict_marker = folder_path / CONFLICT_MARKER
    run_id = conflict["run_id"]

    if action == "approve":
        mapping = mapping if mapping is not None else json.loads(conflict["mapping_json"])
        operations = []
        for orig_name, sub_id, new_name in mapping:
            source_rel = _safe_relative_path(orig_name)
            destination_rel = _safe_relative_path(new_name)
            operations.append((folder_path / source_rel, folder_path / destination_rel))

        # Проверка всех исходников и назначений происходит до первого изменения.
        atomic_rename_many(operations)
        for orig_name, sub_id, new_name in mapping:
            db.log_rename(run_id, folder_path.name, orig_name, new_name, "site")
            with open(str(PROJECT_ROOT / "rename_log.txt"), "a", encoding="utf-8") as log_file:
                log_file.write(f"[{folder_path.name}] {orig_name} -> {new_name}\n")
                
        # Помечаем папку как обработанную
        done_marker = folder_path / ".done"
        done_marker.write_text(
            f"Обработано оператором через веб-интерфейс: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            encoding="utf-8",
        )
        conflict_marker.unlink(missing_ok=True)
        
        # Переносим соответствующий архив в _DONE_
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from main import move_archive_to_done
            archive_dir = conflict.get("archive_dir") or str(folder_path.parent)
            move_archive_to_done(folder_path, Path(archive_dir))
        except Exception as e:
            print(f"Ошибка при переносе архива в resolve_conflict: {e}")
    elif action == "reject":
        # Переносим в ручную проверку
        dest_dir = folder_path.parent / "_REQUIRES_MANUAL_CHECK_"
        dest_dir.mkdir(exist_ok=True)
        dest_folder = dest_dir / folder_path.name
        if dest_folder.exists():
            dest_folder = dest_dir / (folder_path.name + "_" + datetime.now().strftime("%H%M%S"))
        
        conflict_marker.unlink(missing_ok=True)
        if folder_path.exists():
            shutil.move(str(folder_path), str(dest_folder))
            
        reason_file = dest_folder / "_PROBLEM.txt"
        reason_file.write_text(
            f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Папка: {folder_path.name}\n"
            f"Причина: Отклонено оператором в веб-интерфейсе\n",
            encoding="utf-8",
        )
        
        with open(str(PROJECT_ROOT / "rename_log.txt"), "a", encoding="utf-8") as log_file:
            log_file.write(f"[ALERT] [{folder_path.name}] -> _REQUIRES_MANUAL_CHECK_/ | Отклонено оператором\n")

    db.resolve_conflict(conflict_id, action)
