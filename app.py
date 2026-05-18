import streamlit as st
import sqlite3
import requests
import re
import time
from transcript_processor_final import process_video_transcript, init_db as init_transcript_db
from pipeline import fetch_tmdb_details, fetch_tmdb_screenshots, TMDB_API_TOKEN, log_posted_movie, init_db as init_pipeline_db

DB_PATH = "facebook_history.db"

# --- Database Helper Functions ---
def get_unused_movies():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, title, source_video_url, extracted_at FROM transcript_movies WHERE unused = 1 ORDER BY extracted_at DESC")
        rows = cursor.fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return rows

def mark_movie_as_used(movie_id):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("UPDATE transcript_movies SET unused = 0 WHERE id = ?", (movie_id,))
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Failed to update movie: {e}")
    finally:
        conn.close()

def clean_youtube_url(url):
    url = url.strip()
    # Strip sharing params from youtu.be links
    if "youtu.be/" in url and "?" in url:
        url = url.split("?")[0]
    return url

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
        st.error(f"Error searching TMDB: {e}")
    return None

# --- UI Setup ---
st.set_page_config(page_title="Filmden AI Content Engine", layout="wide")

# Inject Custom Sleek CSS for Dark Mode & Premium Aesthetics
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');
    
    /* Global Styles */
    .stApp {
        background: linear-gradient(135deg, #090d16 0%, #111827 50%, #1e1b4b 100%);
        color: #f8fafc;
        font-family: 'Outfit', sans-serif;
    }
    
    h1, h2, h3, h4, h5, h6, p, span, label {
        font-family: 'Outfit', sans-serif !important;
    }
    
    /* Glassmorphism Panels */
    .glass-panel {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 24px;
        padding: 30px;
        margin-bottom: 25px;
        backdrop-filter: blur(20px);
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
    }
    
    /* Interactive Buttons */
    .stButton>button {
        background: linear-gradient(90deg, #6366f1 0%, #4f46e5 100%);
        color: white !important;
        border: none !important;
        padding: 12px 28px !important;
        border-radius: 14px !important;
        font-weight: 600 !important;
        letter-spacing: 0.5px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        box-shadow: 0 4px 15px rgba(99, 102, 241, 0.35) !important;
    }
    
    .stButton>button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 25px rgba(99, 102, 241, 0.55) !important;
        background: linear-gradient(90deg, #4f46e5 0%, #4338ca 100%) !important;
    }
    
    .stButton>button:active {
        transform: translateY(1px) !important;
    }
    
    /* Secondary/Reset Buttons */
    .stButton>button[kind="secondary"] {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: #e2e8f0 !important;
        box-shadow: none !important;
    }
    
    .stButton>button[kind="secondary"]:hover {
        background: rgba(255, 255, 255, 0.1) !important;
        border-color: rgba(255, 255, 255, 0.2) !important;
        transform: translateY(-1px) !important;
    }

    /* Horizontal Scrollable Carousel Container */
    .carousel-container {
        display: flex;
        overflow-x: auto;
        gap: 20px;
        padding: 20px 10px;
        scroll-behavior: smooth;
        border-radius: 16px;
        background: rgba(0, 0, 0, 0.2);
        margin: 15px 0;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    .carousel-container::-webkit-scrollbar {
        height: 8px;
    }
    
    .carousel-container::-webkit-scrollbar-track {
        background: rgba(255, 255, 255, 0.02);
        border-radius: 10px;
    }
    
    .carousel-container::-webkit-scrollbar-thumb {
        background: rgba(99, 102, 241, 0.4);
        border-radius: 10px;
    }
    
    .carousel-container::-webkit-scrollbar-thumb:hover {
        background: rgba(99, 102, 241, 0.6);
    }
    
    /* Movie Cards */
    .movie-card {
        flex: 0 0 240px;
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 20px;
        padding: 15px;
        text-align: center;
        backdrop-filter: blur(10px);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    .movie-card:hover {
        transform: translateY(-6px);
        border-color: rgba(99, 102, 241, 0.45);
        box-shadow: 0 12px 30px rgba(99, 102, 241, 0.15);
        background: rgba(255, 255, 255, 0.05);
    }
    
    .movie-card img {
        width: 100%;
        height: 320px;
        object-fit: cover;
        border-radius: 14px;
        margin-bottom: 12px;
        box-shadow: 0 5px 15px rgba(0,0,0,0.3);
    }
    
    .movie-card-title {
        font-size: 1rem;
        font-weight: 700;
        color: #f8fafc;
        margin-top: 5px;
        letter-spacing: 0.3px;
    }
    
    .movie-card-subtitle {
        font-size: 0.8rem;
        color: #818cf8;
        margin-top: 2px;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

# Ensure database tables exist
init_transcript_db()
init_pipeline_db()

# App Header
st.markdown("""
<div style='text-align: center; padding: 20px 0 40px 0;'>
    <h1 style='font-size: 3rem; font-weight: 800; background: linear-gradient(90deg, #818cf8 0%, #c084fc 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>
        🎬 Filmden AI Content Engine
    </h1>
    <p style='color: #94a3b8; font-size: 1.2rem; margin-top: 10px; font-weight: 400;'>
        Automate your social media pipeline: extract movies, fetch widescreen visuals, and preview interactive Facebook Carousel posts.
    </p>
</div>
""", unsafe_allow_html=True)

# Main Navigation Tabs
tab1, tab2 = st.tabs(["🎲 Trakt & TMDB Recommendation", "📺 Extract from YouTube Transcript"])

# =====================================================================
# TAB 1: Trakt & TMDB Recommendation
# =====================================================================
with tab1:
    st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
    st.header("Get Fresh Trend Suggestion")
    st.write("Fetch high-engagement trending films directly from Trakt & TMDB APIs, ensuring no duplicates from your posting history.")
    
    if st.button("Fetch Fresh Recommendation", key="fetch_trakt_btn"):
        with st.spinner("Fetching trending movies and building Facebook Carousel assets..."):
            # Import recommendation engine directly
            from pipeline import get_fresh_recommendation
            movie = get_fresh_recommendation()
            
            if movie:
                st.session_state['trakt_movie'] = movie
                st.success("Successfully fetched fresh recommendation!")
            else:
                st.warning("All currently trending movies have already been posted! Check your history.")
    
    # Display the recommendation if loaded in session state
    if 'trakt_movie' in st.session_state:
        movie = st.session_state['trakt_movie']
        st.divider()
        
        st.markdown(f"### 📣 Suggested Film: **{movie['title']} ({movie.get('year', 'N/A')})**")
        st.write(f"**TMDB ID:** `{movie['tmdb_id']}`")
        
        # Display Overview
        st.markdown(f"**Generated Caption / Summary:**")
        st.info(movie['overview'])
        
        # Build Horizontal Carousel
        st.write("**Facebook Carousel Post Preview (Horizontal Scroll):**")
        images_to_show = []
        if movie.get('poster_url'):
            images_to_show.append((movie['poster_url'], "Poster Card"))
        for idx, url in enumerate(movie.get('screenshot_urls', [])):
            images_to_show.append((url, f"Scene Card {idx+1}"))
            
        if images_to_show:
            carousel_html = '<div class="carousel-container">'
            for img_url, card_label in images_to_show:
                carousel_html += f"""
                <div class="movie-card">
                    <img src="{img_url}" alt="{card_label}" />
                    <div class="movie-card-title">{card_label}</div>
                    <div class="movie-card-subtitle">{movie['title']}</div>
                </div>
                """
            carousel_html += '</div>'
            st.markdown(carousel_html, unsafe_allow_html=True)
        else:
            st.warning("No images available for this movie.")
            
        st.write("")
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("✅ Mark as Posted", key="post_trakt_btn", type="primary"):
                log_posted_movie(movie['tmdb_id'], movie['title'])
                st.success(f"Logged '{movie['title']}' to history. Will not suggest again!")
                del st.session_state['trakt_movie']
                time.sleep(1.5)
                st.rerun()
        with col2:
            if st.button("🔄 Suggest Another", key="skip_trakt_btn"):
                del st.session_state['trakt_movie']
                st.rerun()
                
    st.markdown('</div>', unsafe_allow_html=True)


# =====================================================================
# TAB 2: YouTube Video Transcript Extractor
# =====================================================================
with tab2:
    # 1. Video Processing Section
    st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
    st.header("Extract Movies from YouTube URL")
    st.write("Input a YouTube video URL (e.g. movie reviews, recap lists, or countdowns) to parse its transcript using AI.")
    
    url_input = st.text_input("YouTube Video URL", placeholder="https://www.youtube.com/watch?v=...", key="yt_url_field")
    
    if st.button("Process & Run AI Extractor", key="run_yt_extractor_btn", type="primary"):
        if url_input:
            cleaned_url = clean_youtube_url(url_input)
            with st.spinner("Fetching transcript & running AI extraction... this may take up to a minute."):
                # Run the extractor
                movies = process_video_transcript(cleaned_url)
                if movies:
                    st.success(f"Successfully extracted {len(movies)} movies and saved them to your unused library!")
                    # Display simple list
                    for idx, movie in enumerate(movies, 1):
                        st.write(f"**{idx}.** {movie}")
                else:
                    st.error("No movies found or transcript extraction failed. Make sure the video has transcripts enabled.")
        else:
            st.warning("Please enter a YouTube video URL first.")
    st.markdown('</div>', unsafe_allow_html=True)

    # 2. Movie Queue & Posting Section
    st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
    st.header("Manage Extracted Movie Queue")
    st.write("Generate Facebook carousel posts from the library of movies you've extracted from transcripts.")
    
    # Load unused movies
    unused_movies = get_unused_movies()
    
    if unused_movies:
        st.write(f"There are currently **{len(unused_movies)}** unused movies in your queue.")
        
        # Format for select box
        movie_options = {row[0]: f"{row[1]} (Found via {row[2]})" for row in unused_movies}
        
        selected_id = st.selectbox(
            "Select an extracted movie to prepare a Facebook post",
            options=list(movie_options.keys()),
            format_func=lambda x: movie_options[x]
        )
        
        # Get selected movie title
        selected_movie_title = next(row[1] for row in unused_movies if row[0] == selected_id)
        
        if st.button("Generate FB Post Preview", key="gen_preview_btn"):
            st.session_state['selected_queue_id'] = selected_id
            st.session_state['selected_queue_title'] = selected_movie_title
            
        # Display the carousel preview from the queue
        if 'selected_queue_id' in st.session_state and st.session_state['selected_queue_id'] == selected_id:
            title = st.session_state['selected_queue_title']
            
            with st.spinner(f"Searching TMDB for details of '{title}'..."):
                tmdb_id = search_tmdb_by_title(title)
                
            if tmdb_id:
                with st.spinner("Fetching full poster and widescreen screenshots..."):
                    details = fetch_tmdb_details(tmdb_id)
                    screenshots = fetch_tmdb_screenshots(tmdb_id, count=5)
                    
                st.divider()
                st.markdown(f"### 📣 Preparing Carousel: **{title}**")
                
                # Display Overview
                st.markdown(f"**Caption / Summary:**")
                st.info(details['overview'] if details['overview'] else "No overview available on TMDB.")
                
                # Render Horizontal Carousel
                st.write("**Facebook Carousel Post Preview (Horizontal Scroll):**")
                images_to_show = []
                if details.get('poster_url'):
                    images_to_show.append((details['poster_url'], "Poster Card"))
                for idx, url in enumerate(screenshots):
                    images_to_show.append((url, f"Scene Card {idx+1}"))
                    
                if images_to_show:
                    carousel_html = '<div class="carousel-container">'
                    for img_url, card_label in images_to_show:
                        carousel_html += f"""
                        <div class="movie-card">
                            <img src="{img_url}" alt="{card_label}" />
                            <div class="movie-card-title">{card_label}</div>
                            <div class="movie-card-subtitle">{title}</div>
                        </div>
                        """
                    carousel_html += '</div>'
                    st.markdown(carousel_html, unsafe_allow_html=True)
                else:
                    st.warning("No images available on TMDB for this movie.")
                
                st.write("")
                col1, col2 = st.columns([1, 4])
                with col1:
                    if st.button("✅ Mark as Posted & Log", key="post_queue_btn", type="primary"):
                        # Mark as used in queue
                        mark_movie_as_used(selected_id)
                        # Log to posted history
                        log_posted_movie(tmdb_id, title)
                        st.success(f"Successfully marked '{title}' as posted!")
                        # Clean session state
                        if 'selected_queue_id' in st.session_state:
                            del st.session_state['selected_queue_id']
                        time.sleep(1.5)
                        st.rerun()
                with col2:
                    if st.button("Skip & Mark as Used Anyway", key="skip_queue_btn"):
                        mark_movie_as_used(selected_id)
                        st.success(f"Skipped and marked '{title}' as used.")
                        if 'selected_queue_id' in st.session_state:
                            del st.session_state['selected_queue_id']
                        time.sleep(1.5)
                        st.rerun()
            else:
                st.error(f"Could not locate '{title}' on TMDB. Check the title spelling or enter details manually.")
                if st.button("Skip & Mark as Used Anyway (Spelling Issue)", key="skip_error_btn"):
                    mark_movie_as_used(selected_id)
                    st.success("Marked as used.")
                    if 'selected_queue_id' in st.session_state:
                        del st.session_state['selected_queue_id']
                    time.sleep(1.5)
                    st.rerun()
    else:
        st.info("Your extracted movie queue is empty. Run the YouTube AI Extractor above to populate it!")
    st.markdown('</div>', unsafe_allow_html=True)
