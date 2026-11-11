"""Hardware-Duplex gegen einen gemockten eSCL-Server.

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


class ScanAdfHardwareDuplex(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch.object(sc.time, "sleep").start()
        self.save = mock.patch.object(sc, "_save_pages", return_value="/out").start()
        self.addCleanup(mock.patch.stopall)

    def scan(self, documents, states=(EMPTY,), exhausted=404, **kwargs):
        self.fake = FakeScanner(documents, states, exhausted)
        self.addCleanup(self.fake.close)
        info = ScannerInfo("S", "h", 80, self.fake.url, "S", 1, 1, [], [], [], None)
        return sc.scan_adf_hardware_duplex(info, **kwargs)

    def saved_pages(self):
        return self.save.call_args.args[0]

    def assert_job_deleted_once(self):
        self.assertEqual(self.fake.deleted, [JOB])

    def test_404_while_loaded_waits_for_next_sheet(self):
        self.scan([b"1v", b"1r", 404, b"2v", b"2r"], states=[LOADED, EMPTY])
        self.assertEqual(self.saved_pages(), [b"1v", b"1r", b"2v", b"2r"])
        self.assert_job_deleted_once()

    def test_multiple_404_while_loaded(self):
        self.scan([b"1", *[404] * 10, b"2"], states=[*[LOADED] * 10, EMPTY])
        self.assertEqual(self.saved_pages(), [b"1", b"2"])

    def test_404_while_empty_still_collects_back_of_last_sheet(self):
        self.scan([b"1v", 404, 404, b"1r"], states=[EMPTY])
        self.assertEqual(self.saved_pages(), [b"1v", b"1r"])

    def test_404_while_empty_ends_after_three_further_attempts(self):
        self.scan([b"1"], states=[EMPTY])
        self.assertEqual(self.fake.next_document_calls, 1 + 1 + 3)
        self.assertEqual(self.sleep.call_count, 3)
        self.assert_job_deleted_once()

    def test_unknown_state_and_jam_are_treated_like_empty(self):
        for state in (None, JAM):
            with self.subTest(state=state):
                self.scan([b"1"], states=[state])
                self.assertEqual(self.fake.next_document_calls, 1 + 1 + 3)

    def test_410_ends_job_immediately(self):
        self.scan([b"1", 410, b"never"], states=[LOADED])
        self.assertEqual(self.saved_pages(), [b"1"])
        self.assertEqual(self.fake.status_calls, 0)
        self.sleep.assert_not_called()
        self.assert_job_deleted_once()

    def test_503_is_retried_without_asking_for_adf_state(self):
        self.scan([503, 503, b"1", 410], states=[LOADED])
        self.assertEqual(self.saved_pages(), [b"1"])
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

    def test_no_pages_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.scan([], states=[EMPTY])
        self.assert_job_deleted_once()

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

    def test_pages_are_sorted_by_sheet_and_side_across_404(self):
        def page(data, sheet, side):
            return data, {"X-Sheet-Number": str(sheet), "X-Side": side}

        self.scan(
            [page(b"1r", 1, "Back"), page(b"1v", 1, "Front"), 404, page(b"2v", 2, "Front")],
            states=[LOADED, EMPTY],
        )
        self.assertEqual(self.saved_pages(), [b"1v", b"1r", b"2v"])

    def test_progress_counts_every_page(self):
        progress = []
        self.scan([b"1", 404, b"2"], states=[LOADED, EMPTY], progress_callback=progress.append)
        self.assertEqual(progress, [1, 2])

    def test_mode_is_passed_on_and_pdf_stays_the_default(self):
        self.scan([b"1"], mode="archive")
        self.assertEqual(self.save.call_args.args[1], "archive")
        self.scan([b"1"])
        self.assertEqual(self.save.call_args.args[1], "multipage")


if __name__ == "__main__":
    unittest.main()
