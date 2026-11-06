import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
from django.test import SimpleTestCase
from scripts.audit_legacy_copy import audit

class OfflineAuditTests(SimpleTestCase):
    def test_copy_is_read_only_and_outputs_only_aggregate_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,'copy.sqlite3');db=sqlite3.connect(path)
            db.execute('CREATE TABLE accounts_user (plain_password TEXT,password_hash TEXT)')
            db.execute('INSERT INTO accounts_user VALUES (?,?)',('private-test-password','a'*64))
            db.execute('CREATE TABLE procurement_receipt (approx_weight_kg REAL,cost_status TEXT)')
            db.execute("INSERT INTO procurement_receipt VALUES (NULL,'pending')")
            db.execute('CREATE TABLE sales_sm_payment (status TEXT)');db.execute("INSERT INTO sales_sm_payment VALUES ('pending_gm')");db.commit();db.close()
            before=hashlib.sha256(open(path,'rb').read()).hexdigest();r=audit(path)
            after=hashlib.sha256(open(path,'rb').read()).hexdigest()
            self.assertEqual(before,after);self.assertEqual(r['checks']['accounts_with_plaintext_password'],1)
            self.assertEqual(r['checks']['sales_sm_payment_status_pending_gm'],1);self.assertEqual(r['tables']['sales_sm_payment'],1)
            self.assertEqual(r['checks']['receipts_without_recorded_weight'],1);self.assertNotIn('private-test-password',str(r))
    def test_confirmation_required(self):
        p=subprocess.run([sys.executable,'scripts/audit_legacy_copy.py','not-a-file'],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0);self.assertIn('--i-confirm-this-is-a-copy',p.stderr)
    def test_copy_integrity_checks_are_aggregate_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,'fixture.sqlite');db=sqlite3.connect(path)
            db.execute('CREATE TABLE parent (id INTEGER PRIMARY KEY)')
            db.execute('CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))')
            db.execute('INSERT INTO child(parent_id) VALUES (42)');db.commit();db.close()
            before=hashlib.sha256(open(path,'rb').read()).hexdigest()
            result=audit(path)
            self.assertTrue(result['checks']['sqlite_quick_check_ok'])
            self.assertEqual(result['checks']['declared_foreign_key_violations'],1)
            self.assertEqual(before,hashlib.sha256(open(path,'rb').read()).hexdigest())
            self.assertNotIn('42',str(result))
