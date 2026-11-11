from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field

from print_ease._log import get_logger
from print_ease.constants import AVAHI_RESOLVE_TIMEOUT, AVAHI_TIMEOUT
from print_ease.printer_model import NetworkPrinter

log = get_logger(__name__)


def discover_network_printers(timeout: int = AVAHI_TIMEOUT) -> list[NetworkPrinter]:
    """
    Findet Netzwerkdrucker via mDNS/DNS-SD (IPP + IPPS, nur IPv4).

    Primär über avahi-browse (nutzt den System-Daemon und dessen Cache).
    Fällt automatisch auf python-zeroconf zurück, wenn avahi-browse fehlt
    oder fehlschlägt (z. B. in einer Flatpak-Sandbox oder auf Systemen
    ohne laufenden avahi-daemon). Duplikate (gleiche IP + Port) werden
    gefiltert.
    """
    log.info("Starte Netzwerkdrucker-Suche (timeout=%ds)", timeout)

    seen: set[tuple[str, int]] = set()
    result: list[NetworkPrinter] = []

    service_types = ("_ipp._tcp", "_ipps._tcp")
    found: dict[str, list[NetworkPrinter]] = {}
    fallback: list[str] = []
    for service_type in service_types:
        lines = _browse_avahi(service_type, timeout)
        if lines is None:
            fallback.append(service_type)
        else:
            found[service_type] = _parse(lines, service_type)
    if fallback:
        # Ein gemeinsames Suchfenster für alle Typen statt eines je Typ
        records = _zeroconf_records(fallback, timeout)
        for service_type in fallback:
            found[service_type] = [
                _make_printer(r.name, r.hostname, r.address, r.port, r.txt, service_type)
                for r in records.get(service_type, [])
            ]

    for service_type in service_types:
        for printer in found[service_type]:
            key = (printer.address, printer.port)
            if key not in seen:
                seen.add(key)
                result.append(printer)

    log.info("Netzwerkdrucker gefunden: %d", len(result))
    for p in result:
        log.debug("  %s @ %s → %s", p.name, p.address, p.uri)

    return result


def resolve_host(hostname: str, timeout: float = AVAHI_RESOLVE_TIMEOUT) -> str | None:
    """
    Löst einen .local-Namen in eine IPv4-Adresse auf, None wenn das nicht gelingt.

    Anders als die libc-Auflösung lässt sich das nach `timeout` abbrechen.
    Primär über avahi-resolve-host-name; fehlt das Programm oder läuft der
    avahi-daemon nicht (Flatpak-Sandbox), fragt python-zeroconf direkt per mDNS.
    """
    try:
        proc = subprocess.run(
            ["avahi-resolve-host-name", "-4", "--", hostname],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.info("%s nach %.1fs nicht aufgelöst", hostname, timeout)
        return None
    except FileNotFoundError:
        log.info("avahi-resolve-host-name nicht gefunden — nutze zeroconf-Fallback")
        return _resolve_zeroconf(hostname, timeout)
    except OSError as exc:
        log.warning("avahi-resolve-host-name nicht ausführbar: %s", exc)
        return None

    if proc.returncode != 0 and "daemon not running" in (proc.stderr or "").lower():
        log.info("avahi-daemon läuft nicht — nutze zeroconf-Fallback")
        return _resolve_zeroconf(hostname, timeout)

    fields = proc.stdout.split()
    return fields[1] if proc.returncode == 0 and len(fields) == 2 else None


# ---------------------------------------------------------------------------
# Weg 1: avahi-browse (System-Daemon)
# ---------------------------------------------------------------------------

def _browse(service_type: str, timeout: int) -> list[str]:
    """
    Gibt die Ausgabezeilen von avahi-browse -r -t -p zurück ([] bei Fehler).

    Ist avahi nicht nutzbar, kommen die Zeilen aus python-zeroconf und sind
    im selben Format nachgebildet — Aufrufer (Scanner-Suche) merken keinen
    Unterschied.
    """
    lines = _browse_avahi(service_type, timeout)
    if lines is not None:
        return lines
    records = _zeroconf_records([service_type], timeout).get(service_type, [])
    return [r.to_avahi_line(service_type) for r in records]


def _browse_avahi(service_type: str, timeout: int) -> list[str] | None:
    """
    Wie _browse, aber None heißt: avahi-Weg nicht nutzbar → Fallback versuchen.

    (Fehlendes Binary, toter Daemon oder unerwarteter Fehler. Ein Timeout bei
    laufendem Daemon bleibt eine leere Liste — der Daemon war erreichbar, es
    gab nur nichts zu finden.)
    """
    try:
        proc = subprocess.run(
            ["avahi-browse", "-r", "-t", "-p", service_type],
            capture_output=True,
            text=True,
            timeout=timeout + 2,  # etwas Puffer über den avahi-browse-eigenen Timeout
        )
    except FileNotFoundError:
        log.info("avahi-browse nicht gefunden — nutze zeroconf-Fallback")
        return None
    except subprocess.TimeoutExpired:
        log.warning("avahi-browse Timeout nach %ds für %s", timeout, service_type)
        return []
    except Exception as exc:
        log.error("avahi-browse Fehler (%s): %s — nutze zeroconf-Fallback", service_type, exc)
        return None

    if proc.returncode != 0:
        # Typisch: "Failed to create client object: Daemon not running"
        first = (proc.stderr or "").strip().splitlines()
        log.warning(
            "avahi-browse fehlgeschlagen (rc=%d): %s — nutze zeroconf-Fallback",
            proc.returncode,
            first[0] if first else "",
        )
        return None
    return proc.stdout.splitlines()


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
        printers.append(_make_printer(name, hostname, address, port, txt, service_type))

    return printers


# ---------------------------------------------------------------------------
# Weg 2: python-zeroconf (eigene Multicast-Sockets, kein Daemon nötig)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Record:
    """Ein aufgelöster mDNS-Dienst, unabhängig vom Discovery-Weg."""
    name: str               # Instanzname, z. B. "Canon TS700 series"
    hostname: str           # ohne Schlusspunkt, z. B. "E1F4F9000000.local"
    address: str            # IPv4
    port: int
    txt: dict[str, str] = field(default_factory=dict)

    def to_avahi_line(self, service_type: str) -> str:
        """Zeile wie avahi-browse -r -p sie ausgibt (für _parse / Scanner-Suche)."""
        txt = " ".join(f'"{k}={v}"' for k, v in self.txt.items())
        return ";".join((
            "=", "zeroconf", "IPv4", _encode_avahi_name(self.name), service_type, "local",
            self.hostname, self.address, str(self.port), txt,
        ))


def _browse_zeroconf(service_type: str, timeout: int) -> list[NetworkPrinter]:
    """
    mDNS-Druckersuche über python-zeroconf. Liefert dieselben NetworkPrinter-
    Objekte wie der avahi-Weg.
    """
    return [
        _make_printer(r.name, r.hostname, r.address, r.port, r.txt, service_type)
        for r in _zeroconf_records([service_type], timeout).get(service_type, [])
    ]


def _zeroconf_records(service_types: list[str], timeout: float) -> dict[str, list[_Record]]:
    """
    Sucht alle `service_types` gleichzeitig per python-zeroconf.

    Läuft komplett im Prozess (eigene Multicast-Sockets) — funktioniert damit
    auch in der Flatpak-Sandbox und ohne avahi-daemon.

    Zwei Details machen das Ergebnis stabil:
    - Nur QM-Fragen (Antwort per Multicast). Die erste Frage wäre sonst QU,
      und die Unicast-Antwort an Port 5353 landet beim avahi-daemon des Hosts,
      wenn der den Port ebenfalls belegt — dann kommt der Dienst erst bei der
      nächsten Wiederholung an, oft erst nach dem Suchfenster.
    - Im Listener werden nur Namen gesammelt; aufgelöst wird nach dem
      Fenster. Die nötigen Records stehen dann meist schon im Cache.
    """
    try:
        from zeroconf import (
            DNSQuestionType,
            IPVersion,
            ServiceBrowser,
            ServiceInfo,
            ServiceListener,
            Zeroconf,
        )
    except ImportError:
        log.warning(
            "python-zeroconf nicht installiert — mDNS-Suche für %s nicht möglich",
            ", ".join(service_types),
        )
        return {}

    full = {f"{t}.local.": t for t in service_types}
    names: dict[str, list[str]] = {t: [] for t in full}

    class _Listener(ServiceListener):
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            if type_ in names and name not in names[type_]:
                names[type_].append(name)

        def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            self.add_service(zc, type_, name)

        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            pass

    try:
        zc = Zeroconf()
    except Exception as exc:
        log.error("zeroconf konnte nicht starten: %s", exc)
        return {}

    result: dict[str, list[_Record]] = {t: [] for t in service_types}
    try:
        browser = ServiceBrowser(
            zc, list(full), _Listener(), question_type=DNSQuestionType.QM
        )
        time.sleep(timeout)
        browser.cancel()

        # Auflösen: aus dem Cache sofort, Nachzügler bekommen zusammen höchstens 2 s
        resolve_deadline = time.monotonic() + 2
        for full_type, svc_names in names.items():
            for name in svc_names:
                info = ServiceInfo(full_type, name)
                remaining_ms = max(int((resolve_deadline - time.monotonic()) * 1000), 1)
                if not info.request(zc, min(remaining_ms, 1000), question_type=DNSQuestionType.QM):
                    log.debug("zeroconf: %s nicht auflösbar", name)
                    continue
                record = _record_from_info(info, full_type, IPVersion.V4Only)
                if record is not None:
                    result[full[full_type]].append(record)
    except Exception as exc:
        log.error("zeroconf-Suche fehlgeschlagen (%s): %s", ", ".join(service_types), exc)
    finally:
        try:
            zc.close()
        except Exception:
            pass

    for service_type, records in result.items():
        log.info("zeroconf: %d Dienste für %s", len(records), service_type)
    return result


def _record_from_info(info, full_type: str, v4only) -> _Record | None:
    # IPv4-Adresse wählen (Verhalten identisch zum avahi-Weg)
    address = next(iter(info.parsed_addresses(v4only)), None)
    if address is None or info.port is None:
        return None

    # "Drucker XY._ipp._tcp.local." → "Drucker XY"
    name = info.name
    suffix = f".{full_type}"
    if name.endswith(suffix):
        name = name[: -len(suffix)]

    txt: dict[str, str] = {}
    for k, v in (info.properties or {}).items():
        if v is None:
            continue
        key = k.decode("utf-8", "replace") if isinstance(k, bytes) else str(k)
        txt[key] = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)

    return _Record(name, (info.server or "").rstrip("."), address, int(info.port), txt)


def _resolve_zeroconf(hostname: str, timeout: float) -> str | None:
    """Löst einen .local-Namen per python-zeroconf in eine IPv4-Adresse auf."""
    try:
        from zeroconf import AddressResolverIPv4, DNSQuestionType, IPVersion, Zeroconf
    except ImportError:
        log.warning("python-zeroconf nicht installiert — %s nicht auflösbar", hostname)
        return None

    try:
        zc = Zeroconf()
    except Exception as exc:
        log.error("zeroconf konnte nicht starten: %s", exc)
        return None
    try:
        resolver = AddressResolverIPv4(hostname.rstrip(".") + ".")
        if resolver.request(zc, int(timeout * 1000), question_type=DNSQuestionType.QM):
            address = next(iter(resolver.parsed_addresses(IPVersion.V4Only)), None)
            if address:
                return address
    except Exception as exc:
        log.error("zeroconf-Auflösung von %s fehlgeschlagen: %s", hostname, exc)
        return None
    finally:
        try:
            zc.close()
        except Exception:
            pass
    log.info("%s nach %.1fs nicht aufgelöst (zeroconf)", hostname, timeout)
    return None


# ---------------------------------------------------------------------------
# Gemeinsames
# ---------------------------------------------------------------------------

def _make_printer(
    name: str,
    hostname: str,
    address: str,
    port: int,
    txt: dict[str, str],
    service_type: str,
) -> NetworkPrinter:
    """Baut aus den Rohdaten beider Discovery-Wege ein NetworkPrinter-Objekt."""
    rp = txt.get("rp", "ipp/print")
    display_name = txt.get("ty") or name
    scheme = "ipps" if service_type == "_ipps._tcp" else "ipp"
    uri = f"{scheme}://{hostname}:{port}/{rp}"

    return NetworkPrinter(
        name=display_name,
        host=hostname,
        address=address,
        port=port,
        uri=uri,
        service_type=service_type,
        txt_records=txt,
        instance_name=name,
    )


def _decode_avahi_name(name: str) -> str:
    """Dekodiert avahi-Escape-Sequenzen (dezimal): \\032 → Leerzeichen."""
    return re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1))), name)


def _encode_avahi_name(name: str) -> str:
    """Gegenstück zu _decode_avahi_name: Zeichen, die das Zeilenformat stören, als \\DDD."""
    return "".join(
        f"\\{ord(c):03d}" if c in "\\; " or (ord(c) < 128 and not c.isprintable()) else c
        for c in name
    )


def _parse_txt(txt_raw: str) -> dict[str, str]:
    """Parst TXT-Record-String: "key=val" "key2=val2" → dict."""
    result: dict[str, str] = {}
    for match in re.finditer(r'"([^"]*)"', txt_raw):
        item = match.group(1)
        if "=" in item:
            key, _, value = item.partition("=")
            result[key] = value
    return result
