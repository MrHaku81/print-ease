"""Welche Gruppe gibt CUPS-Verwaltungsrechte? (ohne GTK, ohne pycups)

Maßgeblich ist ``SystemGroup`` in /etc/cups/cups-files.conf, z. B.
Debian/Ubuntu/Mint ``lpadmin``, Arch/Fedora standardmäßig ``sys root wheel``.
Die Gruppe ``lp`` gibt keine Verwaltungsrechte.
"""
from __future__ import annotations

import grp
import re
from pathlib import Path

from print_ease._i18n import _
from print_ease._log import get_logger

log = get_logger(__name__)

CUPS_FILES_CONF = Path("/etc/cups/cups-files.conf")
FLATPAK_INFO = Path("/.flatpak-info")
# Im Flatpak liegt die os-release des Hosts hier (die eigene beschreibt die Laufzeit).
HOST_OS_RELEASE = Path("/run/host/os-release")


def _system_groups(text: str) -> list[str]:
    """
    Alle Gruppen aus den SystemGroup-Zeilen, in Reihenfolge.

    Wie cupsd (scheduler/conf.c, parse_groups): Direktive ohne Rücksicht auf
    Groß-/Kleinschreibung, mehrere Zeilen werden aneinandergehängt, Trennung
    durch Leerzeichen oder Komma, Namen dürfen in '…' oder "…" stehen.
    """
    groups: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "systemgroup":
            continue
        for quoted_single, quoted_double, plain in re.findall(
            r"'([^']*)'|\"([^\"]*)\"|([^\s,'\"]+)", parts[1]
        ):
            name = quoted_single or quoted_double or plain
            if name:
                groups.append(name)
    return groups


def _group_exists(name: str) -> bool:
    try:
        grp.getgrnam(name)
    except KeyError:
        return False
    return True


def _os_release_ids(path: Path) -> set[str] | None:
    """ID und ID_LIKE aus einer os-release-Datei (kleingeschrieben); None, wenn nicht lesbar."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.debug("%s nicht lesbar: %s", path, exc)
        return None
    ids: set[str] = set()
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in ("ID", "ID_LIKE"):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            ids.update(value.lower().split())
    return ids


def _flatpak_host_admin_group() -> str:
    """
    Im Flatpak: Die Sandbox hat weder cups-files.conf noch die Gruppen des
    Hosts (/etc/group enthält nur den Benutzer). Daher die Distribution des
    Hosts aus /run/host/os-release: Debian-Familie -> lpadmin, sonst wheel.
    """
    ids = _os_release_ids(HOST_OS_RELEASE)
    group = "lpadmin" if ids and "debian" in ids else "wheel"
    log.debug("Flatpak: Host-IDs %s -> CUPS-Admin-Gruppe %s", sorted(ids or ()), group)
    return group


def cups_admin_group(conf_path: Path | None = None) -> str:
    """
    Gruppe, die ein Benutzer für CUPS-Verwaltungsrechte braucht.

    1. Aus SystemGroup in cups-files.conf die erste Gruppe außer root, die
       auf dem System existiert.
    2. Datei nicht lesbar und App im Flatpak: nach der os-release des Hosts
       (ID/ID_LIKE enthält debian -> lpadmin, sonst wheel).
    3. Sonst (Datei nicht lesbar, z. B. Rechte root:cups 0640, oder keine
       passende Gruppe): lpadmin, wenn es die Gruppe gibt, sonst wheel.
    """
    if conf_path is None:
        conf_path = CUPS_FILES_CONF
    try:
        text = conf_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.debug("%s nicht lesbar: %s", conf_path, exc)
        if FLATPAK_INFO.exists():
            return _flatpak_host_admin_group()
    else:
        for name in _system_groups(text):
            if name != "root" and _group_exists(name):
                return name
        log.debug("Keine passende SystemGroup in %s", conf_path)
    return "lpadmin" if _group_exists("lpadmin") else "wheel"


def admin_rights_hint(group: str | None = None) -> str:
    """Übersetzter Hinweis, wie man CUPS-Verwaltungsrechte bekommt."""
    if group is None:
        group = cups_admin_group()
    return _(
        "Möglicherweise fehlen die nötigen CUPS-Admin-Rechte.\n\n"
        "Fügen Sie Ihren Benutzer der Gruppe '%(group)s' hinzu:\n"
        "    sudo gpasswd -a $USER %(group)s\n\n"
        "Anschließend einmal abmelden und wieder anmelden."
    ) % {"group": group}
