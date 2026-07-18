import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

from atomic_rename import RenameTransactionError, atomic_rename_many
import pipeline_runner


class AtomicRenameTests(unittest.TestCase):
    def test_existing_destination_is_never_overwritten(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.tif"
            destination = root / "destination.tif"
            source.write_text("source", encoding="utf-8")
            destination.write_text("keep", encoding="utf-8")

            with self.assertRaises(RenameTransactionError):
                atomic_rename_many([(source, destination)])

            self.assertEqual(source.read_text(encoding="utf-8"), "source")
            self.assertEqual(destination.read_text(encoding="utf-8"), "keep")

    def test_missing_source_aborts_before_any_file_changes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first.tif"
            first.write_text("first", encoding="utf-8")

            with self.assertRaises(RenameTransactionError):
                atomic_rename_many([
                    (first, root / "renamed.tif"),
                    (root / "missing.tif", root / "other.tif"),
                ])

            self.assertTrue(first.exists())
            self.assertFalse((root / "renamed.tif").exists())

    def test_stationary_source_cannot_be_overwritten(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first.tif"
            second = root / "second.tif"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")

            with self.assertRaises(RenameTransactionError):
                atomic_rename_many([(first, second), (second, second)])

            self.assertEqual(first.read_text(encoding="utf-8"), "first")
            self.assertEqual(second.read_text(encoding="utf-8"), "second")

    def test_system_error_rolls_back_staged_and_completed_files(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first.tif"
            second = root / "second.tif"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            real_rename = os.rename
            calls = 0

            def fail_first_final(source, destination):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("simulated failure")
                return real_rename(source, destination)

            with patch("atomic_rename.os.rename", side_effect=fail_first_final):
                with self.assertRaises(RenameTransactionError):
                    atomic_rename_many([
                        (first, root / "new-first.tif"),
                        (second, root / "new-second.tif"),
                    ])

            self.assertEqual(first.read_text(encoding="utf-8"), "first")
            self.assertEqual(second.read_text(encoding="utf-8"), "second")
            self.assertFalse(list(root.glob("*.tmp")))


class PipelineLockTests(unittest.TestCase):
    def setUp(self):
        pipeline_runner._active_run_ids.clear()
        pipeline_runner.run_queues.clear()

    def tearDown(self):
        pipeline_runner._active_run_ids.clear()
        pipeline_runner.run_queues.clear()

    def test_second_run_is_rejected_before_worker_registers_process(self):
        with patch("db.log_run"), patch.object(pipeline_runner.threading, "Thread"):
            first_run = pipeline_runner.start_run("/tmp/input")
            with self.assertRaises(pipeline_runner.PipelineRunningError):
                pipeline_runner.start_run("/tmp/input")

        self.assertIn(first_run, pipeline_runner._active_run_ids)


class ConflictResolutionTests(unittest.TestCase):
    def test_missing_conflict_source_is_not_logged_or_marked_done(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp) / "order"
            folder.mkdir()
            conflict = {
                "status": "pending",
                "folder_name": str(folder),
                "run_id": "run-1",
                "mapping_json": '[["missing.tif", "1", "renamed.tif"]]',
            }
            with patch("db.get_conflict", return_value=conflict), patch("db.log_rename") as log_rename, patch(
                "db.resolve_conflict"
            ) as resolve:
                with self.assertRaises(RenameTransactionError):
                    pipeline_runner.resolve_conflict(1, "approve")

            log_rename.assert_not_called()
            resolve.assert_not_called()
            self.assertFalse((folder / ".done").exists())


if __name__ == "__main__":
    unittest.main()
