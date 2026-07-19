import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import db


class ManualPathSettingsTests(unittest.TestCase):
    def test_manual_paths_survive_database_reopen(self):
        with TemporaryDirectory() as temp:
            database = Path(temp) / "history.db"
            with patch.object(db, "DB_PATH", database):
                db.init_db()
                self.assertEqual(
                    db.get_manual_paths(),
                    {
                        "source_dir": "original_archives",
                        "output_dir": "original_archives",
                    },
                )

                db.save_manual_paths("/mnt/qnap/incoming", "/mnt/qnap/processed")

                self.assertEqual(
                    db.get_manual_paths(),
                    {
                        "source_dir": "/mnt/qnap/incoming",
                        "output_dir": "/mnt/qnap/processed",
                    },
                )


if __name__ == "__main__":
    unittest.main()
