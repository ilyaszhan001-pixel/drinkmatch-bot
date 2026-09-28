# DrinkMatch Bot 🍻

Telegram-бот для поиска собутыльников.

## Быстрый запуск локально

1. Установи Python 3.10+
2. Создай виртуальное окружение:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/Mac
   # или
   venv\Scripts\activate      # Windows
   ```
3. Установи зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Запусти:
   ```bash
   export BOT_TOKEN="твой_токен"
   python bot.py
   ```

## Бесплатный запуск 24/7 (Railway)

1. Зайди на https://railway.app и зарегистрируйся через GitHub
2. New Project → Deploy from GitHub repo (или Empty Project + Upload)
3. Добавь переменную окружения:
   - Key: `BOT_TOKEN`
   - Value: твой токен
4. В настройках сервиса укажи Start Command: `python bot.py`
5. Deploy

Бот будет работать круглосуточно бесплатно (в рамках лимитов Railway).
