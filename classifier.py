import re
from pathlib import Path

FACE_PATTERNS = (r"лиц[ое]", r"^1$", r"face", r"front")
BACK_PATTERNS = (r"зворот", r"оборот", r"^2$", r"back", r"rear")


def _classify(items: list, stem_getter) -> dict:
    """Классифицирует стороны только при однозначном совпадении.

    Несколько кандидатов на одну сторону, совпадение обеих сторон в одном
    имени и отсутствие явных признаков считаются неоднозначностью. В таком
    случае незаполненные стороны остаются ``None`` и вызывающий код может
    направить заказ оператору, не угадывая порядок файлов.
    """
    face_candidates = []
    back_candidates = []
    contradictory = False

    for item in items:
        stem = stem_getter(item).casefold()
        is_face = any(re.search(pattern, stem) for pattern in FACE_PATTERNS)
        is_back = any(re.search(pattern, stem) for pattern in BACK_PATTERNS)
        if is_face and is_back:
            contradictory = True
        elif is_face:
            face_candidates.append(item)
        elif is_back:
            back_candidates.append(item)

    if contradictory or len(face_candidates) > 1 or len(back_candidates) > 1:
        return {"face": None, "back": None}

    result = {
        "face": face_candidates[0] if face_candidates else None,
        "back": back_candidates[0] if back_candidates else None,
    }
    if result["face"] == result["back"]:
        return {"face": None, "back": None}

    # Единственный файл одностороннего заказа по-прежнему является лицом.
    if len(items) == 1 and not result["face"] and not result["back"]:
        result["face"] = items[0]
    return result


def classify_face_back(filenames: list) -> dict:
    """
    Принимает список имен файлов (например, для папки 4-4) 
    и распределяет их на 'лицо' и 'оборот' на основе словаря ключевых слов.
    """
    return _classify(filenames, lambda item: item.rsplit(".", 1)[0])


def classify_face_back_paths(files: list[Path]) -> dict:
    """Версия классификатора для файлов из подпапок.

    Сторона определяется по имени самого файла, а не по имени подпапки.
    Возвращаются объекты Path, поэтому одинаковые имена в разных подпапках
    не смешиваются.
    """
    return _classify(files, lambda item: item.stem)

if __name__ == "__main__":
    # Тест на реальной папке с 4-4
    test_dir = Path("test_archives/04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-face")
    if test_dir.exists():
        files = [f.name for f in test_dir.iterdir() if f.is_file() and not f.name.startswith('.')]
        print(f"Файлы в папке: {files}")
        classified = classify_face_back(files)
        print(f"Результат распределения: Лицо -> {classified['face']}, Оборот -> {classified['back']}\n")
    
    # Синтетические тесты
    test_cases = [
        ['1.pdf', '2.pdf'],
        ['face_image.tif', 'back_image.tif'],
        ['непонятно_что.tif', 'оборот.tif']
    ]
    
    for case in test_cases:
        classified = classify_face_back(case)
        print(f"Тест {case}: Лицо -> {classified['face']}, Оборот -> {classified['back']}")
