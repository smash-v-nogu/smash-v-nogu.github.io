# Сценарии на Playwright

Каждый файл — самостоятельный сценарий: открывает игру в браузере, играет и проверяет результат. Supabase подменён или отключён, настоящая база не трогается.

```bash
pip install playwright && python -m playwright install chromium
python3 -m http.server 8765      # из корня репозитория, в отдельном терминале
cd tests
python3 test_login.py            # вход по имени и ПИН
python3 test_online.py           # онлайн через BroadcastChannel
python3 test_training.py         # тренировка с многоволанкой (идёт пару минут)
```

Переменные окружения: `BASE_URL` — другой адрес игры, `CHROME` — путь к своему Chrome вместо Chromium от Playwright.
