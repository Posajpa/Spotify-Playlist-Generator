from collections import Counter, defaultdict
import streamlit as st
from spotipy import Spotify
from spotipy.cache_handler import CacheHandler
from spotipy.oauth2 import SpotifyOAuth

CLIENT_ID = st.secrets["SPOTIPY_CLIENT_ID"]
CLIENT_SECRET = st.secrets["SPOTIPY_CLIENT_SECRET"]
REDIRECT_URI = st.secrets["SPOTIPY_REDIRECT_URI"]


class StreamlitCacheHandler(CacheHandler):
    def get_cached_token(self):
        return st.session_state.get("spotipy_token")

    def save_token_to_cache(self, token_info):
        st.session_state["spotipy_token"] = token_info


def get_auth_manager():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope="user-library-read playlist-modify-private playlist-modify-public user-read-private",
        show_dialog=True,
        cache_path=None,
        cache_handler=StreamlitCacheHandler()
    )


def create_spotify_client():
    auth_manager = get_auth_manager()
    return Spotify(auth_manager=auth_manager)


def fetch_all_saved_tracks(sp):
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


def get_track_genres(sp, tracks):
    track_genres = defaultdict(list)
    all_artist_ids = set()
    track_artists_map = {}

    for item in tracks:
        track = item.get("track")
        if not track:
            continue
        tid = track.get("id")
        artists = track.get("artists", [])
        artist_ids = [a["id"] for a in artists if a.get("id")]
        track_artists_map[tid] = artist_ids
        all_artist_ids.update(artist_ids)

    artist_ids = list(all_artist_ids)
    artist_genres_map = {}
    for i in range(0, len(artist_ids), 50):
        chunk = artist_ids[i:i + 50]
        artists_info = sp.artists(chunk)["artists"]
        for a in artists_info:
            artist_genres_map[a["id"]] = a.get("genres", [])

    for tid, a_ids in track_artists_map.items():
        genres = []
        for aid in a_ids:
            genres.extend(artist_genres_map.get(aid, []))
        track_genres[tid] = list(set(genres))

    return track_genres


@st.cache_data(show_spinner=False)
def cached_fetch_tracks_and_genres(tracks, track_genres):
    return tracks, track_genres


def filter_tracks_by_selected_genres(tracks, track_genres, selected_genres, mode="or"):
    selected_genres = [g.lower() for g in selected_genres]
    filtered_tracks = []

    for item in tracks:
        track = item.get("track")
        if not track:
            continue
        tid = track.get("id")
        genres = [g.lower() for g in track_genres.get(tid, [])]
        if not genres:
            continue

        if mode == "or" and any(g in genres for g in selected_genres):
            filtered_tracks.append(track)
        elif mode == "and" and all(g in genres for g in selected_genres):
            filtered_tracks.append(track)

    return filtered_tracks


def create_playlist_with_tracks(sp, user_id, playlist_name, tracks_to_add, public=False):
    uris = [t["uri"] for t in tracks_to_add]
    playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=public)
    pid = playlist["id"]

    for i in range(0, len(uris), 100):
        sp.playlist_add_items(pid, uris[i:i + 100])

    return playlist


# -------------------------
# Streamlit App
# -------------------------
st.set_page_config(page_title="Spotify Genre Playlist Generator", layout="centered", page_icon="🎵",
                   initial_sidebar_state="collapsed")
# Header
st.markdown("<h1 style='text-align:center; font-size:32px;'>🎵 Spotify Genre Playlist Generator</h1>",
            unsafe_allow_html=True)
st.markdown(
    "<p style='text-align:center; color:gray; font-size:14px;'>Select your favorite genres from your liked songs and create a playlist instantly.</p>",
    unsafe_allow_html=True)
st.markdown("---")

# Initialize session state
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

auth_manager = get_auth_manager()

# --- STEP 1: Handle redirect back from Spotify ---
if "code" in st.query_params:
    try:
        # This should validate and cache the token
        auth_manager.get_access_token(st.query_params["code"])
        sp = Spotify(auth_manager=auth_manager)
        st.session_state["authenticated"] = True
        st.rerun()  # This will clear the code from URL
    except Exception as e:
        st.error(f"Authentication failed: {e}")
        st.stop()

# --- STEP 2: If token cached, authenticate automatically ---
elif not st.session_state["authenticated"]:
    token = auth_manager.get_cached_token()
    if token and not auth_manager.is_token_expired(token):
        st.session_state["authenticated"] = True
        # Don't create sp here - it will be created after authentication check

# --- STEP 3: If not authenticated yet, show login button ---
if not st.session_state["authenticated"]:
    auth_url = auth_manager.get_authorize_url()
    st.markdown(
        f"<a href='{auth_url}' target='_blank'><button style='margin-top:20px;'>Log in to Spotify</button></a>",
        unsafe_allow_html=True
    )
    st.stop()

# --- IF WE REACH THIS POINT: user is authenticated ---
sp = Spotify(auth_manager=auth_manager)
st.error("6")

# Fetch cached tracks & genres
with st.spinner("Loading your liked songs and genres…"):
    tracks = fetch_all_saved_tracks(sp)
    track_genres = get_track_genres(sp, tracks)
    tracks, track_genres = cached_fetch_tracks_and_genres(tracks, track_genres)

# Count genres
genre_counter = Counter()
for genres in track_genres.values():
    genre_counter.update(genres)

# Sort & show genres
sorted_genres = sorted(genre_counter.items(), key=lambda x: x[1], reverse=True)
genre_list = [f"{genre} ({count})" for genre, count in sorted_genres]
genre_names = [genre for genre, _ in sorted_genres]

# Selection & Controls
selected_idx = st.multiselect(
    "Select genres",
    options=list(range(len(genre_list))),
    format_func=lambda x: genre_list[x],
    help="Scrollable list of genres"
)
selected_genres = [genre_names[i] for i in selected_idx]

# AND / OR selection
mode = st.radio("Match mode", ["or", "and"],
                help="OR = Include any of the selected genres, AND = Must be in all the selected genres")

# Playlist info
playlist_name = st.text_input("Playlist name", placeholder="My Rock Playlist")
make_public = st.checkbox("Make playlist public?", value=True)

# Playlist creation
if st.button("Generate Playlist"):
    if not selected_genres:
        st.error("Please choose at least one genre")
    else:
        with st.spinner("Filtering tracks and creating playlist…"):
            filtered = filter_tracks_by_selected_genres(tracks, track_genres, selected_genres, mode)
            st.write(f"Found {len(filtered)} matching tracks")

            if filtered:
                user_id = sp.current_user()["id"]
                playlist = create_playlist_with_tracks(sp, user_id, playlist_name, filtered, public=make_public)
                st.success(f"Playlist created: {playlist['name']}")
                st.markdown(f"[Open in Spotify](https://open.spotify.com/playlist/{playlist['id']})")
            else:
                st.warning("No tracks matched the selected genres.")

# Footer
st.markdown("---")
