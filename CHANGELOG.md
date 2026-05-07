# Changelog

## [0.1.6] - 2026-05-07

### Added
- New "Standardeinstellungen" (Default Settings) group on the printer
  detail page. Users can now set per-printer CUPS defaults for paper
  format, duplex mode, color mode and print quality directly from the
  GUI — no command-line tools required.
- PWG media names (e.g. `iso_a4_210x297mm`) are translated to readable
  labels (e.g. `A4`) via a new `media_names` module.

### Changed
- Backend functions `get_printer_defaults()` and `set_printer_default()`
  added to `cups_client` for reading and writing CUPS printer defaults
  via pycups `addPrinterOptionDefault()`.

## [0.1.5] - 2026-05-03

### Fixed
- App About dialog now correctly shows the installed version. The
  `APP_VERSION` constant in `src/print_ease/constants.py` was a
  hardcoded "0.1.3" that wasn't bumped during the v0.1.4 release,
  causing the About dialog to display "0.1.3" even on v0.1.4
  installations. Now bumped to "0.1.5" and aligned with all other
  version strings.

## [0.1.4] - 2026-05-03

### Fixed
- Scanner discovery now works with self-signed eSCL certificates.
  Discovery silently failed on systems where CUPS registers AirPrint
  printers with `ipps://` URIs (default on Ubuntu/Debian). Python's
  urllib was rejecting the printer's self-signed certificate. PrintEase
  now creates a permissive SSL context for eSCL traffic, following
  industry standard practice (Apple Print, Mopria).
- Discovery failures are now visible in the log: the "Kein eSCL bei ..."
  message is upgraded from DEBUG to WARNING level.

### Added
- Debian package support. New `debian/` directory enables building
  `.deb` packages via `dpkg-buildpackage` for Debian, Ubuntu, Mint, and
  derivatives. The package is lintian-clean and includes a manpage.

## [0.1.3] — 2026-05-03

### Vorbereitung libcups3-Migration
- cups_client: `_cups_session()` Context-Manager für CUPS-Verbindungen
  eingeführt — ein zentraler Punkt für späteren libcups3-Cleanup
- cups_client: Treiber-Auswahl in `_resolve_driver_kwargs()` extrahiert —
  isoliert die `ppdname="everywhere"`-Logik für späteren libcups3-Switch
- cups_client.get_jobs: Filter-Vergleich von endswith-Heuristik auf
  urlparse-basierten Pfad-Vergleich umgestellt (robuster gegen
  URL-Format-Varianten)
- pyproject.toml: pycups-Dependency auf `>=2,<3` festgepinnt
  (verhindert versehentliche Major-Updates auf inkompatibles pycups3)

### Geändert
- Versionssprung von 0.1.2 auf 0.1.3 in pyproject.toml, constants.py
  und Makefile

### Dokumentation
- docs/cups3-audit.md: vollständiger libcups3-Kompatibilitäts-Audit
- docs/ROADMAP.md: Roadmap v0.1.3 bis v0.5.0+
- docs/v0.2.0-flatbed-multipage.md: Design-Dokument für
  Flachbett-Multipage-Scan (nächstes Feature-Release)

### Hinweis
Die Code-Änderungen in v0.1.3 sind funktional unsichtbar — Verhalten
ist identisch zu v0.1.2. Sie bereiten den späteren libcups3-Switch vor
(siehe docs/cups3-audit.md, Abschnitt 5).

## [0.1.2] — 2026-05-02

### Fixed
- Align version across pyproject.toml, constants.py and Makefile with release tag (was 0.1.0, now 0.1.2)
- Skipped 0.1.1 tag: v0.1.1 was a docs-only patch (README) without Python code changes

## [0.1.1] — 2026-05-02

### Changed
- README: add "How It Works" section explaining plug & play device detection
- README: add "What Gets Installed" section for desktop integration transparency
- README: replace technical subtitle with user-focused tagline

## [0.1.0] — 2026-05-01

### Hinzugefügt

**Projekt-Grundstruktur**
- Projektstruktur angelegt (src-Layout, pyproject.toml, hatchling)
- CUPS-Client via pycups (cups_client.py)
- Avahi-Netzwerkerkennung via avahi-browse (avahi_client.py)
- Datenmodell: PrinterInfo, PrintJob, ScannerInfo, NetworkPrinter (printer_model.py)
- Logging-System: RotatingFileHandler (5 MB, 3 Backups), XDG-Pfad, dev.log-Fallback (_log.py)
- Einstellungen: ~/.config/print-ease/settings.json mit In-Memory-Cache (settings.py)
- Konstanten-Modul mit Timeout-Werten (constants.py): AVAHI=5s, ESCL=3s, CUPS=10s

**GUI**
- GTK4/Adwaita Hauptfenster (MainWindow) mit Two-Pane-Layout
- Druckerliste (Gtk.ListBox) mit PrinterRow: Icon, Name, Status-Badge, Standard-Pill
- Detailansicht (PrinterDetail): Druckerinformationen, Aktionen, Druckjobs
- Drucker hinzufügen: AddPrinterDialog mit Manuell- und Netzwerk-Tab
- Netzwerk-Tab: asynchrone avahi-Suche mit Spinner, Übernahme in Manuell-Tab
- Headerbar: Hinzufügen-Button, Aktualisieren-Button, Sprachauswahl, Hamburger-Menü
- Hamburger-Menü: Über PrintEase (Adw.AboutDialog), Tastaturkürzel, Beenden
- Tastaturkürzel: Ctrl+R / F5 (Aktualisieren), Ctrl+N (Hinzufügen), Ctrl+Q (Beenden)
- GtkShortcutsWindow für Tastaturkürzel-Übersicht
- Fensterzustand wird gespeichert und wiederhergestellt (Größe, Paned-Position)
- Fehlerbanner (Adw.Banner) bei CUPS-Verbindungsfehler
- Alle CUPS-Aktionen asynchron (threading.Thread + GLib.idle_add): kein UI-Freeze
- Druckjobs: asynchrones Laden mit Spinner-Placeholder, einzelne Job-Stornierung
- Drucker entfernen: Bestätigungsdialog (Adw.AlertDialog)
- Fehler-Feedback via Adw.Toast bei fehlgeschlagenen Aktionen

**Scanner / AiO (eSCL / AirScan)**
- scanner_client.py: eSCL-Protokoll-Implementierung (ScannerCapabilities, ScanJobs, NextDocument)
- ScannerPanel: Auflösung, Farbmodus, Quelle als Dropdowns; Einstellungen pro Gerät persistent
- Einzelscan: Flachbett und ADF (einseitig), asynchron mit Abbrechen-Button
- ADF-Mehrseiten-Scan: alle Seiten eines Auftrags bis HTTP 404 abrufen
- ADF-Papier-Erkennung vor Scan (ScannerAdfEmpty → Fehlermeldung, kein stiller Fallback)
- Software-Duplex: zweistufiger ADF-Scan (Vorder- + Rückseiten), Stapel-Umdrehen-Dialog, PDF-Zusammenführung via Pillow
- Gespeicherten Scan anzeigen: Pfad-Anzeige + "Öffnen"-Button (xdg-open)
- Quellen-Labels: Flachbett, Einzug (ADF), Einzug — Duplex (Software)
- "AdfDuplexSoftware" als virtuelle Quelle wenn ADF vorhanden und kein Hardware-Duplex

**Internationalisierung**
- GNU gettext, 33 Sprachen: ar bg cs da de el en es fa fi fr he hi hr hu id it ja nb nl pl pt ro ru sk sr sv th tr uk vi zh_CN zh_TW
- Automatische Systemsprachen-Erkennung, Fallback-Kette: [lang, lang[:2], "en", "de"]
- Sprachwechsel zur Laufzeit (Dropdown in Headerbar, sofortiger Window-Rebuild)
- Makefile: `make pot` (Template), `make mo` (Kompilierung aller Sprachen)

**App-Icon**
- SVG-Icon: data/icons/hicolor/scalable/apps/print-ease.svg (Adwaita-Stil, blau, 128×128)

### Geändert
- cups_client.pause_printer() / resume_printer(): Fehlerbehandlung pro IPP-Aufruf dokumentiert (nicht-atomar)
- _escl_url_for(): IPP-Standardport 631 wird weggelassen; nicht-Standard-Ports (z.B. 8080) bleiben erhalten
- Alle blockierenden gettext-Aufrufe (_()) im GTK-Main-Thread ausgeführt — thread-sicheres i18n
- from __future__ import annotations in allen Modulen

### Infrastruktur
- LICENSE: GNU GPL 3.0 (vollständig)
- .gitignore: Python-Standard + *.mo + dev.log
- data/at.printease.PrintEase.desktop: FreeDesktop-Eintrag, 10 Sprachen
