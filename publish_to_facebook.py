import os
import sqlite3
import requests
import random
import re
from pipeline import fetch_tmdb_details, fetch_tmdb_screenshots, TMDB_API_TOKEN, log_posted_movie, is_already_posted, init_db as init_pipeline_db
from transcript_processor_final import init_db as init_transcript_db

DB_PATH = "facebook_history.db"
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

# --- Load Environment Variables ---
def load_env():
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, val = line.strip().split("=", 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")

# Ensure environment variables are loaded first
load_env()
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

def get_fb_page_id():
    """Automatically queries the Meta Graph API to resolve the Page ID from the Page Access Token."""
    if not FB_PAGE_ACCESS_TOKEN:
        return None
    url = f"https://graph.facebook.com/v19.0/me?access_token={FB_PAGE_ACCESS_TOKEN}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            pid = response.json().get("id")
            print(f"[FB Setup] Successfully auto-resolved FB Page ID from token: {pid}")
            return pid
        else:
            print(f"[FB Setup] Failed to resolve Page ID: {response.text}")
    except Exception as e:
        print(f"[FB Setup] Error auto-resolving Page ID: {e}")
    return None

def search_tmdb_by_title(title):
    # Clean up title (remove year like "(2024)" if present)
    clean_title = re.sub(r'\s*\(\d{4}\)\s*', '', title).strip()
    url = f"https://api.themoviedb.org/3/search/movie?query={clean_title}&api_key={TMDB_API_TOKEN}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            results = response.json().get("results", [])
            if results:
                return results[0].get("id")
    except Exception as e:
        print(f"Error searching TMDB for '{title}': {e}")
    return None

def get_movie_from_queue():
    """Gets an unused movie from the database queue, validating against already posted movies."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Get all unused movies sorted by extraction date (oldest first)
        cursor.execute("SELECT id, title, source_video_url FROM transcript_movies WHERE unused = 1 ORDER BY extracted_at ASC")
        unused = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[Queue] DB Error fetching queue: {e}")
        unused = []
    finally:
        conn.close()

    for movie_id, title, source in unused:
        # Search TMDB to get the exact ID
        tmdb_id = search_tmdb_by_title(title)
        if not tmdb_id:
            print(f"[Queue] TMDB ID not found for '{title}', marking as used to clean up the queue.")
            mark_queue_as_used(movie_id)
            continue
            
        # Check if already posted
        if is_already_posted(tmdb_id):
            print(f"[Queue] '{title}' (TMDB: {tmdb_id}) was already posted previously, marking as used.")
            mark_queue_as_used(movie_id)
            continue
            
        # Found a valid unposted queue movie!
        return {
            "source": "queue",
            "queue_id": movie_id,
            "tmdb_id": tmdb_id,
            "title": title
        }
    return None

def mark_queue_as_used(queue_id):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("UPDATE transcript_movies SET unused = 0 WHERE id = ?", (queue_id,))
        conn.commit()
        print(f"[Queue] Marked queue item #{queue_id} as used.")
    except sqlite3.Error as e:
        print(f"[Queue] DB Error marking used: {e}")
    finally:
        conn.close()

def get_movie_from_api():
    """Gets a trending movie from Trakt API, picking randomly to avoid always selecting top 1."""
    from pipeline import fetch_trakt_trending
    # Fetch 30 trending movies to have a diverse pool
    trending = fetch_trakt_trending(limit=30)
    if not trending:
        print("[API] Could not fetch trending list from Trakt.")
        return None
        
    # Shuffle the list to cover other movies instead of sticking to top 1
    random.shuffle(trending)
    
    for item in trending:
        movie_meta = item.get("movie", {})
        tmdb_id = movie_meta.get("ids", {}).get("tmdb")
        title = movie_meta.get("title", "Unknown Title")
        
        if not tmdb_id:
            continue
            
        if is_already_posted(tmdb_id):
            print(f"[API] Skipping '{title}' (TMDB: {tmdb_id}) - already posted.")
            continue
            
        print(f"[API] Selected movie from API trends: '{title}' (TMDB: {tmdb_id})")
        return {
            "source": "api",
            "tmdb_id": tmdb_id,
            "title": title,
            "year": movie_meta.get("year"),
            "overview": movie_meta.get("overview")
        }
    return None

def upload_photo_to_facebook(image_url):
    """Uploads a photo to Facebook Page as unpublished and returns the photo ID."""
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
    payload = {
        "url": image_url,
        "published": "false",
        "access_token": FB_PAGE_ACCESS_TOKEN
    }
    try:
        response = requests.post(url, data=payload, timeout=20)
        if response.status_code == 200:
            pid = response.json().get("id")
            print(f"[FB] Successfully uploaded photo. ID: {pid}")
            return pid
        else:
            print(f"[FB] Failed to upload photo: {response.text}")
    except Exception as e:
        print(f"[FB] Error uploading photo: {e}")
    return None

def publish_facebook_post(message, photo_ids):
    """Publishes a multi-photo post on the Facebook Page using attached photo IDs."""
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed"
    
    # Format attached media list correctly for Facebook Graph API
    attached_media = [{"media_fbid": pid} for pid in photo_ids]
    
    payload = {
        "message": message,
        "attached_media": str(attached_media).replace("'", '"'),  # Valid JSON double quotes
        "access_token": FB_PAGE_ACCESS_TOKEN
    }
    try:
        response = requests.post(url, data=payload, timeout=20)
        if response.status_code == 200:
            return response.json().get("id")
        else:
            print(f"[FB] Failed to publish feed post: {response.text}")
    except Exception as e:
        print(f"[FB] Error publishing post: {e}")
    return None

def main():
    global FB_PAGE_ID
    
    # 1. Initialize databases
    init_pipeline_db()
    init_transcript_db()

    # Auto-resolve FB Page ID if not provided in environment
    if not FB_PAGE_ID:
        FB_PAGE_ID = get_fb_page_id()

    if not FB_PAGE_ID or not FB_PAGE_ACCESS_TOKEN:
        print("[Error] FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN environment variables not set. Exiting.")
        return
        
    print("[Pipeline] 🚀 Beginning auto-publish workflow...")
    
    # 2. Select the movie to post
    movie_data = get_movie_from_queue()
    
    if movie_data:
        print(f"[Pipeline] Found unused movie in queue: '{movie_data['title']}'")
        # Enrich with details
        details = fetch_tmdb_details(movie_data['tmdb_id'])
        movie_data['overview'] = details.get('overview') or "A remarkable film recommendation for tonight."
        movie_data['genres'] = details.get('genres', [])
        movie_data['poster_url'] = details.get('poster_url')
        movie_data['screenshot_urls'] = fetch_tmdb_screenshots(movie_data['tmdb_id'], count=5)
    else:
        print("[Pipeline] No unused movies in the queue. Fetching from Trakt API trends...")
        movie_data = get_movie_from_api()
        if not movie_data:
            print("[Pipeline] ❌ No unposted movies found anywhere (Queue or API trends). Aborting.")
            return
            
        # Enrich API movie details
        details = fetch_tmdb_details(movie_data['tmdb_id'])
        movie_data['poster_url'] = details.get('poster_url')
        movie_data['genres'] = details.get('genres', [])
        movie_data['screenshot_urls'] = fetch_tmdb_screenshots(movie_data['tmdb_id'], count=5)
        if not movie_data.get('overview'):
            movie_data['overview'] = details.get('overview') or "A trending must-watch movie."

    # Double check double-posting prevention
    if is_already_posted(movie_data['tmdb_id']):
        print(f"[Pipeline] Safety Check Failed: '{movie_data['title']}' was already posted. Aborting.")
        if movie_data.get('source') == 'queue':
            mark_queue_as_used(movie_data['queue_id'])
        return

    print(f"[Pipeline] Preparing multi-photo post for '{movie_data['title']}'...")
    
    # 3. Formulate message caption matching user style requirements
    genres_list = movie_data.get('genres', [])
    genres_str = ", ".join(genres_list) if genres_list else "N/A"
    
    message = (
        f"🎬 Film Recommendation: {movie_data['title']}\n"
        f"🏷️ Genre: {genres_str}\n\n"
        f"🍿 Summary:\n{movie_data['overview']}\n\n"
        f"#movies #movieslist #movietowatch #filmden #cinema #cinephile #mustwatch"
    )
    
    # 4. Upload photo assets to Facebook Page album (Poster first, then screenshots)
    photo_ids = []
    
    # Upload poster
    if movie_data.get('poster_url'):
        print(f"[FB] Uploading poster: {movie_data['poster_url']}")
        pid = upload_photo_to_facebook(movie_data['poster_url'])
        if pid:
            photo_ids.append(pid)
            
    # Upload widescreen screenshots
    for idx, url in enumerate(movie_data.get('screenshot_urls', [])):
        print(f"[FB] Uploading widescreen scene {idx+1}: {url}")
        pid = upload_photo_to_facebook(url)
        if pid:
            photo_ids.append(pid)
            
    if not photo_ids:
        print("[Error] ❌ No media assets could be successfully uploaded to Facebook. Aborting.")
        return
        
    # 5. Publish post on the page feed
    print(f"[FB] Publishing feed post with {len(photo_ids)} images...")
    post_id = publish_facebook_post(message, photo_ids)
    
    if post_id:
        print(f"[Success] 🎉 Post published successfully on Facebook Page! Post ID: {post_id}")
        
        # Log to posted history in SQLite
        log_posted_movie(movie_data['tmdb_id'], movie_data['title'])
        
        # Mark queue item as used if it came from the queue
        if movie_data.get('source') == 'queue':
            mark_queue_as_used(movie_data['queue_id'])
    else:
        print("[Error] ❌ Failed to publish multi-photo post to page feed.")

if __name__ == "__main__":
    main()
