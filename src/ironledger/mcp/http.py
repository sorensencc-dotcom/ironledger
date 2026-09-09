import sys
import hmac
import json
import logging
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from ironledger.audit import append_audit_event
from ironledger.db.connection import connect
from ironledger.mcp.bind import assert_loopback
from ironledger.mcp.protocol import handle_message
from ironledger.mcp.token import load_or_create_token, rotate_token, verify_bearer

_logger = logging.getLogger('ironledger.mcp.http')
MAX_HTTP_BODY: int = 1_048_576

ALLOWED_HOSTS = frozenset({
    '127.0.0.1', 'localhost', '[::1]', '::1'
})

def _is_loopback_host(host_header: str | None) -> bool:
    if not host_header:
        return False
    h = host_header.split(':')[0]
    if host_header.startswith('[') and ']' in host_header:
        h = host_header[:host_header.index(']') + 1]
    return h in ALLOWED_HOSTS

def _is_allowed_origin(origin_header: str | None) -> bool:
    if origin_header is None:
        return True
    o = origin_header.strip()
    if o == 'null':
        return True
    allowed_prefixes = (
        'http://127.0.0.1',
        'http://localhost',
        'http://[::1]',
    )
    for p in allowed_prefixes:
        if o == p or o.startswith(p + ':'):
            return True
    return False

def _audit_denied(db: str | None) -> None:
    if not db:
        return
    try:
        conn = connect(str(db))
        try:
            append_audit_event(
                conn,
                actor='operator',
                action='mcp auth',
                target='http',
                result='denied',
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

class McpHttpHandler(BaseHTTPRequestHandler):
    server: McpHttpServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == '/mcp':
            self.send_response(405)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self) -> None:
        self.send_response(405)
        self.end_headers()

    def do_POST(self) -> None:
        # 1 Path check
        if self.path != '/mcp':
            self.send_response(404)
            self.end_headers()
            return

        # 2 Host header - must be loopback
        host_hdr = self.headers.get('Host')
        if not _is_loopback_host(host_hdr):
            _audit_denied(self.server.db)
            self.send_response(403)
            self.end_headers()
            return

        # 3 Origin header - if present must be allowed
        origin_hdr = self.headers.get('Origin')
        if not _is_allowed_origin(origin_hdr):
            _audit_denied(self.server.db)
            self.send_response(403)
            self.end_headers()
            return

        # 4 Content-Type - if present must be application/json
        ct_hdr = self.headers.get('Content-Type')
        if ct_hdr is not None:
            media_type = ct_hdr.split(';')[0].strip().lower()
            if media_type != 'application/json':
                self.send_response(415)
                self.end_headers()
                return

        # 5 Content-Length / chunked cap (413)
        te_hdr = self.headers.get('Transfer-Encoding', '')
        if 'chunked' in te_hdr.lower():
            self.send_response(413)
            self.end_headers()
            return

        cl_hdr = self.headers.get('Content-Length')
        if not cl_hdr:
            self.send_response(413)
            self.end_headers()
            return

        try:
            content_length = int(cl_hdr)
            if content_length < 0 or content_length > MAX_HTTP_BODY:
                self.send_response(413)
                self.end_headers()
                return
        except ValueError:
            self.send_response(413)
            self.end_headers()
            return

        # 6 Bearer token check (401)
        auth_hdr = self.headers.get('Authorization')
        if not verify_bearer(auth_hdr, self.server.token):
            _audit_denied(self.server.db)
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Bearer')
            self.end_headers()
            return

        # 7 Set 5s timeout and read body
        self.connection.settimeout(5.0)
        try:
            body_bytes = self.rfile.read(content_length)
            if len(body_bytes) != content_length:
                self.close_connection = True
                return
        except (timeout, socket.timeout, OSError):
            self.close_connection = True
            return

        # 8 UTF-8 decode
        try:
            raw_str = body_bytes.decode('utf-8')
        except UnicodeDecodeError:
            err_obj = {
                'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32700, 'message': 'Parse error'},
            }
            err_bytes = json.dumps(err_obj, sort_keys=True).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(err_bytes)))
            self.end_headers()
            self.wfile.write(err_bytes)
            return

        resp = handle_message(
            raw_str,
            ledger_dir=self.server.ledger_dir,
            projection_dir=self.server.projection_dir,
            db=self.server.db,
        )

        if resp is None:
            # Notification -> 202 Accepted
            self.send_response(202)
            self.send_header('Content-Length', '0')
            self.end_headers()
        else:
            resp_bytes = resp.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

class McpHttpServer(HTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        token: str,
        ledger_dir: Path,
        projection_dir: Path,
        db: str | None,
    ):
        super().__init__(server_address, RequestHandlerClass)
        self.token = token
        self.ledger_dir = ledger_dir
        self.projection_dir = projection_dir
        self.db = db

def serve_http(
    *,
    host: str,
    port: int,
    ledger_dir: Path,
    projection_dir: Path,
    db: str | None,
    rotate: bool = False,
) -> McpHttpServer:
    assert_loopback(host)
    ledger_dir = Path(ledger_dir)
    projection_dir = Path(projection_dir)

    if rotate:
        token = rotate_token(projection_dir)
    else:
        token_path = projection_dir / '.mcp-token'
        is_new = not token_path.is_file()
        token = load_or_create_token(projection_dir)
        if is_new:
            print(f"mcp token written to {token_path}", file=sys.stderr)

    server = McpHttpServer(
        (host, port),
        McpHttpHandler,
        token=token,
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    return server
