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
                "PYTHONPATH": os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")),
            }
            script = f"""
from fastapi.testclient import TestClient
from council import main
client = TestClient(main.app)
assert client.get('/').status_code == 200  # Public shell supports browser sign-in.
assert client.get('/health').status_code == 403
assert client.get('/health', headers={{'X-API-Key': 'test-key'}}).json() == {{'status': 'ok'}}
assert client.get('/', headers={{'X-API-Key': 'test-key'}}).status_code == 200
bad_roster = client.post('/ollama/check', headers={{'X-API-Key': 'test-key'}}, json={{'council_config': {{'seat': {{'model': ''}}}}}})
assert bad_roster.status_code == 422, bad_roster.text
cross_site = client.post('/council/stream', headers={{'Origin': 'https://untrusted.example'}}, data={{'topic_text': 'review'}})
assert cross_site.status_code == 403, cross_site.text
blocked = client.post('/ingest/folder', headers={{'X-API-Key': 'test-key'}}, json={{
    'folder_path': {json.dumps(os.path.join(root, 'outside-link'))}, 'max_files': 1,
}})
assert blocked.status_code == 403, blocked.text
cors = client.options('/health', headers={{
    'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'GET',
}})
assert cors.headers.get('access-control-allow-origin') not in ('*', 'https://untrusted.example'), cors.headers
local = client.options('/health', headers={{
    'Origin': 'http://localhost:8765', 'Access-Control-Request-Method': 'GET',
}})
assert local.headers.get('access-control-allow-origin') == 'http://localhost:8765', local.headers
# Entering/exiting the client runs the lifespan; shutdown used to raise TypeError.
with TestClient(main.app) as lifespan_client:
    assert lifespan_client.get('/health', headers={{'X-API-Key': 'test-key'}}).status_code == 200
"""
            # cwd=root keeps a developer's .env out of this fresh interpreter.
            result = subprocess.run(
                [sys.executable, "-c", script],
                env=env,
                cwd=root,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
