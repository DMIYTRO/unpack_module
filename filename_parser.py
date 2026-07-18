import re

def parse_filename(filename: str) -> dict:
    """
    Парсит имя архива и возвращает количество сторон (4-0, 4-4) и номер заказа.
    
    Примеры имен файлов:
    04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-face.rar
    01_KS(K)_Bezlam_90_mel_gl_(100x70)_4-0_T1000_(33342-25509667)_project_offset_1-face.rar
    """
    
    # Регулярное выражение для поиска цветности (сторонности): 4-0, 4-4
    # Ищет цифру 4, затем дефис, затем 0 или 4.
    sides_match = re.search(r'4-[04]', filename)
    sides = sides_match.group(0) if sides_match else None
    
    # Регулярное выражение для поиска номера заказа.
    # Ищет блок вида (число-НОМЕР_ЗАКАЗА) и извлекает вторую часть, например (33342-25509667) -> 25509667
    order_match = re.search(r'\((\d+)-(\d+)\)', filename)
    order_number = order_match.group(2) if order_match else None
    
    return {
        'sides': sides,
        'order_number': order_number
    }

if __name__ == "__main__":
    # Тестовые данные (взяты из ваших реальных файлов)
    test_filenames = [
        "04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-face.rar",
        "01_KS(K)_Bezlam_90_mel_gl_(100x70)_4-0_T1000_(33342-25509667)_project_offset_1-face.rar",
        "04_NP(K)_Bezlam_90_mel_gl_(148x105)_4-0_T2500_(323-25505856)_offset_1-face.rar"
    ]
    
    for fname in test_filenames:
        result = parse_filename(fname)
        print(f"Файл: {fname}")
        print(f"Результат парсинга: Стороны: {result['sides']}, Номер заказа: {result['order_number']}\n")
