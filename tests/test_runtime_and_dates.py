import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import runtime
import scheduler
from website_parser import OrderDataError, fetch_suborders, parse_suborders_response


class SborkaApiTests(unittest.TestCase):
    def test_invalid_order_is_rejected_before_request(self):
        with self.assertRaises(OrderDataError):
            fetch_suborders("2550&statuss=1", api_key="test-key")

    def test_response_is_deduplicated_and_sorted_numerically(self):
        self.assertEqual(
            parse_suborders_response("25509673, 25509671,25509673,"),
            ["25509671", "25509673"],
        )

    @patch("website_parser.requests.post")
    def test_only_get_suborders_request_is_used(self, post):
        response = Mock(text="25509671,25509673,")
        response.raise_for_status.return_value = None
        post.return_value = response

        result = fetch_suborders("25509667", api_key="test-key", timeout=7)

        self.assertEqual(result, ["25509671", "25509673"])
        post.assert_called_once_with(
            "https://sborka.ua/api.php",
            params={"action": "getSubOrders", "id": "25509667"},
            data={"api_key": "test-key"},
            timeout=7,
        )


class SchedulerLifecycleTests(unittest.TestCase):
    def tearDown(self):
        scheduler.shutdown_scheduler()

    def test_scheduler_is_not_started_during_import(self):
        scheduler.shutdown_scheduler()
        self.assertIsNone(scheduler._scheduler)

    @patch("scheduler.BackgroundScheduler")
    def test_start_and_shutdown_are_idempotent(self, scheduler_class):
        instance = Mock()
        instance.running = False
        scheduler_class.return_value = instance

        self.assertIs(scheduler.start_scheduler(), instance)
        instance.running = True
        self.assertIs(scheduler.start_scheduler(), instance)
        self.assertEqual(instance.start.call_count, 1)

        scheduler.shutdown_scheduler()
        scheduler.shutdown_scheduler()
        instance.shutdown.assert_called_once_with(wait=False)


class RuntimeBootstrapTests(unittest.TestCase):
    def setUp(self):
        runtime._started = False

    @patch("runtime.scheduler")
    @patch("runtime.db")
    def test_runtime_initializes_and_restores_schedule_once(self, database, job_scheduler):
        database.get_schedule.return_value = {
            "enabled": 1,
            "cron_expression": "0 9 * * 1-5",
            "target_dir": "incoming",
            "output_dir": "processed",
        }

        runtime.start_runtime()
        runtime.start_runtime()

        database.init_db.assert_called_once_with()
        job_scheduler.start_scheduler.assert_called_once_with()
        job_scheduler.update_schedule.assert_called_once_with(
            "0 9 * * 1-5", True, "incoming", "processed"
        )

    @patch("runtime.scheduler")
    def test_runtime_shutdown_is_idempotent(self, job_scheduler):
        runtime.shutdown_runtime()
        runtime.shutdown_runtime()
        self.assertEqual(job_scheduler.shutdown_scheduler.call_count, 2)


if __name__ == "__main__":
    unittest.main()
