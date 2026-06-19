from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import quote


HOST = "127.0.0.1"
PORT = 8000
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
PHOTO_DIR = ROOT / "dcim"
CONFIG_ROUTE = "/config"
PHOTO_ROUTE = "/photos"
IMAGE_EXTENSIONS = {
    ".avif",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}
DEFAULT_CONFIG = {
    "secondsBetweenPictures": 5,
    "debugOverlay": {
        "enabled": False,
        "showCurrentFile": True,
        "showNextFile": True,
        "showPhotoCount": True,
    },
}


def deep_merge(base, overrides):
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config():
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG

    try:
        with CONFIG_PATH.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read {CONFIG_PATH}: {error}")
        return DEFAULT_CONFIG

    return deep_merge(DEFAULT_CONFIG, config)


def natural_sort_key(path):
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def discover_photos():
    if not PHOTO_DIR.exists():
        return []

    photos = []
    for path in sorted(PHOTO_DIR.iterdir(), key=natural_sort_key):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            photos.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "url": f"/dcim/{quote(path.name)}",
                }
            )
    return photos


class SlideshowHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        route = self.path.split("?", 1)[0]

        if route == CONFIG_ROUTE:
            self.send_json(load_config())
            return

        if route == PHOTO_ROUTE:
            self.send_photos()
            return

        super().do_GET()

    def send_photos(self):
        self.send_json(discover_photos())

    def send_json(self, payload):
        body = json.dumps(payload).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    mimetypes.add_type("image/avif", ".avif")
    server = ThreadingHTTPServer((HOST, PORT), SlideshowHandler)
    print(f"Serving slideshow at http://{HOST}:{PORT}")
    print(f"Using photos from {PHOTO_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
