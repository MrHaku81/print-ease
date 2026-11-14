"""print_ease.gui.scanner_panel importieren – auch ohne PyGObject/GTK.

Die Panel-Tests bauen ScannerPanel mit __new__ und Fake-Widgets; GTK selbst
wird dabei nicht benutzt (Annotationen sind dank ``from __future__ import
annotations`` reine Strings, GLib.idle_add patchen die Tests). Gebraucht wird
gi nur, damit das Modul importiert werden kann.

Ist gi mit Gtk 4 und Adw 1 vorhanden, wird das echte Modul verwendet. Sonst
(z. B. im Debian-Paketbau ohne python3-gi) wird für die Dauer des Imports ein
Platzhalter für ``gi`` und ``gi.repository`` eingesetzt. sys.modules wird
danach wiederhergestellt, andere Tests sehen den Platzhalter nicht.
"""
import sys
import types
from unittest import mock


def _real_gi_available() -> bool:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gio, GLib, Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


REAL_GI = _real_gi_available()


def _stub_modules() -> dict[str, types.ModuleType]:
    gi = types.ModuleType("gi")
    gi.require_version = lambda _namespace, _version: None
    repository = types.ModuleType("gi.repository")
    for name in ("Adw", "Gio", "GLib", "Gtk"):
        setattr(repository, name, mock.MagicMock(name=f"gi.repository.{name}"))
    gi.repository = repository
    return {"gi": gi, "gi.repository": repository}


def import_scanner_panel():
    if REAL_GI or "print_ease.gui.scanner_panel" in sys.modules:
        from print_ease.gui import scanner_panel
        return scanner_panel
    stubs = _stub_modules()
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        from print_ease.gui import scanner_panel
    finally:
        # Nur die gi-Einträge zurücksetzen; die übrigen beim Import geladenen
        # Module (scanner_client, settings, …) bleiben, damit es keine
        # doppelten Modulobjekte gibt.
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return scanner_panel
