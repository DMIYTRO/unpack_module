import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

# Папка для битых архивов
TROUBLES_DIR = "_TROUBLES_"


def _find_extractor() -> str | None:
    """
    Определяет доступный инструмент для распаковки RAR.
    Возвращает имя утилиты или None если ничего не найдено.

    Поддерживаемые инструменты (в порядке приоритета):
      - unar   (macOS: brew install unar  /  Linux: apt install unar)
      - unrar  (Linux: apt install unrar)
      - 7z     (Linux: apt install p7zip-full  /  macOS: brew install p7zip)
      - 7za, 7zz (альтернативные имена 7-zip)
    """
    for tool in ("unar", "unrar", "7z", "7za", "7zz"):
        if shutil.which(tool):
            return tool
    return None


def _build_command(tool: str, rar_file: Path, extract_dir: Path) -> list[str]:
    """Формирует команду распаковки для конкретного инструмента."""
    if tool == "unar":
        # -f перезаписывать, -D не создавать вложенную папку
        return ["unar", "-f", "-D", "-o", str(extract_dir), str(rar_file)]

    elif tool == "unrar":
        # x — распаковать с путями; -o+ перезаписать; -y без вопросов
        return ["unrar", "x", "-o+", "-y", str(rar_file), str(extract_dir) + os.sep]

    elif tool in ("7z", "7za", "7zz"):
        # x — распаковать; -aoa перезаписать всё; -y без вопросов
        return [tool, "x", str(rar_file), f"-o{extract_dir}", "-aoa", "-y"]

    raise ValueError(f"Неизвестный инструмент: {tool}")


def unpack_archives(target_dir: str):
    """
    Разархивирует все .rar файлы в указанной директории.
    Кросс-платформенно: работает на macOS и Linux.
    Битые архивы перемещаются в _TROUBLES_/ с файлом _PROBLEM.txt.
    """
    target_path = Path(target_dir).resolve()
    if not target_path.exists():
        print(f"Директория {target_dir} не найдена.")
        return

    # Определяем инструмент один раз для всего запуска
    tool = _find_extractor()
    if not tool:
        print(
            "❌ Не найден ни один инструмент для распаковки RAR.\n"
            "   macOS : brew install unar\n"
            "   Ubuntu: sudo apt install unar\n"
            "   или   : sudo apt install unrar\n"
            "   или   : sudo apt install p7zip-full"
        )
        return

    print(f"Инструмент распаковки: {tool}")

    rar_files = list(target_path.glob("*.rar"))
    if not rar_files:
        print(f"В директории {target_dir} не найдено .rar файлов.")
        return

    print(f"Найдено архивов для распаковки: {len(rar_files)}")

    for rar_file in rar_files:
        folder_name = rar_file.stem
        extract_dir = target_path / folder_name
        extract_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nРаспаковка {rar_file.name}")
        print(f"В папку -> {extract_dir.name}/")

        error_reason = None

        try:
            cmd = _build_command(tool, rar_file, extract_dir)
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("Успешно распаковано.")

        except subprocess.CalledProcessError as e:
            error_msg = (
                e.stderr.decode("utf-8", errors="ignore").strip()
                or e.stdout.decode("utf-8", errors="ignore").strip()
                or f"{tool} вернул код ошибки {e.returncode}"
            )
            error_reason = f"Ошибка распаковки ({tool}): {error_msg}"
            print(f"❌ {error_reason}")

        except Exception as e:
            error_reason = f"Неожиданная ошибка: {e}"
            print(f"❌ {error_reason}")

        # При ошибке — переносим в _TROUBLES_
        if error_reason:
            troubles_dir = target_path / TROUBLES_DIR
            troubles_dir.mkdir(exist_ok=True)

            dest_rar = troubles_dir / rar_file.name
            shutil.move(str(rar_file), str(dest_rar))

            # Убираем пустую папку если успели создать
            if extract_dir.exists() and not any(extract_dir.iterdir()):
                extract_dir.rmdir()

            # Файл с причиной ошибки
            problem_file = troubles_dir / (rar_file.stem + "_PROBLEM.txt")
            problem_file.write_text(
                f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Архив: {rar_file.name}\n"
                f"Инструмент: {tool}\n"
                f"Причина: {error_reason}\n",
                encoding="utf-8",
            )
            print(f"    📁 Архив перемещён в {TROUBLES_DIR}/")


if __name__ == "__main__":
    target_directory = "test_archives"
    unpack_archives(target_directory)
