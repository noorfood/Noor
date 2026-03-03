from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = 'Seed initial NOOR Foods system users for testing'

    def handle(self, *args, **kwargs):
        users = [
            {'username': 'md', 'full_name': 'Managing Director', 'role': 'md', 'password': 'noor2024md'},
        ]

        created_count = 0
        for data in users:
            username = data.pop('username')
            password = data.pop('password')
            if User.objects.filter(username=username).exists():
                self.stdout.write(self.style.WARNING(f'  User "{username}" already exists — skipping.'))
                continue
            user = User(username=username, status='active', **data)
            user.set_password(password)
            user.save()
            created_count += 1
            self.stdout.write(self.style.SUCCESS(f'  Created: {username} ({user.role}) — password: {password}'))

        self.stdout.write(self.style.SUCCESS(f'\nDone. {created_count} user(s) created.'))
        self.stdout.write('\nLogin credentials:')
        self.stdout.write('  Username: md          Password: noor2024md')
