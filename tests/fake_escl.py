"""Gemockter eSCL-Scanner für die ADF-Tests – ohne echten Socket.

Statt eines HTTP-Servers auf 127.0.0.1 wird ``urllib.request.urlopen``
ersetzt. So laufen die Tests auch dort, wo kein Netz erreichbar ist oder
ein Proxy gesetzt ist (pybuild exportiert ``http_proxy=http://127.0.0.1:9/``
und ``no_proxy=localhost``; Anfragen an 127.0.0.1 liefen deshalb ins Leere).
"""
import email.message
import io
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

LOADED, EMPTY, JAM = "ScannerAdfLoaded", "ScannerAdfEmpty", "ScannerAdfJam"
JOB = "/eSCL/ScanJobs/1"
BASE = "http://scanner.invalid"


class _Response:
    """Das Nötige von http.client.HTTPResponse für scanner_client."""

    def __init__(self, status, body=b"", headers=()):
        self.status = status
        self._body = io.BytesIO(body)
        self.headers = email.message.Message()
        for name, value in headers:
            self.headers[name] = value

    def read(self, *args):
        return self._body.read(*args)

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeScanner:
    """
    Spielt `documents` nacheinander ab: bytes = Seite, (bytes, Header) = Seite
    mit Antwort-Headern, int = HTTP-Status.
    Ist die Liste leer, kommt `exhausted`. ScannerStatus liefert der Reihe
    nach `states` (der letzte Wert bleibt stehen); None = Status nicht abrufbar.

    Ersetzt ``urllib.request.urlopen`` bis ``close()``.
    """

    def __init__(self, documents, states=(EMPTY,), exhausted=404):
        self.documents = list(documents)
        self.states = list(states)
        self.exhausted = exhausted
        self.next_document_calls = 0
        self.status_calls = 0
        self.deleted = []
        self.url = f"{BASE}/eSCL"
        self._patch = mock.patch.object(urllib.request, "urlopen", self._urlopen)
        self._patch.start()

    def close(self):
        self._patch.stop()

    def _urlopen(self, req, data=None, timeout=None, **_kwargs):
        if isinstance(req, urllib.request.Request):
            url, method = req.full_url, req.get_method()
        else:
            url, method = req, "POST" if data is not None else "GET"
        if not url.startswith(BASE):
            raise AssertionError(f"Unerwartete URL im Test: {url}")
        path = urllib.parse.urlparse(url).path
        status, body, headers = self._handle(method, path)
        if status >= 400:
            hdrs = email.message.Message()
            raise urllib.error.HTTPError(url, status, f"HTTP {status}", hdrs, io.BytesIO(body))
        return _Response(status, body, headers)

    def _handle(self, method, path):
        if method == "POST":
            return 201, b"", [("Location", JOB)]
        if method == "DELETE":
            self.deleted.append(path)
            return 200, b"", []
        if path == f"{JOB}/NextDocument":
            self.next_document_calls += 1
            step = self.documents.pop(0) if self.documents else self.exhausted
            if isinstance(step, int):
                return step, b"", []
            if isinstance(step, bytes):
                return 200, step, []
            return 200, step[0], list(step[1].items())
        if path == "/eSCL/ScannerStatus":
            self.status_calls += 1
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            if state is None:
                return 500, b"", []
            return 200, (
                '<scan:ScannerStatus xmlns:scan='
                '"http://schemas.hp.com/imaging/escl/2011/05/03">'
                f"<scan:AdfState>{state}</scan:AdfState></scan:ScannerStatus>"
            ).encode(), []
        return 500, b"", []
