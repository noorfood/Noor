import os
import subprocess
import sys
from django.test import SimpleTestCase

class ProductionGuardTests(SimpleTestCase):
    def run_settings(self, **override):
        env=os.environ.copy();env.update({'NOOR_PRODUCTION':'True','DJANGO_DEBUG':'False','DJANGO_SECRET_KEY':'safe-test-only-'+('x'*64),'DJANGO_ALLOWED_HOSTS':'example.test','DATABASE_URL':'postgres://test:test@localhost/test','SECURE_SSL_REDIRECT':'True'});env.update(override)
        return subprocess.run([sys.executable,'-c','import noor_foods.settings'],env=env,capture_output=True,text=True)
    def test_rejects_unsafe_configuration(self):
        for setting in ({'DJANGO_DEBUG':'True'},{'DJANGO_SECRET_KEY':'short'},{'DJANGO_ALLOWED_HOSTS':'*'},{'DATABASE_URL':''},{'SECURE_SSL_REDIRECT':'False'}):
            with self.subTest(setting=setting):self.assertNotEqual(self.run_settings(**setting).returncode,0)
    def test_minimum_guard_allows_valid_settings_without_connecting(self):
        self.assertEqual(self.run_settings().returncode,0)
