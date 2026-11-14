# Changelog

## [0.2.2] - 2026-11-14

Maintenance release.

### Added
- Scanner: "Ordner öffnen" (Open folder) button next to "Öffnen" — opens
  the folder of the last scan in the file manager with the file
  selected (via the OpenURI portal in the Flatpak).

### Fixed
- Missing CUPS admin rights: the hint recommended adding the user to the
  group `lp`, which grants no CUPS administration rights. The correct
  group is now determined from `SystemGroup` in
  `/etc/cups/cups-files.conf` (e.g. `lpadmin` on Debian/Ubuntu/Mint,
  `sys`/`wheel` on Arch/Fedora); if that file is not readable,
  `lpadmin` is suggested where it exists, otherwise `wheel`.
- Scanner: "Öffnen" (Open) did not check whether opening succeeded and
  logged "Datei geöffnet" even when it failed. Both buttons now use
  `Gtk.FileLauncher`; errors are shown in a dialog and logged. GTK 4.10
  or newer is now required.
- Flatpak: scans and settings were lost when the app was closed (also
  affected 0.2.1). The sandbox had no access to the Pictures folder, so
  scans went to a temporary home directory inside the sandbox; settings
  used `~/.config` there instead of the app's persistent config
  directory. Scans now land in Pictures/Scans
  (`--filesystem=xdg-pictures`), settings and the log use the XDG user
  directories. Outside the Flatpak the paths stay the same. If no
  Pictures folder is configured on the host, the Flatpak saves scans to
  `~/.var/app/at.printease.PrintEase/data/Scans` instead of losing them;
  a warning is logged in that case.
- The test suite now runs without network access, without Pillow and
  without PyGObject/GTK, as on package build machines. The eSCL tests
  no longer start an HTTP server on 127.0.0.1 (which pybuild's
  `http_proxy=http://127.0.0.1:9/` redirected) but mock `urlopen`.
  Tests that really need Pillow are skipped when it is missing.
- Debian package: the tests run again during the build
  (`PYBUILD_DISABLE = test` removed).
- Debian package: `debian/copyright` lists the AppStream metainfo
  file under CC0-1.0, matching its `metadata_license`.

### Changed
- Flatpak: built on the current GNOME 51 runtime (Python 3.14) instead
  of the end-of-life GNOME 47 runtime; bundled zeroconf updated to
  0.154.0.

## [0.2.1] - 2026-11-11

### Added
- **Built-in mDNS discovery fallback** (python-zeroconf): network
  printer and scanner (eSCL) discovery and `.local` host name
  resolution now work without a running Avahi daemon — including
  inside the Flatpak sandbox. Multicast queries share one 3 s search
  window for more stable results.
- **First Flatpak release** (GNOME Platform 47): pycups built against
  the CUPS headers, python-zeroconf and ifaddr bundled. The CUPS test
  page falls back to a bundled copy when the system has none.
- **Multi-page feeder (ADF) scanning**: the feeder now scans all pages
  into one document (PDF by default) and keeps the mode selector.
- **Software duplex** with an optional "rotate back sides by 180°"
  switch (off by default, saved per scanner) for scanners that deliver
  the backs upside down; shown only for feeder + software duplex.

### Changed
- Scanner discovery per printer reworked into a search cascade, limited
  by `SCANNER_SEARCH_TIMEOUT`: eSCL at the address from the CUPS device
  URI (now also for `dnssd://` and `implicitclass://` URIs), an mDNS
  search for `_uscan`/`_uscans`, and an HTTP probe of known printer
  addresses. Scanners of other devices are never assigned; the detail
  page shows "Kein Scanner gefunden" (no scanner found) instead of
  staying blank.
- Software duplex flip prompt now blocks until confirmed and runs on the
  GTK main thread; three cases that could pair a back with the wrong
  front are handled (skipped dialog, Esc, empty feeder after
  "continue").
- PDFs embed the images at the actual scan resolution instead of a fixed
  200 ppi. `NEXT_DOCUMENT_TIMEOUT` raised to 60 s for slow 600 dpi scans.

### Fixed
- Decoding of escaped mDNS service names: avahi's `\DDD` escapes are
  decimal, not octal (`\032` is a space, not the control character
  0x1A).
- A Hindi mistranslation; new flip-dialog wording in all 33 languages.

## [0.2.0] - 2026-05-17

### Added
- **The Scan Release.** Three new scanning workflows for the
  flatbed and ADF:
  - **ADF hardware duplex** (BETA) — single eSCL job with
    `InputSource=AdfDuplex` when the scanner reports the
    capability, with metadata-based front/back ordering and
    fallback to stream order. Untested locally; marked BETA.
  - **Multi-page flatbed document** — scans single pages from
    the flatbed and assembles them into one PDF, with a per-page
    dialog (Next Page / Done / Cancel) that lets the user decide
    after each page whether to continue.
  - **Multi-page flatbed archive** — same workflow as Multi-page
    Document, but produces a multi-page TIFF with LZW compression
    instead of PDF.
- New `Modus` (Mode) dropdown in the scanner panel for selecting
  Single page / Multi-page document / Archive (TIFF) when the
  flatbed is the source.
- Capability parser extended to detect `AdfDuplexInputCaps` /
  `<scan:AdfOption>Duplex</scan:AdfOption>` and expose hardware
  duplex when available.

### Changed
- Scanner panel restructured: Source and Duplex are now two
  separate dropdowns instead of one combined list. Visibility
  is capability-driven — Mode row shown for Platen, Duplex row
  shown for ADF.
- Output file names made distinct so each scan kind is
  immediately recognisable:
  - `scan_<ts>.jpg` — single-page Platen scan
  - `scan_duplex_<ts>.pdf` — ADF software duplex
  - `scan_multipage_<ts>.pdf` — multi-page Platen document
  - `scan_archive_<ts>.tif` — multi-page Platen archive
- Internal refactor: `scan_document()` split into a thin wrapper
  plus `_scan_single_page()` that returns raw JPEG bytes, so the
  multi-page paths can collect pages in memory without touching
  disk between pages.

### Fixed
- Hardcoded German labels in printer-default dropdowns
  (`SIDES_LABELS`, `COLOR_MODE_LABELS`, `QUALITY_LABELS`) and in
  the PWG media-name table now go through gettext, so values
  like `Einseitig`, `Farbe`, `Normal`, `DL Umschlag`,
  `Foto 4×6 Zoll` and `Hagaki Postkarte` are translated
  correctly in every locale rather than staying German.
- Three v0.2.0 strings rewritten to avoid suffix-on-placeholder
  bugs in agglutinative languages (Finnish, Hungarian, Hebrew),
  which would otherwise have produced ungrammatical wordforms
  when the `{container}` placeholder was interpolated.

### Internationalisation
- Complete translations for all 33 supported languages
  (ar, bg, cs, da, de, el, en, es, fa, fi, fr, he, hi, hr, hu,
  id, it, ja, nb, nl, pl, pt, ro, ru, sk, sr, sv, th, tr, uk,
  vi, zh_CN, zh_TW) — ~1750 translations across the new v0.2.0
  scanner strings, the previously untranslated v0.1.6 printer-
  default group, the app-menu entries and the paper-size tokens.
  `zh_CN` and `zh_TW` are differentiated by region-specific
  vocabulary, not just by character set.

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
