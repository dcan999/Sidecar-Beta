"""Offline checks for Pi source."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PiReleaseTests(unittest.TestCase):
    def _source(self, name):
        selected = ROOT / 'host/pi/runtime' / name
        if (ROOT / 'host/pi/release' / name).exists():
            selected = ROOT / 'host/pi/release' / name
        return selected

    def test_healthcheck_is_read_only_and_requires_all_three_commands(self):
        module = load_module(self._source('sc_u1_healthcheck.py'), 'healthcheck_test')
        with tempfile.TemporaryDirectory() as directory:
            module.OUT = Path(directory) / 'status.json'
            calls = []
            def get_json(url, timeout=5.0):
                calls.append(url)
                if url.endswith('/server/info'):
                    return {'result': {'klippy_connected': True, 'klippy_state': 'ready'}}
                if '/objects/query?' in url:
                    return {'result': {'status': {'print_stats': {'state': 'printing'}}}}
                return {'result': {name: 'registered' for name in module.COMMANDS}}
            with patch.object(module, 'get_json', side_effect=get_json):
                self.assertEqual(module.main(), 0)
            self.assertEqual(len(calls), 3)
            self.assertTrue(all('/printer/gcode/script' not in url for url in calls))
            status = json.loads(module.OUT.read_text())
            self.assertEqual(status['print_state'], 'printing')
            self.assertTrue(status['ok'])

            def missing(url, timeout=5.0):
                result = get_json(url, timeout)
                if url.endswith('/printer/gcode/help'):
                    del result['result']['SC_BG_UNLOAD']
                return result
            with patch.object(module, 'get_json', side_effect=missing):
                self.assertEqual(module.main(), 2)
            self.assertEqual(json.loads(module.OUT.read_text())['missing_commands'],
                             ['SC_BG_UNLOAD'])

    def test_watcher_preserves_raw_upload_when_preprocessing_fails(self):
        with patch.dict(os.environ, {'RUN_ONCE': '1', 'STABILITY_PASSES': '1',
                                     'FIREWALL_RAW': '0', 'DELETE_RAW': '0',
                                     'AUTO_START': '0'}):
            module = load_module(self._source('sc_watchd.py'), 'watchd_test')
            with tempfile.TemporaryDirectory() as directory:
                def info(url):
                    if url.endswith('/server/info'):
                        return {'result': {'klippy_state': 'ready', 'klippy_connected': True}}
                    return {'result': [{'path': 'job.gcode', 'size': 4,
                                        'modified': 1000.0}]}
                def download(url, path):
                    path.write_bytes(b'G1 X')
                output = io.StringIO()
                with (patch.dict(os.environ, {'JOB_ROOT': directory}),
                      patch.object(module, 'http_get_json', side_effect=info),
                      patch.object(module, 'http_get_range', return_value=module.MARK_REQ),
                      patch.object(module, 'http_download', side_effect=download),
                      patch.object(module, 'run_preprocess', side_effect=RuntimeError('bad input')),
                      patch.object(module, 'move_file') as moved,
                      patch.object(module, 'upload_file') as uploaded,
                      patch.object(module, 'delete_file') as deleted,
                      contextlib.redirect_stdout(output)):
                    self.assertEqual(module.main(), 0)
                self.assertIn('RAW_UNCHANGED: job.gcode', output.getvalue())
                moved.assert_not_called()
                uploaded.assert_not_called()
                deleted.assert_not_called()

    def test_watcher_rejects_moonraker_error_response(self):
        module = load_module(self._source('sc_watchd.py'), 'watchd_error_test')
        result = types.SimpleNamespace(returncode=0, stdout='{"error":{"message":"fail"}}',
                                       stderr='')
        with patch.object(module.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'Moonraker request failed'):
                module.curl_json(['curl', 'example'])

    def test_preprocessor_preserves_final_cooldown_and_emits_docked_prep(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / 'job.gcode'
            raw.write_text('T0\nT4\nM104 T0 S70 ; cooldown\n'
                           'T1\nM104 T0 S70 ; cooldown\n', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(self._source('sc_preprocess_block4.py')),
                 str(raw)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            processed = (raw.parent / 'SCPRO_job.gcode').read_text()
            self.assertIn('EV=UNLOAD head=0 lane=1', processed)
            self.assertIn('EV=LOAD head=0 lane=2', processed)
            self.assertEqual(processed.count('M104 T0 S70 ; cooldown'), 1)
            self.assertEqual(processed.count('T4\n'), 1)
            self.assertEqual(processed.count('T1\n'), 1)

    def test_preprocessor_respects_enabled_heads_and_rejects_other_lane_maps(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / 'job.gcode'
            raw.write_text('T0\nT4\nM104 T0 S70 ; cooldown\nT1\n', encoding='utf-8')
            script = str(self._source('sc_preprocess_block4.py'))
            result = subprocess.run([sys.executable, script, '--sc-heads', '1',
                                     str(raw)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            processed = (raw.parent / 'SCPRO_job.gcode').read_text()
            self.assertNotIn('EV=UNLOAD', processed)
            self.assertIn('M104 T0 S70 ; cooldown', processed)
            for options in (['--lanes-per-sc', '3'], ['--sc-heads', '0,4'],
                            ['--sc-heads', '0,0']):
                result = subprocess.run([sys.executable, script, *options, str(raw)],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)

    def test_api_rejects_foreign_browser_origin_before_dispatch(self):
        with (patch.dict(sys.modules, {'websocket': types.SimpleNamespace()}),
              patch('socket.socket') as sock):
            sock.return_value.getsockname.return_value = ('127.0.0.1', 0)
            module = load_module(self._source('sc_gate.py'), 'gate_origin_test')
        def handler(origin):
            h = object.__new__(module._ApiHandler)
            h.headers = {'Origin': origin}
            h.path = '/api/v1/heads'
            h.wfile = io.BytesIO()
            h.send_response = lambda code: setattr(h, 'code', code)
            h.sent_headers = {}
            h.send_header = lambda key, value: h.sent_headers.__setitem__(key, value)
            h.end_headers = lambda: None
            return h
        for method in ('do_GET', 'do_POST', 'do_OPTIONS'):
            h = handler('https://untrusted.example')
            getattr(h, method)()
            self.assertEqual(h.code, 403)
            self.assertNotIn('Access-Control-Allow-Origin', h.sent_headers)
        h = handler('http://localhost:8088')
        h.do_OPTIONS()
        self.assertEqual(h.code, 204)
        self.assertEqual(h.sent_headers['Access-Control-Allow-Origin'],
                         'http://localhost:8088')


if __name__ == '__main__':
    unittest.main()
