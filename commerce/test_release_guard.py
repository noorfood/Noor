import os
import subprocess
import sys
from pathlib import Path
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent

class ReleaseGuardTests(SimpleTestCase):
    """Release-approved 2026-11-06: the development-only guards that
    blocked deployment were removed when the user decided to go live
    on Render. These tests lock in the new behaviour: wsgi loads under
    live-like settings, and build.sh is a real build (install,
    collectstatic, migrate), not a stop sign."""

    def run_wsgi(self, **changes):
        env = os.environ.copy()
        for k in ('NOOR_UNSAFE_DEV_WSGI','NOOR_PRODUCTION','DATABASE_URL','DJANGO_DEBUG','DJANGO_SETTINGS_MODULE'):
            env.pop(k, None)
        env.update(changes)
        return subprocess.run([sys.executable, '-c', 'import noor_foods.wsgi'], cwd=ROOT, env=env, capture_output=True, text=True)

    def test_wsgi_loads_under_live_like_settings(self):
        for env in ({}, {'DATABASE_URL': 'postgres://u:p@localhost/db', 'DJANGO_DEBUG': 'False'}, {'DATABASE_URL': 'postgres://u:p@localhost/db'}):
            with self.subTest(env=env):
                result = self.run_wsgi(**env)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_is_a_real_build_not_a_stop_sign(self):
        # Do not execute build.sh here: it installs packages and runs
        # migrations. Assert on its content instead.
        text = (ROOT / 'build.sh').read_text()
        self.assertNotIn('STOP:', text)
        self.assertNotIn('exit 1', text)
        self.assertIn('pip install -r requirements.txt', text)
        self.assertIn('collectstatic --noinput', text)
        self.assertIn('migrate --noinput', text)
