"""Поиск файлов макета внутри распакованного заказа."""
from pathlib import Path


def list_layout_files(root: Path) -> list[Path]:
    """Возвращает все видимые файлы в папке заказа и её подпапках.

    Служебные файлы и папки, начинающиеся с точки, исключаются: в частности,
    маркер ``.done`` не считается макетом при повторном запуске.
    """
    files = []
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        files.append(candidate)

    return sorted(files, key=lambda item: str(item.relative_to(root)).casefold())
