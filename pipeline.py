import sqlite3
import random
import requests

# --- Configuration Credentials ---
TRAKT_CLIENT_ID = "881282f9b893b4198abc8d79e93093bda2e7285a7b35029cae3ffc8a4ae40aa8"
TMDB_API_TOKEN = "30959d8b46ef03ac4c8b81d06be9ba18"

HEADERS_TRAKT = {
    "Content-Type": "application/json",
    "trakt-api-key": TRAKT_CLIENT_ID,
    "trakt-api-version": "2",
    "User-Agent": "MovieRecBot/1.0"
}

HEADERS_TMDB = {
    "accept": "application/json"
}

DB_PATH = "facebook_history.db"

# ─────────────────────────────────────────
# Database Tracking Layer
# ─────────────────────────────────────────

def init_db():
    """Creates the SQLite tracking table if it doesn't exist."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posted_movies (
                tmdb_id  INTEGER PRIMARY KEY,
                title    TEXT,
                posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[DB] Init failed: {e}")
        raise

def is_already_posted(tmdb_id: int) -> bool:
    """Returns True if this movie has already been posted."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT 1 FROM posted_movies WHERE tmdb_id = ?", (tmdb_id,)
        ).fetchone()
        conn.close()
        return row is not None
    except sqlite3.Error:
        # If DB check fails, treat as NOT posted so we don't silently skip
        return False

def log_posted_movie(tmdb_id: int, title: str):
    """Marks a movie as posted so it won't be picked again."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR IGNORE INTO posted_movies (tmdb_id, title) VALUES (?, ?)",
            (tmdb_id, title)
        )
        conn.commit()
        conn.close()
        print(f"[DB] Logged: {title} (TMDB ID: {tmdb_id})")
    except sqlite3.Error as e:
        print(f"[DB] Failed to log movie: {e}")

# ─────────────────────────────────────────
# Sourcing Layer — Trakt
# ─────────────────────────────────────────

def fetch_trakt_trending(limit: int = 20) -> list:
    """
    Fetches trending movies from Trakt with full extended info.
    ?extended=full gives us the overview/summary directly from Trakt,
    which we use as a fallback if TMDB's overview is missing.
    Returns a list of dicts or empty list on failure.
    """
    url = f"https://api.trakt.tv/movies/trending?limit={limit}&extended=full"
    try:
        response = requests.get(url, headers=HEADERS_TRAKT, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"[Trakt] HTTP error: {e}")
    except requests.exceptions.ConnectionError:
        print("[Trakt] Connection failed. Check your internet.")
    except requests.exceptions.Timeout:
        print("[Trakt] Request timed out.")
    except Exception as e:
        print(f"[Trakt] Unexpected error: {e}")
    return []

# ─────────────────────────────────────────
# Bridging Layer — TMDB
# ─────────────────────────────────────────

def fetch_tmdb_details(tmdb_id: int) -> dict:
    """
    Fetches movie details (overview, poster) from TMDB.
    Returns a dict with 'overview' and 'poster_url', or empty values on failure.
    """
    result = {"overview": None, "poster_url": None}
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?language=en-US&api_key={TMDB_API_TOKEN}"
    try:
        response = requests.get(url, headers=HEADERS_TMDB, timeout=10)
        if response.status_code == 200:
            data = response.json()
            result["overview"] = data.get("overview") or None
            poster_path = data.get("poster_path")
            result["poster_url"] = (
                f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
            )
        else:
            print(f"[TMDB] Details returned {response.status_code} for ID {tmdb_id}")
    except requests.exceptions.Timeout:
        print(f"[TMDB] Details request timed out for ID {tmdb_id}")
    except Exception as e:
        print(f"[TMDB] Details error for ID {tmdb_id}: {e}")
    return result

def fetch_tmdb_screenshots(tmdb_id: int, count: int = 5) -> list:
    """
    Fetches widescreen scene screenshots (backdrops) from TMDB.
    include_image_language=en,null ensures maximum results.
    Picks `count` random images from the full pool.
    Returns a list of image URLs.
    """
    url = (
        f"https://api.themoviedb.org/3/movie/{tmdb_id}/images"
        f"?api_key={TMDB_API_TOKEN}&include_image_language=en,null"
    )
    try:
        response = requests.get(url, headers=HEADERS_TMDB, timeout=10)
        if response.status_code == 200:
            backdrops = response.json().get("backdrops", [])
            if not backdrops:
                return []
            # Pick randomly from the full pool — different images each run
            chosen = random.sample(backdrops, min(count, len(backdrops)))
            return [
                f"https://image.tmdb.org/t/p/w1280{img['file_path']}"
                for img in chosen
            ]
        else:
            print(f"[TMDB] Images returned {response.status_code} for ID {tmdb_id}")
    except requests.exceptions.Timeout:
        print(f"[TMDB] Images request timed out for ID {tmdb_id}")
    except Exception as e:
        print(f"[TMDB] Images error for ID {tmdb_id}: {e}")
    return []

# ─────────────────────────────────────────
# Main Pipeline
# ─────────────────────────────────────────

def get_fresh_recommendation() -> dict:
    """
    Full pipeline:
      1. Pull trending movies from Trakt (with extended summary)
      2. Skip any already posted (SQLite check)
      3. Enrich with TMDB details (poster + overview)
      4. Summary priority: TMDB overview -> Trakt overview -> generic fallback
      5. Fetch random 5 scene screenshots from TMDB
    Returns a populated movie dict, or {} if nothing fresh is available.
    """

    # Step 1: Get trending list from Trakt
    trending_items = fetch_trakt_trending(limit=20)
    if not trending_items:
        print("[Pipeline] Could not fetch Trakt trending list. Aborting.")
        return {}

    # Step 2: Walk the list and pick the first unposted movie
    selected_movie = None
    trakt_overview = None  # Save Trakt's own overview as a fallback

    for item in trending_items:
        movie_meta = item.get("movie", {})
        tmdb_id = movie_meta.get("ids", {}).get("tmdb")

        if not tmdb_id:
            continue  # Skip if no TMDB ID mapping available

        if is_already_posted(tmdb_id):
            continue  # Already posted — move to next

        # Found a fresh one — capture it
        selected_movie = {
            "title":   movie_meta.get("title", "Unknown Title"),
            "year":    movie_meta.get("year"),
            "tmdb_id": tmdb_id,
        }
        # Trakt extended=full gives us an overview too — save it as fallback
        trakt_overview = movie_meta.get("overview") or None
        break

    if not selected_movie:
        print("[Pipeline] All trending movies have already been posted.")
        return {}

    # Step 3 & 4: Enrich with TMDB (primary) and fall back to Trakt summary
    tmdb_details = fetch_tmdb_details(selected_movie["tmdb_id"])

    selected_movie["poster_url"] = tmdb_details["poster_url"]

    # Summary priority: TMDB -> Trakt extended -> generic fallback
    summary = (
        tmdb_details["overview"]
        or trakt_overview
        or "A must-watch trending film. Check it out tonight!"
    )
    selected_movie["overview"] = summary

    # Step 5: Grab random 5 scene screenshots
    selected_movie["screenshot_urls"] = fetch_tmdb_screenshots(selected_movie["tmdb_id"])

    return selected_movie

# ─────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    
    # Import the transcript processor
    from transcript_processor_final import process_video_transcript
    
    print("Choose an option:")
    print("1. Process YouTube URL to extract movies")
    print("2. Get fresh movie recommendation from Trakt/TMDB")
    
    choice = input("\nEnter your choice (1 or 2): ").strip()
    
    if choice == "1":
        # Process YouTube URL
        url = input("\nEnter YouTube video URL: ").strip()
        
        if not url:
            print("No URL provided. Exiting.")
        else:
            print(f"\nProcessing video: {url}")
            movies = process_video_transcript(url)
            
            if movies:
                print(f"\nSuccessfully extracted {len(movies)} movies:")
                for i, movie in enumerate(movies, 1):
                    print(f"  {i}. {movie}")
            else:
                print("\nNo movies found or extraction failed.")
                
    elif choice == "2":
        # Original Trakt/TMDB functionality
        print("\nFetching fresh movie recommendation...\n")
        movie = get_fresh_recommendation()

        if not movie:
            print("Nothing to post right now.")
        else:
            print("=" * 55)
            print(f"  Title    : {movie['title']} ({movie.get('year', 'N/A')})")
            print(f"  TMDB ID  : {movie['tmdb_id']}")
            print(f"  Poster   : {movie['poster_url']}")
            print(f"  Summary  : {movie['overview']}")
            screenshots = movie.get("screenshot_urls", [])
            if screenshots:
                print(f"\n  Scene Screenshots ({len(screenshots)} selected randomly):")
                for i, url in enumerate(screenshots, 1):
                    print(f"    [{i}] {url}")
            else:
                print("\n  No screenshots available for this movie.")
            print("=" * 55)

            # Uncomment these two lines when your Facebook post succeeds:
            # log_posted_movie(movie['tmdb_id'], movie['title'])
            # print("\n[DB] Movie saved to history. Will not post again.")
    else:
        print("Invalid choice. Please run the program again and select 1 or 2.")
