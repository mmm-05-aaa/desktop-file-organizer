import http.client
import json
import tempfile
import threading
import time
import unittest
import socket
from pathlib import Path
from unittest import mock

import organizer
import web_app


class WebSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'note.txt').write_text('round trip', encoding='utf-8')
        self.old = organizer.DESKTOP
        self.old_state = organizer.STATE_DIR
        self.old_log = organizer.LOG_FILE
        organizer.DESKTOP = self.root
        organizer.STATE_DIR = self.root / 'state'
        organizer.LOG_FILE = organizer.STATE_DIR / 'last_move.json'
        self.server = web_app.create_server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.origin = f'http://127.0.0.1:{self.port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        organizer.DESKTOP = self.old
        organizer.STATE_DIR = self.old_state
        organizer.LOG_FILE = self.old_log
        self.tmp.cleanup()

    def req(self, method='GET', path='/api/scan', headers=None, body=None, host=None):
        h = {'Host': host or f'127.0.0.1:{self.port}'}
        if method == 'POST': h['Origin'] = self.origin
        if headers: h.update(headers)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request(method, path, body=body, headers=h)
        response = conn.getresponse(); raw = response.read(); conn.close()
        try: data = json.loads(raw.decode())
        except Exception: data = raw
        return response.status, data, response.getheaders()

    def test_authority_origin_and_unknown_paths(self):
        for headers, host in [({'Origin': 'http://evil.example'}, None), ({'Origin': 'http://127.0.0.1:1'}, None), ({'Origin': self.origin}, '127.0.0.1.evil')]:
            status, _, _ = self.req(headers=headers, host=host)
            self.assertEqual(status, 403)
        status, _, _ = self.req(headers={'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(status, 403)
        status, _, _ = self.req(path='/secret')
        self.assertEqual(status, 404)

    def test_real_browser_get_without_origin_is_allowed_but_cross_site_is_not(self):
        status, data, headers = self.req(path='/')
        self.assertEqual(status, 200); self.assertIn(b'<title>', data); self.assertTrue(any(k.lower() == 'content-type' for k, _ in headers))
        status, _, _ = self.req(path='/api/scan')
        self.assertEqual(status, 200)
        status, _, _ = self.req(path='/api/scan', headers={'Origin': 'http://evil.example'})
        self.assertEqual(status, 403)

    def test_plans_are_independent_root_bound_and_single_use(self):
        s1, d1, _ = self.req(); s2, d2, _ = self.req()
        self.assertEqual((s1, s2), (200, 200)); self.assertNotEqual(d1['plan']['id'], d2['plan']['id'])
        token = d1['token']; body = json.dumps({'plan_id': d1['plan']['id'], 'confirm': True})
        headers = {'X-Request-Token': token, 'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        status, _, _ = self.req('POST', '/api/execute', headers=headers, body=body)
        self.assertEqual(status, 200)
        status, data, _ = self.req('POST', '/api/execute', headers=headers, body=body)
        self.assertEqual(status, 409); self.assertIn('plan', data['message'])
        self.assertFalse((self.root / 'note.txt').exists())

    def test_plan_expiry_and_root_change_are_enforced(self):
        _, scan, _ = self.req(); body = json.dumps({'plan_id': scan['plan']['id'], 'confirm': True})
        headers = {'X-Request-Token': scan['token'], 'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        self.server.plans[scan['plan']['id']]['created'] -= web_app.PLAN_TTL + 1
        self.assertEqual(self.req('POST', '/api/execute', headers=headers, body=body)[0], 409)
        _, scan, _ = self.req(); body = json.dumps({'plan_id': scan['plan']['id'], 'confirm': True})
        headers['Content-Length'] = str(len(body)); organizer.DESKTOP = self.root / 'other'; organizer.DESKTOP.mkdir()
        self.assertEqual(self.req('POST', '/api/execute', headers=headers, body=body)[0], 409)
        self.assertTrue((self.root / 'note.txt').exists())

    def test_mutations_require_token_confirmation_and_valid_body(self):
        status, _, _ = self.req('POST', '/api/undo', headers={'Content-Type': 'application/json', 'Content-Length': '15'}, body='{"confirm":true}')
        self.assertEqual(status, 403)
        _, scan, _ = self.req(); token = scan['token']
        common = {'X-Request-Token': token, 'Content-Type': 'application/json'}
        status, _, _ = self.req('POST', '/api/undo', headers=common, body='{}')
        self.assertEqual(status, 400)
        status, _, _ = self.req('POST', '/api/undo', headers=common, body='{"confirm":true}')
        self.assertEqual(status, 200)
        status, _, _ = self.req('POST', '/api/undo', headers=common, body='{"confirm":true}')
        self.assertEqual(status, 200)

    def test_body_framing_is_bounded(self):
        _, scan, _ = self.req(); token = scan['token']
        base = {'X-Request-Token': token, 'Content-Type': 'application/json'}
        status, _, _ = self.req('POST', '/api/undo', headers=base, body='{}')
        self.assertEqual(status, 400)
        huge = base | {'Content-Length': str(web_app.MAX_BODY + 1)}
        status, _, _ = self.req('POST', '/api/undo', headers=huge, body='x')
        self.assertEqual(status, 413)
        for extra in ({'Content-Length': '-1'}, {'Content-Length': '1, 1'}, {'Transfer-Encoding': 'chunked'}):
            status, _, _ = self.req('POST', '/api/undo', headers=base | extra, body='{}')
            self.assertIn(status, (400, 413, 501))
        sock = socket.create_connection(('127.0.0.1', self.port), timeout=3)
        sock.sendall((f'POST /api/undo HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: {self.origin}\r\nX-Request-Token: {token}\r\nContent-Type: application/json\r\nContent-Length: 20\r\n\r\n{{').encode())
        sock.settimeout(web_app.REQUEST_TIMEOUT + 1)
        self.assertIn(b'400', sock.recv(1024)); sock.close()

    def test_post_requires_exact_origin_and_json(self):
        _, scan, _ = self.req(); token = scan['token']
        body = '{"confirm":true}'
        base = {'X-Request-Token': token, 'Content-Length': str(len(body)), 'Content-Type': 'application/json'}
        self.assertEqual(self.req('POST', '/api/undo', headers=base | {'Origin': 'http://127.0.0.1:1'}, body=body)[0], 403)
        self.assertEqual(self.req('POST', '/api/undo', headers=base | {'Origin': self.origin, 'Content-Type': 'text/plain'}, body=body)[0], 415)

    def test_server_rejects_non_loopback_bind(self):
        with self.assertRaises(ValueError): web_app.create_server(host='0.0.0.0')

    def test_execute_then_undo_roundtrip_preserves_full_content(self):
        original = (self.root / 'note.txt').read_bytes()
        _, scan, _ = self.req(); body = json.dumps({'plan_id': scan['plan']['id'], 'confirm': True})
        headers = {'X-Request-Token': scan['token'], 'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        status, _, _ = self.req('POST', '/api/execute', headers=headers, body=body)
        self.assertEqual(status, 200)
        moved = list(self.root.rglob('note.txt')); self.assertEqual(len(moved), 1)
        payload = '{"confirm":true}'
        status, _, _ = self.req('POST', '/api/undo', headers=headers | {'Content-Length': str(len(payload))}, body=payload)
        self.assertEqual(status, 200)
        self.assertEqual((self.root / 'note.txt').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
