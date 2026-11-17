"""Общие помощники для сценариев: запуск браузера и адрес локального сервера."""
import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get('BASE_URL', 'http://localhost:8765/index.html')
CHROME = os.environ.get('CHROME')  # путь к своему Chrome, если не хочется качать Chromium от Playwright


def launch(pw):
    args = ['--no-sandbox']
    return pw.chromium.launch(executable_path=CHROME, args=args) if CHROME else pw.chromium.launch(args=args)


def sign_up(page, name, pin='1234'):
    """Первый вход: имя + ПИН, потом закрыть правила, которые открываются новичку."""
    page.fill('#nameInput', name)
    page.fill('#pinInput', pin)
    page.press('#pinInput', 'Enter')
    page.wait_for_timeout(500)
    if page.is_visible('#rClose'):
        page.click('#rClose')


__all__ = ['sync_playwright', 'BASE', 'launch', 'sign_up']
