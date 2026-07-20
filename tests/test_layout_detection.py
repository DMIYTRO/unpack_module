import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from classifier import classify_face_back, classify_face_back_paths
from file_discovery import list_layout_files
from validator import validate_folder
import main


class LayoutDetectionTests(unittest.TestCase):
    def test_only_supported_layout_formats_are_discovered(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("layout.TIF", "vector.pdf", "photo.jpg", "scan.JPEG", "notes.txt", "order.json"):
                (root / name).write_bytes(b"data")

            self.assertEqual(
                [path.name for path in list_layout_files(root)],
                ["layout.TIF", "photo.jpg", "scan.JPEG", "vector.pdf"],
            )

    def test_bulk_jpeg_mapping_uses_natural_order_and_keeps_nested_folder(self):
        folder = Path("job_4-0_(1-25610245)_face")
        nested = folder / "Дієслова"
        files = [nested / "файл 10.jpg", nested / "файл 2.jpg", nested / "файл 1.jpg"]
        files_sorted = sorted(files, key=lambda path: main.natural_layout_sort_key(folder, path))

        mapping = main.build_bulk_jpeg_mapping(folder, files_sorted, ["25610245"])

        self.assertIsNotNone(mapping)
        self.assertEqual([item[0].name for item in mapping], ["файл 1.jpg", "файл 2.jpg", "файл 10.jpg"])
        self.assertEqual([item[2] for item in mapping], [
            "job_4-0_(1-25610245)_face_1.jpg",
            "job_4-0_(1-25610245)_face_2.jpg",
            "job_4-0_(1-25610245)_face_3.jpg",
        ])

    def test_hidden_supported_file_is_ignored(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            hidden = root / ".cache"
            hidden.mkdir()
            (hidden / "layout.tif").write_bytes(b"data")
            self.assertEqual(list_layout_files(root), [])

    def test_explicit_face_and_back_are_classified(self):
        self.assertEqual(
            classify_face_back(["front.pdf", "rear.pdf"]),
            {"face": "front.pdf", "back": "rear.pdf"},
        )

    def test_unknown_pair_is_not_assigned_alphabetically(self):
        self.assertEqual(
            classify_face_back(["alpha.tif", "beta.tif"]),
            {"face": None, "back": None},
        )

    def test_duplicate_face_candidates_are_ambiguous(self):
        files = [Path("face-one.tif"), Path("front-two.tif")]
        self.assertEqual(
            classify_face_back_paths(files),
            {"face": None, "back": None},
        )

    def test_single_neutral_file_is_classified_as_face(self):
        file_path = Path("Фото 18х12 см - Глянець - 8 шт.pdf")
        self.assertEqual(
            classify_face_back_paths([file_path]),
            {"face": file_path, "back": None},
        )

    def test_ambiguous_two_sided_order_requires_manual_check(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "order_4-4_face"
            root.mkdir()
            (root / "alpha.tif").write_bytes(b"layout")
            (root / "beta.tif").write_bytes(b"layout")
            self.assertIn("ambiguous face/back", validate_folder(str(root)))

    def test_service_file_does_not_change_expected_layout_count(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "order_4-0_face"
            root.mkdir()
            (root / "layout.tif").write_bytes(b"layout")
            (root / "readme.txt").write_text("instructions", encoding="utf-8")
            self.assertEqual(validate_folder(str(root)), "good")

    def test_web_pipeline_sends_ambiguous_pair_to_operator(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "job_4-4_(1-12345)_face"
            folder.mkdir()
            (folder / "left.tif").write_bytes(b"left")
            (folder / "right.tif").write_bytes(b"right")

            output = StringIO()
            with patch("main.unpack_archives"), patch("main.WEB_MODE", True), patch(
                "website_parser.fetch_suborders", return_value=["12345"]
            ), redirect_stdout(output):
                main.process_archives(str(root))

            self.assertIn("CONFLICT_DATA:", output.getvalue())
            self.assertFalse((folder / ".done").exists())
            self.assertTrue((folder / "left.tif").exists())
            self.assertTrue((folder / "right.tif").exists())

    def test_web_pipeline_adds_main_order_to_api_suborders(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "job_4-0_(1-25610128)_face"
            folder.mkdir()
            for index in range(1, 6):
                (folder / f"{index}.pdf").write_bytes(f"layout-{index}".encode())

            output = StringIO()
            with patch("main.unpack_archives"), patch("main.WEB_MODE", True), patch(
                "website_parser.fetch_suborders",
                return_value=["25610129", "25610130", "25610131", "25610132"],
            ), redirect_stdout(output):
                main.process_archives(str(root))

            self.assertNotIn("CONFLICT_DATA:", output.getvalue())
            self.assertTrue((folder / ".done").exists())
            expected_orders = range(25610128, 25610133)
            for index, order_id in enumerate(expected_orders, start=1):
                expected = folder / f"job_4-0_(1-{order_id})_face_{index}.pdf"
                self.assertTrue(expected.exists(), expected)

    def test_web_pipeline_proposes_all_jpegs_for_main_order(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "job_4-0_(1-25610245)_face"
            nested = folder / "Дієслова"
            nested.mkdir(parents=True)
            for name in ("файл 10.jpg", "файл 2.jpg", "файл 1.jpg"):
                (nested / name).write_bytes(b"image")

            output = StringIO()
            with patch("main.unpack_archives"), patch("main.WEB_MODE", True), patch(
                "website_parser.fetch_suborders", return_value=[]
            ), redirect_stdout(output):
                main.process_archives(str(root))

            payload_line = next(
                line for line in output.getvalue().splitlines()
                if line.startswith("CONFLICT_DATA:")
            )
            payload = json.loads(payload_line.removeprefix("CONFLICT_DATA:"))
            self.assertEqual(len(payload["mapping"]), 3)
            self.assertEqual([item[0] for item in payload["mapping"]], [
                "Дієслова/файл 1.jpg",
                "Дієслова/файл 2.jpg",
                "Дієслова/файл 10.jpg",
            ])
            self.assertEqual([Path(item[2]).name for item in payload["mapping"]], [
                "job_4-0_(1-25610245)_face_1.jpg",
                "job_4-0_(1-25610245)_face_2.jpg",
                "job_4-0_(1-25610245)_face_3.jpg",
            ])
            self.assertFalse((folder / ".done").exists())


if __name__ == "__main__":
    unittest.main()
