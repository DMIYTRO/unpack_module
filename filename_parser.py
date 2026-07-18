import re

def parse_filename(filename: str) -> dict:
    """
    Парсит имя архива и возвращает количество сторон и номер заказа.

    Поддерживаемые форматы сторонности (X-Y):
      4-0, 4-4  — стандарт (офсет)
      5-0, 5-5  — пятикрасочная
      1-0, 1-1  — однокрасочная
      0-1       — оборот без лица
      и любые другие числовые комбинации X-Y

    Примеры имен файлов:
    04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-face.rar
    01_KS(K)_Bezlam_90_mel_gl_(100x70)_5-0_T1000_(33342-25509667)_project_offset_1-face.rar
    """

    # Ищем паттерн _X-Y_ (сторонность обрамлена подчёркиваниями или началом/концом строки).
    # \d+ с обеих сторон — любое целое число (не только 4).
    # Lookahead/lookbehind на _ гарантируют, что мы не схватим 33342-25509667 из номера заказа.
    sides_match = re.search(r'(?<![()\d])(\d+)-(\d+)(?![()\d])', filename)
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
    test_filenames = [
        ("4-4", "04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-face.rar"),
        ("4-0", "01_KS(K)_Bezlam_90_mel_gl_(100x70)_4-0_T1000_(33342-25509667)_project_offset_1-face.rar"),
        ("4-0", "04_NP(K)_Bezlam_90_mel_gl_(148x105)_4-0_T2500_(323-25505856)_offset_1-face.rar"),
        ("5-0", "04_NP_Brand_5-0_T500_(111-25599999)_offset-face.rar"),
        ("5-5", "04_NP_Brand_5-5_T500_(111-25599999)_offset-face.rar"),
        ("1-0", "01_KS_Brand_1-0_T100_(111-25599998)_offset-face.rar"),
        ("1-1", "01_KS_Brand_1-1_T100_(111-25599998)_offset-face.rar"),
        ("0-1", "01_KS_Brand_0-1_T100_(111-25599997)_offset-face.rar"),
    ]

    print(f"{'Ожидается':^6} | {'Получено':^6} | {'OK':^4} | Файл")
    print("-" * 80)
    for expected, fname in test_filenames:
        result = parse_filename(fname)
        got = result['sides']
        ok = "✅" if got == expected else "❌"
        print(f"  {expected:^6} | {str(got):^6} | {ok:^4} | {fname[:50]}")
