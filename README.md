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

4. Скачайте файлы модели детекции лиц и положите их в корень проекта:
   - [deploy.prototxt](https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt)
   - [res10_300x300_ssd_iter_140000.caffemodel](https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel)

   Вы также можете использовать автоматический скрипт для их загрузки:
   ```powershell
   python download_model.py
   ```

5. Запустите бота:

```powershell
.\.venv\Scripts\python.exe main_bot.py
```

Секреты, OAuth-токены, скачанные и обработанные видео не хранятся в репозитории.
Модели весов OpenCV игнорируются для новых коммитов.

## Тестирование

Для запуска тестов установите `pytest` и запустите его из корня проекта:

```powershell
pip install pytest
$env:PYTHONPATH="."
pytest
```
