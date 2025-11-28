#!/usr/bin/env python3
"""Run birthday notifications now (send to admins + settings.ADMIN_CHAT_ID).

This script will call db.notifications.send_birthday_notifications for days=3 and days=0.
Use with caution: it sends real Telegram messages using settings.API_KEY.
"""
import asyncio
import os
import sys
repo_root = os.path.dirname(os.path.dirname(__file__))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from telegram import Bot
import settings
from db.notifications import send_birthday_notifications

async def main():
    bot = Bot(token=settings.API_KEY)
    print('Sending reminders for 3 days before...')
    sent3 = await send_birthday_notifications(bot, 3)
    print('Messages sent (3 days):', sent3)
    print('Sending reminders for today...')
    sent0 = await send_birthday_notifications(bot, 0)
    print('Messages sent (today):', sent0)

if __name__ == '__main__':
    asyncio.run(main())
