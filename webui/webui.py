from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import posixpath
import re
import shutil
from urllib.parse import parse_qs, quote, unquote, urlsplit


HOST = "127.0.0.1"
PORT = 8001
WEBUI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEBUI_DIR.parent
HTML_PATH = WEBUI_DIR / "index.html"
DCIM_DIR = PROJECT_ROOT / "dcim"
MAX_BODY_SIZE = 512 * 1024 * 1024

IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".webm"}



def natural_sort_key(path):
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def clean_relative_path(raw_path):
    decoded = unquote(raw_path or "").replace("\\", "/")
    normalized = posixpath.normpath(f"/{decoded}").lstrip("/")
    return "" if normalized == "." else normalized


def resolve_dcim_path(raw_path):
    relative_path = clean_relative_path(raw_path)
    path = (DCIM_DIR / relative_path).resolve()
    dcim_root = DCIM_DIR.resolve()

    if path != dcim_root and dcim_root not in path.parents:
        raise ValueError("Path must stay inside DCIM")

    return path, relative_path


def safe_name(raw_name):
    name = Path(raw_name or "").name.strip()
    name = re.sub(r"[\x00-\x1f]", "", name)
    if not name or name in {".", ".."}:
        raise ValueError("Invalid name")
    return name


def unique_destination(directory, filename):
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    destination = directory / filename
    counter = 1

    while destination.exists():
        destination = directory / f"{stem} ({counter}){suffix}"
        counter += 1

    return destination


def item_payload(path):
    stat = path.stat()
    relative_path = path.relative_to(DCIM_DIR).as_posix()
    suffix = path.suffix.lower()

    if path.is_dir():
        kind = "folder"
    elif suffix in IMAGE_EXTENSIONS:
        kind = "image"
    elif suffix in VIDEO_EXTENSIONS:
        kind = "video"
    else:
        kind = "file"

    return {
        "name": path.name,
        "path": relative_path,
        "is_dir": path.is_dir(),
        "kind": kind,
        "size": None if path.is_dir() else stat.st_size,
        "modified": f"{stat.st_mtime:.0f}",
    }


class FileManagerHandler(BaseHTTPRequestHandler):
    server_version = "DCIMFileManager/1.0"

    def log_message(self, format, *args):
        print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))

    def do_GET(self):
        route, query = self.route()

        try:
            if route == "/":
                self.send_html(HTML_PATH.read_text(encoding="utf-8"))
            elif route == "/api/files":
                self.handle_files(query)
            elif route == "/media":
                self.handle_file_response(query, inline=True)
            elif route == "/download":
                self.handle_file_response(query, inline=False)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except OSError as error:
            self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        route, _query = self.route()

        try:
            if route == "/api/upload":
                self.handle_upload()
            elif route == "/api/delete":
                self.handle_delete()
            elif route == "/api/rename":
                self.handle_rename()
            elif route == "/api/mkdir":
                self.handle_mkdir()
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except OSError as error:
            self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def route(self):
        parsed = urlsplit(self.path)
        return parsed.path, parse_qs(parsed.query, keep_blank_values=True)

    def handle_files(self, query):
        directory, relative_path = resolve_dcim_path(query.get("path", [""])[0])
        if not directory.exists():
            raise ValueError("Folder does not exist")
        if not directory.is_dir():
            raise ValueError("Path is not a folder")

        files = [
            item_payload(path)
            for path in sorted(directory.iterdir(), key=natural_sort_key)
            if not path.name.startswith(".")
        ]
        files.sort(key=lambda item: (not item["is_dir"], natural_sort_key(Path(item["name"]))))
        self.send_json({"path": relative_path, "files": files})

    def handle_file_response(self, query, inline):
        path, _relative_path = resolve_dcim_path(query.get("path", [""])[0])
        if not path.exists() or not path.is_file():
            raise ValueError("File does not exist")

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        disposition = "inline" if inline else "attachment"
        with path.open("rb") as file:
            body = file.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'{disposition}; filename="{quote(path.name)}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Upload must use multipart/form-data")

        body = self.read_body()
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )

        target_path = ""
        files = []
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "path":
                target_path = (part.get_content() or "").strip()
            elif name == "files":
                filename = part.get_filename()
                if filename:
                    files.append((safe_name(filename), part.get_payload(decode=True) or b""))

        directory, _relative_path = resolve_dcim_path(target_path)
        if not directory.exists():
            raise ValueError("Upload folder does not exist")
        if not directory.is_dir():
            raise ValueError("Upload path is not a folder")
        if not files:
            raise ValueError("No files were uploaded")

        saved = []
        for filename, data in files:
            destination = unique_destination(directory, filename)
            destination.write_bytes(data)
            saved.append(destination.relative_to(DCIM_DIR).as_posix())

        self.send_json({"saved": saved}, HTTPStatus.CREATED)

    def handle_delete(self):
        payload = self.read_json()
        path, _relative_path = resolve_dcim_path(payload.get("path", ""))
        if path == DCIM_DIR.resolve():
            raise ValueError("Cannot delete DCIM")
        if not path.exists():
            raise ValueError("Path does not exist")

        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

        self.send_json({"deleted": True})

    def handle_rename(self):
        payload = self.read_json()
        path, _relative_path = resolve_dcim_path(payload.get("path", ""))
        if path == DCIM_DIR.resolve():
            raise ValueError("Cannot rename DCIM")
        if not path.exists():
            raise ValueError("Path does not exist")

        destination = path.with_name(safe_name(payload.get("name", "")))
        if destination.exists():
            raise ValueError("A file or folder with that name already exists")

        path.rename(destination)
        self.send_json({"path": destination.relative_to(DCIM_DIR).as_posix()})

    def handle_mkdir(self):
        payload = self.read_json()
        directory, _relative_path = resolve_dcim_path(payload.get("path", ""))
        if not directory.exists() or not directory.is_dir():
            raise ValueError("Parent folder does not exist")

        destination = directory / safe_name(payload.get("name", ""))
        if destination.exists():
            raise ValueError("A file or folder with that name already exists")
        destination.mkdir()

        self.send_json({"path": destination.relative_to(DCIM_DIR).as_posix()}, HTTPStatus.CREATED)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_SIZE:
            raise ValueError("Request is too large")
        return self.rfile.read(length)

    def read_json(self):
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise ValueError("Expected application/json")

        try:
            return json.loads(self.read_body().decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("Invalid JSON") from error

    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    mimetypes.add_type("image/avif", ".avif")
    DCIM_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), FileManagerHandler)
    print(f"Serving DCIM file manager at http://{HOST}:{PORT}")
    print(f"Managing files in {DCIM_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
