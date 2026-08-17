import os
import json
import subprocess
import sys
import tempfile
import unittest


class ApiBoundaryTests(unittest.TestCase):
    def test_real_asgi_app_enforces_http_boundaries(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            os.symlink(outside, os.path.join(root, "outside-link"))
            env = os.environ | {
                "COUNCIL_PROJECT_ROOT": root,
                "COUNCIL_API_KEY": "test-key",
                "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "src"),
            }
            script = f"""
from fastapi.testclient import TestClient
from council import main
client = TestClient(main.app)
assert client.get('/health').status_code == 403
assert client.get('/health', headers={{'X-API-Key': 'test-key'}}).json() == {{'status': 'ok'}}
assert client.get('/', headers={{'X-API-Key': 'test-key'}}).status_code == 200
blocked = client.post('/ingest/folder', headers={{'X-API-Key': 'test-key'}}, json={{
    'folder_path': {json.dumps(os.path.join(root, 'outside-link'))}, 'max_files': 1,
}})
assert blocked.status_code == 403, blocked.text
cors = client.options('/health', headers={{
    'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'GET',
}})
assert cors.headers.get('access-control-allow-origin') != 'https://untrusted.example'
"""
            result = subprocess.run(
                [sys.executable, "-c", script],
                env=env,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
