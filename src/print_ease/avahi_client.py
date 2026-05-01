from __future__ import annotations

import re
import subprocess

from print_ease._log import get_logger
from print_ease.constants import AVAHI_TIMEOUT
from print_ease.printer_model import NetworkPrinter

log = get_logger(__name__)


def discover_network_printers(timeout: int = AVAHI_TIMEOUT) -> list[NetworkPrinter]:
    """
    Findet Netzwerkdrucker via avahi-browse (IPP + IPPS, nur IPv4).
    Duplikate (gleiche IP + Port) werden gefiltert.
    """
    log.info("Starte Netzwerkdrucker-Suche (timeout=%ds)", timeout)

    seen: set[tuple[str, int]] = set()
    result: list[NetworkPrinter] = []

    for service_type in ("_ipp._tcp", "_ipps._tcp"):
        lines = _browse(service_type, timeout)
        for printer in _parse(lines, service_type):
            key = (printer.address, printer.port)
            if key not in seen:
                seen.add(key)
                result.append(printer)

    log.info("Netzwerkdrucker gefunden: %d", len(result))
    for p in result:
        log.debug("  %s @ %s → %s", p.name, p.address, p.uri)

    return result


# ---------------------------------------------------------------------------
# Internes
# ---------------------------------------------------------------------------

def _browse(service_type: str, timeout: int) -> list[str]:
    """Führt avahi-browse -r -t -p aus und gibt die Ausgabezeilen zurück."""
    try:
        proc = subprocess.run(
            ["avahi-browse", "-r", "-t", "-p", service_type],
            capture_output=True,
            text=True,
            timeout=timeout + 2,  # etwas Puffer über den avahi-browse-eigenen Timeout
        )
        return proc.stdout.splitlines()
    except FileNotFoundError:
        log.warning("avahi-browse nicht gefunden — Netzwerkdrucker-Suche nicht möglich")
        return []
    except subprocess.TimeoutExpired:
        log.warning("avahi-browse Timeout nach %ds für %s", timeout, service_type)
        return []
    except Exception as exc:
        log.error("avahi-browse Fehler (%s): %s", service_type, exc)
        return []


def _parse(lines: list[str], service_type: str) -> list[NetworkPrinter]:
    """
    Parst avahi-browse -p Ausgabe.
    Format der aufgelösten Einträge (=):
      =;iface;protocol;name;svc_label;domain;hostname;address;port;txt_fields
    """
    printers: list[NetworkPrinter] = []

    for line in lines:
        if not line.startswith("="):
            continue

        parts = line.split(";", 9)
        if len(parts) < 10:
            continue

        _, _iface, protocol, raw_name, _svc_label, _domain, hostname, address, port_str, txt_raw = parts

        # IPv4 bevorzugen — IPv6-Einträge überspringen (selbe IP erscheint doppelt)
        if protocol != "IPv4":
            continue

        try:
            port = int(port_str)
        except ValueError:
            log.debug("Ungültiger Port '%s' in Zeile: %s", port_str, line[:80])
            continue

        name = _decode_avahi_name(raw_name)
        txt = _parse_txt(txt_raw)

        rp = txt.get("rp", "ipp/print")
        display_name = txt.get("ty") or name
        scheme = "ipps" if service_type == "_ipps._tcp" else "ipp"
        uri = f"{scheme}://{hostname}:{port}/{rp}"

        printers.append(NetworkPrinter(
            name=display_name,
            host=hostname,
            address=address,
            port=port,
            uri=uri,
            service_type=service_type,
            txt_records=txt,
        ))

    return printers


def _decode_avahi_name(name: str) -> str:
    """Dekodiert avahi-Escape-Sequenzen: \\032 → Leerzeichen."""
    return re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1), 8)), name)


def _parse_txt(txt_raw: str) -> dict[str, str]:
    """Parst TXT-Record-String: "key=val" "key2=val2" → dict."""
    result: dict[str, str] = {}
    for match in re.finditer(r'"([^"]*)"', txt_raw):
        item = match.group(1)
        if "=" in item:
            key, _, value = item.partition("=")
            result[key] = value
    return result
