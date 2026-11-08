from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from functools import partial
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent
SEED_FILE = ROOT / "properties.seed.json"
DATA_HOME = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RJW"
DATABASE_PATH = Path(os.environ.get("RJW_DATABASE", DATA_HOME / "properties.sqlite3"))
DEVELOPER_KEY = os.environ.get("RJW_DEVELOPER_KEY", "")
HOST = os.environ.get("RJW_HOST", "127.0.0.1")
PORT = int(os.environ.get("RJW_PORT", "8000"))
COOKIE_SECURE = os.environ.get("RJW_COOKIE_SECURE", "0") == "1"
SESSION_SECONDS = 8 * 60 * 60
MAX_REQUEST_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGES = 8
CATEGORIES = {"Terrenos", "Apartamentos", "Casas", "Vehiculos", "Maquinaria", "Equipos", "Habitaciones"}
DEPARTMENTS = {
    "Alta Verapaz", "Baja Verapaz", "Chimaltenango", "Chiquimula", "El Progreso",
    "Escuintla", "Guatemala", "Huehuetenango", "Izabal", "Jalapa", "Jutiapa", "Petén",
    "Quetzaltenango", "Quiché", "Retalhuleu", "Sacatepéquez", "San Marcos", "Santa Rosa",
    "Sololá", "Suchitepéquez", "Totonicapán", "Zacapa"
}
SERVICES = {"Agua", "Luz", "Drenaje", "Cisterna"}
PAYMENTS = {"Al Contado", "Financiamiento"}
MODES = {"sale", "rent"}
SESSIONS: dict[str, dict[str, object]] = {}
SESSIONS_LOCK = threading.RLock()
LOGIN_ATTEMPTS: dict[str, tuple[float, int]] = {}
LOGIN_LOCK = threading.RLock()


@contextmanager
def connect_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with connect_database() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS properties ("
            "id TEXT PRIMARY KEY, status TEXT NOT NULL, verified INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        seeded = connection.execute("SELECT value FROM app_meta WHERE key='seeded_v1'").fetchone()
        if not seeded and SEED_FILE.exists():
            seed_properties = json.loads(SEED_FILE.read_text(encoding="utf-8"))
            for property_data in seed_properties:
                property_data["publicationStatus"] = "published"
                property_data.setdefault("verifiedByDeveloper", False)
                connection.execute(
                    "INSERT INTO properties (id, status, verified, payload) VALUES (?, ?, ?, ?)",
                    (
                        property_data["id"],
                        "published",
                        int(bool(property_data["verifiedByDeveloper"])),
                        json.dumps(property_data, ensure_ascii=False),
                    ),
                )
            connection.execute("INSERT INTO app_meta (key, value) VALUES ('seeded_v1', '1')")


def clean_text(value: object, field: str, max_length: int, required: bool = False) -> str:
    if not isinstance(value, str):
        if value is None and not required:
            return ""
        raise ValueError(f"Invalid {field}.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} is required.")
    if len(value) > max_length:
        raise ValueError(f"{field} is too long.")
    return value


def validate_image_reference(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_REQUEST_BYTES:
        raise ValueError("Invalid image.")
    if value.startswith("data:image/"):
        header, separator, encoded = value.partition(",")
        if not separator or not re.fullmatch(r"data:image/(jpeg|png|webp);base64", header):
            raise ValueError("Only JPEG, PNG, or WebP images are allowed.")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Invalid image encoding.") from error
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("Each image must be smaller than 2 MB after compression.")
        return value
    if value.startswith("/") or "\\" in value or ":" in value:
        raise ValueError("Invalid local image path.")
    decoded_path = unquote(value)
    candidate = (ROOT / decoded_path).resolve()
    if (
        not re.fullmatch(r"[A-Za-z0-9_%(). -]+\.(jpg|jpeg|png|webp)", value, re.IGNORECASE)
        or candidate == ROOT
        or not candidate.is_relative_to(ROOT)
        or not candidate.is_file()
    ):
        raise ValueError("Invalid local image path.")
    return value


def validate_property(data: object, previous: dict[str, object] | None = None) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("A property object is required.")
    previous = previous or {}
    result: dict[str, object] = dict(previous)

    category = clean_text(data.get("category", previous.get("category")), "category", 40, True)
    if category not in CATEGORIES:
        raise ValueError("Unsupported category.")
    is_equipment = category in {"Vehiculos", "Maquinaria", "Equipos"}
    result["category"] = category

    modes = data.get("modes", previous.get("modes"))
    if not isinstance(modes, list) or not modes or any(not isinstance(mode, str) or mode not in MODES for mode in modes):
        raise ValueError("Select Venta, Renta, or both.")
    result["modes"] = list(dict.fromkeys(modes))

    for field, max_length, required in (
        ("name", 120, True),
        ("description", 1000, True),
        ("measures", 120, False),
        ("location", 240, not is_equipment),
        ("department", 40, not is_equipment),
        ("serviceNotes", 240, False),
        ("deedType", 40, False),
        ("documentStatus", 80, False),
        ("price", 80, False),
        ("unitPrice", 80, False),
        ("paymentTerms", 240, False),
        ("contactEmail", 254, False),
        ("brand", 80, False),
        ("model", 80, False),
        ("year", 20, False),
        ("condition", 40, False),
        ("usageMetric", 80, False),
        ("technicalDetails", 1000, False),
        ("warranty", 120, False),
    ):
        result[field] = clean_text(data.get(field, previous.get(field)), field, max_length, required)

    if result["department"] and result["department"] not in DEPARTMENTS:
        raise ValueError("Select a valid department.")

    for field, allowed in (("services", SERVICES), ("paymentOptions", PAYMENTS)):
        values = data.get(field, previous.get(field, []))
        if not isinstance(values, list) or any(not isinstance(value, str) or value not in allowed for value in values):
            raise ValueError(f"Invalid {field} selection.")
        result[field] = list(dict.fromkeys(values))

    extras = data.get("extras", previous.get("extras", []))
    if not isinstance(extras, list) or any(not isinstance(item, str) or len(item) > 120 for item in extras):
        raise ValueError("Invalid extras.")
    result["extras"] = [item.strip() for item in extras if item.strip()]

    for field in ("availableCount", "waterSources"):
        value = data.get(field, previous.get(field))
        if value in (None, ""):
            result.pop(field, None)
        else:
            try:
                number = int(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid {field}.") from error
            if number < 1 or number > 100000:
                raise ValueError(f"Invalid {field}.")
            result[field] = number

    available_unit = clean_text(data.get("availableUnit", previous.get("availableUnit", "unidades")), "availableUnit", 24)
    if available_unit not in {"unidades", "lotes", "habitaciones", "equipos", "maquinarias"}:
        raise ValueError("Invalid available unit.")
    result["availableUnit"] = available_unit

    images = data.get("images", previous.get("images"))
    if images is None:
        image = data.get("image", previous.get("image"))
        images = [image] if image else []
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES:
        raise ValueError("A property must have between one and eight images.")
    result["images"] = [validate_image_reference(image) for image in images]
    result["image"] = result["images"][0]

    alts = data.get("imageAlts", previous.get("imageAlts", []))
    if not isinstance(alts, list):
        alts = []
    result["imageAlts"] = [clean_text(alt, "image alt", 240) for alt in alts[:MAX_IMAGES]]
    result["imageAlt"] = result["imageAlts"][0] if result["imageAlts"] else result["name"]

    return result


def sanitize_public_property(property_data: dict[str, object]) -> dict[str, object]:
    result = dict(property_data)
    result.pop("contactEmail", None)
    result.pop("userSubmitted", None)
    return result


def save_property(property_data: dict[str, object], status: str, verified: bool) -> None:
    property_data["publicationStatus"] = status
    property_data["verifiedByDeveloper"] = verified
    with connect_database() as connection:
        connection.execute(
            "INSERT INTO properties (id, status, verified, payload) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, verified=excluded.verified, payload=excluded.payload",
            (
                str(property_data["id"]),
                status,
                int(verified),
                json.dumps(property_data, ensure_ascii=False),
            ),
        )


def get_property(property_id: str) -> tuple[str, bool, dict[str, object]] | None:
    with connect_database() as connection:
        row = connection.execute(
            "SELECT status, verified, payload FROM properties WHERE id = ?", (property_id,)
        ).fetchone()
    if row is None:
        return None
    return row["status"], bool(row["verified"]), json.loads(row["payload"])


class RJWHandler(SimpleHTTPRequestHandler):
    server_version = "RJWLocal/1.0"

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; connect-src 'self'; frame-ancestors 'none'",
        )
        super().end_headers()

    def send_json(self, status: int, data: object, cookie: str | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_api_error(self, status: int, message: str) -> None:
        self.send_json(status, {"error": message})

    def make_cookie(self, session_id: str, max_age: int = SESSION_SECONDS) -> str:
        secure = "; Secure" if COOKIE_SECURE else ""
        return f"rjw_session={session_id}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}"

    def get_session(self, create: bool = False) -> tuple[str | None, dict[str, object] | None, bool]:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            morsel = cookie.get("rjw_session")
            session_id = morsel.value if morsel else None
        except Exception:
            session_id = None

        now = time.time()
        with SESSIONS_LOCK:
            expired = [key for key, value in SESSIONS.items() if float(value["expires"]) <= now]
            for key in expired:
                SESSIONS.pop(key, None)
            session = SESSIONS.get(session_id) if session_id else None
            if session:
                session["expires"] = now + SESSION_SECONDS
                return session_id, session, False
            if not create:
                return None, None, False
            session_id = secrets.token_urlsafe(32)
            session = {"csrf": secrets.token_urlsafe(32), "developer": False, "expires": now + SESSION_SECONDS}
            SESSIONS[session_id] = session
            return session_id, session, True

    def check_origin_and_csrf(self, session: dict[str, object] | None) -> bool:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if origin and host and urlsplit(origin).netloc.lower() != host.lower():
            self.send_api_error(403, "Cross-origin request rejected.")
            return False
        token = self.headers.get("X-CSRF-Token", "")
        if not session or not hmac.compare_digest(token, str(session["csrf"])):
            self.send_api_error(403, "Invalid or expired CSRF token.")
            return False
        return True

    def require_developer(self, session: dict[str, object] | None) -> bool:
        if not session or not session.get("developer"):
            self.send_api_error(401, "Developer login required.")
            return False
        return True

    def read_json_body(self) -> dict[str, object] | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_api_error(400, "Invalid content length.")
            return None
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            self.send_api_error(413, "Request is too large.")
            return None
        try:
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_api_error(400, "Invalid JSON body.")
            return None
        if not isinstance(payload, dict):
            self.send_api_error(400, "A JSON object is required.")
            return None
        return payload

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/api/session":
            session_id, session, is_new = self.get_session(create=True)
            cookie = self.make_cookie(str(session_id)) if is_new else None
            self.send_json(200, {"developer": bool(session and session.get("developer")), "csrfToken": session["csrf"]}, cookie)
            return

        if parsed.path == "/api/properties":
            _, session, _ = self.get_session()
            query = parse_qs(parsed.query)
            pending_only = query.get("status", [""])[0] == "pending"
            if pending_only and not self.require_developer(session):
                return
            if not pending_only and query.get("manage", [""])[0] == "1" and not self.require_developer(session):
                return
            with connect_database() as connection:
                if pending_only:
                    rows = connection.execute("SELECT payload FROM properties WHERE status='pending' ORDER BY rowid DESC").fetchall()
                elif query.get("manage", [""])[0] == "1":
                    rows = connection.execute("SELECT payload FROM properties WHERE status='published' ORDER BY rowid").fetchall()
                else:
                    rows = connection.execute("SELECT payload FROM properties WHERE status='published' ORDER BY rowid").fetchall()
            is_developer = bool(session and session.get("developer"))
            properties = [json.loads(row["payload"]) for row in rows]
            if not is_developer:
                properties = [sanitize_public_property(item) for item in properties]
            self.send_json(200, {"properties": properties})
            return

        if parsed.path.startswith("/api/"):
            self.send_api_error(404, "API route not found.")
            return

        static_path = unquote(parsed.path).lstrip("/")
        if static_path in {"server.py", "properties.seed.json"}:
            self.send_error(404)
            return
        self.path = parsed.path
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        _, session, _ = self.get_session()

        if parsed.path == "/api/auth/login":
            if not self.check_origin_and_csrf(session):
                return
            if not DEVELOPER_KEY:
                self.send_api_error(503, "Developer login is disabled until RJW_DEVELOPER_KEY is configured on the server.")
                return
            address = self.client_address[0]
            now = time.time()
            with LOGIN_LOCK:
                started, attempts = LOGIN_ATTEMPTS.get(address, (now, 0))
                if now - started > 300:
                    started, attempts = now, 0
                if attempts >= 5:
                    self.send_api_error(429, "Too many login attempts. Try again in five minutes.")
                    return
            payload = self.read_json_body()
            if payload is None:
                return
            key = payload.get("key")
            if not isinstance(key, str) or not hmac.compare_digest(key.encode("utf-8"), DEVELOPER_KEY.encode("utf-8")):
                with LOGIN_LOCK:
                    LOGIN_ATTEMPTS[address] = (started, attempts + 1)
                self.send_api_error(401, "Invalid developer key.")
                return
            with LOGIN_LOCK:
                LOGIN_ATTEMPTS.pop(address, None)
            old_session_id = self.get_session()[0]
            if old_session_id:
                with SESSIONS_LOCK:
                    SESSIONS.pop(old_session_id, None)
            new_id = secrets.token_urlsafe(32)
            new_session = {"csrf": secrets.token_urlsafe(32), "developer": True, "expires": now + SESSION_SECONDS}
            with SESSIONS_LOCK:
                SESSIONS[new_id] = new_session
            self.send_json(200, {"developer": True, "csrfToken": new_session["csrf"]}, self.make_cookie(new_id))
            return

        if parsed.path == "/api/auth/logout":
            if not self.check_origin_and_csrf(session):
                return
            session_id = self.get_session()[0]
            if session_id:
                with SESSIONS_LOCK:
                    SESSIONS.pop(session_id, None)
            new_id = secrets.token_urlsafe(32)
            new_session = {"csrf": secrets.token_urlsafe(32), "developer": False, "expires": time.time() + SESSION_SECONDS}
            with SESSIONS_LOCK:
                SESSIONS[new_id] = new_session
            self.send_json(200, {"developer": False, "csrfToken": new_session["csrf"]}, self.make_cookie(new_id))
            return

        if not parsed.path.startswith("/api/properties"):
            self.send_api_error(404, "API route not found.")
            return
        if not self.check_origin_and_csrf(session):
            return

        segments = [part for part in parsed.path.split("/") if part]
        if len(segments) == 2:
            payload = self.read_json_body()
            if payload is None:
                return
            try:
                property_data = validate_property(payload)
            except ValueError as error:
                self.send_api_error(400, str(error))
                return
            developer = bool(session and session.get("developer"))
            property_data["id"] = secrets.token_urlsafe(18)
            property_data["userSubmitted"] = True
            save_property(property_data, "published" if developer else "pending", developer)
            response = {
                "id": property_data["id"],
                "status": property_data["publicationStatus"],
                "verifiedByDeveloper": property_data["verifiedByDeveloper"],
            }
            if developer:
                response["property"] = property_data
            self.send_json(201, response)
            return

        if len(segments) == 3 and segments[2] == "login":
            self.send_api_error(404, "API route not found.")
            return

        if len(segments) == 4 and segments[3] in {"approve", "reject"}:
            if not self.require_developer(session):
                return
            property_id = segments[2]
            row = get_property(property_id)
            if not row or row[0] != "pending":
                self.send_api_error(404, "Pending property not found.")
                return
            if segments[3] == "reject":
                with connect_database() as connection:
                    connection.execute("DELETE FROM properties WHERE id=? AND status='pending'", (property_id,))
                self.send_json(200, {"status": "rejected"})
                return
            property_data = row[2]
            save_property(property_data, "published", True)
            self.send_json(200, {"status": "published", "property": property_data})
            return

        self.send_api_error(404, "API route not found.")

    def do_PATCH(self) -> None:
        parsed = urlsplit(self.path)
        _, session, _ = self.get_session()
        if not self.require_developer(session):
            return
        if not self.check_origin_and_csrf(session):
            return
        segments = [part for part in parsed.path.split("/") if part]
        if len(segments) != 3 or segments[:2] != ["api", "properties"]:
            self.send_api_error(404, "API route not found.")
            return
        current = get_property(segments[2])
        if not current or current[0] != "published":
            self.send_api_error(404, "Published property not found.")
            return
        payload = self.read_json_body()
        if payload is None:
            return
        try:
            property_data = validate_property(payload, current[2])
        except ValueError as error:
            self.send_api_error(400, str(error))
            return
        property_data["id"] = segments[2]
        property_data["userSubmitted"] = current[2].get("userSubmitted", False)
        save_property(property_data, "published", True)
        self.send_json(200, {"property": property_data})

    def do_DELETE(self) -> None:
        _, session, _ = self.get_session()
        if not self.require_developer(session):
            return
        if not self.check_origin_and_csrf(session):
            return
        segments = [part for part in urlsplit(self.path).path.split("/") if part]
        if len(segments) != 3 or segments[:2] != ["api", "properties"]:
            self.send_api_error(404, "API route not found.")
            return
        with connect_database() as connection:
            cursor = connection.execute("DELETE FROM properties WHERE id=? AND status='published'", (segments[2],))
        if cursor.rowcount == 0:
            self.send_api_error(404, "Published property not found.")
            return
        self.send_json(200, {"deleted": True})

    def do_PUT(self) -> None:
        self.send_api_error(405, "Use PATCH to update a property.")


def main() -> None:
    initialize_database()
    handler = partial(RJWHandler, directory=str(ROOT))
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"RJW local server: http://{HOST}:{PORT}")
    print("Developer login is enabled." if DEVELOPER_KEY else "Developer login disabled: set RJW_DEVELOPER_KEY in the server environment.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping RJW server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
