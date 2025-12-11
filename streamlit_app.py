# streamlit_spotify_playlist_app.py
# Smart Spotify Playlist Generator - Streamlit + Spotipy
# Single-file Streamlit app you can run locally or deploy.
# Instructions (short):
# 1) Create a Spotify app at https://developer.spotify.com/dashboard
#    - Add Redirect URI: http://localhost:8501 or your deployed URL + "/"
# 2) Set the CLIENT_ID and CLIENT_SECRET below or export as env vars
#    - SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET
# 3) Install requirements: pip install -r requirements.txt
# 4) Run: streamlit run streamlit_spotify_playlist_app.py

# Requirements (put in requirements.txt):
# streamlit
# spotipy
# pandas
# numpy

import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd
import time
import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")

SCOPE = (
    "user-library-read playlist-modify-private playlist-modify-public user-read-private"
)
CACHE_PATH = ".cache"

# -------------------------
# Helper functions
# -------------------------

def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=CACHE_PATH,
        show_dialog=True,
    )


def get_token_from_code(code: str):
    sp_oauth = get_spotify_oauth()
    token_info = sp_oauth.get_access_token(code)
    return token_info


@st.cache_data
def fetch_all_saved_tracks(sp: spotipy.Spotify) -> List[dict]:
    """Fetch all saved (liked) tracks for the current user."""
    limit = 50
    offset = 0
    all_items = []

    while True:
        res = sp.current_user_saved_tracks(limit=limit, offset=offset)
        items = res.get("items", [])
        if not items:
            break
        all_items.extend(items)
        offset += limit
    return all_items


def normalize_text(s: str) -> str:
    return (s or "").lower()


def filter_tracks(tracks: List[dict], keyword: str, min_bpm=None, max_bpm=None, min_dance=None, min_valence=None) -> List[dict]:
    keyword = normalize_text(keyword)
    if keyword == "":
        # if empty keyword, return empty list
        return []

    filtered = []
    # We'll batch query audio features to allow BPM/danceability/valence filtering
    track_ids = [t["track"]["id"] for t in tracks if t.get("track") and t["track"].get("id")]

    # Get audio features in chunks of 100
    sp = st.session_state.get("sp")
    features_map = {}
    for i in range(0, len(track_ids), 100):
        chunk = track_ids[i:i+100]
        afs = sp.audio_features(chunk)
        for af in afs:
            if af and af.get("id"):
                features_map[af["id"]] = af

    for item in tracks:
        track = item["track"]
        if not track:
            continue
        name = normalize_text(track.get("name", ""))
        artists = ", ".join([a["name"] for a in track.get("artists", [])])
        artists = normalize_text(artists)
        album = normalize_text(track.get("album", {}).get("name", ""))

        match = (keyword in name) or (keyword in artists) or (keyword in album)

        if match:
            # check audio features filters
            af = features_map.get(track.get("id"))
            if af is None:
                # if no audio features, include it (or you may skip)
                filtered.append(track)
                continue

            bpm = af.get("tempo")
            dance = af.get("danceability")
            valence = af.get("valence")

            if min_bpm is not None and bpm is not None and bpm < min_bpm:
                continue
            if max_bpm is not None and bpm is not None and bpm > max_bpm:
                continue
            if min_dance is not None and dance is not None and dance < min_dance:
                continue
            if min_valence is not None and valence is not None and valence < min_valence:
                continue

            filtered.append(track)

    return filtered


def create_playlist_and_add_tracks(sp: spotipy.Spotify, user_id: str, playlist_name: str, track_uris: List[str], public: bool = False) -> dict:
    playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=public)
    pid = playlist["id"]
    # add in chunks of 100
    for i in range(0, len(track_uris), 100):
        sp.playlist_add_items(pid, track_uris[i : i + 100])
    return playlist


# -------------------------
# Streamlit UI
# -------------------------

st.set_page_config(page_title="Smart Spotify Playlist Generator", layout="centered")
st.title("🎛️ Smart Spotify Playlist Generator")
st.write("Create playlists from your Liked Songs using keywords and audio filters.")

# AUTH
sp = None
if "auth_done" not in st.session_state:
    st.session_state.auth_done = False

# If we already have token info in cache file, Spotipy will pick it up.
sp_oauth = get_spotify_oauth()

# Check for code in query params (after redirect from spotify auth)
params = st.query_params
code = params.get("code", [None])[0]

if code and not st.session_state.auth_done:
    try:
        token_info = get_token_from_code(code)
        access_token = token_info["access_token"] if isinstance(token_info, dict) else token_info
        sp = spotipy.Spotify(auth=access_token)
        st.session_state.sp = sp
        st.session_state.auth_done = True
        st.experimental_set_query_params()  # clear query params
        st.success("Authentication successful — you're connected to Spotify!")
        time.sleep(0.8)
        st.experimental_rerun()
    except Exception as e:
        st.error("Failed to complete authentication: {}".format(e))

if not st.session_state.get("auth_done"):
    st.info("You need to connect your Spotify account to use the app.")
    auth_url = sp_oauth.get_authorize_url()
    st.markdown(f"[Connect to Spotify]({auth_url})")
    st.caption("After connecting, Spotify will redirect back to this app. If the redirect doesn't return, copy the URL and paste it here.")
    # Allow manual paste of redirect URL (fallback)
    redirect_url_input = st.text_input("If auth didn't finish automatically, paste the redirected URL here (the URL will contain '?code=...'):")
    if redirect_url_input:
        # try to extract code
        import urllib.parse as up

        q = up.urlparse(redirect_url_input).query
        qp = up.parse_qs(q)
        code_try = qp.get("code", [None])[0]
        if code_try:
            try:
                token_info = get_token_from_code(code_try)
                access_token = token_info["access_token"] if isinstance(token_info, dict) else token_info
                sp = spotipy.Spotify(auth=access_token)
                st.session_state.sp = sp
                st.session_state.auth_done = True
                st.success("Authentication successful — you're connected to Spotify!")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Failed to exchange code: {e}")

# If authenticated, create sp client (Spotipy will use cache file if available)
if st.session_state.get("auth_done"):
    try:
        # Try to create Spotify instance using cached credentials
        oauth = get_spotify_oauth()
        token_info = oauth.get_cached_token()
        if token_info is None:
            # Attempt to refresh automatically (Spotipy handles it) by getting a new token using the oauth object
            st.warning("Token not found in cache — you may need to re-authenticate.")
        else:
            sp = spotipy.Spotify(auth=token_info["access_token"])
            st.session_state.sp = sp
    except Exception as e:
        st.error(f"Error creating Spotify client: {e}")

if st.session_state.get("sp"):
    sp = st.session_state.sp
    user = sp.current_user()
    st.sidebar.write(f"Logged in as: {user.get('display_name')} ({user.get('id')})")

    with st.expander("App settings & options", expanded=False):
        st.write("These settings control how we filter and build playlists.")
        default_public = False
        is_public = st.checkbox("Make playlist public?", value=default_public)

    # Main controls
    st.subheader("Search your Liked Songs")
    keyword = st.text_input("Keyword (search in track name, artist, album)", value="italian")

    col1, col2 = st.columns(2)
    with col1:
        bpm_range = st.slider("BPM range", 0, 220, (0, 220))
    with col2:
        dance_min = st.slider("Min danceability (0-1)", 0.0, 1.0, 0.0, step=0.05)
        valence_min = st.slider("Min valence (0-1, happiness)", 0.0, 1.0, 0.0, step=0.05)

    playlist_name = st.text_input("Playlist name", value=f"{keyword.capitalize()} Playlist (Auto)")

    if st.button("Generate playlist"):
        if not keyword.strip():
            st.error("Please enter a keyword.")
        else:
            with st.spinner("Fetching your liked songs (this may take a moment)..."):
                saved = fetch_all_saved_tracks(sp)
            st.write(f"Total liked songs: {len(saved)}")

            with st.spinner("Filtering songs..."):
                filtered = filter_tracks(
                    saved,
                    keyword,
                    min_bpm=bpm_range[0] if bpm_range[0] > 0 else None,
                    max_bpm=bpm_range[1] if bpm_range[1] < 220 else None,
                    min_dance=dance_min if dance_min > 0 else None,
                    min_valence=valence_min if valence_min > 0 else None,
                )

            st.write(f"Found {len(filtered)} matching tracks")

            if len(filtered) == 0:
                st.info("No tracks matched your filters. Try relaxing filters or a different keyword.")
            else:
                # show a preview table
                df_preview = pd.DataFrame([
                    {
                        "name": t.get("name"),
                        "artists": ", ".join([a["name"] for a in t.get("artists", [])]),
                        "album": t.get("album", {}).get("name"),
                        "uri": t.get("uri"),
                    }
                    for t in filtered
                ])
                st.dataframe(df_preview.head(50))

                if st.button("Create playlist on Spotify with these songs"):
                    with st.spinner("Creating playlist and adding songs..."):
                        user_id = user.get("id")
                        uris = [t.get("uri") for t in filtered]
                        playlist = create_playlist_and_add_tracks(sp, user_id, playlist_name, uris, public=is_public)
                        st.success(f"Playlist created: {playlist.get('name')}")
                        st.markdown(f"Open in Spotify: [Open playlist](https://open.spotify.com/playlist/{playlist.get('id')})")

    st.markdown("---")
    st.write("Tips:")
    st.write("- Use short keywords like 'italian', 'reggaeton', 'acoustic', or artist names.")
    st.write("- Use the BPM / danceability sliders to refine mood or energy.")
    st.write("- For portfolio: take screenshots of the app, include the GitHub repo and a live demo link.")

else:
    st.write("Please connect your Spotify account first (left section).")

# EOF
