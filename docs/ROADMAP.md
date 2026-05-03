# PrintEase Roadmap

**Stand:** 2026-05-03
**Aktuelle Version:** v0.1.2 (AUR live)
**Format:** Versionen mit Zielen, Akzeptanzkriterien, Risiken, Abhängigkeiten und groben Zeitschätzungen. Kalenderdaten bewusst vermieden — die Schätzungen sind „aktive Arbeitstage“, keine Wandkalender-Tage.

---

## Leitlinien

Diese Roadmap folgt vier Prinzipien, die in der bisherigen Entwicklung sichtbar sind und beibehalten werden:

**Qualität vor Tempo.** v0.1.0 ist nach einer 49-Punkte-Audit-Reihe (8a/8b/8c) released worden. Dieser Modus bleibt.

**Hardware-First.** Features werden gegen die zwei verfügbaren Geräte (Canon PIXMA TS705a, Ricoh M C240FW) verifiziert. Was dort nicht reproduzierbar funktioniert, ist nicht released.

**Driverless-First.** Keine PPD-basierten Treiber-Eskapaden, keine vendor-spezifischen Hacks. Alles, was nicht über IPP Everywhere oder eSCL/AirScan abbildbar ist, geht in einen separaten Plug-in-Layer (oder gar nicht).

**Distro-agnostisch, AUR-zentriert.** AUR ist der primäre Vertriebskanal, Flatpak folgt. Beide bekommen denselben Code-Stand zur selben Zeit.

---

## v0.1.3 — Wartungs-Release

**Status:** offen
**Zeitschätzung:** 0.5–1 Arbeitstag
**Abhängigkeiten:** keine

**Inhalt:**

- Maintainer-Kürzel im PKGBUILD von `MrHaku81` auf `Haku81` angleichen (passend zum AUR-Account).
- Entscheidung: Werden die in CUPS-3-Audit identifizierten vorbereitenden Refactorings (Connection-Context-Manager, `_resolve_driver_kwargs`-Helper, robusterer Job-URI-Filter) hier mitgeschnitten oder erst in v0.2.0? Empfehlung: in v0.1.3 mitnehmen, weil sie nicht funktional sind und das spätere v0.2.0-Diff sauberer halten.
- `pyproject.toml`: `pycups`-Bound auf `>=2,<3` setzen.

**Akzeptanzkriterien:**

- AUR-Push erfolgreich, Pacman-Update auf bestehendem Test-System bricht nichts.
- Bestehende Tests (Canon Print, Ricoh Print + Scan + Duplex) laufen unverändert durch.

**Risiko:** minimal. Im Wesentlichen ein Cosmetic-Patch mit zwei harmlosen Refactorings.

---

## v0.2.0 — Flachbett-Multipage

**Status:** Hauptthema; Design-Dokument als separater Anhang.
**Zeitschätzung:** 5–8 Arbeitstage (3–5 für Implementierung, 2–3 für UI-Politur und Geräte-Tests)
**Abhängigkeiten:** Pillow (`python-pillow`) — bereits optional in v0.1.x für Software-Duplex-PDF.

**Ziel.** Flachbett-Scanner können heute nur Einzelseiten erzeugen. Für mehrseitige Dokumente, deren Vorlagen nicht für den ADF geeignet sind (gebundene Bücher, fragile Originale, Pässe, Ausweise, Quittungen mit ungewöhnlichen Formaten, einseitige Artefakte), muss der User aktuell N Einzelscans manuell zu einer PDF zusammenbauen. v0.2.0 macht das zum nativen Workflow.

**Funktionaler Umfang:**

- Im Scan-Panel ein neuer Quellen-Eintrag „Flachbett — Mehrseitig (PDF)“ neben der bestehenden „Flachbett“ und „Einzug“-Wahl.
- Scan-Ablauf: pro Seite ein eSCL-Job (mit Source `Platen`), dazwischen ein Dialog „Nächste Seite einlegen oder fertigstellen?“ mit zwei Buttons: **Weiter scannen**, **Fertigstellen**, plus einem dritten Button **Abbrechen** (verwirft alles bisher Gescannte).
- Live-Vorschau: schon gescannte Seiten als Thumbnail-Reihe im Dialog sichtbar — der User soll sehen, was er schon hat.
- Ergebnis: eine PDF-Datei via dieselbe Pillow-Pipeline, die auch Software-Duplex nutzt (`scanner_client.py` Zeile 489 ff., `_create_pdf`).
- Speicherort: `~/Pictures/Scans/scan_multipage_<TIMESTAMP>.pdf` analog zum Duplex-Naming.
- Fortschritts-Feedback während des Scans selbst über das bestehende Spinner+Cancel-Pattern.

**Code-Ansatz.** Die Software-Duplex-Logik in `scanner_client.py` ist bereits eine Multipage-PDF-Pipeline mit zwei Phasen. Multipage-Flachbett ist die Verallgemeinerung: 1..N Phasen, eine Seite pro Phase, ohne den Rückseiten-Reverse-Step. Konkret:

- Neue Funktion `scan_flatbed_multipage(scanner, color_mode, resolution, next_page_callback, cancel_event)` in `scanner_client.py`.
- `next_page_callback() -> bool` blockiert auf dem GTK-Main-Thread und gibt zurück, ob weitergescannt werden soll. Das Pattern existiert bereits als `flip_callback` in `scan_duplex_software` (Zeile 230) — Wiederverwendung mit unterschiedlicher Semantik.
- `_create_pdf` (Zeile 489) wird unverändert wiederverwendet.

**UI-Komponenten.**

- Erweiterung im Quellen-Dropdown des `ScannerPanel`. Die virtuelle Quelle „AdfDuplexSoftware“, die in v0.1 schon als Pattern eingeführt wurde, wird ergänzt um eine virtuelle Quelle „PlatenMultipage“.
- Ein neuer Adw.Dialog `MultipageScanDialog` zwischen den Scan-Schritten.
- Dialog-Inhalt: Adw.HeaderBar + Thumbnail-Reihe (GtkScrolledWindow → GtkBox mit GtkPicture-Children) + Action-Buttons.

**Akzeptanzkriterien:**

1. Mit Ricoh M C240FW (Flachbett vorhanden) lassen sich 5 Seiten nacheinander scannen, der User erhält eine 5-seitige PDF.
2. Wird im Scan-Schritt der Cancel-Button gedrückt, werden alle bisher gescannten Seiten verworfen, der eSCL-Job sauber beendet (`_delete_job`), kein temporärer Datenmüll im Filesystem.
3. Wird der Dialog mit „Fertigstellen“ nach 1 Seite geschlossen, ist die resultierende PDF eine 1-seitige PDF — kein Sonderfall.
4. Die Auflösung (300 dpi default) und der Farbmodus werden über alle Seiten konstant gehalten.
5. Speicherprofil unter Kontrolle: für 10 Seiten 300dpi A4 RGB sollte der Peak-RAM-Verbrauch unter 400 MB bleiben (JPEGs werden im Memory gehalten, bis `_create_pdf` läuft).
6. Das Quellen-Dropdown bleibt für Geräte ohne Flachbett (Platen) deaktiviert.

**Risiken:**

- *Speicher bei sehr vielen Seiten.* 50-seitige RGB-Scans könnten >2 GB RAM belegen. Mitigation: Im Code einen Soft-Limit-Warnhinweis bei N > 30 einblenden, optional in der Settings-Datei einen Hard-Limit konfigurierbar machen. Für v0.2.0 noch kein Streaming-PDF-Writer — das wäre v0.3.x.
- *Dialog-Modalität auf KDE Plasma.* Ist der Dialog nicht-modal, kann der User parallel auf den Scanner zugreifen und den Job zerstören. Adw.Dialog ist standardmäßig modal — aber: bei manchen Tilern wird das nicht respektiert. Test auf KDE Plasma + i3wm explizit nötig.
- *Pillow als harte Abhängigkeit.* Aktuell ist Pillow optional (`python-pillow` als Optional in der Requirements-Tabelle). Mit v0.2.0 wird Multipage zum Kern-Feature und Pillow zur Hard-Dependency. PKGBUILD muss `python-pillow` von `optdepends` zu `depends` verschieben.

**Design-Notizen mit UI-Flow:** im separaten Dokument `design/v0.2.0-flatbed-multipage.md`.

---

## v0.3.0 — pycups3 / libcups3-Switch (vorgezogen, falls Arch das Paket umstellt)

**Status:** Backlog, abhängig von Distro-Verfügbarkeit.
**Zeitschätzung:** 3–5 Arbeitstage (2–3 für Code-Switch dank vorbereiteter Helper, 1–2 für CI/Test-Container, 1 für AUR-Anpassung)
**Abhängigkeiten:** Arch oder ein anderer ausgewählter Test-Distro shippt libcups3 + pycups3 stabil.

**Auslöser.** Die Reihenfolge zwischen v0.3.0 (Multi-Region) und einem libcups3-Switch ist in der aktuellen Roadmap-Skizze noch nicht festgelegt. Die pragmatische Position: sobald die Distro-Lage es erfordert, wird der libcups3-Switch zur v0.3.0, und Multi-Region rutscht zur v0.4.0. Bis dahin steht libcups3 als Backlog-Item.

**Inhalt:** das, was im CUPS-3-Audit als „beim Switch anwenden“ markiert ist:

- `_resolve_driver_kwargs` auf libcups3-Variante umschalten (leere kwargs).
- Wrapper für `pause/resume`-Funktionsnamen anpassen, falls pycups3 umbenennt.
- `printTestPage`-Fallback aktivieren, falls Convenience-Wrapper entfällt.
- Raw-Queue-Pfad final entfernen.
- AUR-PKGBUILD Build-Dependency aktualisieren.
- README: Mindest-CUPS-Version dokumentieren.

**Akzeptanzkriterien:**

- Auf einem libcups3-System: alle bisherigen Hardware-Tests (Canon Print, Ricoh Print + Scan + ADF + Duplex) bestehen.
- Auf einem libcups2-System: PrintEase v0.2.x bleibt installierbar (Branch-getrennt im Repo, falls nötig — eine v0.2.x-Wartungslinie für libcups2-Distros parallel zu v0.3.x für libcups3).

**Risiken:**

- *Doppelte Wartung.* Wenn Arch lange beide libcups-Versionen parallel ausliefert, muss PrintEase ggf. zwei Codepfade pflegen. Mitigation: ein dünner Compat-Layer in `cups_client.py`, der zur Laufzeit erkennt, gegen welche libcups gelinkt wurde, und entsprechend dispatched. Aufwand dann eher 5–7 Arbeitstage statt 3–5.

---

## v0.4.0 — Multi-Region-Scan (oder v0.3.0, falls libcups3-Switch verschoben wird)

**Status:** Backlog, mit konkretem Designziel.
**Zeitschätzung:** 7–10 Arbeitstage (Komplexität liegt in der UI, nicht im Scan-Code).
**Abhängigkeiten:** v0.2.0 (Multipage-PDF-Infrastruktur als Basis).

**Ziel.** Mehrere Scan-Regionen pro Vorlage — typischer Use-Case: vier 10×15-Fotos auf einer A4-Glasplatte. Statt vier Einzelscans plus Crop-Schritt: ein Scan mit vier definierten Regionen, vier separate Output-Dateien.

**Funktionaler Umfang (vorläufig, vor Detailspezifikation):**

- Scan-Vorschau: ein Niedrig-Auflösungs-Vor-Scan (75 dpi) liefert ein Übersichtsbild der gesamten Glasplatte.
- Region-Auswahl im Vorschaubild: Drag-and-Drop für Rechtecke, mehrere parallel.
- Pro Region: ein eSCL-Job mit eigenen `XOffset`/`YOffset`/`Width`/`Height` in `_SCAN_SETTINGS_XML` (`scanner_client.py` Zeile 32 ff. — die Region-Logik ist im Schema bereits vorgesehen, derzeit aber hardcoded auf eine ganze Vorlage).
- Pro Region: separate Ausgabedatei oder Bündelung in einer PDF (User-Wahl).

**Risiken:**

- *Vorschau-Rendering.* eSCL-Vor-Scans bei 75 dpi sind klein, aber das Mapping zwischen UI-Pixeln und eSCL-Koordinaten (1/300 Zoll) ist fummelig. Ein DPI-Bug schiebt Regionen subtil daneben.
- *Geräte-Kompatibilität.* Nicht jeder eSCL-Scanner respektiert mehrere Regions in einem Job. Workaround: pro Region ein separater Job. Ricoh M C240FW Verhalten muss explizit getestet werden.
- *UI-Komplexität.* Die Region-Editor-UI ist substanziell größer als alles, was PrintEase bisher hat. Das ist die Hauptzeit-Investition.

**Akzeptanzkriterien (vorläufig):**

1. Vier Fotos (10×15) auf einer A4-Glasplatte werden in einem Workflow als vier separate JPEGs erkannt und gespeichert.
2. Die Region-Selektion bleibt zwischen aufeinanderfolgenden Scans erhalten (für Batch-Modus mit gleicher Vorlagen-Anordnung).
3. Funktioniert auf Ricoh M C240FW; bei anderen Scannern ohne explizites Multi-Region-Support fällt der Code automatisch auf „mehrere Einzeljobs“ zurück.

---

## v0.5.0+ — weiteres Backlog (ungeordnet)

Diese Punkte sind sicher relevant, aber nicht durchpriorisiert:

- **Scan-Profile.** Benannte Voreinstellungen („Quittungsscan SW 200dpi“, „Foto Color 600dpi“). Pro-Profil-Speicherung der Region-Sets aus v0.4.0.
- **OCR-Integration.** Tesseract-Aufruf für gescannte PDFs. Optional, weil große Modell-Daten und Sprach-Choice involviert sind. Lokal-only, wie alle Anhängigkeiten in PrintEase.
- **Druckjob-Vorschau.** Vor dem Submit ein PDF-Render des Jobs zeigen. Braucht Poppler oder MuPDF.
- **Drucker-Tray-/Fach-Auswahl.** Über IPP-Attribute `media-source`. Heute hartkodierter Default.
- **Disc-Print-Integration.** Wenn das separate Disc-Print-App-Projekt produktiv ist, eine optionale Brücke (eigene Quelle im PrintEase-UI für Disc-fähige Drucker — der TS705a wäre dafür der Test-Kandidat).
- **Erweiterte Job-Verwaltung.** Job-Reihenfolge ändern, Hold/Release, Kopien-Anzahl nachträglich anpassen.
- **Drucker-Kostenrechnung.** Job-History, Seitenzähler, Tonerstand (sofern eSCL/IPP es ausliefert).

---

## Was bewusst nicht in der Roadmap steht

- **PPD-basierte Treiber-Unterstützung.** Driverless-First-Prinzip; PrintEase wird kein universeller PPD-Browser.
- **system-config-printer-Feature-Parität.** PrintEase ist ein Ersatz für moderne Drucker, kein 1:1-Klon des Legacy-Tools. Manche Features (CUPS-Class-Verwaltung, Sambda-Drucker, JetDirect-Konfiguration) sind explizit out-of-scope.
- **Cloud-Druck.** Lokal-Only-Prinzip; keine Google-Cloud-Print-/Mopria-Cloud-/etc.-Integrationen.
- **Mobile-Apps.** Desktop-Linux ist die einzige Zielplattform.

---

## Update-Kadenz

Mit Patch-Releases (`v0.x.y` → `v0.x.(y+1)`): bei kritischen Bugs oder Hardware-Kompatibilitäts-Findings, ohne festen Rhythmus.

Mit Minor-Releases (`v0.x` → `v0.(x+1)`): wenn das in der Roadmap zugeordnete Feature stabil und auf beiden Test-Geräten verifiziert ist. Die Kadenz folgt dem Audit-Prinzip aus v0.1 — kein Datum vor abgeschlossener Audit-Reihe.

Major-Release `v1.0`: wenn libcups3-Switch abgeschlossen ist, Multi-Region produktiv läuft, und eine substanzielle reale Test-User-Basis (nicht nur das eigene Hardware-Setup) existiert. Das ist explizit kein Zeitziel — es ist ein Reifegrad-Ziel.
