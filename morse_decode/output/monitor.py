"""Read-only browser monitor served on the receiver's loopback interface."""

import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


PAGE = b"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MorseDecode receiver</title>
<style>
  html { color-scheme: light dark; font: 1rem system-ui; }
  body { margin: 2rem auto; max-width: 56rem; padding: 0 1rem; }
  article { border-top: 1px solid GrayText; padding: 1rem 0; }
  pre { margin-bottom: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
<h1>MorseDecode receiver</h1>
<p id="status" role="status">Connecting to receiver...</p>
<main id="channels"></main>
<script>
const token = location.hash.slice(1);
const status = document.getElementById('status');
const channels = document.getElementById('channels');
const rows = [];

async function poll() {
  try {
    const response = await fetch('/snapshot', {
      headers: {Authorization: 'Bearer ' + token},
      signal: AbortSignal.timeout(3000)
    });
    if (response.status === 401) {
      status.textContent = 'Open the monitor link shown on the receiver.';
      return;
    }
    if (!response.ok) throw new Error(response.status);
    const snapshots = await response.json();
    while (rows.length > snapshots.length) rows.pop().article.remove();
    snapshots.forEach((channel, index) => {
      if (!rows[index]) {
        const article = channels.appendChild(document.createElement('article'));
        rows[index] = {
          article,
          heading: article.appendChild(document.createElement('strong')),
          copy: article.appendChild(document.createElement('pre'))
        };
      }
      const {heading, copy} = rows[index];
      const label = channel.active
        ? channel.speed_wpm.toFixed(1) + ' WPM | ' + channel.signal_db.toFixed(1) + ' dB'
        : 'Idle';
      heading.textContent = [channel.freq_hz + ' Hz', label, channel.callsign].filter(Boolean).join(' | ');
      if (copy.textContent !== channel.text) copy.textContent = channel.text;
    });
    status.textContent = snapshots.length ? 'Connected' : 'Waiting for audio';
  } catch {
    status.textContent = 'Receiver disconnected. Retrying...';
  }
  setTimeout(poll, 500);
}
poll();
</script>
"""


class Monitor:
    def __init__(self, port: int) -> None:
        self.token = secrets.token_urlsafe(24)
        self._snapshot = b"[]"
        monitor = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(1)
                super().setup()

            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path == "/":
                    code, content_type, body = 200, "text/html; charset=utf-8", PAGE
                elif self.path == "/snapshot":
                    auth = self.headers.get("Authorization", "").encode("utf-8")
                    if secrets.compare_digest(auth, f"Bearer {monitor.token}".encode("ascii")):
                        code, content_type, body = 200, "application/json", monitor._snapshot
                    else:
                        code, content_type, body = 401, "text/plain", b"Authorization required.\n"
                else:
                    code, content_type, body = 404, "text/plain", b"Not found.\n"
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy",
                                 "default-src 'none'; connect-src 'self'; script-src 'unsafe-inline'; "
                                 "style-src 'unsafe-inline'; frame-ancestors 'none'")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

        self._server = HTTPServer(("127.0.0.1", port), Handler)
        self.port = self._server.server_port
        self._thread = Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#{self.token}"

    def publish(self, channels: list[dict]) -> None:
        self._snapshot = json.dumps(channels, allow_nan=False).encode("utf-8")

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
