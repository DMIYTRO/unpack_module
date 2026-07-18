import os
from pathlib import Path
from classifier import classify_face_back

def generate_new_names(folder_name: str, classified_files: dict) -> dict:
    """
    Генерирует новые имена для лица и оборота на основе имени папки.
    
    Пример:
    folder_name: 04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-face
    face -> 04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-face.tif
    back -> 04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-back.tif
    """
    new_names = {}
    
    # Имя для лица (всегда равно имени папки)
    if classified_files.get('face'):
        ext = Path(classified_files['face']).suffix
        new_names['face'] = f"{folder_name}{ext}"
        
    # Имя для оборота (имя папки, где -face меняется на -back)
    if classified_files.get('back'):
        ext = Path(classified_files['back']).suffix
        
        if folder_name.endswith('-face'):
            back_base = folder_name[:-5] + '-back'
        elif folder_name.endswith('_face'):
            back_base = folder_name[:-5] + '_back'
        else:
            # Если по какой-то причине в имени нет слова face, просто добавляем -back
            back_base = f"{folder_name}-back"
            
        new_names['back'] = f"{back_base}{ext}"
        
    return new_names

def rename_files_in_folder(folder_path: str):
    """
    Переименовывает файлы в указанной папке согласно логике.
    """
    path = Path(folder_path)
    if not path.is_dir():
        print(f"Ошибка: {folder_path} не является папкой.")
        return
        
    folder_name = path.name
    files = [f.name for f in path.iterdir() if f.is_file() and not f.name.startswith('.')]
    
    if not files:
        print(f"Папка {folder_name} пуста.")
        return
        
    # Шаг 1. Определяем, где лицо, а где оборот
    classified = classify_face_back(files)
    
    # Шаг 2. Генерируем новые имена
    new_names = generate_new_names(folder_name, classified)
    
    # Шаг 3. Переименовываем
    print(f"\n--- Переименование в папке: {folder_name} ---")
    for side, original_name in classified.items():
        if original_name and original_name in files:
            new_name = new_names.get(side)
            if new_name:
                old_path = path / original_name
                new_path = path / new_name
                
                print(f"[{side.upper()}] {original_name}  --->  {new_name}")
                
                # Фактическое переименование файла:
                os.rename(old_path, new_path)
                
                # Запись в лог
                with open("rename_log.txt", "a", encoding="utf-8") as log_file:
                    log_file.write(f"[{folder_name}] {original_name} -> {new_name}\n")

if __name__ == "__main__":
    # Тестируем на нашей 4-4 папке
    test_dir = "test_archives/04_NP_Glam11_350_mel_(90x50)_4-4_T100_(17618-25516399)_offset-face"
    rename_files_in_folder(test_dir)
