import requests
import sqlite3
import json
import time
import os

# AniList GraphQL API endpoint
ANILIST_API_URL = "https://graphql.anilist.co"

# GraphQL query to fetch global anime data using pagination
GLOBAL_QUERY = '''
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      total
      currentPage
      lastPage
      hasNextPage
      perPage
    }
    media(type: ANIME) {
      id
      title {
        romaji
        english
        native
      }
      episodes
      genres
      tags {
        name
        rank  # Tag relevance ranking (out of 100) if available
      }
      averageScore
      popularity
      description(asHtml: false)
      rankings {
        rank
        type
        context
      }
    }
  }
}
'''

CHECKPOINT_FILE = "checkpoint.txt"

def init_global_db(db_path="anilist_global.db"):
    """
    Initializes a separate SQLite database for global AniList data with extended fields.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_media (
            id INTEGER PRIMARY KEY,
            title_romaji TEXT,
            title_english TEXT,
            title_native TEXT,
            episodes INTEGER,
            description TEXT,
            genres TEXT,
            tags TEXT,
            average_score INTEGER,
            popularity INTEGER,
            rankings TEXT
        )
    ''')
    conn.commit()
    return conn

def fetch_global_data(page, per_page=50):
    """
    Fetches one page of global anime data from AniList.
    """
    variables = {
        "page": page,
        "perPage": per_page
    }
    response = requests.post(
        ANILIST_API_URL,
        json={'query': GLOBAL_QUERY, 'variables': variables},
        headers={'Content-Type': 'application/json'}
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Global query failed with status code {response.status_code}: {response.text}")

def store_global_data(data, conn):
    """
    Parses the global AniList data and stores it in the database with additional fields.
    Uses an upsert (ON CONFLICT) so that if a record already exists, it will be updated.
    """
    cursor = conn.cursor()
    page_data = data.get('data', {}).get('Page', {})
    media_list = page_data.get('media', [])
    
    for media in media_list:
        media_id = media.get('id')
        title = media.get('title', {})
        title_romaji = title.get('romaji')
        title_english = title.get('english')
        title_native = title.get('native')
        episodes = media.get('episodes')
        description = media.get('description')
        genres = media.get('genres', [])
        average_score = media.get('averageScore')
        popularity = media.get('popularity')
        rankings = media.get('rankings', [])
        
        # Store full tag info (name and rank) as JSON for flexibility
        tags_list = media.get('tags', [])
        tags_json = json.dumps(tags_list)
        genres_json = json.dumps(genres)
        rankings_json = json.dumps(rankings)
        
        cursor.execute('''
            INSERT INTO global_media 
            (id, title_romaji, title_english, title_native, episodes, description, genres, tags, average_score, popularity, rankings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title_romaji=excluded.title_romaji,
                title_english=excluded.title_english,
                title_native=excluded.title_native,
                episodes=excluded.episodes,
                description=excluded.description,
                genres=excluded.genres,
                tags=excluded.tags,
                average_score=excluded.average_score,
                popularity=excluded.popularity,
                rankings=excluded.rankings
        ''', (
            media_id, title_romaji, title_english, title_native, episodes, description,
            genres_json, tags_json, average_score, popularity, rankings_json
        ))
    
    conn.commit()
    return page_data.get('pageInfo', {})

def read_checkpoint():
    """
    Reads the checkpoint file to determine which page to start from.
    """
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return 1
    return 1

def write_checkpoint(page):
    """
    Writes the current page number to the checkpoint file.
    """
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(str(page))

def main():
    conn = init_global_db()
    per_page = 50
    # Start from the checkpoint if available; otherwise, start at page 1.
    current_page = read_checkpoint()

    while True:
        try:
            print(f"Fetching page {current_page}...")
            data = fetch_global_data(current_page, per_page)
            page_info = store_global_data(data, conn)
            print(f"Stored page {current_page} of {page_info.get('lastPage')}.")
            
            # Write checkpoint after a successful page fetch and store.
            write_checkpoint(current_page)
            
            if page_info.get('hasNextPage'):
                current_page += 1
                # Sleep a bit to avoid rate limits; adjust the duration as needed.
                time.sleep(1)
            else:
                print("Global data ingestion completed!")
                # Optionally, remove the checkpoint file if ingestion is complete.
                if os.path.exists(CHECKPOINT_FILE):
                    os.remove(CHECKPOINT_FILE)
                break

        except Exception as e:
            print(f"Error encountered on page {current_page}: {e}")
            print("Waiting for 60 seconds before retrying...")
            time.sleep(60)
            # The checkpoint remains so that you resume from the failed page.
    
    conn.close()

if __name__ == '__main__':
    main()