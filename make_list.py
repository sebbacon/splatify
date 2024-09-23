import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
import re
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# Load environment variables
load_dotenv()

# Set up Slack client
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
if not SLACK_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN environment variable is not set")
print(f"SLACK_TOKEN (first 10 chars): {SLACK_TOKEN[:10]}...")
slack_client = WebClient(token=SLACK_TOKEN)

# Set up Spotify client
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")

SPOTIFY_PLAYLIST_ID = os.getenv("SPOTIFY_PLAYLIST_ID")

# Check if all required environment variables are set
required_vars = [
    "SPOTIPY_CLIENT_ID",
    "SPOTIPY_CLIENT_SECRET",
    "SPOTIPY_REDIRECT_URI",
    "SPOTIFY_PLAYLIST_ID",
]
for var in required_vars:
    if not os.getenv(var):
        raise ValueError(f"{var} environment variable is not set")

sp = Spotify(
    auth_manager=SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope="playlist-modify-public",
    )
)


def join_channel(channel_id):
    try:
        result = slack_client.conversations_join(channel=channel_id)
        if result["ok"]:
            print(f"Successfully joined channel {channel_id}")
        else:
            print(f"Failed to join channel {channel_id}: {result['error']}")
    except SlackApiError as e:
        if "missing_scope" in str(e):
            print("Error: The bot doesn't have permission to join the channel.")
            print(
                "Please add the 'channels:join' scope to your Slack app's permissions."
            )
            print("1. Go to your Slack App settings (https://api.slack.com/apps)")
            print("2. Select your app and go to 'OAuth & Permissions'")
            print("3. Under 'Scopes', add 'channels:join' to Bot Token Scopes")
            print("4. Reinstall your app to the workspace")
            print("After updating permissions, run this script again.")
            exit(1)
        else:
            print(f"Error joining channel: {e}")


def extract_youtube_links(channel_id, oldest_timestamp=None):
    youtube_links = []
    cursor = None
    try:
        while True:
            result = slack_client.conversations_history(
                channel=channel_id,
                oldest=oldest_timestamp,
                cursor=cursor,
                limit=1000,  # Maximum allowed by Slack API
            )
            for message in result["messages"]:
                links = re.findall(
                    r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)\S+)",
                    message["text"],
                )
                for link in links:
                    youtube_links.append((link, message["ts"]))

            if not result["has_more"]:
                break

            cursor = result["response_metadata"]["next_cursor"]

    except SlackApiError as e:
        print(f"SlackApiError: {e}")
        print(f"Error details: {e.response['error']}")
        print(f"Slack API Response: {e.response}")
        if e.response["error"] == "not_in_channel":
            print("Bot is not in the channel. Attempting to join...")
            join_channel(channel_id)
            # If join_channel doesn't exit the script, try to extract links again
            return extract_youtube_links(channel_id, oldest_timestamp)
    except Exception as e:
        print(f"Unexpected error: {e}")

    return youtube_links


def extract_video_id(url):
    parsed_url = urlparse(url)
    if parsed_url.hostname == "youtu.be":
        return parsed_url.path.lstrip("/")
    if parsed_url.hostname in ("www.youtube.com", "youtube.com"):
        if parsed_url.path == "/watch":
            return parse_qs(parsed_url.query).get("v", [None])[0]
        if parsed_url.path.startswith(("/embed/", "/v/")):
            return parsed_url.path.split("/")[2]
    return None


def search_spotify(query):
    results = sp.search(q=query, type="track", limit=1)
    if results["tracks"]["items"]:
        return results["tracks"]["items"][0]["uri"]
    return None


def add_to_playlist(track_uri):
    track_info = sp.track(track_uri)
    track_name = track_info["name"]
    sp.playlist_add_items(SPOTIFY_PLAYLIST_ID, [track_uri])
    print(f"Added '{track_name}' to Spotify playlist")


def main():
    channel_id = "C043V7CGHFU"  # random-music
    print(f"Using Slack channel ID: {channel_id}")
    join_channel(channel_id)
    youtube_links = extract_youtube_links(channel_id)
    print(f"Found {len(youtube_links)} YouTube links")

    for link, timestamp in youtube_links:
        video_id = extract_video_id(link)
        if video_id:
            # Here you would typically use youtube-dl or a similar library to get video info
            # For this example, we'll just use the video ID as the search query
            spotify_uri = search_spotify(video_id)
            if spotify_uri:
                add_to_playlist(spotify_uri)
                # Convert timestamp to readable date
                date = datetime.fromtimestamp(float(timestamp)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                print(f"Original Slack message date: {date}")
            else:
                print(f"Couldn't find a Spotify track for YouTube video ID: {video_id}")


if __name__ == "__main__":
    main()
