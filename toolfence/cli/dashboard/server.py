"""Read-only results dashboard server (C-6).

Serves pre-committed trial records from a results directory.  No model calls,
no outbound network, no environment variable reads.

Endpoints
---------
GET /                     → static/index.html
GET /static/<filename>    → static/<filename>
GET /api/results          → JSON array of all TrialRecord dicts in results_dir
GET /api/summary          → ResultSummary.model_dump() aggregated from results_dir

stdlib only: http.server, json, pathlib, argparse.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_STATIC_DIR = _HERE / "static"


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class _DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the ToolFence dashboard."""

    # Injected by the server factory before the first request.
    results_dir: Path = Path("results")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence the default per-request log to keep stdout clean."""

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]  # strip query string

        if path in ("/", ""):
            self._serve_file(_STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif path.startswith("/static/"):
            filename = path[len("/static/"):]
            self._serve_file(_STATIC_DIR / filename, _mime(filename))
        elif path == "/api/results":
            self._serve_results()
        elif path == "/api/summary":
            self._serve_summary()
        else:
            self._not_found()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _serve_file(self, filepath: Path, content_type: str) -> None:
        if not filepath.is_file():
            self._not_found()
            return
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_results(self) -> None:
        records = _load_records(self.results_dir)
        body = json.dumps(records, default=str).encode("utf-8")
        self._send_json(body)

    def _serve_summary(self) -> None:
        from toolfence.contracts.trial import TrialRecord
        from toolfence.engine.scoring import aggregate

        raw_records = _load_records(self.results_dir)
        trial_records = []
        for r in raw_records:
            try:
                trial_records.append(TrialRecord.model_validate(r))
            except Exception:  # noqa: BLE001
                pass

        summary = aggregate(trial_records, run_id="dashboard")
        body = json.dumps(summary.model_dump(), default=str).encode("utf-8")
        self._send_json(body)

    def _send_json(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mime(filename: str) -> str:
    if filename.endswith(".html"):
        return "text/html; charset=utf-8"
    if filename.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if filename.endswith(".css"):
        return "text/css; charset=utf-8"
    return "application/octet-stream"


def _load_records(results_dir: Path) -> list[dict]:
    """Load all *.json files from *results_dir* as plain dicts."""
    records = []
    if not results_dir.is_dir():
        return records
    for jf in sorted(results_dir.glob("*.json")):
        try:
            records.append(json.loads(jf.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return records


def make_server(host: str, port: int, results_dir: Path) -> HTTPServer:
    """Create and return a configured ``HTTPServer`` (does not start it)."""

    # Bind results_dir into the handler class via a subclass so each request
    # can find it without global state.
    handler = type(
        "_Handler",
        (_DashboardHandler,),
        {"results_dir": results_dir},
    )
    return HTTPServer((host, port), handler)


# ---------------------------------------------------------------------------
# CLI entry point (called from toolfence/cli/main.py serve subcommand)
# ---------------------------------------------------------------------------

def run_server(host: str = "localhost", port: int = 8080,
               results_dir: Path = Path("results")) -> None:
    """Start the dashboard server and block until interrupted."""
    server = make_server(host, port, results_dir)
    print(f"ToolFence dashboard listening on http://{host}:{port}")
    print(f"Serving results from: {results_dir.resolve()}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# Direct invocation
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ToolFence dashboard server")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()
    run_server(args.host, args.port, Path(args.results_dir))
