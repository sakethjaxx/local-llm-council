import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import council_env

SRC = str(Path(__file__).resolve().parents[1] / "src")


def checkout(root: Path, env_text: str, with_pyproject: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if with_pyproject:
        (root / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (root / ".env").write_text(env_text, encoding="utf-8")
    return root


class CouncilEnvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_checkout_env_is_loaded_when_no_override(self):
        root = checkout(self.tmp / "repo", "COUNCIL_ENV_PROBE=checkout\n")
        with patch.dict(os.environ, {"COUNCIL_ENV_FILE": ""}, clear=False):
            os.environ.pop("COUNCIL_ENV_PROBE", None)
            self.assertEqual(council_env.load_council_env(root), root / ".env")
            self.assertEqual(os.environ["COUNCIL_ENV_PROBE"], "checkout")

    def test_explicit_file_replaces_the_checkout_file(self):
        root = checkout(self.tmp / "repo", "COUNCIL_ENV_PROBE=checkout\nCOUNCIL_ENV_ONLY_CHECKOUT=1\n")
        explicit = self.tmp / "deploy.env"
        explicit.write_text("COUNCIL_ENV_PROBE=explicit\n", encoding="utf-8")
        with patch.dict(os.environ, {"COUNCIL_ENV_FILE": str(explicit)}):
            os.environ.pop("COUNCIL_ENV_PROBE", None)
            os.environ.pop("COUNCIL_ENV_ONLY_CHECKOUT", None)
            self.assertEqual(council_env.load_council_env(root), explicit)
            self.assertEqual(os.environ["COUNCIL_ENV_PROBE"], "explicit")
            self.assertNotIn("COUNCIL_ENV_ONLY_CHECKOUT", os.environ)

    def test_real_environment_wins_over_files(self):
        root = checkout(self.tmp / "repo", "COUNCIL_ENV_PROBE=checkout\n")
        with patch.dict(os.environ, {"COUNCIL_ENV_FILE": "", "COUNCIL_ENV_PROBE": "process"}):
            council_env.load_council_env(root)
            self.assertEqual(os.environ["COUNCIL_ENV_PROBE"], "process")

    def test_directory_without_pyproject_is_not_trusted(self):
        root = checkout(self.tmp / "not-a-checkout", "COUNCIL_ENV_PROBE=untrusted\n", with_pyproject=False)
        with patch.dict(os.environ, {"COUNCIL_ENV_FILE": ""}):
            os.environ.pop("COUNCIL_ENV_PROBE", None)
            self.assertIsNone(council_env.load_council_env(root))
            self.assertNotIn("COUNCIL_ENV_PROBE", os.environ)

    def test_missing_explicit_file_fails_loudly(self):
        with patch.dict(os.environ, {"COUNCIL_ENV_FILE": str(self.tmp / "missing.env")}):
            with self.assertRaises(SystemExit):
                council_env.load_council_env(self.tmp)

    def test_working_directory_env_is_never_loaded(self):
        hostile = checkout(self.tmp / "downloads", "COUNCIL_API_KEY=attacker\nCOUNCIL_ENV_PROBE=cwd\n")
        env = {k: v for k, v in os.environ.items() if k not in {"COUNCIL_ENV_PROBE", "COUNCIL_API_KEY"}}
        env["PYTHONPATH"] = SRC
        script = "import os, council; print(os.getenv('COUNCIL_ENV_PROBE'), os.getenv('COUNCIL_API_KEY'))"
        for entry in (["-c", script], ["-c", "import sys; sys.path.insert(0, r'%s'); " % os.path.join(SRC, "council")
                                       + "import cli, os; print(os.getenv('COUNCIL_ENV_PROBE'), os.getenv('COUNCIL_API_KEY'))"]):
            out = subprocess.run([sys.executable, *entry], cwd=hostile, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr[-800:])
            self.assertEqual(out.stdout.strip().splitlines()[-1], "None None")


class EntrypointLookupTests(unittest.TestCase):
    def test_served_app_answers_main_lookups(self):
        script = ("import sys, council.main as served, main_routes_helper as h; "
                  "assert sys.modules['main'] is served; "
                  "assert h._main_attr('CouncilOrchestrator', None) is served.CouncilOrchestrator; print('ok')")
        env = {**os.environ, "PYTHONPATH": SRC}
        out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=180,
                             cwd=tempfile.gettempdir())
        self.assertEqual(out.stdout.strip().splitlines()[-1:], ["ok"], out.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
