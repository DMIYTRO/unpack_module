import os
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from datetime import datetime

# Папка для битых архивов
TROUBLES_DIR = "_TROUBLES_"
EXTRACT_TIMEOUT_SECONDS = 15 * 60


def _unique_path(directory: Path, filename: str) -> Path:
    """Возвращает свободный путь, не перезаписывая существующие данные."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    return directory / f"{Path(filename).stem}_{datetime.now().strftime('%H%M%S')}{Path(filename).suffix}"


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


def _extract_zip_safely(zip_file: Path, extract_dir: Path):
    """Распаковывает ZIP, не позволяя записи выйти за пределы extract_dir."""
    root = extract_dir.resolve()
    with zipfile.ZipFile(zip_file) as archive:
        for member in archive.infolist():
            destination = (root / member.filename).resolve()
            if destination != root and root not in destination.parents:
                raise ValueError(f"ZIP содержит небезопасный путь: {member.filename}")
        archive.extractall(root)


def unpack_archives(source_dir: str, output_dir: str | None = None):
    """
    Разархивирует все .rar файлы из source_dir в output_dir.
    Кросс-платформенно: работает на macOS и Linux.
    Битые архивы перемещаются в source_dir/_TROUBLES_/ с файлом _PROBLEM.txt.
    """
    source_path = Path(source_dir).resolve()
    output_path = Path(output_dir or source_dir).resolve()
    if not source_path.exists() or not source_path.is_dir():
        print(f"Директория с архивами {source_dir} не найдена.")
        return
    output_path.mkdir(parents=True, exist_ok=True)

    archive_files = sorted(
        (item for item in source_path.iterdir() if item.is_file() and item.suffix.lower() in {".rar", ".zip"}),
        key=lambda item: item.name.casefold(),
    )
    if not archive_files:
        print(f"В директории {source_dir} не найдено .rar или .zip файлов.")
        return

    # Внешний распаковщик нужен только для RAR. ZIP обрабатывает Python.
    has_rar = any(item.suffix.lower() == ".rar" for item in archive_files)
    tool = _find_extractor() if has_rar else None
    if has_rar and not tool:
        print(
            "❌ Не найден ни один инструмент для распаковки RAR.\n"
            "   macOS : brew install unar\n"
            "   Ubuntu: sudo apt install unar\n"
            "   или   : sudo apt install unrar\n"
            "   или   : sudo apt install p7zip-full"
        )
        return

    if tool:
        print(f"Инструмент распаковки RAR: {tool}")
    if any(item.suffix.lower() == ".zip" for item in archive_files):
        print("Инструмент распаковки ZIP: встроенный модуль Python")

    print(f"Найдено архивов для распаковки: {len(archive_files)}")

    for archive_file in archive_files:
        folder_name = archive_file.stem
        extract_dir = output_path / folder_name
        # Никогда не распаковываем поверх имеющейся папки: это может смешать
        # старые и новые файлы при повторном запуске.
        extract_dir_exists = extract_dir.exists()
        temp_dir = output_path / f".extracting_{folder_name}_{uuid.uuid4().hex}"

        print(f"\nРаспаковка {archive_file.name}")
        print(f"Во временную папку -> {temp_dir.name}/")

        error_reason = None

        try:
            if extract_dir_exists:
                raise FileExistsError(
                    f"Рабочая папка {extract_dir.name}/ уже существует; архив не будет перезаписан"
                )

            temp_dir.mkdir(parents=True, exist_ok=False)
            if archive_file.suffix.lower() == ".zip":
                _extract_zip_safely(archive_file, temp_dir)
            else:
                cmd = _build_command(tool, archive_file, temp_dir)
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=EXTRACT_TIMEOUT_SECONDS,
                )
            # Публикуем результат только после успешной распаковки.
            temp_dir.replace(extract_dir)
            print("Успешно распаковано.")

        except subprocess.CalledProcessError as e:
            error_msg = (
                e.stderr.decode("utf-8", errors="ignore").strip()
                or e.stdout.decode("utf-8", errors="ignore").strip()
                or f"{tool} вернул код ошибки {e.returncode}"
            )
            error_reason = f"Ошибка распаковки ({tool}): {error_msg}"
            print(f"❌ {error_reason}")

        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, ValueError) as e:
            error_reason = f"Ошибка распаковки ZIP: {e}"
            print(f"❌ {error_reason}")

        except subprocess.TimeoutExpired:
            error_reason = f"Распаковка превысила лимит {EXTRACT_TIMEOUT_SECONDS // 60} минут"
            print(f"❌ {error_reason}")

        except Exception as e:
            error_reason = f"Неожиданная ошибка: {e}"
            print(f"❌ {error_reason}")

        # При ошибке — переносим в _TROUBLES_
        if error_reason:
            troubles_dir = source_path / TROUBLES_DIR
            troubles_dir.mkdir(exist_ok=True)

            dest_archive = _unique_path(troubles_dir, archive_file.name)
            shutil.move(str(archive_file), str(dest_archive))

            # Сохраняем частичную распаковку для диагностики, не подмешивая её
            # в рабочую папку, которую затем обходит main.py.
            if temp_dir.exists():
                partial_dir = _unique_path(
                    troubles_dir, f"{archive_file.stem}_partial_{datetime.now().strftime('%H%M%S')}"
                )
                shutil.move(str(temp_dir), str(partial_dir))

            # Файл с причиной ошибки
            problem_file = troubles_dir / (archive_file.stem + "_PROBLEM.txt")
            problem_file.write_text(
                f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Архив: {archive_file.name}\n"
                f"Инструмент: {tool or 'zipfile'}\n"
                f"Причина: {error_reason}\n",
                encoding="utf-8",
            )
            print(f"    📁 Архив перемещён в {TROUBLES_DIR}/")


if __name__ == "__main__":
    target_directory = "test_archives"
    unpack_archives(target_directory)
