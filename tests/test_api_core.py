import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from api_core import ApiCoreError, build_api_mapping, process_archives_with_api
from website_parser import SiteAccessError


class ApiCoreTests(unittest.TestCase):
    def test_two_sided_mapping_uses_suborder_and_face_back(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp) / "job_4-4_(1-12345)_face"
            folder.mkdir()
            first = folder / "1.pdf"
            second = folder / "2.pdf"
            first.write_bytes(b"face")
            second.write_bytes(b"back")

            mapping = build_api_mapping(folder, [second, first], ["90001"])

            self.assertEqual(
                [(source.name, destination.name) for source, destination in mapping],
                [
                    ("1.pdf", "job_4-4_(1-90001)_face.pdf"),
                    ("2.pdf", "job_4-4_(1-90001)_back.pdf"),
                ],
            )

    def test_count_mismatch_is_rejected_before_rename(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp) / "job_4-4_(1-12345)_face"
            folder.mkdir()
            layout = folder / "1.pdf"
            layout.write_bytes(b"layout")

            with self.assertRaises(ApiCoreError):
                build_api_mapping(folder, [layout], ["90001"])

            self.assertTrue(layout.exists())

    def test_two_sided_mapping_respects_explicit_cyrillic_side_names(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp) / "job_4-4_(1-12345)_face"
            folder.mkdir()
            back = folder / "зворот.tif"
            face = folder / "лице.tif"
            back.write_bytes(b"back")
            face.write_bytes(b"face")

            mapping = build_api_mapping(folder, [back, face], ["12345"])

            self.assertEqual(
                [(source.name, destination.name) for source, destination in mapping],
                [
                    ("лице.tif", "job_4-4_(1-12345)_face.tif"),
                    ("зворот.tif", "job_4-4_(1-12345)_back.tif"),
                ],
            )

    @patch("api_core.unpack_archives")
    @patch("api_core.fetch_suborders", return_value=[])
    def test_pipeline_renames_and_marks_order_done(self, fetch, unpack):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "job_4-0_(1-12345)_face"
            folder.mkdir()
            (folder / "layout.pdf").write_bytes(b"layout")

            summary = process_archives_with_api(root, api_key="test-key")

            self.assertTrue(summary.ok)
            self.assertEqual(summary.processed, [folder.name])
            self.assertTrue((folder / "job_4-0_(1-12345)_face_1.pdf").exists())
            self.assertTrue((folder / ".done").exists())
            fetch.assert_called_once_with("12345", api_key="test-key", timeout=10)

    @patch("api_core.fetch_suborders", return_value=[])
    def test_pipeline_finds_zip_and_moves_it_to_done(self, fetch):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            archive_name = "job_4-0_(1-12345)_face.zip"
            with zipfile.ZipFile(root / archive_name, "w") as archive:
                archive.writestr("layout.pdf", b"layout")

            summary = process_archives_with_api(root, api_key="test-key")

            folder = root / "job_4-0_(1-12345)_face"
            self.assertTrue(summary.ok)
            self.assertTrue((folder / "job_4-0_(1-12345)_face_1.pdf").exists())
            self.assertTrue((root / "_DONE_" / archive_name).exists())
            self.assertFalse((root / archive_name).exists())

    @patch("api_core.unpack_archives")
    @patch("api_core.fetch_suborders", side_effect=SiteAccessError("timeout"))
    def test_api_failure_leaves_order_untouched_for_retry(self, fetch, unpack):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "job_4-0_(1-12345)_face"
            folder.mkdir()
            layout = folder / "layout.pdf"
            layout.write_bytes(b"layout")

            summary = process_archives_with_api(root, api_key="test-key")

            self.assertFalse(summary.ok)
            self.assertTrue(layout.exists())
            self.assertFalse((folder / ".done").exists())


if __name__ == "__main__":
    unittest.main()
