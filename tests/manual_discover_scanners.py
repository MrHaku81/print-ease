#!/usr/bin/env python3
"""Echter Lauf gegen CUPS, Avahi und die Geräte im Netz (ohne GUI).

Ausführen: python3 tests/manual_discover_scanners.py

Kein Unit-Test: Das Ergebnis hängt vom Netz ab. Der Dateiname passt bewusst
nicht auf test*.py, damit unittest discover und der Debian-Build ihn auslassen.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from print_ease import cups_client, scanner_client  # noqa: E402


def main() -> int:
    started = time.monotonic()
    linked = scanner_client.linked_printers_by_ip()
    print(f"\nIP-Map ({time.monotonic() - started:.1f} s): {linked}")

    started = time.monotonic()
    scanners = scanner_client.discover_scanners(linked)
    print(f"\ndiscover_scanners ({time.monotonic() - started:.1f} s): {len(scanners)} gefunden")
    for s in scanners:
        print(f"  {s.name} @ {s.escl_url}")
        print(f"    Drucker: {s.linked_printer}  Quellen: {s.document_sources}")
        print(f"    Farben: {s.color_modes}  dpi: {s.resolutions}")

    print("\nKaskade je CUPS-Drucker:")
    for printer in cups_client.get_printers():
        started = time.monotonic()
        scanner = scanner_client.find_scanner_for_printer(printer)
        result = f"{scanner.name} @ {scanner.escl_url}" if scanner else "Kein Scanner gefunden"
        print(f"  {printer.name} ({printer.uri}), {time.monotonic() - started:.1f} s: {result}")

    return 0 if scanners else 1


if __name__ == "__main__":
    sys.exit(main())
