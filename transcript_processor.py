import requests
import sqlite3
import re
import json
from typing import List, Dict, Any

# --- Configuration ---
YOUTUBE_TRANSCRIPTS_API_KEY = "ac6eab7af3mshb76f329520376abp1de914jsne60da10d035d"
YOUTUBE_TRANSCRIPTS_HOST = "youtube-transcripts.p.rapidapi.com"
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

# --- Movie Name Extraction Functions ---
def extract_movie_names_from_text(text: str) -> List[str]:
    """
    Extracts potential movie names from transcript text.
    This is a simplistic implementation - in practice you'd want to use NLP or check against a movie database.
    
    Args:
        text: Transcript text to analyze
        
    Returns:
        List of potential movie names found
    """
    # Convert to string if needed
    if not isinstance(text, str):
        text = str(text)
    
    movie_names = []
    
    # Pattern 1: Text in quotes (common for movie titles in discussions)
    quoted_pattern = r'["""][^""]+["""]'
    quoted_matches = re.findall(quoted_pattern, text)
    for match in quoted_matches:
        # Remove the quotes
        clean_match = match.strip('"""\'')
        if len(clean_match) > 1:  # Avoid single characters
            movie_names.append(clean_match)
    
    # Pattern 2: Look for title case phrases that might be movie titles
    # This is very simplistic - real implementation would be more sophisticated
    title_case_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b'
    title_matches = re.findall(title_case_pattern, text)
    for match in title_matches:
        # Filter out common non-movie phrases
        common_phrases = {
            'The', 'And', 'Or', 'But', 'In', 'On', 'At', 'To', 'For', 'Of', 'With', 'By',
            'Is', 'Are', 'Was', 'Were', 'Be', 'Been', 'Being', 'Have', 'Has', 'Had',
            'Do', 'Does', 'Did', 'Will', 'Would', 'Could', 'Should', 'May', 'Might', 'Must',
            'I', 'You', 'He', 'She', 'It', 'We', 'They', 'Me', 'Him', 'Her', 'Us', 'Them',
            'This', 'That', 'These', 'Those', 'My', 'Your', 'His', 'Her', 'Its', 'Our', 'Their'
        }
        words = match.split()
        if not all(word in common_phrases for word in words):
            movie_names.append(match)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_movies = []
    for movie in movie_names:
        if movie not in seen:
            seen.add(movie)
            unique_movies.append(movie)
    
    return unique_movies

def process_transcript_for_movies(transcript_data: Dict[str, Any]) -> List[str]:
    """
    Processes transcript data to extract movie names.
    
    Args:
        transcript_data: The transcript data from YouTube Transcripts API
        
    Returns:
        List of movie names found in the transcript
    """
    if not transcript_data or 'content' not in transcript_data:
        return []
    
    # Extract all text from transcript segments
    full_text = ""
    for segment in transcript_data.get('content', []):
        if isinstance(segment, dict) and 'text' in segment:
            full_text += " " + str(segment['text'])
    
    # For debugging, let's see what text we're working with (handle encoding issues)
    try:
        debug_text = full_text[:500]
        print(f"[Transcript Debug] Full text extracted ({len(full_text)} chars):")
        print(debug_text + ("..." if len(full_text) > 500 else ""))
    except UnicodeEncodeError:
        # If we can't print the text due to encoding, just show the length
        print(f"[Transcript Debug] Full text extracted ({len(full_text)} chars) - contains non-printable characters")
    
    # Extract movie names from the combined text
    movie_names = extract_movie_names_from_text(full_text)
    return movie_names

# --- Main Processing Function ---
def process_video_transcript(video_url: str) -> List[str]:
    """
    Main function to process a YouTube video: get transcript, extract movie names, save to DB.
    
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
    
    # Step 2: Extract movie names
    movie_names = process_transcript_for_movies(transcript_data)
    if not movie_names:
        print("[Transcript] No movie names found in transcript")
        return []
    
    print(f"[Transcript] Found {len(movie_names)} potential movie names: {movie_names}")
    
    # Step 3: Save to database
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