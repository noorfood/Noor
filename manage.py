#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'noor_foods.settings')
    
    # Version Guard for Python 3.14 compatibility
    import django
    from packaging import version
    if sys.version_info >= (3, 14) and version.parse(django.get_version()) < version.parse("5.1"):
        print("\n" + "!" * 60)
        print("CRITICAL ERROR: INCOMPATIBLE ENVIRONMENT DETECTED")
        print(f"You are running Python {sys.version.split()[0]} with Django {django.get_version()}.")
        print("Django version 4.2 is NOT compatible with Python 3.14 (AttributeError in Admin).")
        print("\nHOW TO FIX THIS:")
        print("1. Stop the current server (Ctrl+C).")
        print("2. Run the server using the virtual environment:")
        print("   .\\venv\\Scripts\\python.exe manage.py runserver")
        print("!" * 60 + "\n")
        sys.exit(1)

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
