import os
import subprocess
from pathlib import Path

def unpack_archives(target_dir):
    """
    Разархивирует все .rar файлы в указанной директории.
    Для каждого архива создает папку с именем архива (без .rar)
    и извлекает в нее все файлы.
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
        
        # Используем системную утилиту unar для извлечения
        # '-f' - принудительно перезаписывать, '-D' - не создавать вложенную директорию
        try:
            subprocess.run(
                ['unar', '-f', '-D', '-o', str(extract_dir), str(rar_file)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print(f"Успешно распаковано.")
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode('utf-8', errors='ignore') or e.stdout.decode('utf-8', errors='ignore')
            print(f"Ошибка при распаковке {rar_file.name}: {error_msg}")
        except FileNotFoundError:
            print("Ошибка: утилита 'unar' не найдена в системе. Пожалуйста, установите ее (например: brew install unar).")
            break

if __name__ == "__main__":
    # В качестве примера берем тестовую папку
    # Можно заменить на 'original_archives' для полного прогона
    target_directory = "test_archives"
    unpack_archives(target_directory)
