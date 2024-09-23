import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
import re
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json

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
    "YOUTUBE_API_KEY",
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


if "DOKKU_APP_TYPE" in os.environ:
    STATE_JSON = "/app/data/last_processed.json"
else:
    STATE_JSON = "last_processed.json"


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


def extract_youtube_links(channel_id):
    youtube_links = []
    cursor = None
    last_processed_timestamp = get_last_processed_timestamp()

    try:
        while True:
            result = slack_client.conversations_history(
                channel=channel_id,
                oldest=last_processed_timestamp,
                cursor=cursor,
                limit=1000,  # Maximum allowed by Slack API
            )
            for message in result["messages"]:
                links = re.findall(
                    r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)\S+)",
                    message["text"],
                )
                for link in links:
                    # Strip the '>' character from the end of the link if present
                    cleaned_link = link.rstrip(">")
                    youtube_links.append((cleaned_link, message["ts"]))

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
            return extract_youtube_links(channel_id)
    except Exception as e:
        print(f"Unexpected error: {e}")

    return youtube_links


def extract_video_id(url):
    # Remove any trailing pipe and additional content
    url = url.split("|")[0]
    parsed_url = urlparse(url)
    if parsed_url.hostname == "youtu.be":
        return parsed_url.path.lstrip("/")
    if parsed_url.hostname in ("www.youtube.com", "youtube.com"):
        if parsed_url.path == "/watch":
            return parse_qs(parsed_url.query).get("v", [None])[0]
        if parsed_url.path.startswith(("/embed/", "/v/")):
            return parsed_url.path.split("/")[2]
    return None


def get_video_info(video_id):
    youtube = build("youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY"))
    try:
        request = youtube.videos().list(part="snippet", id=video_id)
        response = request.execute()

        if response["items"]:
            snippet = response["items"][0]["snippet"]
            return {
                "title": snippet.get("title", ""),
            }
        else:
            print(f"No video found for ID: {video_id}")
            print(f"Search text: {video_id}")
            return None
    except HttpError as e:
        print(f"An HTTP error {e.resp.status} occurred: {e.content}")
        print(f"Search text: {video_id}")
        return None


def search_spotify(video_info):
    if not video_info:
        return None
    query = f"{video_info['title']}"
    results = sp.search(q=query, type="track", limit=1)
    if results["tracks"]["items"]:
        return results["tracks"]["items"][0]["uri"]
    return None


def is_track_in_playlist(track_uri):
    playlist_tracks = sp.playlist_items(SPOTIFY_PLAYLIST_ID)
    return any(item["track"]["uri"] == track_uri for item in playlist_tracks["items"])


def add_to_playlist(track_uri):
    if is_track_in_playlist(track_uri):
        track_info = sp.track(track_uri)
        track_name = track_info["name"]
        print(f"'{track_name}' is already in the Spotify playlist")
    else:
        track_info = sp.track(track_uri)
        track_name = track_info["name"]
        sp.playlist_add_items(SPOTIFY_PLAYLIST_ID, [track_uri])
        print(f"Added '{track_name}' to Spotify playlist")


def get_last_processed_timestamp():
    try:
        with open(STATE_JSON, "r") as f:
            data = json.load(f)
            return data.get("last_processed_timestamp")
    except FileNotFoundError:
        # If the file doesn't exist, create it with the initial timestamp
        initial_timestamp = "1727092800"  # 23 Sept 2024 12:00:00 UTC
        save_last_processed_timestamp(initial_timestamp)
        return initial_timestamp


def save_last_processed_timestamp(timestamp):
    with open(STATE_JSON, "w") as f:
        json.dump({"last_processed_timestamp": timestamp}, f)


def main():
    channel_id = "C043V7CGHFU"  # random-music
    print(f"Using Slack channel ID: {channel_id}")
    join_channel(channel_id)
    youtube_links = extract_youtube_links(channel_id)
    print(f"Found {len(youtube_links)} YouTube links")

    processed_links = set()
    last_processed_timestamp = None

    for link, timestamp in sorted(youtube_links, key=lambda x: x[1], reverse=True):
        if link in processed_links:
            continue
        processed_links.add(link)

        video_id = extract_video_id(link)
        if video_id:
            video_info = get_video_info(video_id)
            if video_info:
                spotify_uri = search_spotify(video_info)
                if spotify_uri:
                    add_to_playlist(spotify_uri)
                    # Convert timestamp to readable date
                    date = datetime.fromtimestamp(float(timestamp)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    print(f"Processed '{video_info['title']}' ")
                    print(f"Original Slack message date: {date}")
                else:
                    print(f"Couldn't find a Spotify track for: {video_info['title']}")
            else:
                print(f"Couldn't fetch video info for YouTube video ID: {video_id}")
                print(f"Search text: {link}")
        else:
            print(f"Couldn't extract video ID from link: {link}")

        if last_processed_timestamp is None:
            last_processed_timestamp = timestamp

    if last_processed_timestamp:
        save_last_processed_timestamp(last_processed_timestamp)
        print(f"Updated last processed timestamp to: {last_processed_timestamp}")


if __name__ == "__main__":
    main()
