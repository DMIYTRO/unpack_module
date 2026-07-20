import os
import re
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# WEB_MODE=1 — запущен из Flask, конфликты через stdout/stdin
WEB_MODE = os.environ.get("WEB_MODE") == "1"

# Импортируем наши готовые модули
from unpack import unpack_archives
from validator import validate_folder
from renamer import rename_files_in_folder
from filename_parser import parse_filename
from file_discovery import list_layout_files
from atomic_rename import atomic_rename_many

# Маркер успешной обработки папки
DONE_MARKER = ".done"
# Папка для проблемных заказов
MANUAL_CHECK_DIR = "_REQUIRES_MANUAL_CHECK_"


def _network_mount_root(path: Path) -> Path | None:
    """Return the mount root for the network locations used in production."""
    if not path.is_absolute():
        return None

    parts = path.parts
    if len(parts) >= 3 and parts[1] in {"mnt", "Volumes"}:
        return Path(parts[0]) / parts[1] / parts[2]
    return None


def ensure_pipeline_directory(path: Path, label: str) -> bool:
    """Create a pipeline directory without masking an unavailable NAS mount."""
    mount_root = _network_mount_root(path)
    if mount_root is not None and not os.path.ismount(mount_root):
        print(f"❌ Сетевой ресурс недоступен: {mount_root} не примонтирован.")
        print(f"   Не удалось подготовить {label.lower()}: {path}")
        print("   Проверьте подключение NAS/QNAP и повторите запуск.")
        return False

    existed = path.exists()
    try:
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            print(f"❌ {label} не является каталогом: {path}")
            return False
        # Проверяем доступ к каталогу сейчас, а не только наличие записи пути.
        next(path.iterdir(), None)
    except OSError as exc:
        print(f"❌ {label} недоступен: {path}")
        print(f"   Сетевая папка не подключена или нет доступа: {exc}")
        return False

    if not existed:
        print(f"📁 {label} не найден — создан: {path}")
    return True


def files_per_suborder(folder_name: str) -> int:
    """Сколько файлов должен содержать один подзаказ по его сторонности."""
    sides = parse_filename(folder_name).get("sides")
    if not sides:
        return 1
    _, back_side = sides.split("-", maxsplit=1)
    return 2 if int(back_side) > 0 else 1


def _site_name_for_side(base_name: str, side: str) -> str:
    """Создаёт имя face/back, сохраняя номер макета из имени папки."""
    pattern = r"([_-]?)(\d*)-?(face|back)"

    def replace_side(match):
        prefix, number = match.group(1), match.group(2)
        if number:
            return f"{prefix}{number}-{side}"
        return f"{prefix}{side}"

    if re.search(pattern, base_name, flags=re.IGNORECASE):
        return re.sub(pattern, replace_side, base_name, flags=re.IGNORECASE)
    return f"{base_name}-{side}"


def build_site_mapping(folder: Path, files_sorted: list[Path], suborders: list[str]) -> tuple[list[tuple[Path, str, str]], int]:
    """Строит привязку файлов к подзаказам с учётом одно-/двусторонности."""
    per_suborder = files_per_suborder(folder.name)
    mapping = []
    for order_index, sub_id in enumerate(suborders):
        batch_start = order_index * per_suborder
        batch = files_sorted[batch_start:batch_start + per_suborder]
        if len(batch) != per_suborder:
            break

        base_name = folder.name.replace(parse_filename(folder.name).get("order_number") or "", sub_id)
        for side_index, file_obj in enumerate(batch):
            if per_suborder == 2:
                side = "face" if side_index == 0 else "back"
                new_name = _site_name_for_side(base_name, side) + file_obj.suffix
            else:
                new_name = f"{base_name}_{order_index + 1}{file_obj.suffix}"
            mapping.append((file_obj, sub_id, new_name))
    return mapping, per_suborder


def move_archive_to_done(folder: Path, archive_dir: Path | None = None):
    """Переносит исходный .rar или .zip архив из входящей папки в _DONE_."""
    base_dir = (archive_dir or folder.parent).resolve()
    done_dir = base_dir / "_DONE_"
    
    archive_path = next(
        (base_dir / f"{folder.name}{suffix}" for suffix in (".rar", ".zip") if (base_dir / f"{folder.name}{suffix}").exists()),
        None,
    )

    if archive_path:
        done_dir.mkdir(exist_ok=True)
        dest_path = done_dir / archive_path.name
        if dest_path.exists():
            dest_path = done_dir / (folder.name + "_" + datetime.now().strftime("%H%M%S") + archive_path.suffix)
        try:
            shutil.move(str(archive_path), str(dest_path))
            print(f"    📦 Исходный архив {archive_path.name} перемещен в _DONE_/")
        except Exception as e:
            print(f"    ⚠️ Не удалось переместить архив {archive_path.name}: {e}")


def is_already_done(folder: Path) -> bool:
    """Проверяет, была ли папка уже успешно обработана ранее."""
    return (folder / DONE_MARKER).exists()


def mark_as_done(folder: Path, archive_dir: Path | None = None):
    """Создаёт маркер-файл, чтобы не обрабатывать папку повторно, и переносит архив в _DONE_."""
    (folder / DONE_MARKER).write_text(
        f"Обработано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        encoding="utf-8",
    )
    move_archive_to_done(folder, archive_dir)


def move_to_manual_check(folder: Path, reason: str, base_dir: Path):
    """
    Перемещает проблемную папку в _REQUIRES_MANUAL_CHECK_,
    записывая туда причину проблемы.
    """
    dest_dir = base_dir / MANUAL_CHECK_DIR
    dest_dir.mkdir(exist_ok=True)

    dest_folder = dest_dir / folder.name
    # Если папка с таким именем уже есть — добавляем суффикс
    if dest_folder.exists():
        dest_folder = dest_dir / (folder.name + "_" + datetime.now().strftime("%H%M%S"))

    shutil.move(str(folder), str(dest_folder))

    # Записываем причину в файл внутри перемещённой папки
    reason_file = dest_folder / "_PROBLEM.txt"
    reason_file.write_text(
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Папка: {folder.name}\n"
        f"Причина: {reason}\n",
        encoding="utf-8",
    )
    print(f"    📁 Папка перемещена в {MANUAL_CHECK_DIR}/")

    with open("rename_log.txt", "a", encoding="utf-8") as log_file:
        log_file.write(f"[ALERT] [{folder.name}] -> {MANUAL_CHECK_DIR}/ | {reason}\n")


def process_archives(source_dir: str, output_dir: str | None = None):
    source_path = Path(source_dir).resolve()
    target_path = Path(output_dir or source_dir).resolve()

    if not ensure_pipeline_directory(source_path, "Входной каталог"):
        return False
    if target_path != source_path and not ensure_pipeline_directory(target_path, "Выходной каталог"):
        return False

    print("=== ЭТАП 1: Распаковка архивов ===")
    print(f"Источник архивов: {source_path}")
    print(f"Папка обработки:  {target_path}")
    try:
        unpack_archives(str(source_path), str(target_path))
        if not source_path.is_dir() or not target_path.is_dir():
            print("❌ Сетевой ресурс стал недоступен во время распаковки.")
            print("   Проверьте подключение NAS/QNAP и повторите запуск.")
            return False
    except OSError as exc:
        print(f"❌ Ошибка доступа к сетевому ресурсу: {exc}")
        print("   Проверьте, что входной и выходной каталоги примонтированы.")
        return False

    print("\n=== ЭТАП 2: Проверка и Переименование ===")
    failures = []
    try:
        folders = sorted(target_path.iterdir())
    except OSError as exc:
        print(f"❌ Не удалось прочитать выходной каталог {target_path}: {exc}")
        print("   Сетевой ресурс недоступен или каталог не примонтирован.")
        return False

    for folder in folders:
        # Игнорируем файлы и служебные папки
        if not folder.is_dir():
            continue
        if folder.name.startswith("_"):
            continue

        # ✅ ИСПРАВЛЕНИЕ 1: Пропускаем уже обработанные папки
        if is_already_done(folder):
            print(f"\n[✓] Уже обработано, пропуск: {folder.name}")
            continue

        # Валидируем папку
        print(f"\n{'='*60}")
        print(f"📦 ОБРАБОТКА ПАПКИ: {folder.name}")
        print(f"{'='*60}")
        
        status = validate_folder(str(folder))
        requires_operator = "ambiguous" in status.lower()

        if status == "good":
            print(f"\n[+] Папка прошла проверку (Локальный режим): {folder.name}")
            rename_files_in_folder(str(folder))
            mark_as_done(folder, source_path)

        else:
            print(f"\n[-] Папка требует проверки на сайте (Сложный режим): {folder.name}")
            print(f"    Причина: {status}")

            info = parse_filename(folder.name)
            order_number = info.get("order_number")

            if order_number:
                print(f"    -> Запрос API для заказа № {order_number} ...")
                try:
                    from website_parser import fetch_suborders
                    suborders = fetch_suborders(order_number)

                    # Ищем макеты во всей структуре распакованного заказа.
                    files = list_layout_files(folder)

                    def sort_key(x):
                        m = re.search(r"\d+", x.name)
                        return (0, int(m.group()), x.name.casefold()) if m else (1, 0, x.name.casefold())

                    files_sorted = sorted(files, key=sort_key)
                    # Для 4-4, 5-5 и т.п. два файла образуют один подзаказ:
                    # первый — лицо, второй — оборот.
                    mapping_full, files_per_order = build_site_mapping(folder, files_sorted, suborders)
                    expected_file_count = len(suborders) * files_per_order

                    max_name_len = max((len(item[0].name) for item in mapping_full), default=30)
                    max_name_len = min(max(max_name_len, 30), 60) # ширина от 30 до 60 символов

                    print("\n    ┌─ ПРЕДПРОСМОТР ПРИВЯЗКИ ────────────────────────────────")
                    for i, (file_obj, sub_id, new_name) in enumerate(mapping_full):
                        display_name = file_obj.name
                        if len(display_name) > max_name_len:
                            display_name = display_name[:max_name_len-3] + "..."
                        print(f"    │  {i+1:2d}. {display_name:<{max_name_len}}  →  {new_name}")
                        
                    if expected_file_count != len(files):
                        print(
                            f"    │  🚨 ВНИМАНИЕ: Файлов {len(files)}, ожидается {expected_file_count} "
                            f"({len(suborders)} подзаказов × {files_per_order} сторон)!"
                        )
                    print("    └────────────────────────────────────────────────────────")

                    if expected_file_count == len(files) and not requires_operator:
                        # Полное совпадение — переименовываем сразу без вопросов
                        print("    -> Переименовываем...")
                        operations = [(file_obj, file_obj.with_name(new_name)) for file_obj, _, new_name in mapping_full]
                        atomic_rename_many(operations)
                        log_entries = []
                        for file_obj, sub_id, new_name in mapping_full:
                            new_path = file_obj.with_name(new_name)
                            display_name = str(file_obj.relative_to(folder))
                            if len(display_name) > max_name_len:
                                display_name = display_name[:max_name_len-3] + "..."
                            print(f"    [SITE] {display_name:<{max_name_len}}  →  {new_name}")
                            log_entries.append(
                                f"[{folder.name}] {file_obj.relative_to(folder)} -> "
                                f"{new_path.relative_to(folder)}\n"
                            )
                        with open("rename_log.txt", "a", encoding="utf-8") as log_file:
                            log_file.writelines(log_entries)
                        mark_as_done(folder, source_path)
                    else:
                        # Несовпадение или неоднозначные стороны — решает оператор.
                        if WEB_MODE:
                            conflict_data = {
                                "folder_path": str(folder.resolve()),
                                "folder_name": folder.name,
                                "archive_dir": str(source_path),
                                "files": [str(f.relative_to(folder)) for f in files_sorted],
                                "suborders": suborders,
                                "mapping": [
                                    [
                                        str(f.relative_to(folder)),
                                        sub_id,
                                        str(f.relative_to(folder).with_name(new_n)),
                                    ]
                                    for f, sub_id, new_n in mapping_full
                                ],
                            }
                            print(f"CONFLICT_DATA:{json.dumps(conflict_data)}", flush=True)
                            print(f"    ⏸ Конфликт сохранен в веб-интерфейсе. Папка отложена.")
                            continue
                        else:
                            # Консольный режим
                            prompt_reason = (
                                "Стороны макетов определены неоднозначно"
                                if requires_operator
                                else "Количество файлов не совпадает"
                            )
                            answer = input(
                                f"\n    {prompt_reason}! Всё равно переименовать сопоставленные? [y/n]: "
                            ).strip().lower()
                            if answer == "y":
                                print("    -> Переименовываем...")
                                operations = [(file_obj, file_obj.with_name(new_name)) for file_obj, _, new_name in mapping_full]
                                atomic_rename_many(operations)
                                log_entries = []
                                for file_obj, sub_id, new_name in mapping_full:
                                    new_path = file_obj.with_name(new_name)
                                    display_name = str(file_obj.relative_to(folder))
                                    if len(display_name) > max_name_len:
                                        display_name = display_name[:max_name_len-3] + "..."
                                    print(f"    [SITE] {display_name:<{max_name_len}}  →  {new_name}")
                                    log_entries.append(
                                        f"[{folder.name}] {file_obj.relative_to(folder)} -> "
                                        f"{new_path.relative_to(folder)}\n"
                                    )
                                with open("rename_log.txt", "a", encoding="utf-8") as log_file:
                                    log_file.writelines(log_entries)
                                mark_as_done(folder, source_path)
                            else:
                                reason = (
                                    f"Отклонено оператором (файлов: {len(files)}, ожидалось: "
                                    f"{expected_file_count})"
                                )
                                print(f"    ⏭ Пропуск. Папка перемещена на ручную проверку.")
                                move_to_manual_check(folder, reason, target_path)
                                continue

                except Exception as e:
                    print(f"    ❌ [ОШИБКА] Сбой при работе с сайтом: {e}")
                    failures.append(f"{folder.name}: {e}")
            else:
                reason = f"В имени папки нет номера заказа ({status})"
                print(f"    ❌ {reason}")
                failures.append(f"{folder.name}: {reason}")

    if failures:
        raise RuntimeError("Не обработаны заказы: " + "; ".join(failures))
    return True


if __name__ == "__main__":
    # Очищаем лог-файл перед новым запуском
    with open("rename_log.txt", "w", encoding="utf-8") as f:
        f.write(f"=== ЛОГ ПЕРЕИМЕНОВАНИЙ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===\n")

    # Папка для всех архивов (может быть передана как аргумент командной строки)
    source_directory = sys.argv[1] if len(sys.argv) > 1 else "original_archives"
    output_directory = sys.argv[2] if len(sys.argv) > 2 else source_directory
    if not process_archives(source_directory, output_directory):
        # Понятное сообщение уже выведено выше; завершаемся без traceback,
        # но с ненулевым кодом, чтобы веб-интерфейс отметил запуск как ошибку.
        sys.exit(2)
