#!/usr/bin/env python3
"""Test runner for birthday notifications (prints messages instead of sending).

Usage: python scripts/birthday_notifier_test.py [days]
If days is not provided, runs for days=3 and days=0.
"""
import sys
import os
# ensure repo root is on sys.path so `import db` works when running from scripts/
repo_root = os.path.dirname(os.path.dirname(__file__))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
from db import notifications


def run_for(days):
    admins = notifications.get_admin_telegram_ids()
    rows = notifications.get_birthdays_for_days_before(days)
    print(f"Days={days}: admins found={len(admins)}, birthdays={len(rows)}")
    if not rows:
        return
    msg = notifications.build_birthday_message(rows, days)
    print('\n--- MESSAGE PREVIEW ---\n')
    print(msg)
    print('\n--- END PREVIEW ---\n')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        run_for(int(sys.argv[1]))
    else:
        run_for(3)
        run_for(0)
