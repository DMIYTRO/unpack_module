import os
import re
from pathlib import Path

def classify_face_back(filenames: list) -> dict:
    """
    Принимает список имен файлов (например, для папки 4-4) 
    и распределяет их на 'лицо' и 'оборот' на основе словаря ключевых слов.
    """
    # Словари/паттерны для определения сторон
    face_patterns = [r'лиц[ое]', r'^1$', r'face', r'front']
    back_patterns = [r'зворот', r'оборот', r'^2$', r'back', r'rear']
    
    result = {'face': None, 'back': None}
    
    for fname in filenames:
        # Убираем расширение для точной проверки
        name_without_ext = fname.rsplit('.', 1)[0].lower()
        
        is_face = any(re.search(p, name_without_ext) for p in face_patterns)
        is_back = any(re.search(p, name_without_ext) for p in back_patterns)
        
        if is_face and not is_back:
            result['face'] = fname
        elif is_back and not is_face:
            result['back'] = fname

    # Логика подстраховки (fallback):
    # Если мы уверенно нашли только лицо, оставшийся файл автоматически считаем оборотом
    if result['face'] and not result['back']:
        result['back'] = next((f for f in filenames if f != result['face']), None)
    # Если уверенно нашли только оборот, оставшийся файл считаем лицом
    elif result['back'] and not result['face']:
        result['face'] = next((f for f in filenames if f != result['back']), None)
    # Если ничего не совпало (редкий случай), просто сортируем по алфавиту
    elif not result['face'] and not result['back'] and len(filenames) == 2:
        filenames_sorted = sorted(filenames)
        result['face'] = filenames_sorted[0]
        result['back'] = filenames_sorted[1]
    # Если это заказ 4-0 и есть всего один файл, то он по умолчанию считается лицом
    elif not result['face'] and not result['back'] and len(filenames) == 1:
        result['face'] = filenames[0]
        
    return result

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
