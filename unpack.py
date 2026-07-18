import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

# Папка для битых архивов
TROUBLES_DIR = "_TROUBLES_"

def unpack_archives(target_dir):
    """
    Разархивирует все .rar файлы в указанной директории.
    Для каждого архива создает папку с именем архива (без .rar)
    и извлекает в нее все файлы.
    Битые или недоступные архивы перемещаются в _TROUBLES_/.
    """
    target_path = Path(target_dir).resolve()
    if not target_path.exists():
        print(f"Директория {target_dir} не найдена.")
        return

    # Находим все .rar файлы в директории
    rar_files = list(target_path.glob('*.rar'))

    if not rar_files:
        print(f"В директории {target_dir} не найдено .rar файлов.")
        return

    print(f"Найдено архивов для распаковки: {len(rar_files)}")

    for rar_file in rar_files:
        # Имя папки будет совпадать с именем архива без расширения
        folder_name = rar_file.stem
        extract_dir = target_path / folder_name

        # Создаем папку
        extract_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nРаспаковка {rar_file.name}")
        print(f"В папку -> {extract_dir.name}/")

        error_reason = None

        try:
            result = subprocess.run(
                ['unar', '-f', '-D', '-o', str(extract_dir), str(rar_file)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print(f"Успешно распаковано.")

        except subprocess.CalledProcessError as e:
            error_msg = (
                e.stderr.decode('utf-8', errors='ignore').strip()
                or e.stdout.decode('utf-8', errors='ignore').strip()
                or f"unar вернул код ошибки {e.returncode}"
            )
            error_reason = f"Ошибка распаковки: {error_msg}"
            print(f"❌ {error_reason}")

        except FileNotFoundError:
            print("❌ Ошибка: утилита 'unar' не найдена. Установите: brew install unar")
            break

        except Exception as e:
            error_reason = f"Неожиданная ошибка: {e}"
            print(f"❌ {error_reason}")

        # Если была ошибка — перемещаем архив (и пустую папку) в _TROUBLES_
        if error_reason:
            troubles_dir = target_path / TROUBLES_DIR
            troubles_dir.mkdir(exist_ok=True)

            # Перемещаем сам архив
            dest_rar = troubles_dir / rar_file.name
            shutil.move(str(rar_file), str(dest_rar))

            # Удаляем пустую папку, если она образовалась
            if extract_dir.exists() and not any(extract_dir.iterdir()):
                extract_dir.rmdir()

            # Создаём файл с описанием проблемы рядом с архивом
            problem_file = troubles_dir / (rar_file.stem + "_PROBLEM.txt")
            problem_file.write_text(
                f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Архив: {rar_file.name}\n"
                f"Причина: {error_reason}\n",
                encoding="utf-8",
            )
            print(f"    📁 Архив перемещён в {TROUBLES_DIR}/")

if __name__ == "__main__":
    # В качестве примера берем тестовую папку
    target_directory = "test_archives"
    unpack_archives(target_directory)

