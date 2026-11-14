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


def cups_admin_group(conf_path: Path = CUPS_FILES_CONF) -> str:
    """
    Gruppe, die ein Benutzer für CUPS-Verwaltungsrechte braucht.

    1. Aus SystemGroup in cups-files.conf die erste Gruppe außer root, die
       auf dem System existiert.
    2. Sonst (Datei nicht lesbar, z. B. Rechte root:cups 0640 oder
       Flatpak-Sandbox, oder keine passende Gruppe): lpadmin, wenn es die
       Gruppe gibt, sonst wheel.
    """
    try:
        text = conf_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.debug("%s nicht lesbar: %s", conf_path, exc)
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
