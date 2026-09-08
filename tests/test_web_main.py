import json
import unittest
from unittest import mock
import organizer
from tests import test_web_safety as fixture

class WebAcceptance(unittest.TestCase):
    setUp=fixture.WebSafetyTests.setUp
    tearDown=fixture.WebSafetyTests.tearDown
    req=fixture.WebSafetyTests.req
    def test_cross_port_same_site_request_is_rejected(self):
        self.assertEqual(self.req(headers={'Sec-Fetch-Site':'same-site'})[0],403)
    def test_framing_headers_and_mime_are_protected(self):
        status,_,headers=self.req(path='/')
        headers={k.lower():v for k,v in headers}
        self.assertEqual(status,200)
        self.assertEqual(headers.get('x-frame-options'),'DENY')
        self.assertEqual(headers.get('x-content-type-options'),'nosniff')
        self.assertEqual(headers.get('cross-origin-resource-policy'),'same-origin')
    def test_ambiguous_transfer_encoding_is_rejected(self):
        _,scan,_=self.req()
        status,_,_=self.req('POST','/api/undo',headers={'X-Request-Token':scan['token'],'Content-Type':'application/json','Transfer-Encoding':'chunked'},body='{"confirm":true}')
        self.assertEqual(status,400)
        self.assertTrue((self.root/'note.txt').exists())
    def test_scan_failure_returns_json_not_dropped_connection(self):
        with mock.patch.object(organizer,'scan',side_effect=PermissionError('synthetic denied')):
            status,data,_=self.req()
        self.assertEqual(status,500); self.assertIn('message',data)
    def test_preview_displays_warning_and_rule_score(self):
        (self.root/'broken.pdf').write_bytes(b'<html>not a PDF')
        status,data,_=self.req()
        self.assertEqual(status,200)
        self.assertIn('规则匹配分',data['text'])
        self.assertIn('文件头不是 PDF',data['text'])

if __name__=='__main__': unittest.main()
