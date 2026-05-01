# youtube_uploader.py
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
from datetime import datetime
import subprocess

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# Путь к файлам авторизации
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.pickle"
TELEGRAM_CHANNEL_LINK = os.getenv("TELEGRAM_CHANNEL_LINK", "https://t.me/your_channel")


def is_shorts_video(filepath):
    """Проверяет, соответствует ли видео требованиям YouTube Shorts"""
    try:
        # Используем ffprobe для проверки длительности и разрешения
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration,width,height",
                "-of",
                "csv=p=0",
                filepath,
            ],
            capture_output=True,
            text=True,
        )

        duration, width, height = map(float, result.stdout.strip().split(","))

        # Требования Shorts: длительность <= 60 сек, соотношение 9:16, разрешение >= 720p
        return (
            duration <= 60
            and width / height <= 0.5625  # 9/16 = 0.5625
            and height >= 720
        )
    except Exception:
        return False


def upload_to_youtube(filepath, title, clip_data=None):
    if clip_data is None:
        clip_data = {}
    # Улучшенный заголовок с хэштегами и именем стримера
    title_with_hashtags = (
        f"{title[:80]} | #Shorts #Twitch #Gaming "
        f"#{clip_data.get('broadcaster_name', '').replace(' ', '')}"
    )

    # Проверка на Shorts
    is_shorts = is_shorts_video(filepath)
    if is_shorts:
        title_with_hashtags += " #Shorts"

    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)

    youtube = build("youtube", "v3", credentials=creds)

    # Улучшенное описание с timestamp и ссылками
    description = f"""
🎮 Игра: {clip_data.get('game_name', 'Various Games')}
#Twitch #Gaming #LiveStream #Highlights #Shorts{' #Shorts' if is_shorts else ''}
👉 Больше бонусов в закрепленном комментарии
    """.strip()

    request_body = {
        "snippet": {
            "categoryId": "20",  # Gaming
            "title": title_with_hashtags,
            "description": description,
            "tags": [
                "twitch",
                "gaming",
                "live",
                "stream",
                "highlights",
                "clips",
                "shorts",
                "twitch clips",
                "twitch highlights",
                *[
                    tag.strip("#")
                    for tag in title_with_hashtags.split()
                    if tag.startswith("#")
                ],
            ],
        },
        "status": {
            "privacyStatus": "public",
            "madeForKids": False,
            "selfDeclaredMadeForKids": False,
        },
        **({"contentDetails": {"isShort": True}} if is_shorts else {}),
    }

    media = MediaFileUpload(filepath, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(
        part="snippet,status,contentDetails", body=request_body, media_body=media
    )
    response = None

    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")

    video_id = response["id"]

    # Добавляем закрепленный комментарий
    try:
        comment_body = {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": (
                            f"🔥 Больше крутых бонусов в моем канале: "
                            f"{TELEGRAM_CHANNEL_LINK}\n\n"
                        )
                    }
                },
            }
        }

        comment_response = (
            youtube.commentThreads().insert(part="snippet", body=comment_body).execute()
        )

        # Закрепляем комментарий
        youtube.comments().setModerationStatus(
            id=comment_response["id"], moderationStatus="published"
        )
        print(f"Закрепленный комментарий добавлен к видео {video_id}")
    except Exception as e:
        print(f"Ошибка при добавлении комментария: {e}")

    return f"https://youtu.be/{video_id}"
