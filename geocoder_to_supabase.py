# geocoder_to_supabase.py
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import json
import os
import hashlib
import time
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# Setup Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Supabase Setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Known Indian city coordinates ──
CITY_COORDS = {
    "delhi":      (28.6139, 77.2090),
    "mumbai":     (19.0760, 72.8777),
    "kolkata":    (22.5726, 88.3639),
    "bengaluru":  (12.9716, 77.5946),
    "hyderabad":  (17.3850, 78.4867),
    "chennai":    (13.0827, 80.2707),
    "thane":      (19.2183, 72.9781),
    "pune":       (18.5204, 73.8567),
    "nagpur":     (21.1458, 79.0882),
    "ahmedabad":  (23.0225, 72.5714),
    "jaipur":     (26.9124, 75.7873),
    "lucknow":    (26.8467, 80.9462),
    "patna":      (25.5941, 85.1376),
    "surat":      (21.1702, 72.8311),
    "agra":       (27.1767, 78.0081),
    "bhopal":     (23.2599, 77.4126),
    "indore":     (22.7196, 75.8577),
    "chandigarh": (30.7333, 76.7794),
    "goa":        (15.2993, 74.1240),
    "kochi":      (9.9312,  76.2673),
    "guwahati":   (26.1445, 91.7362),
    "bhubaneswar":(20.2961, 85.8245),
    "noida":      (28.5355, 77.3910),
    "gurugram":   (28.4595, 77.0266),
}

def geocode_with_llm(city, local_area, state):
    model = genai.GenerativeModel("gemini-1.5-flash")
    location_str = f"{local_area}, {city}, {state}" if local_area else f"{city}, {state}"
    prompt = f"Return ONLY a JSON object with lat/lng for: {location_str}. Format: {{\"lat\": 0.0, \"lng\": 0.0}}"
    
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        coords = json.loads(response.text)
        return (coords["lat"], coords["lng"])
    except:
        return None

def get_row_hash(row):
    s = f"{row.get('date', '')}_{row.get('summary', '')}"
    return hashlib.md5(s.encode('utf-8')).hexdigest()

if __name__ == "__main__":
    print("🚀 Starting Geocoder to Supabase...")
    
    # Read Google Sheet
    creds = Credentials.from_service_account_file("service_account.json", scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    rows = gc.open("India Crime Data 2026").sheet1.get_all_records()

    new_incidents = []
    geocodes_done = 0
    MAX_GEOCODES = 20

    for raw_row in rows:
        row = {str(k).lower().replace(" ", "_"): v for k, v in raw_row.items()}
        row_hash = get_row_hash(row)
        
        # Check if already exists in Supabase
        exists = supabase.table("crime_data").select("id").eq("hash", row_hash).execute()
        if exists.data:
            continue

        city = row.get("city", "")
        local_area = row.get("local_area", "")
        state = row.get("state", "")

        if not city: continue

        coords = CITY_COORDS.get(city.lower())
        if not coords and geocodes_done < MAX_GEOCODES:
            print(f"Geocoding {city}...")
            coords = geocode_with_llm(city, local_area, state)
            geocodes_done += 1
            time.sleep(2)

        if coords:
            data = {
                "hash": row_hash,
                "incident_date": row.get("date"),
                "category": row.get("category"),
                "title": row.get("title", "Serious Crime Incident"),
                "description": row.get("summary"),
                "city": city,
                "state": state,
                "severity": int(row.get("severity", 5)),
                "victim_count": int(row.get("victim_count", 1)),
                "source": row.get("source", "News Scraper"),
                "latitude": coords[0],
                "longitude": coords[1],
                "created_at": datetime.now().isoformat()
            }
            new_incidents.append(data)

    if new_incidents:
        print(f"Pushing {len(new_incidents)} records to Supabase...")
        supabase.table("crime_incidents").insert(new_incidents).execute()
        print("✅ Done.")
    else:
        print("No new records to push.")
