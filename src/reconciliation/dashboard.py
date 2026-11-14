"""Loopback dashboard for an operator with access to this checkout."""

import json
import os
import re
import secrets
import socket
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import rmtree
from tempfile import TemporaryDirectory
from threading import Lock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from . import workbench
from .contracts import CATEGORIES, scope_id
from .dashboard_pipeline import DashboardPipeline
from .db import event, query
from .generator import generate
from .reporting import atomic_write, json_file, render_report
from .storage import LocalStore

ASSETS = Path(__file__).with_name("web")
STATIC = {"/": ("index.html", "text/html"), "/dashboard.css": ("dashboard.css", "text/css"),
          "/dashboard.js": ("dashboard.js", "text/javascript")}
FORMATS = {"json": "application/json", "csv": "text/csv", "md": "text/markdown"}
ID = r"([1-9][0-9]{0,18})"
DATASET_ID = r"[a-f0-9]{32}"
DATASET_FILE = {
    "ledger.csv": ("inputs", "text/csv"),
    "settlements.csv": ("inputs", "text/csv"),
    "manifest.json": ("inputs", "application/json"),
    "answer_key.json": ("truth", "application/json"),
}


class RequestError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def report_index(db, scope=None, day=None):
    with db.connect() as conn:
        if scope is None:
            rows = query(conn, """
                SELECT r.id,r.scope,r.business_date,r.cutoff FROM current_results c
                JOIN results r ON r.id=c.result_id
                ORDER BY r.business_date DESC,r.cutoff DESC,r.id DESC
            """)
        else:
            rows = query(conn, """
                SELECT r.id,r.scope,r.business_date,r.cutoff,c.result_id=r.id AS current
                FROM results r JOIN current_results c USING (scope,business_date)
                WHERE r.scope=:scope AND r.business_date=:day
                ORDER BY (c.result_id=r.id) DESC,r.cutoff DESC,r.id DESC
            """, scope=scope, day=day)
        return [dict(row) for row in rows.mappings()]


def report_by_id(db, result_id):
    with db.connect() as conn:
        row = query(conn, """
            SELECT r.report,r.result_hash,c.result_id=r.id AS current,
              (SELECT min(id) FROM operations WHERE detail->>'result_id'=CAST(r.id AS text)) AS run_id
            FROM results r JOIN current_results c USING (scope,business_date) WHERE r.id=:id
        """, id=result_id).one_or_none()
    if row is None:
        raise RequestError(404, "Report not found.")
    return dict(**row.report, result_id=result_id, run_id=row.run_id, result_hash=row.result_hash,
                current=row.current)


def issue_options(params):
    scope = scope_id(params.get("scope", ""))
    day = date.fromisoformat(params.get("day", ""))
    status, category = params.get("status"), params.get("category")
    if status not in {None, "open", "resolved"} or category not in {None, *CATEGORIES}:
        raise RequestError(400, "Choose a supported status or exception type.")
    after = int(params.get("after", 0))
    if not 0 <= after < 2**63:
        raise RequestError(400, "Invalid exception cursor.")
    return dict(scope=scope, day=day, status=status, category=category, after=after,
                merchant=params.get("merchant"), include_inactive=params.get("include_inactive") == "1")


def browser_numbers(value):
    """Preserve integer precision in browser JSON without changing report exports."""
    if type(value) is int and abs(value) >= 2**53:
        return str(value)
    if isinstance(value, dict):
        return {key: browser_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [browser_numbers(item) for item in value]
    return value


def current_dataset(root):
    try:
        return json.loads((root / "current.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def remove_previous_datasets(root, current_id):
    cleanup_pending = False
    for bundle in root.iterdir():
        if (bundle.name == current_id or not re.fullmatch(DATASET_ID, bundle.name)
                or not bundle.is_dir() or bundle.resolve() != bundle):
            continue
        # Only remove generator bundles directly inside the resolved dataset root.
        try:
            rmtree(bundle)
        except OSError as exc:
            cleanup_pending = True
            event("dashboard-dataset", status="cleanup-pending", error=type(exc).__name__)
    return cleanup_pending


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, db, port, *, local_demo=False, dataset_root=Path("artifacts/work/dashboard-datasets"),
                 raw_root=None):
        self.db = db
        self.local_demo = local_demo
        self.dataset_root = dataset_root.resolve()
        self.dataset_lock = Lock()
        self.pipeline = DashboardPipeline(db, LocalStore(raw_root or os.getenv("RECON_RAW_DIR", "artifacts/work/raw")))
        self.access_key = None if local_demo else secrets.token_urlsafe(32)
        self.session = None if local_demo else secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), DashboardHandler)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.localhost = f"localhost:{self.server_port}"
        self.cookie_name = f"recon_dashboard_{self.server_port}"

    def server_bind(self):
        if os.name == "nt":
            # SO_REUSEADDR alone allows two Windows listeners on the same port.
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    @property
    def access_url(self):
        if self.local_demo:
            return f"http://{self.localhost}/"
        return f"{self.origin}/#access={self.access_key}"


class DashboardHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, *_):
        # Access links, payloads, source records, and database errors stay out of request logs.
        pass

    def do_GET(self):
        self.handle_dashboard()

    def do_POST(self):
        self.handle_dashboard()

    def handle_dashboard(self):
        try:
            host = self.headers.get("Host")
            allowed = {self.server.host}
            if self.server.local_demo:
                allowed.add(self.server.localhost)
            if host not in allowed:
                raise RequestError(403, "Open the dashboard using its local address.")
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{host}":
                raise RequestError(403, "Open the dashboard directly in your browser.")
            target = urlsplit(self.path)
            if self.command == "GET" and target.path in STATIC:
                name, content_type = STATIC[target.path]
                return self.send_data(200, (ASSETS / name).read_bytes(), content_type)
            if self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
                raise RequestError(403, "Open the dashboard directly in your browser.")
            if self.command == "POST":
                if (origin != f"http://{host}"
                        or self.headers.get_content_type() != "application/json"):
                    raise RequestError(403, "Submit changes from the dashboard.")
                body = self.read_json()
                if target.path == "/api/session":
                    if self.server.local_demo:
                        return self.send_json(200, {"signed_in": True})
                    if not self.matches(body.get("key"), self.server.access_key):
                        raise RequestError(401, "This link is no longer valid. Use the link from the running dashboard.")
                    cookie = f"{self.server.cookie_name}={self.server.session}; Path=/; HttpOnly; SameSite=Strict"
                    return self.send_json(200, {"signed_in": True}, cookie=cookie)
            if not self.server.local_demo:
                cookies = [part.strip() for part in self.headers.get("Cookie", "").split(";")]
                name = self.server.cookie_name + "="
                if not any(self.matches(part[len(name):], self.server.session) for part in cookies if part.startswith(name)):
                    raise RequestError(401, "Open the access link printed by the dashboard command.")
            if self.command == "POST":
                if target.path == "/api/datasets":
                    return self.generate_dataset()
                if route := re.fullmatch(rf"/api/datasets/({DATASET_ID})/reconcile", target.path):
                    return self.start_pipeline(route[1])
                return self.update_review(target.path, body)
            params = {key: values[-1] for key, values in parse_qs(target.query, max_num_fields=16).items()}
            self.read_api(target.path, params)
        except RequestError as exc:
            self.send_json(exc.status, {"error": str(exc)})
        except (TypeError, ValueError, OverflowError):
            self.send_json(400, {"error": "Check the request values and try again."})
        except SQLAlchemyError as exc:
            event("dashboard", error=type(exc).__name__)
            self.send_json(503, {"error": "PostgreSQL is unavailable. Check the local database and try again."})
        except OSError as exc:
            event("dashboard", error=type(exc).__name__)
            self.send_json(500, {"error": "Could not read or save a dashboard file. Check the local disk and try again."})

    @staticmethod
    def matches(value, expected):
        return isinstance(value, str) and value.isascii() and secrets.compare_digest(value, expected)

    def read_json(self):
        size = int(self.headers.get("Content-Length", 0))
        if not 0 < size <= 8192:
            raise RequestError(400, "Send a JSON object of at most 8 KB.")
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise RequestError(400, "Send a JSON object.")
        return data

    def read_api(self, path, params):
        db = self.server.db
        if path == "/api/pipeline":
            return self.send_json(200, self.server.pipeline.snapshot())
        if path == "/api/datasets/current":
            with self.server.dataset_lock:
                dataset = current_dataset(self.server.dataset_root)
            return self.send_json(200, dataset)
        if route := re.fullmatch(rf"/api/datasets/({DATASET_ID})/([a-z_.]+)", path):
            return self.download_dataset(*route.groups())
        if path == "/api/reports":
            scope = scope_id(params["scope"]) if "scope" in params else None
            day = date.fromisoformat(params.get("day", "")) if scope is not None else None
            return self.send_json(200, report_index(db, scope, day))
        if route := re.fullmatch(rf"/api/reports/{ID}(?:\.(json|csv|md))?", path):
            result_id, extension = route.groups()
            report = report_by_id(db, self.record_id(result_id))
            if extension:
                content = render_report(report)[extension].encode("utf-8")
                filename = f"reconciliation-{report['business_date']}-{result_id}.{extension}"
                return self.send_data(200, content, FORMATS[extension], filename=filename)
            return self.send_json(200, report)
        if path == "/api/issues":
            rows = workbench.list_issues(db, **issue_options(params), limit=31)
            return self.send_json(200, {"issues": rows[:30], "next": rows[29]["id"] if len(rows) > 30 else None})
        if route := re.fullmatch(rf"/api/issues/{ID}", path):
            exception_id = self.record_id(route[1])
            try:
                issue = workbench.show(db, exception_id)
                audit = workbench.history(db, exception_id)
            except ValueError as exc:
                raise RequestError(404, "Exception not found.") from exc
            return self.send_json(200, {"issue": issue, "history": audit})
        raise RequestError(404, "Page not found.")

    def generate_dataset(self):
        root = self.server.dataset_root
        if not self.server.dataset_lock.acquire(blocking=False):
            raise RequestError(409, "The dataset is busy. Try again in a moment.")
        dataset_id = uuid4().hex
        try:
            job = self.server.pipeline.snapshot()
            if job and job["status"] == "running":
                raise RequestError(409, "Wait for reconciliation to finish before generating a new dataset.")
            root.mkdir(parents=True, exist_ok=True)
            previous = current_dataset(root)
            seed = secrets.randbits(48)
            while previous and seed == previous["seed"]:
                seed = secrets.randbits(48)
            with TemporaryDirectory(dir=root) as temp:
                bundle = Path(temp) / "dataset"
                manifest = generate(bundle / "inputs", bundle / "truth", seed, two_files=True, merchant_profiles=True)
                bundle.rename(root / dataset_id)
            dataset = {"id": dataset_id, "seed": seed, "files": manifest["files"]}
            json_file(root / "current.json", dataset)
            cleanup_pending = remove_previous_datasets(root, dataset_id)
        finally:
            self.server.dataset_lock.release()
        self.send_json(201, {**dataset, "cleanup_pending": cleanup_pending})

    def start_pipeline(self, dataset_id):
        with self.server.dataset_lock:
            root = self.server.dataset_root
            dataset = current_dataset(root)
            if not dataset or dataset["id"] != dataset_id:
                raise RequestError(404, "This dataset is no longer available. Refresh for the latest dataset.")
            job = self.server.pipeline.start(dataset, root / dataset_id / "inputs")
        self.send_json(202, job)

    def download_dataset(self, dataset_id, name):
        if name not in DATASET_FILE:
            raise RequestError(404, "Dataset file not found.")
        directory, content_type = DATASET_FILE[name]
        with self.server.dataset_lock:
            root = self.server.dataset_root
            dataset = current_dataset(root)
            if not dataset or dataset["id"] != dataset_id:
                raise RequestError(404, "This dataset is no longer available. Refresh for the latest downloads.")
            path = root / dataset_id / directory / name
            try:
                payload = path.read_bytes()
            except FileNotFoundError as exc:
                raise RequestError(404, "Dataset file not found. Generate a dataset first.") from exc
        self.send_data(200, payload, content_type, filename=name)

    def update_review(self, path, body):
        route = re.fullmatch(rf"/api/issues/{ID}/review", path)
        if not route:
            raise RequestError(404, "Page not found.")
        actor, reason, version, action = (body.get(key) for key in ("actor", "reason", "version", "action"))
        if not (isinstance(actor, str) and 0 < len(actor.strip()) <= 100
                and isinstance(reason, str) and 0 < len(reason.strip()) <= 1000
                and "\x00" not in actor and "\x00" not in reason and type(version) is int
                and 0 < version < 2**31 and action in ("resolve", "reopen")):
            raise RequestError(400, "Enter an operator name and a review reason.")
        try:
            issue = workbench.review(self.server.db, self.record_id(route[1]), version, actor, reason, action)
        except RequestError:
            raise
        except ValueError as exc:
            status = 404 if str(exc) == "Unknown exception ID" else 409
            raise RequestError(status, str(exc)) from exc
        self.send_json(200, issue)

    @staticmethod
    def record_id(raw):
        value = int(raw)
        if value >= 2**63:
            raise RequestError(404, "Record not found.")
        return value

    def send_json(self, status, value, *, cookie=None):
        payload = json.dumps(browser_numbers(value), default=str).encode("utf-8")
        self.send_data(status, payload, "application/json", cookie=cookie)

    def send_data(self, status, payload, content_type, *, cookie=None, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)


def serve(db, port, link_file=None, *, open_browser=False, local_demo=False):
    try:
        server = DashboardServer(db, port, local_demo=local_demo)
    except OSError as exc:
        if getattr(exc, "winerror", None) in {10013, 10048}:
            raise SystemExit(f"Cannot listen on port {port}. If the dashboard is already running, stop it before restarting.") from None
        raise
    with server:
        if link_file is not None:
            link_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(link_file, server.access_url + "\n")
        address = server.access_url if local_demo else f"{server.origin}/"
        print(f"Local dashboard: {address}", flush=True)
        if not local_demo and link_file is None:
            print(f"Open this private access link: {server.access_url}", flush=True)
        try:
            if open_browser:
                try:
                    opened = webbrowser.open(server.access_url)
                except (OSError, webbrowser.Error):
                    opened = False
                if not opened:
                    if local_demo or link_file is None:
                        print("Could not open the browser. Open the link printed above.", flush=True)
                    else:
                        print(f"Could not open the browser. Read the access link in {link_file}.", flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if link_file is not None:
                link_file.unlink(missing_ok=True)
