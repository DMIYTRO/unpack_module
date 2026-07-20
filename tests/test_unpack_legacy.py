import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from unpack import (
    MAX_ARCHIVE_SIZE_BYTES,
    _extract_zip_safely,
    decode_legacy_zip_name,
    unpack_archives,
)


class LegacyZipInfo(zipfile.ZipInfo):
    """Позволяет тесту записать байты имени без UTF-8-флага."""

    def _encodeFilenameFlags(self):
        return self.filename.encode("cp437"), self.flag_bits & ~0x800


class LegacyZipEncodingTests(unittest.TestCase):
    def test_cp866_filename_is_restored(self):
        expected = "лице макета.tif"
        mojibake = expected.encode("cp866").decode("cp437")
        self.assertEqual(decode_legacy_zip_name(mojibake, 0), expected)

    def test_cp1251_filename_is_restored(self):
        expected = "Привет мир.txt"
        mojibake = expected.encode("cp1251").decode("cp437")
        self.assertEqual(decode_legacy_zip_name(mojibake, 0), expected)

    def test_utf8_filename_is_not_changed(self):
        expected = "макети/зворот.tif"
        self.assertEqual(decode_legacy_zip_name(expected, 0x800), expected)

    def test_legacy_zip_is_extracted_with_readable_cyrillic(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            zip_path = root / "legacy.zip"
            expected = "макеты/лице.tif"
            mojibake = expected.encode("cp866").decode("cp437")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(LegacyZipInfo(mojibake), b"layout")

            output = root / "output"
            output.mkdir()
            _extract_zip_safely(zip_path, output)

            self.assertEqual((output / expected).read_bytes(), b"layout")

    def test_corrected_extractor_still_blocks_path_traversal(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            zip_path = root / "unsafe.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../outside.txt", b"unsafe")

            output = root / "output"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "небезопасный путь"):
                _extract_zip_safely(zip_path, output)
            self.assertFalse((root / "outside.txt").exists())

    def test_symbolic_link_member_is_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            zip_path = root / "symlink.zip"
            link = zipfile.ZipInfo("link.tif")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(link, "target.tif")

            output = root / "output"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "символическую ссылку"):
                _extract_zip_safely(zip_path, output)


class ArchiveLimitTests(unittest.TestCase):
    def test_archive_over_one_and_half_gb_moves_to_troubles(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "oversized.zip"
            with archive.open("wb") as stream:
                stream.truncate(MAX_ARCHIVE_SIZE_BYTES + 1)

            unpack_archives(str(root))

            moved = root / "_TROUBLES_" / archive.name
            problem = root / "_TROUBLES_" / "oversized_PROBLEM.txt"
            self.assertTrue(moved.exists())
            self.assertFalse(archive.exists())
            self.assertIn("превышает лимит 1,5 ГБ", problem.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
