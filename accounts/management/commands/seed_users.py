from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Disabled: fixed-credential accounts must not be created.'

    def handle(self, *args, **options):
        raise CommandError('Fixed-credential account seeding is disabled. Provision accounts securely.')
