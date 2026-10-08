#!/usr/bin/env python3
"""
BOOKORA — Local Development Static Server with Render Rewrite Rules

Serves the standalone frontend/ directory on http://localhost:3000 and
accurately reproduces Render Static Site URL rewrite rules locally for
end-to-end testing.

Rewrites:
  /movie/*      -> /movie-details.html
  /shows/*      -> /shows.html
  /seats/*      -> /seat-selection.html
  /my-bookings  -> /my-bookings.html
  /profile      -> /profile.html
  /saved-movies -> /saved-movies.html
"""

import os
import sys
import argparse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))


class RenderStaticRewriteHandler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Render static rewrite rules
        if path == '/' or path == '':
            self.path = '/index.html'
        elif path.startswith('/movie/'):
            self.path = '/movie-details.html'
        elif path.startswith('/shows/'):
            self.path = '/shows.html'
        elif path.startswith('/seats/'):
            self.path = '/seat-selection.html'
        elif path in ('/my-bookings', '/my-bookings/'):
            self.path = '/my-bookings.html'
        elif path in ('/profile', '/profile/'):
            self.path = '/profile.html'
        elif path in ('/saved-movies', '/saved-movies/'):
            self.path = '/saved-movies.html'
        elif not os.path.exists(os.path.join(FRONTEND_DIR, path.lstrip('/'))):
            # Check if adding .html exists (e.g. /index -> /index.html)
            candidate = os.path.join(FRONTEND_DIR, f"{path.lstrip('/')}.html")
            if os.path.exists(candidate):
                self.path = f"{path}.html"

        # Preserve query string if any
        if parsed.query:
            self.path = f"{self.path}?{parsed.query}"

        try:
            return super().do_GET()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def end_headers(self):
        # Disable caching for local development testing
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, format, *args):
        # Keep dev server output clean and readable
        sys.stderr.write(f"[StaticServer 3000] {self.address_string()} - {format % args}\n")


def run(port=3000, host='127.0.0.1'):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, RenderStaticRewriteHandler)
    httpd.daemon_threads = True
    print(f"==================================================")
    print(f" Bookora Local Static Server running at:")
    print(f" http://{host}:{port}/")
    print(f" Serving directory: {FRONTEND_DIR}")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping static server...")
        httpd.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Bookora Local Static Server")
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '3000')), help="Port to listen on (default 3000)")
    parser.add_argument('--host', type=str, default='127.0.0.1', help="Host to bind to (default 127.0.0.1)")
    args = parser.parse_args()
    run(port=args.port, host=args.host)
