"""Tests für den zeroconf-Fallback (Discovery ohne avahi-Programme, z. B. im Flatpak)."""
from __future__ import annotations

import subprocess
import sys
import types
import unittest
from unittest import mock

from print_ease import avahi_client
from print_ease import scanner_client as sc

R = avahi_client._Record


class BrowseFallback(unittest.TestCase):
    def setUp(self):
        mock.patch.object(avahi_client, "_browse_avahi", return_value=None).start()
        self.zc = mock.patch.object(avahi_client, "_zeroconf_records").start()
        self.addCleanup(mock.patch.stopall)

    def test_scanner_urls_come_from_zeroconf_without_avahi(self):
        self.zc.side_effect = lambda types_, _t: {
            "_uscan._tcp": {"_uscan._tcp": [R("M C240FW", "h.local", "10.0.0.1", 80, {"rs": "eSCL"})]},
            "_uscans._tcp": {"_uscans._tcp": [R("M C240FW", "h.local", "10.0.0.1", 443, {"rs": "/eSCL"}),
                                              R("N", "n.local", "10.0.0.2", 8443, {})]},
        }[types_[0]]
        self.assertEqual(sc._avahi_scanner_urls(), [
            "http://10.0.0.1/eSCL",
            "https://10.0.0.1/eSCL",
            "https://10.0.0.2:8443/eSCL",
        ])

    def test_avahi_line_roundtrip_keeps_odd_names(self):
        rec = R("Büro; 2. OG \\ links", "h.local", "10.0.0.1", 631, {"ty": "X Y", "rp": "ipp/print"})
        self.zc.return_value = {"_ipp._tcp": [rec]}
        lines = avahi_client._browse("_ipp._tcp", 1)
        printer, = avahi_client._parse(lines, "_ipp._tcp")
        self.assertEqual(printer.instance_name, rec.name)
        self.assertEqual((printer.host, printer.address, printer.port), ("h.local", "10.0.0.1", 631))
        self.assertEqual(printer.txt_records, rec.txt)
        self.assertEqual(printer.uri, "ipp://h.local:631/ipp/print")

    def test_printer_discovery_uses_one_zeroconf_pass_for_both_types(self):
        self.zc.return_value = {
            "_ipp._tcp": [R("A", "a.local", "10.0.0.1", 631, {"ty": "A"})],
            "_ipps._tcp": [R("A", "a.local", "10.0.0.1", 631, {}), R("B", "b.local", "10.0.0.2", 443, {})],
        }
        printers = avahi_client.discover_network_printers(timeout=1)
        self.zc.assert_called_once_with(["_ipp._tcp", "_ipps._tcp"], 1)
        self.assertEqual([(p.address, p.port, p.service_type) for p in printers],
                         [("10.0.0.1", 631, "_ipp._tcp"), ("10.0.0.2", 443, "_ipps._tcp")])


class ScannerWindow(unittest.TestCase):
    def test_scanner_search_uses_the_scanner_window(self):
        with mock.patch.object(avahi_client, "_browse", return_value=[]) as browse, \
             mock.patch.object(sc.avahi_client, "discover_network_printers", return_value=[]) as disc, \
             mock.patch.object(sc.cups_client, "get_printers", return_value=[]):
            sc._avahi_scanner_urls()
            sc.linked_printers_by_ip()
        self.assertEqual({c.args[1] for c in browse.call_args_list}, {sc.SCANNER_MDNS_WINDOW})
        self.assertEqual(disc.call_args.kwargs["timeout"], sc.SCANNER_MDNS_WINDOW)
        self.assertEqual(sc.SCANNER_MDNS_WINDOW, 3)


class ResolveHostFallback(unittest.TestCase):
    def run_with(self, **kwargs):
        with mock.patch.object(avahi_client.subprocess, "run", **kwargs), \
             mock.patch.object(avahi_client, "_resolve_zeroconf", return_value="10.0.0.9") as zc:
            return avahi_client.resolve_host("dev.local"), zc

    def test_missing_avahi_tool_uses_zeroconf(self):
        ip, zc = self.run_with(side_effect=FileNotFoundError("avahi-resolve-host-name"))
        self.assertEqual(ip, "10.0.0.9")
        zc.assert_called_once_with("dev.local", 2)

    def test_dead_daemon_uses_zeroconf(self):
        done = subprocess.CompletedProcess([], 1, "", "Failed to create client object: Daemon not running\n")
        self.assertEqual(self.run_with(return_value=done)[0], "10.0.0.9")

    def test_unknown_host_does_not_ask_twice(self):
        done = subprocess.CompletedProcess([], 1, "", "Failed to resolve host name 'dev.local': Timeout reached\n")
        ip, zc = self.run_with(return_value=done)
        self.assertIsNone(ip)
        zc.assert_not_called()


class ZeroconfRecords(unittest.TestCase):
    """_zeroconf_records gegen ein nachgebautes zeroconf-Modul."""

    def setUp(self):
        self.calls = calls = []

        class Info:
            def __init__(self, type_, name):
                self.type_, self.name = type_, name
                self.port, self.server = 631, "h.local."
                self.properties = {b"ty": b"Model", b"empty": None}

            def request(self, zc, timeout, question_type=None):
                calls.append(("request", self.name, question_type))
                return not self.name.startswith("lost")

            def parsed_addresses(self, version=None):
                return ["10.0.0.1"]

        class Browser:
            def __init__(self, zc, types_, listener, question_type=None):
                calls.append(("browse", tuple(types_), question_type))
                listener.add_service(zc, "_ipp._tcp.local.", "P._ipp._tcp.local.")
                listener.update_service(zc, "_ipp._tcp.local.", "P._ipp._tcp.local.")
                listener.add_service(zc, "_ipp._tcp.local.", "lost._ipp._tcp.local.")

            def cancel(self):
                calls.append(("cancel",))

        fake = types.ModuleType("zeroconf")
        fake.DNSQuestionType = types.SimpleNamespace(QM="QM", QU="QU")
        fake.IPVersion = types.SimpleNamespace(V4Only="v4")
        fake.ServiceBrowser, fake.ServiceInfo = Browser, Info
        fake.ServiceListener = object
        fake.Zeroconf = lambda: mock.Mock()
        mock.patch.dict(sys.modules, {"zeroconf": fake}).start()
        mock.patch.object(avahi_client.time, "sleep", lambda s: calls.append(("sleep", s))).start()
        self.addCleanup(mock.patch.stopall)

    def test_one_browse_qm_only_resolved_after_window(self):
        result = avahi_client._zeroconf_records(["_ipp._tcp", "_ipps._tcp"], 5)
        self.assertEqual(result, {
            "_ipp._tcp": [R("P", "h.local", "10.0.0.1", 631, {"ty": "Model"})],
            "_ipps._tcp": [],
        })
        kinds = [c[0] for c in self.calls]
        self.assertEqual(kinds, ["browse", "sleep", "cancel", "request", "request"])
        self.assertEqual(self.calls[0], ("browse", ("_ipp._tcp.local.", "_ipps._tcp.local."), "QM"))
        self.assertTrue(all(c[2] == "QM" for c in self.calls if c[0] == "request"))

    def test_missing_zeroconf_means_empty(self):
        with mock.patch.dict(sys.modules, {"zeroconf": None}):
            self.assertEqual(avahi_client._zeroconf_records(["_ipp._tcp"], 1), {})
            self.assertIsNone(avahi_client._resolve_zeroconf("dev.local", 1))


if __name__ == "__main__":
    unittest.main()
