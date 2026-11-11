"""Gemockter eSCL-Server für die ADF-Tests."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOADED, EMPTY, JAM = "ScannerAdfLoaded", "ScannerAdfEmpty", "ScannerAdfJam"
JOB = "/eSCL/ScanJobs/1"


class FakeScanner:
    """
    Spielt `documents` nacheinander ab: bytes = Seite, (bytes, Header) = Seite
    mit Antwort-Headern, int = HTTP-Status.
    Ist die Liste leer, kommt `exhausted`. ScannerStatus liefert der Reihe
    nach `states` (der letzte Wert bleibt stehen); None = Status nicht abrufbar.
    """

    def __init__(self, documents, states=(EMPTY,), exhausted=404):
        self.documents = list(documents)
        self.states = list(states)
        self.exhausted = exhausted
        self.next_document_calls = 0
        self.status_calls = 0
        self.deleted = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, body=b"", headers=()):
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.reply(201, headers=[("Location", JOB)])

            def do_DELETE(self):
                fake.deleted.append(self.path)
                self.reply(200)

            def do_GET(self):
                if self.path == f"{JOB}/NextDocument":
                    fake.next_document_calls += 1
                    step = fake.documents.pop(0) if fake.documents else fake.exhausted
                    if isinstance(step, int):
                        self.reply(step)
                    elif isinstance(step, bytes):
                        self.reply(200, step)
                    else:
                        self.reply(200, step[0], step[1].items())
                elif self.path == "/eSCL/ScannerStatus":
                    fake.status_calls += 1
                    state = fake.states.pop(0) if len(fake.states) > 1 else fake.states[0]
                    if state is None:
                        self.reply(500)
                    else:
                        self.reply(200, (
                            '<scan:ScannerStatus xmlns:scan='
                            '"http://schemas.hp.com/imaging/escl/2011/05/03">'
                            f"<scan:AdfState>{state}</scan:AdfState></scan:ScannerStatus>"
                        ).encode())
                else:
                    self.reply(500)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/eSCL"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
