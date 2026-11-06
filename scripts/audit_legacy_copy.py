#!/usr/bin/env python3
"""Read aggregate migration-risk counts from an operator-supplied SQLite COPY.

No records, credentials, financial amounts or names are exported. This does not
reconcile balances, validate semantics, migrate data, or prove deploy readiness.
Obtain the copy using SQLite's backup API so it includes committed WAL changes.
"""
import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

EXPECTED=('accounts_user','procurement_receipt','procurement_issuance','cleaning_clean_receipt',
          'clean_store_issuance','clean_store_return','production_milling_batch','production_packaging_batch',
          'production_brand_sale','finished_store_receipt','finished_store_issuance','finished_store_return',
          'sales_person','sales_record','sales_payment','sales_retail_ledger','sales_sm_collection',
          'sales_distribution_record','sales_result','sales_sm_payment','sales_direct_payment',
          'sales_gm_remittance','reconciliation_money_receipt','reconciliation_flag')

def audit(path):
    path=Path(path).expanduser().resolve(strict=True)
    if not path.is_file():raise ValueError('Expected a SQLite database file.')
    conn=sqlite3.connect('file:'+quote(str(path),safe='/')+'?mode=ro',uri=True)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report={'kind':'read-only aggregate assessment of operator-identified copy','tables':{},'checks':{},'limitations':['Counts are not migration, reconciliation, valuation, or approval.','Table names may differ in another schema; missing means not assessed.','Keep this report confidential; do not use live data or share credentials.','Integrity and declared foreign-key checks do not establish reconciliation or data completeness.']}
        # These checks inspect SQLite's structure and declared foreign keys only;
        # they do not establish completeness, business correctness or reconciliation.
        try:
            results=conn.execute('PRAGMA quick_check')
            report['checks']['sqlite_quick_check_ok']=all(row[0]=='ok' for row in results)
        except sqlite3.Error:
            report['checks']['sqlite_quick_check_ok']=None
        try:
            report['checks']['declared_foreign_key_violations']=sum(1 for _ in conn.execute('PRAGMA foreign_key_check'))
        except sqlite3.Error:
            report['checks']['declared_foreign_key_violations']=None
        for name in EXPECTED:
            # Identifiers are constants, never user input.
            report['tables'][name]=conn.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0] if name in tables else None
        def columns(table):
            return {r[1] for r in conn.execute('PRAGMA table_info("'+table+'")')} if table in tables else set()
        ac=columns('accounts_user');rc=columns('procurement_receipt')
        if 'plain_password' in ac:report['checks']['accounts_with_plaintext_password']=conn.execute("SELECT COUNT(*) FROM accounts_user WHERE plain_password IS NOT NULL AND plain_password <> ''").fetchone()[0]
        if 'password_hash' in ac:report['checks']['accounts_with_64_character_legacy_hash']=conn.execute("SELECT COUNT(*) FROM accounts_user WHERE LENGTH(password_hash)=64").fetchone()[0]
        if 'approx_weight_kg' in rc:report['checks']['receipts_without_recorded_weight']=conn.execute('SELECT COUNT(*) FROM procurement_receipt WHERE approx_weight_kg IS NULL').fetchone()[0]
        if 'cost_status' in rc:report['checks']['receipts_not_approved_for_cost']=conn.execute("SELECT COUNT(*) FROM procurement_receipt WHERE cost_status IS NULL OR cost_status <> 'approved'").fetchone()[0]
        if {'cost_status','total_cost'} <= rc:report['checks']['approved_receipts_without_total_cost']=conn.execute("SELECT COUNT(*) FROM procurement_receipt WHERE cost_status = 'approved' AND total_cost IS NULL").fetchone()[0]
        # These are exact raw status counts, not declarations that other rows are reconciled.
        for name,status in [('clean_store_issuance','pending'),('finished_store_issuance','pending'),('sales_sm_collection','pending'),('sales_sm_payment','pending_gm'),('sales_direct_payment','pending_md'),('sales_gm_remittance','pending_md')]:
            if 'status' in columns(name):
                report['checks'][name+'_status_'+status]=conn.execute('SELECT COUNT(*) FROM "'+name+'" WHERE status=?',(status,)).fetchone()[0]
        if 'milling_batch_id' in columns('production_packaging_batch'):
            report['checks']['packaging_records_without_milling_link']=conn.execute('SELECT COUNT(*) FROM production_packaging_batch WHERE milling_batch_id IS NULL').fetchone()[0]
        return report
    finally:conn.close()

def main():
    p=argparse.ArgumentParser(description='Assess a consistent SQLite COPY; never point this at a live database.')
    p.add_argument('copy',help='Path to an operator-provided consistent SQLite backup copy')
    p.add_argument('--i-confirm-this-is-a-copy',action='store_true',required=True,help='Confirm the file is a copy, not the live database')
    args=p.parse_args()
    try:print(json.dumps(audit(args.copy),indent=2))
    except (OSError,ValueError,sqlite3.Error) as exc:p.exit(2,'Could not assess the copy: '+str(exc)+'\n')
if __name__=='__main__':main()
