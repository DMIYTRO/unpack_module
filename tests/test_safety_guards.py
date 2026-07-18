import sys
import os
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

from filename_parser import parse_filename
from validator import parse_sides_from_foldername
from website_parser import OrderDataError, parse_suborders_from_html
from unpack import unpack_archives
from renamer import rename_files_in_folder
from validator import validate_folder
from main import build_site_mapping, move_archive_to_done
import pipeline_runner


class SafetyGuardTests(unittest.TestCase):
    def test_order_number_is_not_treated_as_print_sides(self):
        folder_name = "job_(17618-25516399)_offset"
        self.assertIsNone(parse_sides_from_foldername(folder_name))

    def test_standard_sides_are_still_parsed(self):
        name = "04_NP_Glam_(90x50)_4-4_T100_(17618-25516399)_offset-face"
        self.assertEqual(parse_filename(name)["sides"], "4-4")
        self.assertEqual(parse_sides_from_foldername(name), "4-4")

    def test_changed_site_markup_is_an_explicit_error(self):
        with self.assertRaises(OrderDataError):
            parse_suborders_from_html("<html><body>temporary error</body></html>", "25509667")

    def test_failed_unpack_does_not_create_a_working_folder(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            archive = base / "order_4-0.rar"
            archive.write_bytes(b"not a real archive")

            import subprocess
            failure = subprocess.CalledProcessError(2, ["unar"], stderr=b"broken archive")
            with patch("unpack._find_extractor", return_value="unar"), patch(
                "unpack.subprocess.run", side_effect=failure
            ):
                unpack_archives(str(base))

            self.assertFalse((base / "order_4-0").exists())
            self.assertTrue((base / "_TROUBLES_" / "order_4-0.rar").exists())
            self.assertFalse(list(base.glob(".extracting_*")))

    def test_nested_file_uses_the_root_order_name(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "order_4-0_face"
            nested = root / "source" / "print"
            nested.mkdir(parents=True)
            (nested / "1.tif").write_bytes(b"layout")

            self.assertEqual(validate_folder(str(root)), "good")
            old_cwd = Path.cwd()
            try:
                os.chdir(temp)
                rename_files_in_folder(str(root))
            finally:
                os.chdir(old_cwd)

            self.assertTrue((nested / "order_4-0_face.tif").exists())
            self.assertFalse((nested / "1.tif").exists())

    def test_manual_name_keeps_file_in_its_subfolder(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "order"
            source = root / "nested" / "source.tif"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"layout")
            conflict = {
                "status": "pending",
                "folder_name": str(root),
                "files_json": '["nested/source.tif"]',
            }
            with patch("db.get_conflict", return_value=conflict):
                mapping = pipeline_runner.build_manual_mapping(
                    1, ["nested/source.tif"], ["assigned-name.tif"]
                )

            self.assertEqual(mapping, [["nested/source.tif", "manual", "nested/assigned-name.tif"]])

    def test_finished_archive_moves_from_source_not_output_folder(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "incoming"
            output_dir = root / "processed"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "order_4-0.rar").write_bytes(b"archive")
            processed_folder = output_dir / "order_4-0"
            processed_folder.mkdir()

            move_archive_to_done(processed_folder, source_dir)

            self.assertFalse((source_dir / "order_4-0.rar").exists())
            self.assertTrue((source_dir / "_DONE_" / "order_4-0.rar").exists())
            self.assertTrue(processed_folder.exists())

    def test_zip_unpacks_to_the_separate_output_folder(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "incoming"
            output_dir = root / "processed"
            source_dir.mkdir()
            archive = source_dir / "order_4-0.zip"
            with zipfile.ZipFile(archive, "w") as zip_archive:
                zip_archive.writestr("nested/layout.tif", b"layout")

            unpack_archives(str(source_dir), str(output_dir))

            self.assertTrue((output_dir / "order_4-0" / "nested" / "layout.tif").exists())
            self.assertTrue(archive.exists())

    def test_two_sided_files_are_grouped_per_suborder(self):
        folder = Path("21_NP_(70x100)_4-4_(11844-25603159)_1-face")
        files = [folder / name for name in ("1.1.tif", "1.2.tif", "2.1.tif", "2.2.tif")]

        mapping, files_per_order = build_site_mapping(
            folder, files, ["25603159", "25603160"]
        )

        self.assertEqual(files_per_order, 2)
        self.assertEqual([entry[1] for entry in mapping], ["25603159", "25603159", "25603160", "25603160"])
        self.assertTrue(mapping[0][2].endswith("_1-face.tif"))
        self.assertTrue(mapping[1][2].endswith("_1-back.tif"))


if __name__ == "__main__":
    unittest.main()
