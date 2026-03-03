from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import connection
from accounts.models import User
from django.contrib.sessions.models import Session

class Command(BaseCommand):
    help = 'Wipe all operational data except MD accounts'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING("Starting system-wide RAW SQL data wipe..."))
        
        with connection.cursor() as cursor:
            # 1. Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            
            # 2. Define tables to preserve or handle specially
            preserve = ['django_migrations', 'django_content_type', 'sqlite_sequence']
            special = {
                'accounts_user': "DELETE FROM accounts_user WHERE role != 'md';",
            }
            
            # 3. Disable FKs
            cursor.execute("PRAGMA foreign_keys = OFF;")
            
            for table in tables:
                if table in preserve:
                    continue
                
                if table in special:
                    sql = special[table]
                    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE role != 'md';")
                    count = cursor.fetchone()[0]
                    cursor.execute(sql)
                    self.stdout.write(self.style.SUCCESS(f"  Cleaned {table}: Wiped {count} non-MD users"))
                else:
                    cursor.execute(f"SELECT COUNT(*) FROM {table};")
                    count = cursor.fetchone()[0]
                    if count > 0:
                        cursor.execute(f"DELETE FROM {table};")
                        self.stdout.write(f"  Wiped {count} records from {table}")
            
            # 4. Re-enable FKs and Vacuum
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute("VACUUM;")
            
        self.stdout.write(self.style.SUCCESS("\nSystem data wipe complete via Raw SQL. Only MD accounts remain."))
