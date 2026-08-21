import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# route.py sits one level up (route/route.py). Put that directory first on the
# path so `import route` finds the module, not the route/ package directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from route import result_json, route


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.respond(200, {
            "status": "ok",
            "runtime": f"python-{sys.version_info.major}.{sys.version_info.minor}",
        })

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 1_000_000:
                raise ValueError("request body must be between 1 byte and 1 MB")
            data = json.loads(self.rfile.read(length))
            self.respond(200, result_json(route(data)))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self.respond(400, {"error": str(error)})
