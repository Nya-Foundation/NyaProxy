# save as server.py
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class SimpleHandler(BaseHTTPRequestHandler):
    def _set_headers(self, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            self._set_headers()
            self.wfile.write(json.dumps({"message": "Hello, world!"}).encode())
        elif self.path == "/v1/status":
            self._set_headers()
            self.wfile.write(json.dumps({"status": "OK"}).encode())
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

        # then dump all headers
        print("Headers:")
        for key, value in self.headers.items():
            print(f"{key}: {value}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        data = json.loads(body or b"{}")
        self._set_headers()
        # echo back whatever was sent
        self.wfile.write(json.dumps({"received": data}).encode())

        # then dump all headers
        print("Headers:")
        for key, value in self.headers.items():
            print(f"{key}: {value}")


if __name__ == "__main__":  #
    addr = ("0.0.0.0", 8000)
    print(f"Serving on http://{addr[0]}:{addr[1]}")
    HTTPServer(addr, SimpleHandler).serve_forever()
