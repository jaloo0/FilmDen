import requests
import sqlite3
import json
import re
from typing import List, Dict, Any

# --- Configuration ---
YOUTUBE_TRANSCRIPTS_API_KEY = "ac6eab7af3mshb76f329520376abp1de914jsne60da10d035d"
YOUTUBE_TRANSCRIPTS_HOST = "youtube-transcripts.p.rapidapi.com"
OPENROUTER_API_KEY = "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"
OPENROUTER_HOST = "openrouter.ai"
DB_PATH = "facebook_history.db"  # Reuse same database as pipeline.py

# --- Database Functions ---
def init_db():
    """Creates the SQLite table for tracking movies from transcripts if it doesn't exist."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcript_movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                tmdb_id INTEGER,  -- Optional TMDB ID if we can match it
                source_video_url TEXT,  -- The YouTube video URL where we found this
                extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                unused BOOLEAN DEFAULT 1  -- 1 = unused, 0 = used/processed
            )
        """)
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[DB] Init failed: {e}")
        raise

def save_movie_from_transcript(title: str, source_video_url: str, tmdb_id: int = None):
    """Saves a movie extracted from transcript to the database with unused tag."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO transcript_movies (title, tmdb_id, source_video_url, unused)
            VALUES (?, ?, ?, 1)
            """,
            (title, tmdb_id, source_video_url)
        )
        conn.commit()
        conn.close()
        print(f"[DB] Saved movie from transcript: {title} (unused)")
    except sqlite3.Error as e:
        print(f"[DB] Failed to save movie from transcript: {e}")

# --- YouTube Transcript Functions ---
def get_youtube_transcript(video_url: str, video_id: str = None, chunk_size: int = 500, lang: str = "en") -> Dict[str, Any]:
    """
    Fetches transcript from YouTube video using the RapidAPI YouTube Transcripts API.
    
    Args:
        video_url: The YouTube video URL
        video_id: Optional YouTube video ID (will be extracted from URL if not provided)
        chunk_size: Size of chunks for transcript (default 500)
        lang: Language code for transcript (default "en")
    
    Returns:
        Dictionary containing transcript data or empty dict on failure
    """
    # Extract video ID from URL if not provided
    if not video_id:
        # Handle various YouTube URL formats
        patterns = [
            r'youtube\.com\/watch\?v=([^&]+)',
            r'youtu\.be\/([^&]+)',
            r'youtube\.com\/embed\/([^&]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, video_url)
            if match:
                video_id = match.group(1)
                break
    
    if not video_id:
        print("[Transcript] Could not extract video ID from URL")
        return {}
    
    # Prepare API request
    url = f"https://{YOUTUBE_TRANSCRIPTS_HOST}/youtube/transcript"
    params = {
        "url": video_url,
        "videoId": video_id,
        "chunkSize": chunk_size,
        "text": "false",  # We want structured data, not plain text
        "lang": lang
    }
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": YOUTUBE_TRANSCRIPTS_HOST,
        "x-rapidapi-key": YOUTUBE_TRANSCRIPTS_API_KEY
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[Transcript] API request failed: {e}")
        return {}
    except json.JSONDecodeError as e:
        print(f"[Transcript] Failed to parse JSON response: {e}")
        return {}

# --- OpenRouter AI Functions ---
def extract_movies_with_ai(transcript_text: str) -> List[str]:
    """
    Uses OpenRouter AI to extract movie names from transcript text.
    
    Args:
        transcript_text: The full transcript text to analyze
        
    Returns:
        List of movie names found in the transcript
    """
    if not transcript_text or len(transcript_text.strip()) == 0:
        return []
    
    # Prepare the prompt for the AI
    prompt = f"""
    Analyze the following transcript text and extract all movie titles mentioned.
    Return only a JSON array of movie titles, nothing else.
    If no movies are mentioned, return an empty array [].
    
    Transcript text:
    {transcript_text[:8000]}  # Limit to first 8000 chars to avoid token limits
    """
    
    # Prepare API request to OpenRouter
    url = f"https://{OPENROUTER_HOST}/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.1,  # Low temperature for more consistent outputs
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        # Extract the AI's response
        ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')
        
        # Try to parse as JSON
        try:
            movie_list = json.loads(ai_response)
            if isinstance(movie_list, list):
                # Filter out empty strings and clean up
                movies = [str(movie).strip() for movie in movie_list if str(movie).strip()]
                return movies
            else:
                print(f"[AI] Unexpected response format: {ai_response}")
                return []
        except json.JSONDecodeError:
            print(f"[AI] Failed to parse JSON response: {ai_response}")
            # Fallback: try to extract movie names manually from the response
            # Look for patterns like ["Movie1", "Movie2"] or just list items
            quoted_matches = re.findall(r'["""]([^""]+)["""]', ai_response)
            if quoted_matches:
                return [match.strip() for match in quoted_matches if match.strip()]
            return []
            
    except requests.exceptions.RequestException as e:
        print(f"[AI] API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[AI] Response status: {e.response.status_code}")
            print(f"[AI] Response text: {e.response.text}")
        return {}
    except Exception as e:
        print(f"[AI] Unexpected error: {e}")
        return []

# --- Main Processing Function ---
def process_video_transcript(video_url: str) -> List[str]:
    """
    Main function to process a YouTube video: get transcript, extract movie names using AI, save to DB.
    
    Args:
        video_url: YouTube video URL to process
        
    Returns:
        List of movie names that were extracted and saved
    """
    print(f"[Transcript] Processing video: {video_url}")
    
    # Step 1: Get transcript
    transcript_data = get_youtube_transcript(video_url)
    if not transcript_data:
        print("[Transcript] Failed to get transcript")
        return []
    
    # Step 2: Extract all text from transcript segments
    full_text = ""
    for segment in transcript_data.get('content', []):
        if isinstance(segment, dict) and 'text' in segment:
            full_text += " " + str(segment['text'])
    
    if not full_text.strip():
        print("[Transcript] No text found in transcript")
        return []
    
    print(f"[Transcript] Extracted {len(full_text)} characters of text")
    
    # Step 3: Use AI to extract movie names
    movie_names = extract_movies_with_ai(full_text)
    if not movie_names:
        print("[Transcript] No movie names found in transcript via AI")
        return []
    
    print(f"[Transcript] AI found {len(movie_names)} potential movie names: {movie_names}")
    
    # Step 4: Save to database
    saved_count = 0
    for movie_name in movie_names:
        save_movie_from_transcript(movie_name, video_url)
        saved_count += 1
    
    print(f"[Transcript] Saved {saved_count} movies to database with unused tag")
    return movie_names

# --- Entry Point ---
if __name__ == "__main__":
    # Initialize database
    init_db()
    
    # Example usage - in practice, you'd get this from user input or arguments
    import sys
    
    if len(sys.argv) > 1:
        video_url = sys.argv[1]
    else:
        # Default to a test video if none provided
        video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rick Roll
        print(f"[Transcript] No video URL provided, using default: {video_url}")
    
    # Process the video
    movies = process_video_transcript(video_url)
    
    if movies:
        print(f"\n[Transcript] Successfully processed video and found {len(movies)} movie names:")
        for i, movie in enumerate(movies, 1):
            print(f"  {i}. {movie}")
    else:
        print("\n[Transcript] No movie names were extracted from the video.")