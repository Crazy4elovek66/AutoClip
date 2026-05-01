# twitch_fetcher.py
import os
import requests
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv
from utils import sanitize_filename

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

class TwitchClipFetcher:
    def __init__(self):
        self.token = self.get_access_token()
        self.headers = {
            'Client-ID': CLIENT_ID,
            'Authorization': f'Bearer {self.token}'
        }

    def get_access_token(self):
        url = 'https://id.twitch.tv/oauth2/token'
        params = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }
        response = requests.post(url, params=params)
        return response.json()['access_token']

    def get_user_id(self, username):
        url = 'https://api.twitch.tv/helix/users'
        params = {'login': username}
        res = requests.get(url, headers=self.headers, params=params)
        data = res.json().get('data', [])
        return data[0]['id'] if data else None

    def get_clips(self, user_id):
        started_at = (datetime.utcnow() - timedelta(days=14)).isoformat("T") + "Z"
        url = 'https://api.twitch.tv/helix/clips'
        params = {
            'broadcaster_id': user_id,
            'first': 10,
            'started_at': started_at
        }
        res = requests.get(url, headers=self.headers, params=params)
        return res.json().get('data', [])

    def fetch_top_clips(self):
        channels = os.getenv("CHANNELS", "shroud").split(',')
        all_clips = []
        for channel in channels:
            uid = self.get_user_id(channel.strip())
            if uid:
                clips = self.get_clips(uid)
                for clip in clips:
                    clip['broadcaster_name'] = channel.strip()
                    all_clips.append(clip)
        all_clips.sort(key=lambda x: x.get('view_count', 0), reverse=True)
        return all_clips

    def download_clip(self, clip):
        url = clip['url']
        title = sanitize_filename(f"{clip['broadcaster_name']} - {clip['title']}")
        out_path = os.path.join("downloads", f"{title}.mp4")
        os.makedirs("downloads", exist_ok=True)
        subprocess.run(["yt-dlp", "-o", out_path, url], check=True)
        return out_path
