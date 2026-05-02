# Changelog

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
