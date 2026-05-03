# CUPS-3-Kompatibilitäts-Audit

**Projekt:** PrintEase
**Audit-Stand:** 2026-05-03
**Audit-Bezug:** Code zum Stand `main` nach v0.1.2 (PKGBUILD im AUR)
**Auditierte Module:** `cups_client.py`, `gui/add_printer_dialog.py`, `pyproject.toml`, PKGBUILD

---

## Kurzfassung

PrintEase ist gegen libcups2/pycups2 gebaut und in dieser Form auf libcups3 nicht ohne Anpassungen lauffähig. Die kritischen Punkte liegen nicht im Anwendungs-Code selbst, sondern im Stack darunter: pycups in der derzeit ausgelieferten Version 2.x linkt gegen libcups2; eine pycups3-Variante existiert bisher nur als GSoC-2025-Refactor-Branch und ist nicht im Arch-Repo. Die in PrintEase verwendeten Calls sind sehr eng auf die `cups.Connection`-API beschränkt und fast alle haben in libcups3 ein klares Mapping. Die zwei substanziellen Risiken sind: (1) das `ppdname="everywhere"`-Argument in `add_printer()`, das in der libcups3-Welt durch reine IPP-Attribute oder eine Printer-Application-Auflösung ersetzt wird, und (2) die `pause/resume`-Sequenzen, die Implementierungsdetail von libcups2 sind und in libcups3 möglicherweise andere semantische Bezeichner verwenden.

Ein Wechsel ist heute nicht akut nötig — Arch shippt weiterhin cups 2.4.x. PrintEase sollte sich jedoch jetzt eine dünne Abstraktionsschicht zulegen, die den Übergang trivial macht, sobald pycups3 stabil ausgeliefert wird (voraussichtlich 2026 H2).

---

## 1. Status libcups3 / pycups3 (Mai 2026)

| Komponente | Status | Bemerkung |
|---|---|---|
| libcups 3.0.0 | Stabil released (Anfang 2026) | Quelle: openprinting.github.io/libcups-3.0.0/ |
| CUPS 3.x Daemon-Suite | Aufgeteilt in `cups-local` (Desktop) + `cups-sharing` (Server) | Kein klassischer `cupsd` mehr im Desktop-Fall |
| Arch `extra/cups` | 2.4.x | Stand 2026-05; weiterhin libcups2 |
| Arch `extra/libcups` | Folgt cups-Paket | libcups3 liegt nicht parallel im offiziellen Repo (Stand Audit) |
| pycups 2.x (PyPI / Arch `python-pycups`) | C-Extension, gegen libcups2 | Aktuell verwendet von PrintEase |
| pycups3 / pycups-Refactor | GSoC 2025 Endabgabe (Soumya Ghosh, OpenPrinting), `feat-refactor`-Branch | CFFI-basiert, noch kein offizielles PyPI-Release |

**Konsequenz:** Auf einem heutigen CachyOS / Arch-System läuft PrintEase v0.1.2 unverändert. Ein Audit ist trotzdem sinnvoll, weil libcups2 auf mittlere Sicht abgekündigt wird und PrintEase durch frühe Abstraktion einen späteren Hard-Cut vermeidet.

---

## 2. Strukturelle Änderungen libcups2 → libcups3

Die für PrintEase relevanten Punkte:

**Aufteilung des Daemons.** CUPS 3 trennt local printing (`cups-local`, ein User-Daemon-Modell) von sharing (`cups-sharing`, der klassische Netzwerk-Server). Ein reiner Desktop-User braucht den Sharing-Server in der Regel nicht mehr. Für PrintEase bedeutet das: die Annahme „localhost:631“ als zentraler IPP-Endpunkt bleibt funktional, aber die Verbindungssemantik kann sich ändern — ein lokaler User-Bus ist denkbar.

**PPD-Support entfernt aus libcups3.** PPD-Dateien werden durch IPP-Attribute (`get-printer-attributes`) bzw. Printer-Applications (System-Daemons, die nicht-driverless-Drucker als IPP-Everywhere-Geräte emulieren) ersetzt. Funktionen mit PPD-Argumenten verschwinden aus der API; Legacy-Support liegt in `libppd` als eigenes Paket.

**API-Normalisierung.** Veraltete APIs sind entfernt, neue Namen folgen einer einheitlicheren Konvention. Die genauen Funktions-Renames betreffen Anwendungen, die die C-API direkt verwenden; pycups als Wrapper reicht das in seinem `Connection`-Objekt-Modell weiter.

**Driverless-First.** IPP-Everywhere und AirPrint sind nicht mehr eine Option neben PPD-Treibern, sondern der Default. Raw-Queues und PPD-basierte Treiber sind „deprecated“ und werfen seit cups 2.4 Warnungen.

---

## 3. Datei-für-Datei-Audit

### 3.1 `src/print_ease/cups_client.py`

Diese Datei ist das gesamte CUPS-Interface von PrintEase. Ich gehe sie Funktion für Funktion durch.

**`_connect()` (Zeile 17–24)**

Code:
```python
conn = cups.Connection()
```

Verwendung in libcups2: parameterloser Konstruktor, der gegen den lokalen `cupsd` auf `localhost:631` connectet. In pycups3 (CFFI-basiert) bleibt das Konzept einer Connection-Klasse erhalten. Risiko: Wenn CUPS 3 im Local-Server-Modus auf einen User-Socket statt auf Port 631 hört, muss die Verbindung u. U. anders aufgebaut werden. Das ist allerdings transparent für den Wrapper, sofern `cupsd` weiterhin den Standard-Endpunkt anbietet — was für die Migrationsphase fast sicher der Fall ist.

**Empfehlung:** keine sofortige Änderung. Aber: den Connection-Aufbau in einen Context-Manager `_cups_session()` extrahieren, damit ein späterer Wechsel auf eine andere Verbindungsklasse nur an einer Stelle passieren muss.

**`get_printers()` (Zeile 27–52) — Risiko: niedrig**

Calls:
- `conn.getPrinters()` → liefert Dict `{name: attrs}`
- `conn.getDefault()` → liefert String oder None

Verwendete Attribute aus dem `attrs`-Dict:
- `printer-state` (Integer-Code, 3/4/5 → idle/processing/stopped)
- `printer-info`, `printer-location`, `printer-is-shared`
- `printer-state-message`, `device-uri`

**libcups3-Kompatibilität:** Alle genannten IPP-Attribute sind RFC 8011 / PWG-Standard und bleiben in IPP Everywhere unverändert. `printer-state` als Enum 3/4/5 (idle/processing/stopped) ist seit RFC 2911 stabil.

**Risikopunkt:** Die Hardcodierung des Mappings in `_CUPS_STATE_MAP` (Zeile 10–14) ist robust, weil die IPP-Codes 3/4/5 normativ sind. Kein Handlungsbedarf.

**`set_default_printer()` (Zeile 55–62) — Risiko: niedrig**

Call: `conn.setDefault(printer_name)` → IPP-Operation `cups-set-default`. Bleibt in libcups3 erhalten, da Teil der CUPS-eigenen IPP-Erweiterungen.

**`pause_printer()` (Zeile 65–88) und `resume_printer()` (Zeile 91–114) — Risiko: mittel**

Calls:
- `conn.disablePrinter(name)` / `conn.enablePrinter(name)`
- `conn.rejectJobs(name)` / `conn.acceptJobs(name)`

Diese vier Calls mappen auf die IPP-Operationen `pause-printer`/`resume-printer` und `cups-reject-jobs`/`cups-accept-jobs`. Die Pause/Resume-Operationen sind RFC-Standard, die Reject/Accept-Variante ist eine CUPS-Erweiterung.

**Risikopunkt:** Die nicht-atomare Sequenz (disable + reject) ist im aktuellen Code dokumentiert — das ist gut. In libcups3 bleibt die Nicht-Atomarität bestehen, weil sie aus dem IPP-Modell selbst kommt, nicht aus libcups2. Die Funktionsnamen `disablePrinter`/`rejectJobs` im pycups2-Wrapper könnten in pycups3 anders heißen (Naming-Vereinheitlichung war ein Ziel des Refactors). Konkretes Beispiel aus dem GSoC-Bericht: pycups3 verwendet stärker Pythonische Namen mit Properties statt Setter-Funktionen.

**Empfehlung:** Den Vier-Call-Block in private Hilfsfunktionen `_pause_atomic()` / `_resume_atomic()` extrahieren, die genau diese pycups-Methodennamen kapseln. Beim pycups3-Switch ist das die einzige zu ändernde Stelle.

**`print_test_page()` (Zeile 117–124) — Risiko: niedrig**

Call: `conn.printTestPage(printer_name)`. In libcups2 ist das ein Convenience-Wrapper, der die mitgelieferte Test-PDF an den Drucker submittet. In libcups3 könnte das als Wrapper ganz wegfallen oder umbenannt werden — der zugrundeliegende Mechanismus (eine Datei via `cupsCreateJob` + `cupsStartDocument` + `cupsWriteRequestData` + `cupsFinishDocument` senden) bleibt gleich.

**Empfehlung:** Vorsichtshalber als optionalen Codepfad behandeln. Falls `printTestPage` in pycups3 nicht mehr existiert, ist der Fallback eine eigene Test-PDF im Paket (data/test-page.pdf) plus Submission via `printFile()`.

**`get_jobs()` (Zeile 127–148) — Risiko: niedrig**

Calls:
- `conn.getJobs(which_jobs="not-completed", my_jobs=False)`

Nutzt die IPP-Operation `get-jobs`. Standardisiert. Die Filter-Parameter (`which_jobs`, `my_jobs`) sind pycups-spezifische Convenience-Parameter, die in pycups3 erhalten sein sollten.

Die Logik in Zeile 138 — `attrs.get("job-printer-uri", "").endswith("/" + printer_name)` — ist eine Filter-Heuristik, weil `getJobs()` ohne `printer_uri`-Parameter alle Jobs liefert. Diese Heuristik ist fragil, falls Job-URIs in libcups3 anders formatiert werden (etwa mit `printer-uri` statt `job-printer-uri` als Schlüssel).

**Empfehlung:** Statt `endswith` lieber den Hostnamen ignorieren und den letzten Pfad-Bestandteil vergleichen:
```python
from urllib.parse import urlparse
job_uri = attrs.get("job-printer-uri", "")
if urlparse(job_uri).path.rsplit("/", 1)[-1] == printer_name:
    ...
```
Robuster gegen URL-Format-Änderungen und gegen Drucker mit Bindestrich am Ende.

**`add_printer()` (Zeile 151–178) — Risiko: HOCH**

Das ist der einzige wirklich problematische Call.

```python
if ppd_file:
    kwargs["filename"] = ppd_file
elif uri.startswith(("ipp://", "ipps://")):
    kwargs["ppdname"] = "everywhere"
# else: raw queue (no PPD)
```

Die drei Pfade:

1. **`filename=ppd_file`** — explizite PPD-Datei. Im aktuellen PrintEase-Code wird diese Variante nicht aktiv genutzt (kein UI-Pfad reicht ein `ppd_file`-Argument durch); sie steht im API-Vertrag aber drin. In libcups3 ist PPD-Support komplett raus — `filename=` mit einer `.ppd` würde scheitern.

2. **`ppdname="everywhere"`** — der treiberlose Pfad. Das `everywhere`-Modell ist ein synthetisches PPD, das libcups2 zur Laufzeit aus den per Get-Printer-Attributes abgefragten IPP-Eigenschaften des Druckers generiert. In libcups3 verschwindet dieser Mechanismus, weil PPDs an sich verschwinden. Stattdessen erzeugt CUPS 3 die Queue direkt aus den IPP-Attributen — `ppdname` als Argument existiert nicht mehr.

3. **Raw-Queue** — keine PPD, einfaches Durchreichen. Raw-Queues sind seit cups 2.4 deprecated und werden in cups 3 entfernt.

**Konkreter Migrationspfad für libcups3:**

In libcups3 wird ein Drucker via `cupsAddDestination` / `cupsCreatePrinter` (genaue API-Namen können in pycups3 abweichen) angelegt — ohne PPD-Argument. Die Treiber-Auswahl entfällt komplett, weil der Drucker als IPP-Everywhere-Endpunkt schon alle nötigen Attribute selbst liefert. Für nicht-driverless Drucker übernimmt eine Printer Application diese Rolle: sie läuft als eigener Daemon, registriert sich als IPP-Everywhere-Service via DNS-SD, und CUPS 3 spricht mit ihr wie mit jedem anderen IPP-Drucker.

**Empfehlung:**

Heute keine funktionalen Änderungen, aber:

a) Den `add_printer`-Vertrag so ändern, dass das `ppd_file`-Argument als „legacy, für libcups2-Pfad“ markiert ist (Docstring-Hinweis).

b) Den `ppdname="everywhere"`-Pfad in eine Hilfsfunktion `_make_driverless_kwargs(uri)` extrahieren, die heute `{"ppdname": "everywhere"}` zurückgibt und morgen `{}` (libcups3 macht es automatisch) oder einen anderen, von pycups3 vorgegebenen Schlüssel.

c) Die Raw-Queue-Branch (`else`-Zweig) im UI nicht mehr offerieren. Aktuell wird sie nicht aktiv vom UI angesprungen — `add_printer_dialog.py` gibt nur ipp:// oder ipps:// URIs aus dem Avahi-Tab durch (Zeile 285 in `add_printer_dialog.py`: `self._uri_row.set_text(printer.uri)` — die URI ist immer ipp/ipps), und aus dem Manuell-Tab könnte ein User theoretisch eine `socket://`- oder `lpd://`-URI eingeben. Das ist der Pfad, der unter libcups3 mit cups 3.x bricht. Sollte spätestens vor v1.0 entweder mit Warning versehen oder entfernt werden.

**`cancel_job()` (Zeile 181–188), `remove_printer()` (Zeile 191–198), `get_printer_attributes()` (Zeile 201–209) — Risiko: niedrig**

Calls: `conn.cancelJob(id, purge_job=False)`, `conn.deletePrinter(name)`, `conn.getPrinterAttributes(name)`.

Alle drei sind dünne Wrapper um RFC-Standard-IPP-Operationen (`cancel-job`, `cups-delete-printer`, `get-printer-attributes`) und sollten in pycups3 unter ähnlichen Namen verfügbar sein.

### 3.2 `src/print_ease/gui/add_printer_dialog.py`

Diese Datei ruft `cups_client.add_printer()` aus (Zeile 155):

```python
cups_client.add_printer(name, uri, description, location)
```

Der Aufruf ohne `ppd_file=` läuft also durch den `ppdname="everywhere"`-Zweig (oder den Raw-Zweig, falls die URI weder ipp:// noch ipps:// ist). Das ist genau die Stelle, die unter libcups3 angepasst werden muss — aber zentralisiert in `cups_client.py`. Im UI-Code selbst ist nichts CUPS-3-spezifisch zu ändern.

Die URI-Validierung erfolgt über das Tooltip in Zeile 94 (`ipp://192.168.1.100:631/ipp/print`). Für CUPS 3 könnte sich der Default-Resource-Path ändern (`/ipp/print` bleibt aber Standard). Kein Handlungsbedarf.

### 3.3 `pyproject.toml`

```toml
dependencies = [
    "pycups",
]
```

**Risiko:** unspezifisch — `pip install pycups` zieht aktuell pycups 2.x (PyPI). Wenn pycups3 als separates Paket auf PyPI landet (offener Punkt — könnte als `pycups>=3` oder als neues Paket `pycups3` erscheinen), muss der Dependency-Eintrag angepasst werden.

**Empfehlung:** Sobald die pycups3-Veröffentlichungsstrategie klar ist, eine obere Versionsgrenze setzen (`pycups>=2,<3`), um nicht versehentlich gegen einen API-Inkompatiblen pycups3-Major zu installieren.

### 3.4 PKGBUILD (AUR)

Die AUR-Build-Dependency `python-pycups` ist Arch-paketiert und folgt dem System-cups. Solange Arch bei cups 2.4.x bleibt, ist `python-pycups` libcups2-basiert. Bei einem Arch-Wechsel auf cups 3 wird `python-pycups` entweder mitgehoben (libcups3-basiert) oder durch ein neues Paket abgelöst.

**Risiko mittel:** Wenn Arch parallel libcups2 und libcups3 paketiert (siehe Forum-Diskussion: „I could also see Arch shipping both for a while“), könnte `python-pycups` einer von beiden sein, ohne dass das aus dem Paketnamen ablesbar ist. Praktischer Test wäre dann notwendig.

---

## 4. Risiko-Matrix (sortiert)

| # | Stelle | Risiko | Aufwand für Fix | Wann fixen |
|---|---|---|---|---|
| 1 | `cups_client.add_printer` `ppdname="everywhere"` | hoch | klein (Hilfsfunktion) | jetzt vorbereiten, schalten beim pycups3-Switch |
| 2 | `pyproject.toml` `pycups`-Bound | mittel | trivial | bei pycups3-Release |
| 3 | `cups_client.pause_printer/resume_printer` Methodennamen | mittel | klein (Wrapper) | beim pycups3-Switch |
| 4 | `cups_client.get_jobs` Job-URI-Filter | niedrig-mittel | klein (urlparse) | jetzt sinnvoll |
| 5 | Raw-Queue-Zweig in `add_printer` | mittel | klein (Branch entfernen oder warnen) | vor v1.0 |
| 6 | `cups_client._connect` Connection-Setup | niedrig | klein (Context-Manager) | sinnvoll, nicht dringend |
| 7 | `cups_client.print_test_page` API-Name | niedrig | klein (Fallback-Pfad) | beim pycups3-Switch |
| 8 | `pyproject.toml` Distro-Tests gegen libcups3 | niedrig | mittel (CI-Setup) | wenn Arch libcups3 paketiert |

---

## 5. Konkrete Code-Vorbereitung — was sofort sinnvoll ist

Drei Refactorings, die heute funktional nichts ändern, aber den späteren Wechsel zu einer Ein-Datei-Änderung machen.

**5.1 Connection-Helper in Context-Manager.** In `cups_client.py`:

```python
from contextlib import contextmanager

@contextmanager
def _cups_session():
    conn = _connect()
    try:
        yield conn
    finally:
        # libcups3 könnte explizites close() erwarten
        pass
```

Alle Funktionen rufen statt `conn = _connect()` dann `with _cups_session() as conn:`. Beim Switch auf pycups3 wird im `finally`-Block die nötige Cleanup-Operation ergänzt.

**5.2 Treiber-Auswahl-Helper für `add_printer`.** In `cups_client.py`:

```python
def _resolve_driver_kwargs(uri: str, ppd_file: str | None) -> dict:
    """Liefert die Treiber-spezifischen kwargs für conn.addPrinter().

    libcups2: ppdname="everywhere" für IPP-URIs, filename=ppd für PPD-Pfade.
    libcups3: leere kwargs (CUPS löst Treiber automatisch via IPP-Attribute auf).
    """
    if ppd_file:
        return {"filename": ppd_file}
    if uri.startswith(("ipp://", "ipps://")):
        return {"ppdname": "everywhere"}
    return {}  # raw queue
```

Im Hauptcode dann `kwargs.update(_resolve_driver_kwargs(uri, ppd_file))`. Beim Switch wird die Funktion zur Stub.

**5.3 Job-URI-Vergleich robuster.** In `cups_client.py`, `get_jobs()`:

```python
from urllib.parse import urlparse

job_uri_path = urlparse(attrs.get("job-printer-uri", "")).path
if job_uri_path.rsplit("/", 1)[-1] == printer_name:
    ...
```

---

## 6. Test-Strategie

Sobald libcups3 und pycups3 verfügbar sind:

1. **Distro-Container.** Ein Fedora-Rawhide- oder Ubuntu-Devel-Container mit libcups3 als Test-Sandbox. Vor Arch ankommt, ist Fedora der wahrscheinlich erste Distro-Test-Punkt — Red Hat war früh bei der libcups3-Adoption.

2. **Smoke-Test-Reihe:**
   - `get_printers()` mit einem driverless IPP-Drucker registriert
   - `add_printer()` mit ipp:// URI eines neuen Druckers
   - `pause_printer()` / `resume_printer()` Sequenz
   - `get_jobs()` mit einem Test-Job
   - `cancel_job()` für den Test-Job
   - `remove_printer()` zum Aufräumen

3. **Regressions-Set.** Die unter libcups2 funktionierende Konfiguration mit Canon TS705a und Ricoh M C240FW als Referenz beibehalten, um Verhalten zwischen libcups2 und libcups3 abzugleichen.

---

## 7. Empfehlungen — priorisiert

**Jetzt (vor v0.1.3):**
- Refactoring 5.1, 5.2, 5.3 anwenden — keine funktionale Änderung, aber One-Stop-Shop für späteren Switch.
- `pyproject.toml` Bound auf `pycups>=2,<3` setzen.
- Im CHANGELOG vermerken: „Vorbereitung auf libcups3, keine Funktionsänderung.“

**Vor v0.2.0:**
- Raw-Queue-Pfad in `add_printer` mit User-sichtbarer Warnung versehen oder entfernen.

**Sobald Arch libcups3 / pycups3 paketiert:**
- Test-Container aufsetzen, Smoke-Test-Reihe durchlaufen.
- `_resolve_driver_kwargs` auf libcups3-Variante umstellen.
- Falls pycups3 Methoden-Renames hat: `pause/resume`-Wrapper sowie `printTestPage`-Fallback aktivieren.
- AUR-PKGBUILD Build-Dependency auf das neue pycups-Paket aktualisieren.

**Vor v1.0:**
- Vollständiger End-to-End-Test gegen libcups3-System.
- Dokumentation der Mindest-CUPS-Version im README.
