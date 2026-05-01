# AutoClip

Telegram-бот для поиска Twitch-клипов, обработки видео в вертикальный формат и публикации контента в Telegram/YouTube.

## Запуск

1. Создайте виртуальное окружение:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. Скопируйте `.env.example` в `.env` и заполните ключи.

3. Установите `ffmpeg` и `ffprobe` так, чтобы они были доступны из папки проекта или из `PATH`.

4. Запустите бота:

```powershell
.\.venv\Scripts\python.exe main_bot.py
```

Секреты, OAuth-токены, скачанные и обработанные видео не хранятся в репозитории.
