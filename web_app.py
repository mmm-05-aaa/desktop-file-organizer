from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit

import organizer

MAX_BODY = 64 * 1024
PLAN_TTL = 300
MAX_PLANS = 32
REQUEST_TIMEOUT = 2
MAX_CONCURRENT = 8

HTML = '''<!doctype html><meta charset="utf-8"><title>桌面整理器</title>
<button id="scan">扫描</button><button id="run" disabled>确认并执行</button><button id="undo">确认撤销</button><pre id="out"></pre>
<script>
(() => {
  const scanButton = document.getElementById('scan');
  const runButton = document.getElementById('run');
  const undoButton = document.getElementById('undo');
  const output = document.getElementById('out');
  let plan = null;
  let token = null;
  let busy = false;
  function show(message) { output.textContent = message; }
  async function request(url, options) {
    const response = await fetch(url, options);
    let data = {};
    try { data = await response.json(); } catch (_) { data = {message: '服务器返回无效响应'}; }
    if (!response.ok) throw new Error(data.message || ('HTTP ' + response.status));
    return data;
  }
  async function scan() {
    if (busy) return;
    busy = true; scanButton.disabled = true; runButton.disabled = true; plan = null;
    try {
      const data = await request('/api/scan');
      token = data.token;
      plan = data.plan;
      show(data.text);
      runButton.disabled = !plan.executable;
    } catch (error) { show(error.message); }
    finally { busy = false; scanButton.disabled = false; }
  }
  async function runPlan() {
    if (busy || !plan || !token || !confirm('确认执行当前扫描计划？')) return;
    busy = true; runButton.disabled = true;
    try { const data = await request('/api/execute', {method:'POST', headers:{'Content-Type':'application/json','X-Request-Token':token}, body:JSON.stringify({plan_id:plan.id, confirm:true})}); show(data.message); plan = null; }
    catch (error) { show(error.message); }
    finally { busy = false; }
  }
  async function undo() {
    if (busy || !token || !confirm('确认撤销最近一次整理？')) return;
    busy = true; undoButton.disabled = true;
    try { const data = await request('/api/undo', {method:'POST', headers:{'Content-Type':'application/json','X-Request-Token':token}, body:JSON.stringify({confirm:true})}); show(data.message); }
    catch (error) { show(error.message); }
    finally { busy = false; undoButton.disabled = false; }
  }
  scanButton.addEventListener('click', scan); runButton.addEventListener('click', runPlan); undoButton.addEventListener('click', undo); scan();
})();</script>'''


def _authority(host, headers, server, require_origin=False):
    if len(headers.get_all('Host', [])) != 1 or len(headers.get_all('Origin', [])) > 1:
        return False
    if not host or host != server.authority:
        return False
    origin = headers.get('Origin')
    if require_origin and origin != server.expected_origin:
        return False
    if origin is not None and origin != server.expected_origin:
        return False
    fetch_site = headers.get('Sec-Fetch-Site')
    if fetch_site and fetch_site.lower() not in ('same-origin', 'none'):
        return False
    return True


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT)

    def handle_one_request(self):
        try:
            return super().handle_one_request()
        except socket.timeout:
            self.close_connection = True

    def _authorized(self):
        return _authority(self.headers.get('Host'), self.headers, self.server)

    def _json(self, data, code=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def end_headers(self):
        self.send_header('Connection', 'close')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        super().end_headers()

    def _body(self):
        if self.headers.get('Transfer-Encoding') is not None:
            raise ValueError('Transfer-Encoding is not supported')
        values = self.headers.get_all('Content-Length', [])
        if len(values) != 1 or not values[0].strip().isdigit():
            raise ValueError('Content-Length required')
        length = int(values[0])
        if length < 0 or length > MAX_BODY:
            raise OverflowError('request too large')
        try:
            raw = self.rfile.read(length)
        except socket.timeout as exc:
            raise ValueError('request body timeout') from exc
        if len(raw) != length:
            raise ValueError('short request body')
        try:
            return json.loads(raw.decode('utf-8')) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('invalid JSON') from exc

    def do_GET(self):
        self.close_connection = True
        if not _authority(self.headers.get('Host'), self.headers, self.server):
            return self._json({'message': 'forbidden'}, 403)
        path = urlsplit(self.path).path
        if path == '/api/scan':
            with self.server.state_lock:
                try:
                    moves = organizer.scan()
                except Exception as error:
                    return self._json({'message': f'扫描失败：{type(error).__name__}'}, 500)
                selected = [m for m in moves if m.confidence >= 70 and not m.warning]
                plan_id = secrets.token_urlsafe(18)
                self.server.plans[plan_id] = {'created': time.monotonic(), 'root': str(Path(organizer.DESKTOP).resolve()), 'moves': [organizer.asdict(m) for m in selected]}
                while len(self.server.plans) > MAX_PLANS:
                    self.server.plans.popitem(last=False)
            lines = ['桌面（仅执行无警告且规则匹配分达到 70 的预览项目）']
            for m in moves:
                target = Path(m.target).relative_to(organizer._absolute(organizer.DESKTOP))
                lines.append(f'{Path(m.source).name} → {target} | 规则匹配分 {m.confidence} | {m.warning or m.reason}')
            return self._json({'text': '\n'.join(lines), 'token': self.server.token, 'plan': {'id': plan_id, 'executable': bool(selected)}})
        if path == '/':
            raw = HTML.encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(raw); return
        self._json({'message': 'not found'}, 404)

    def do_POST(self):
        self.close_connection = True
        if not _authority(self.headers.get('Host'), self.headers, self.server, require_origin=True) or not secrets.compare_digest(self.headers.get('X-Request-Token', ''), self.server.token):
            return self._json({'message': 'forbidden'}, 403)
        if self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
            return self._json({'message': 'JSON body required'}, 415)
        try:
            body = self._body()
        except OverflowError as exc:
            return self._json({'message': str(exc)}, 413)
        except ValueError as exc:
            return self._json({'message': str(exc)}, 400)
        path = urlsplit(self.path).path
        if path == '/api/execute':
            plan_id = body.get('plan_id') if isinstance(body, dict) else None
            if not isinstance(plan_id, str) or body.get('confirm') is not True:
                return self._json({'message': 'explicit confirmation and plan required'}, 400)
            with self.server.state_lock:
                plan = self.server.plans.get(plan_id)
                if plan is None: return self._json({'message': 'unknown or already used plan'}, 409)
                if time.monotonic() - plan['created'] > PLAN_TTL: return self._json({'message': 'plan expired'}, 409)
                if plan['root'] != str(Path(organizer.DESKTOP).resolve()): return self._json({'message': 'plan root changed'}, 409)
                del self.server.plans[plan_id]
            try:
                result = organizer.execute([organizer.FileRecord(**x) for x in plan['moves']])
                return self._json({'message': f'已整理 {len(result["moves"])} 个文件'})
            except Exception as exc:
                return self._json({'message': str(exc)}, 409)
        if path == '/api/undo':
            if not isinstance(body, dict) or body.get('confirm') is not True:
                return self._json({'message': 'explicit confirmation required'}, 400)
            try:
                count, warnings = organizer.undo()
                return self._json({'message': f'已恢复 {count} 个文件' + (('；' + '；'.join(warnings)) if warnings else '')})
            except Exception as exc:
                return self._json({'message': str(exc)}, 409)
        return self._json({'message': 'not found'}, 404)

    def log_message(self, *_args):
        pass


def create_server(host='127.0.0.1', port=0):
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('server must bind to loopback')
    class LimitedServer(ThreadingHTTPServer):
        daemon_threads = True
        def process_request(self, request, client_address):
            if not self.request_slots.acquire(blocking=False):
                request.close()
                return
            try:
                super().process_request(request, client_address)
            except Exception:
                self.request_slots.release()
                raise
        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.request_slots.release()
    server = LimitedServer((host, port), Handler)
    server.token = secrets.token_urlsafe(32)
    server.authority = f'{host}:{server.server_port}'
    server.expected_origin = f'http://{server.authority}'
    server.state_lock = threading.RLock()
    server.plans = OrderedDict()
    server.handler_headers = {}
    server.request_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
    return server


if __name__ == '__main__':
    create_server(port=8765).serve_forever()
