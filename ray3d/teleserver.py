"""Serveur local pour le télémètre : un smartphone sur le même réseau saisit les mesures.

- HTTP (port 8765 par défaut) : page d'accueil, application mobile (/app), API JSON (/api/…),
  téléchargement de l'application Android (/ray3d-telemetre.apk).
- Découverte UDP (port 47800) : l'application Android envoie « RAY3D? » en diffusion, le serveur
  répond avec son nom et son port.

Les requêtes sont exécutées dans le fil de l'interface (signal Qt) : la scène n'est jamais modifiée
depuis le fil du serveur.
"""
from __future__ import annotations

import glob
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from PySide6 import QtCore

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
DISCOVERY_PORT = 47800
APK_NAME = "ray3d-telemetre.apk"
USER_DIR = os.path.join(os.path.expanduser("~"), ".ray3d")


def apk_path():
    """APK à servir : ~/.ray3d/ray3d-telemetre.apk, sinon celui du dépôt (android/…)."""
    root = os.path.dirname(HERE)
    cands = [os.path.join(USER_DIR, APK_NAME), os.path.join(root, "android", APK_NAME)]
    cands += sorted(glob.glob(os.path.join(root, "android", "app", "build", "outputs", "apk", "*", "*.apk")))
    return next((p for p in cands if os.path.isfile(p)), None)


def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))          # aucun paquet envoyé : choisit l'interface par défaut
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


class Bridge(QtCore.QObject):
    """Exécute une fonction dans le fil Qt et rend le résultat au fil du serveur."""
    _job = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self._job.connect(self._run, QtCore.Qt.ConnectionType.QueuedConnection)

    def call(self, fn, *args, timeout=8.0):
        box = dict(ev=threading.Event(), res=None, err=None)
        self._job.emit((fn, args, box))
        if not box["ev"].wait(timeout):
            raise TimeoutError("l'application ne répond pas")
        if box["err"] is not None:
            raise box["err"]
        return box["res"]

    def _run(self, job):
        fn, args, box = job
        try:
            box["res"] = fn(*args)
        except Exception as e:          # renvoyé au téléphone
            box["err"] = e
        finally:
            box["ev"].set()


class TeleServer:
    """api : objet avec state(), set_ref(d), save_point(d), delete_point(id), build(d), name."""

    def __init__(self, api, port=8765):
        self.api = api
        self.port = int(port)
        self.bridge = Bridge()
        self.httpd = None
        self.udp = None
        self.threads = []

    @property
    def running(self):
        return self.httpd is not None

    def urls(self):
        return [f"http://{ip}:{self.port}" for ip in local_ips()]

    def start(self):
        if self.httpd:
            return
        handler = _make_handler(self)
        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        self.httpd.daemon_threads = True
        t = threading.Thread(target=self.httpd.serve_forever, name="ray3d-http", daemon=True)
        t.start()
        self.threads = [t]
        try:
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp.bind(("", DISCOVERY_PORT))
            self.udp.settimeout(0.5)
            u = threading.Thread(target=self._discovery, name="ray3d-udp", daemon=True)
            u.start()
            self.threads.append(u)
        except OSError:
            self.udp = None          # la découverte est facultative

    def _discovery(self):
        sock = self.udp
        while self.udp is sock:
            try:
                data, addr = sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            if data.strip().startswith(b"RAY3D?"):
                msg = json.dumps(dict(app="ray3d", name=socket.gethostname(), port=self.port)).encode()
                try:
                    sock.sendto(msg, addr)
                except OSError:
                    pass

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.udp:
            s, self.udp = self.udp, None
            try:
                s.close()
            except OSError:
                pass


def _read(name):
    with open(os.path.join(WEB, name), "rb") as fh:
        return fh.read()


def _index_page(server):
    apk = apk_path()
    urls = server.urls()
    dl = (f'<a class="btn pri" href="/{APK_NAME}">Télécharger l\'application Android</a>'
          f'<p class="note">Sur le téléphone : autorisez l\'installation depuis le navigateur, puis ouvrez le '
          f'fichier. L\'application trouve ce serveur toute seule sur le Wi-Fi.</p>') if apk else (
          '<p class="note">L\'application Android n\'est pas encore disponible sur ce serveur : placez '
          f'<code>{APK_NAME}</code> dans <code>~/.ray3d/</code> (voir le README). En attendant, utilisez la '
          'version navigateur ci-dessous : elle fait la même chose.</p>')
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ray 3D · télémètre</title>
<style>body{{background:#0c0e11;color:#d8dce1;font:15px/1.45 "Roboto Condensed",system-ui,sans-serif;margin:0;padding:22px}}
h1{{font-size:16px;letter-spacing:.22em;margin:0 0 18px}}h1 i{{color:#e9a23b;font-style:normal}}
.btn{{display:block;text-align:center;background:#191d22;color:#d8dce1;border:1px solid #262b32;border-radius:2px;
padding:14px;margin:10px 0;font-weight:600;letter-spacing:.1em;text-transform:uppercase;text-decoration:none}}
.btn.pri{{background:#e9a23b;color:#1a1206;border-color:#e9a23b}}.note{{color:#7b8490;font-size:13px}}
code{{color:#e9a23b}}</style></head><body><h1>RAY <i>3D</i> · TÉLÉMÈTRE</h1>
<p>Scène : <b>{server.api.name()}</b></p>{dl}
<a class="btn" href="/app">Ouvrir dans le navigateur</a>
<p class="note">Adresse(s) du serveur : {" · ".join(urls)}</p></body></html>""".encode()


def _make_handler(server):
    class H(BaseHTTPRequestHandler):
        server_version = "Ray3D"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=float).encode())

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path in ("/", "/index.html"):
                    self._send(200, _index_page(server), "text/html; charset=utf-8")
                elif path in ("/app", "/app/"):
                    self._send(200, _read("telemetre.html"), "text/html; charset=utf-8")
                elif path == "/api/state":
                    self._json(server.bridge.call(server.api.state))
                elif path == "/api/ping":
                    self._json(dict(app="ray3d", name=server.bridge.call(server.api.name)))
                elif path == f"/{APK_NAME}":
                    p = apk_path()
                    if not p:
                        self._send(404, "APK absent du serveur".encode(), "text/plain; charset=utf-8")
                        return
                    with open(p, "rb") as fh:
                        data = fh.read()
                    self._send(200, data, "application/vnd.android.package-archive",
                               {"Content-Disposition": f'attachment; filename="{APK_NAME}"'})
                else:
                    self._send(404, b"{}")
            except Exception as e:
                self._json(dict(error=str(e)), 500)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}") if n else {}
                fn = {"/api/ref": server.api.set_ref, "/api/point": server.api.save_point,
                      "/api/delete": server.api.delete_point, "/api/build": server.api.build,
                      "/api/preview": server.api.preview}.get(path)
                if fn is None:
                    self._send(404, b"{}")
                    return
                self._json(server.bridge.call(fn, data))
            except Exception as e:
                self._json(dict(error=str(e)), 400)

    return H
