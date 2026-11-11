"""Offline-Tests der Scanner-Kaskade.

Ausführen: python3 -m unittest discover -s tests -v

Ohne pycups (z.B. im Debian-Build, dort fehlt python3-cups in den
Build-Depends) überspringen sich diese Tests selbst.
"""
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from print_ease import avahi_client, scanner_client as sc
except ImportError as exc:
    raise unittest.SkipTest(f"print_ease nicht importierbar: {exc}")

from print_ease.printer_model import NetworkPrinter, PrinterInfo, ScannerInfo


def printer(uri: str, name: str = "Queue") -> PrinterInfo:
    return PrinterInfo(name, "", "", False, False, "idle", "", uri)


def net(address, host="dev.local", ty="Model", instance="Instance", uuid="") -> NetworkPrinter:
    return NetworkPrinter(
        ty, host, address, 631, f"ipp://{host}:631/ipp/print", "_ipp._tcp",
        {"UUID": uuid} if uuid else {}, instance,
    )


def scanner(url: str, linked: str | None) -> ScannerInfo:
    return ScannerInfo("S", "h", 80, url, "S", 1, 1, [], [], [], linked)


class EsclUrlFor(unittest.TestCase):
    def test_uris(self):
        cases = {
            "ipp://printer.local:631/ipp/print": "http://printer.local/eSCL",
            "ipps://printer.local:443/ipp/print": "https://printer.local/eSCL",
            "ipps://printer.local:631/ipp/print": "https://printer.local/eSCL",
            "ipp://192.168.0.116/ipp/print": "http://192.168.0.116/eSCL",
            "ipp://localhost:60000/ipp/print": "http://localhost:60000/eSCL",
            "http://192.168.0.116:8080/ipp": "http://192.168.0.116:8080/eSCL",
            "dnssd://Canon%20TS700._ipp._tcp.local/?uuid=abc": None,
            "implicitclass://Canon_TS700/": None,
            "usb://Canon/TS700?serial=1": None,
            "file:/dev/null": None,
            "ipp:///ipp/print": None,
            "ipp://:631/ipp/print": None,
            "ipp://host:notaport/ipp/print": None,
            "": None,
        }
        for uri, expected in cases.items():
            with self.subTest(uri=uri):
                self.assertEqual(sc._escl_url_for(printer(uri)), expected)


class PrinterIps(unittest.TestCase):
    def test_ip_literal_needs_no_avahi(self):
        for uri in ("ipp://192.168.0.5/ipp/print", "socket://192.168.0.5:9100", "lpd://192.168.0.5/q"):
            with self.subTest(uri=uri):
                self.assertEqual(sc._printer_ips(printer(uri), []), {"192.168.0.5"})

    def test_mdns_host_is_case_insensitive(self):
        network = [net("10.0.0.1", host="ET788C.local")]
        self.assertEqual(sc._printer_ips(printer("ipp://et788c.local.:631/x"), network), {"10.0.0.1"})

    def test_dnssd_by_uuid_beats_name(self):
        network = [net("10.0.0.1", instance="Other", uuid="AB-CD"), net("10.0.0.2", instance="Canon TS700")]
        uri = "dnssd://Canon%20TS700._ipp._tcp.local/?uuid=ab-cd"
        self.assertEqual(sc._printer_ips(printer(uri), network), {"10.0.0.1"})

    def test_dnssd_by_instance_name(self):
        network = [net("10.0.0.1", instance="Canon TS700")]
        for service in ("_ipp", "_ipps", "_pdl-datastream"):
            with self.subTest(service=service):
                uri = f"dnssd://Canon%20TS700.{service}._tcp.local./"
                self.assertEqual(sc._printer_ips(printer(uri), network), {"10.0.0.1"})

    def test_implicitclass_matches_ty(self):
        network = [net("10.0.0.1", ty="RICOH M C240FW", instance="M C240FW")]
        uri = "implicitclass://RICOH_M_C240FW/"
        self.assertEqual(sc._printer_ips(printer(uri), network), {"10.0.0.1"})

    def test_two_identical_models_stay_unassigned(self):
        network = [net("10.0.0.1", ty="Same"), net("10.0.0.2", ty="Same")]
        self.assertEqual(sc._printer_ips(printer("implicitclass://Same/"), network), set())

    def test_no_address_for_local_uris(self):
        network = [net("10.0.0.1", host="canon", ty="Canon")]
        for uri in ("usb://Canon/TS700", "file:/dev/null", "", "ipp:///x"):
            with self.subTest(uri=uri):
                self.assertEqual(sc._printer_ips(printer(uri), network), set())


class AvahiScannerUrls(unittest.TestCase):
    def browse(self, service, _timeout):
        return {
            "_uscan._tcp": [
                '+;wlan0;IPv4;M\\032C240FW;_uscan._tcp;local',
                '=;wlan0;IPv4;M;_uscan._tcp;local;h.local;10.0.0.1;80;"rs=eSCL" "ty=X"',
                '=;wlan0;IPv6;M;_uscan._tcp;local;h.local;10.0.0.1;80;"rs=eSCL"',
                '=;wlan0;IPv4;N;_uscan._tcp;local;n.local;10.0.0.2;8080;"rs=/scan/"',
            ],
            "_uscans._tcp": ['=;wlan0;IPv4;M;_uscans._tcp;local;h.local;10.0.0.1;443;"ty=X"'],
        }[service]

    def test_parsing(self):
        with mock.patch.object(avahi_client, "_browse", self.browse):
            self.assertEqual(sc._avahi_scanner_urls(), [
                "http://10.0.0.1/eSCL",
                "http://10.0.0.2:8080/scan",
                "https://10.0.0.1/eSCL",
            ])


class DiscoverScanners(unittest.TestCase):
    def run_discovery(self, avahi_urls, linked, responding):
        probed = []

        def caps(url, linked_printer=None, timeout=None):
            probed.append(url)
            return scanner(url, linked_printer) if url in responding else None

        with mock.patch.object(sc, "_avahi_scanner_urls", return_value=avahi_urls), \
             mock.patch.object(sc, "get_scanner_capabilities", caps):
            return sc.discover_scanners(linked), probed

    def test_one_device_is_reported_once(self):
        urls = ["http://10.0.0.1/eSCL", "https://10.0.0.1/eSCL"]
        found, _ = self.run_discovery(urls, {"10.0.0.1": "Q"}, set(urls))
        self.assertEqual([(s.escl_url, s.linked_printer) for s in found], [("http://10.0.0.1/eSCL", "Q")])

    def test_ip_probe_finds_device_without_avahi_record(self):
        found, _ = self.run_discovery([], {"10.0.0.1": "Q"}, {"https://10.0.0.1/eSCL"})
        self.assertEqual([s.escl_url for s in found], ["https://10.0.0.1/eSCL"])

    def test_avahi_url_beats_ip_probe(self):
        avahi, probe = "http://10.0.0.1:8080/eSCL", "http://10.0.0.1/eSCL"
        found, _ = self.run_discovery([avahi], {"10.0.0.1": "Q"}, {avahi, probe})
        self.assertEqual([s.escl_url for s in found], [avahi])

    def test_unlinked_avahi_scanner_is_reported_without_printer(self):
        url = "http://10.0.0.9/eSCL"
        found, _ = self.run_discovery([url], {}, {url})
        self.assertEqual([s.linked_printer for s in found], [None])


class FindScannerForPrinter(unittest.TestCase):
    def setUp(self):
        self.caps = mock.patch.object(sc, "get_scanner_capabilities", return_value=None).start()
        self.linked = mock.patch.object(sc, "linked_printers_by_ip", return_value={}).start()
        self.urls = mock.patch.object(sc, "_avahi_scanner_urls", return_value=[]).start()
        self.probe = mock.patch.object(sc, "_probe_hosts", return_value=[]).start()
        self.resolve = mock.patch.object(avahi_client, "resolve_host", return_value=None).start()
        self.addCleanup(mock.patch.stopall)

    def test_a_uri_hit_wins_over_discovery(self):
        hit = scanner("http://h/eSCL", "Q")
        self.caps.return_value = hit
        self.assertIs(sc.find_scanner_for_printer(printer("ipp://h/ipp/print", "Q")), hit)
        self.probe.assert_not_called()

    def test_a_local_name_is_probed_by_ip(self):
        self.resolve.return_value = "10.0.0.1"
        sc.find_scanner_for_printer(printer("ipp://Dev.local.:8080/ipp/print", "Q"))
        self.resolve.assert_called_once_with("dev.local")
        self.assertEqual(self.caps.call_args.args[0], "http://10.0.0.1:8080/eSCL")

    def test_a_unresolvable_local_name_is_never_probed(self):
        hit = scanner("http://10.0.0.1/eSCL", "Q")
        self.linked.return_value = {"10.0.0.1": "Q"}
        self.probe.return_value = [hit]
        self.assertIs(sc.find_scanner_for_printer(printer("ipp://dev.local/ipp/print", "Q")), hit)
        self.caps.assert_not_called()

    def test_b_dnssd_falls_through_to_discovery(self):
        hit = scanner("http://10.0.0.1/eSCL", "Q")
        self.linked.return_value = {"10.0.0.1": "Q"}
        self.probe.return_value = [hit]
        self.assertIs(sc.find_scanner_for_printer(printer("dnssd://x._ipp._tcp.local/", "Q")), hit)
        self.caps.assert_not_called()

    def test_failed_uri_probe_falls_through_to_discovery(self):
        hit = scanner("https://10.0.0.1/eSCL", "Q")
        self.linked.return_value = {"10.0.0.1": "Q"}
        self.probe.return_value = [hit]
        self.assertIs(sc.find_scanner_for_printer(printer("ipp://10.0.0.1/ipp/print", "Q")), hit)

    def test_scanner_of_another_printer_is_not_returned(self):
        self.linked.return_value = {"10.0.0.1": "Q", "10.0.0.2": "Other"}
        self.probe.return_value = [scanner("http://10.0.0.2/eSCL", "Other")]
        self.assertIsNone(sc.find_scanner_for_printer(printer("dnssd://x._ipp._tcp.local/", "Q")))

    def test_d_usb_printer_never_gets_a_network_scanner(self):
        self.linked.return_value = {"10.0.0.2": "Other"}
        self.probe.return_value = [scanner("http://10.0.0.2/eSCL", "Other")]
        self.assertIsNone(sc.find_scanner_for_printer(printer("usb://Canon/TS700", "Q")))
        self.probe.assert_not_called()

    def test_hanging_avahi_cannot_exceed_the_deadline(self):
        self.linked.side_effect = lambda *_: time.sleep(1) or {}
        started = time.monotonic()
        with mock.patch.object(sc, "SCANNER_SEARCH_TIMEOUT", 0.1):
            self.assertIsNone(sc.find_scanner_for_printer(printer("usb://x/y", "Q")))
        self.assertLess(time.monotonic() - started, 0.5)

    def test_probes_only_get_the_remaining_time(self):
        self.linked.return_value = {"10.0.0.1": "Q"}
        with mock.patch.object(sc, "SCANNER_SEARCH_TIMEOUT", 1):
            sc.find_scanner_for_printer(printer("ipp://10.0.0.1/ipp/print", "Q"))
        self.assertLessEqual(self.caps.call_args.kwargs["timeout"], 1)
        self.assertLessEqual(self.probe.call_args.args[2], 1)


class ResolveHost(unittest.TestCase):
    def run_with(self, **kwargs):
        with mock.patch.object(avahi_client.subprocess, "run", **kwargs) as run:
            return avahi_client.resolve_host("dev.local"), run

    def test_success(self):
        done = subprocess.CompletedProcess([], 0, "dev.local\t10.0.0.1\n", "")
        ip, run = self.run_with(return_value=done)
        self.assertEqual(ip, "10.0.0.1")
        self.assertEqual(run.call_args.kwargs["timeout"], 2)

    def test_failures_mean_none(self):
        cases = {
            "not found": {"return_value": subprocess.CompletedProcess([], 1, "", "Timeout")},
            "empty": {"return_value": subprocess.CompletedProcess([], 0, "", "")},
            "timeout": {"side_effect": subprocess.TimeoutExpired("x", 2)},
            "not installed": {"side_effect": FileNotFoundError("x")},
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                self.assertIsNone(self.run_with(**kwargs)[0])


class LinkedPrintersByIp(unittest.TestCase):
    def test_prefer_wins_when_two_queues_share_a_device(self):
        queues = [printer("ipp://10.0.0.1/a", "First"), printer("ipp://10.0.0.1/b", "Second")]
        with mock.patch.object(sc.avahi_client, "discover_network_printers", return_value=[]), \
             mock.patch.object(sc.cups_client, "get_printers", return_value=queues):
            self.assertEqual(sc.linked_printers_by_ip(prefer="First"), {"10.0.0.1": "First"})
            self.assertEqual(sc.linked_printers_by_ip(prefer="Second"), {"10.0.0.1": "Second"})


class CapabilityProbeErrors(unittest.TestCase):
    def test_non_oserror_failures_mean_no_scanner(self):
        import http.client
        for error in (http.client.BadStatusLine("x"), http.client.InvalidURL("x"), ValueError("x")):
            with self.subTest(error=error), mock.patch.object(sc.urllib.request, "urlopen", side_effect=error):
                self.assertIsNone(sc.get_scanner_capabilities("http://h/eSCL"))


class AvahiInstanceName(unittest.TestCase):
    def test_instance_name_is_decoded_and_kept(self):
        line = '=;wlan0;IPv4;M\\032C240FW;Internet Printer;local;h.local;10.0.0.1;631;"ty=RICOH M C240FW"'
        (parsed,) = avahi_client._parse([line], "_ipp._tcp")
        self.assertEqual((parsed.instance_name, parsed.name), ("M C240FW", "RICOH M C240FW"))

    def test_avahi_escapes_are_decimal(self):
        self.assertEqual(avahi_client._decode_avahi_name("A\\032B\\058C"), "A B:C")


if __name__ == "__main__":
    unittest.main()
