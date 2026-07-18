from pathlib import Path
from filename_parser import parse_filename
from file_discovery import list_layout_files
from classifier import classify_face_back_paths

def parse_sides_from_foldername(foldername: str) -> str | None:
    """Извлекает сторонность тем же строгим парсером, что и номер заказа."""
    return parse_filename(foldername)["sides"]

def validate_folder(folder_path: str) -> str:
    """
    Проверяет папку на соответствие количества файлов заявленной сторонности.
    Возвращает 'good', если все сходится, и 'bad' ('requires_check'), если есть отклонения.
    """
    path = Path(folder_path)
    if not path.is_dir():
        return "error: not a directory"
        
    sides_str = parse_sides_from_foldername(path.name)
    if not sides_str:
        return "bad: unknown format (no X-X in name)"
        
    # Считаем макеты в самой папке заказа и во всех вложенных папках.
    files = list_layout_files(path)
    file_count = len(files)
    
    # Определяем, сколько сторон заявлено
    # Например, '4-0' или '1-0' -> вторая цифра '0', значит сторона одна.
    # '4-4' или '4-2' -> вторая цифра больше '0', значит сторон две.
    parts = sides_str.split('-')
    if len(parts) == 2:
        back_side = int(parts[1])
        expected_files = 1 if back_side == 0 else 2
    else:
        return "bad: cannot parse sides"

    # Логика пользователя:
    if expected_files == 1:
        if file_count == 1:
            return "good"
        else:
            return f"bad: expected 1 file for {sides_str}, but got {file_count}"
    elif expected_files == 2:
        if file_count == 2:
            classified = classify_face_back_paths(files)
            if classified["face"] is not None and classified["back"] is not None:
                return "good"
            return "bad: ambiguous face/back classification (needs extra check)"
        elif file_count == 1:
            return f"bad: expected 2 files for {sides_str}, but got 1 (needs extra check)"
        else:
            return f"bad: expected 2 files for {sides_str}, but got {file_count}"

if __name__ == "__main__":
    test_dir = Path("test_archives")
    print(f"{'Folder Name':<80} | {'Status'}")
    print("-" * 100)
    for folder in test_dir.iterdir():
        if folder.is_dir():
            status = validate_folder(str(folder))
            print(f"{folder.name[:78]:<80} | {status}")
