"""ADF-Mehrseiten-Scan gegen einen gemockten eSCL-Server.

Ausführen: python3 -m unittest discover -s tests -v
"""
import sys
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_escl import EMPTY, JAM, JOB, LOADED, FakeScanner
from print_ease import scanner_client as sc
from print_ease.printer_model import ScannerInfo


class ScanAdfAllPages(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch.object(sc.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def scan(self, documents, states=(EMPTY,), exhausted=404, **kwargs):
        self.fake = FakeScanner(documents, states, exhausted)
        self.addCleanup(self.fake.close)
        info = ScannerInfo("S", "h", 80, self.fake.url, "S", 1, 1, [], [], [], None)
        return sc.scan_adf_all_pages(info, **kwargs)

    def assert_job_deleted_once(self):
        self.assertEqual(self.fake.deleted, [JOB])

    def test_404_while_loaded_waits_for_next_page(self):
        pages = self.scan([b"1", 404, b"2", 404, b"3"], states=[LOADED, LOADED, EMPTY])
        self.assertEqual(pages, [b"1", b"2", b"3"])
        self.assert_job_deleted_once()
        self.assertEqual(self.sleep.call_args_list[0], mock.call(sc._ADF_RETRY_DELAY))

    def test_multiple_404_while_loaded_are_not_limited_by_empty_retries(self):
        pages = self.scan([b"1", *[404] * 10, b"2"], states=[*[LOADED] * 10, EMPTY])
        self.assertEqual(pages, [b"1", b"2"])

    def test_404_while_empty_still_collects_last_page_in_transfer(self):
        pages = self.scan([b"1", 404, 404, b"2"], states=[EMPTY])
        self.assertEqual(pages, [b"1", b"2"])

    def test_404_while_empty_ends_after_three_further_attempts(self):
        pages = self.scan([b"1"], states=[EMPTY])
        self.assertEqual(pages, [b"1"])
        self.assertEqual(self.fake.next_document_calls, 1 + 1 + 3)
        self.assertEqual(self.sleep.call_count, 3)
        self.assert_job_deleted_once()

    def test_unknown_state_is_treated_like_empty(self):
        pages = self.scan([b"1"], states=[None])
        self.assertEqual(pages, [b"1"])
        self.assertEqual(self.fake.next_document_calls, 1 + 1 + 3)

    def test_jam_does_not_wait_like_loaded(self):
        self.assertEqual(self.scan([b"1"], states=[JAM]), [b"1"])
        self.assertEqual(self.fake.next_document_calls, 1 + 1 + 3)

    def test_empty_retries_start_over_after_each_page(self):
        pages = self.scan([b"1", 404, 404, 404, b"2", 404, 404, 404, b"3"], states=[EMPTY])
        self.assertEqual(pages, [b"1", b"2", b"3"])

    def test_empty_feeder_returns_no_pages(self):
        self.assertEqual(self.scan([], states=[EMPTY]), [])
        self.assert_job_deleted_once()

    def test_410_ends_job_immediately(self):
        pages = self.scan([b"1", 410, b"never"], states=[LOADED])
        self.assertEqual(pages, [b"1"])
        self.assertEqual(self.fake.status_calls, 0)
        self.sleep.assert_not_called()
        self.assert_job_deleted_once()

    def test_410_after_404_ends_job(self):
        self.assertEqual(self.scan([b"1", 404, 410], states=[LOADED]), [b"1"])
        self.assertEqual(self.fake.status_calls, 1)

    def test_503_is_retried_without_asking_for_adf_state(self):
        pages = self.scan([503, 503, b"1", 410], states=[LOADED])
        self.assertEqual(pages, [b"1"])
        self.assertEqual(self.fake.status_calls, 0)
        self.assertEqual(self.sleep.call_args_list, [mock.call(1), mock.call(1)])

    def test_permanent_503_still_times_out(self):
        with self.assertRaises(TimeoutError):
            self.scan([], exhausted=503)
        self.assertEqual(self.fake.next_document_calls, 30)
        self.assert_job_deleted_once()

    def test_permanent_404_while_loaded_hits_the_upper_limit(self):
        with self.assertRaises(TimeoutError):
            self.scan([b"1"], states=[LOADED])
        self.assertEqual(self.fake.next_document_calls, 1 + sc._ADF_MAX_MISSES + 1)
        self.assert_job_deleted_once()

    def test_upper_limit_counts_only_404_without_new_page(self):
        documents = [step for page in range(40) for step in (b"p", 404, 404)]
        pages = self.scan(documents, states=[*[LOADED] * 80, EMPTY])
        self.assertEqual(len(pages), 40)

    def test_other_http_errors_still_propagate(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.scan([b"1", 500])
        self.assert_job_deleted_once()

    def test_cancel_during_wait_stops_scan(self):
        cancel = threading.Event()
        self.sleep.side_effect = lambda _delay: cancel.set()
        with self.assertRaises(InterruptedError):
            self.scan([b"1"], states=[LOADED], cancel_event=cancel)
        self.assert_job_deleted_once()


if __name__ == "__main__":
    unittest.main()
