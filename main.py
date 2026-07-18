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

# Маркер успешной обработки папки
DONE_MARKER = ".done"
# Папка для проблемных заказов
MANUAL_CHECK_DIR = "_REQUIRES_MANUAL_CHECK_"


def is_already_done(folder: Path) -> bool:
    """Проверяет, была ли папка уже успешно обработана ранее."""
    return (folder / DONE_MARKER).exists()


def mark_as_done(folder: Path):
    """Создаёт маркер-файл, чтобы не обрабатывать папку повторно."""
    (folder / DONE_MARKER).write_text(
        f"Обработано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        encoding="utf-8",
    )


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


def process_archives(target_dir: str):
    print("=== ЭТАП 1: Распаковка архивов ===")
    unpack_archives(target_dir)

    target_path = Path(target_dir).resolve()

    print("\n=== ЭТАП 2: Проверка и Переименование ===")
    for folder in sorted(target_path.iterdir()):
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
        status = validate_folder(str(folder))

        if status == "good":
            print(f"\n[+] Папка прошла проверку (Локальный режим): {folder.name}")
            rename_files_in_folder(str(folder))
            mark_as_done(folder)

        else:
            print(f"\n[-] Папка требует проверки на сайте (Сложный режим): {folder.name}")
            print(f"    Причина: {status}")

            info = parse_filename(folder.name)
            order_number = info.get("order_number")

            if order_number:
                print(f"    -> Запуск Playwright для заказа № {order_number} ...")
                try:
                    from website_parser import fetch_suborders
                    suborders = fetch_suborders(order_number)

                    files = [f for f in folder.iterdir() if f.is_file() and not f.name.startswith(".")]

                    # ✅ ИСПРАВЛЕНИЕ 3: При несовпадении — перемещаем в MANUAL_CHECK
                    if len(suborders) != len(files):
                        reason = (
                            f"Файлов в архиве: {len(files)}, "
                            f"подзаказов на сайте: {len(suborders)}"
                        )
                        print(f"    🚨 [АЛЕРТ] {reason}")
                        move_to_manual_check(folder, reason, target_path)
                        continue

                    # ✅ ИСПРАВЛЕНИЕ 2: Показываем предпросмотр привязки ДО переименования
                    def sort_key(x):
                        m = re.search(r"\d+", x.name)
                        return int(m.group()) if m else x.name

                    files_sorted = sorted(files, key=sort_key)

                    print("\n    ┌─ ПРЕДПРОСМОТР ПРИВЯЗКИ (проверьте!) ───────────────────")
                    for i, file_obj in enumerate(files_sorted):
                        sub_id = suborders[i]
                        base_name = folder.name.replace(order_number, sub_id)
                        if re.search(r"([_-]?)\d*-?(face|back)", base_name, flags=re.IGNORECASE):
                            new_name = re.sub(
                                r"([_-]?)\d*-?(face|back)",
                                rf"\g<1>{i+1}-\g<2>",
                                base_name,
                                flags=re.IGNORECASE,
                            ) + file_obj.suffix
                        else:
                            new_name = f"{base_name}_{i+1}{file_obj.suffix}"
                        print(f"    │  {i+1}. {file_obj.name:30s}  ->  {new_name}")
                    print("    └────────────────────────────────────────────────────────")

                    # Запрашиваем подтверждение (терминал или веб)
                    if WEB_MODE:
                        conflict_data = {
                            "folder": folder.name,
                            "files":  [f.name for f in files_sorted],
                            "suborders": suborders,
                            "mapping": [[f.name, suborders[i]] for i, f in enumerate(files_sorted)],
                        }
                        print(f"CONFLICT_DATA:{json.dumps(conflict_data)}", flush=True)
                        response = sys.stdin.readline().strip()  # APPROVE или REJECT
                        answer = "y" if response == "APPROVE" else "n"
                    else:
                        answer = input("\n    Всё верно? Переименовать? [y/n]: ").strip().lower()

                    if answer != "y":
                        reason = "Оператор отклонил привязку файлов"
                        print(f"    ⏭ Пропуск. Папка перемещена на ручную проверку.")
                        move_to_manual_check(folder, reason, target_path)
                        continue

                    # Переименовываем после подтверждения
                    print("    -> Переименовываем...")
                    for i, file_obj in enumerate(files_sorted):
                        sub_id = suborders[i]
                        base_name = folder.name.replace(order_number, sub_id)
                        if re.search(r"([_-]?)\d*-?(face|back)", base_name, flags=re.IGNORECASE):
                            new_name = re.sub(
                                r"([_-]?)\d*-?(face|back)",
                                rf"\g<1>{i+1}-\g<2>",
                                base_name,
                                flags=re.IGNORECASE,
                            ) + file_obj.suffix
                        else:
                            new_name = f"{base_name}_{i+1}{file_obj.suffix}"

                        new_path = folder / new_name
                        print(f"    [SITE] {file_obj.name}  --->  {new_name}")
                        os.rename(str(file_obj), str(new_path))

                        with open("rename_log.txt", "a", encoding="utf-8") as log_file:
                            log_file.write(f"[{folder.name}] {file_obj.name} -> {new_name}\n")

                    mark_as_done(folder)

                except Exception as e:
                    print(f"    ❌ [ОШИБКА] Сбой при работе с сайтом: {e}")


if __name__ == "__main__":
    # Очищаем лог-файл перед новым запуском
    with open("rename_log.txt", "w", encoding="utf-8") as f:
        f.write(f"=== ЛОГ ПЕРЕИМЕНОВАНИЙ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===\n")

    # Папка для всех архивов (может быть передана как аргумент командной строки)
    target_directory = sys.argv[1] if len(sys.argv) > 1 else "original_archives"
    process_archives(target_directory)
