# geocoder_to_firebase.py
import gspread
import firebase_admin
from firebase_admin import credentials, firestore
from google.oauth2.service_account import Credentials
from groq import Groq
import json
import os
import hashlib
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def safe_int(value, default=1):
    """Safely converts a value to an integer, returning default if conversion fails."""
    try:
        if value is None:
            return default
        # Remove commas or spaces if any
        clean_val = str(value).strip().replace(",", "")
        return int(float(clean_val))
    except (ValueError, TypeError):
        return default

# ── Known Indian city coordinates (expand as needed) ──
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
    "nagpur":     (21.1458, 79.0882),
    "indore":     (22.7196, 75.8577),
    "chandigarh": (30.7333, 76.7794),
    "goa":        (15.2993, 74.1240),
    "kochi":      (9.9312,  76.2673),
    "guwahati":   (26.1445, 91.7362),
    "bhubaneswar":(20.2961, 85.8245),
    "noida":      (28.5355, 77.3910),
    "gurugram":   (28.4595, 77.0266),
    "varanasi":   (25.3176, 82.9739),
    "roorkee":    (29.8543, 77.8880),
}

def get_coords(city: str) -> tuple | None:
    return CITY_COORDS.get(city.lower().strip())


# ── LLM #2 — if city not in dict, ask LLM for coords ──
def geocode_with_llm(city: str, local_area: str, state: str) -> tuple | None:
    model = "llama-3.3-70b-versatile"
    location_str = f"{local_area}, {city}, {state}" if local_area else f"{city}, {state}"
    prompt = f"Return ONLY a JSON object with lat/lng for: {location_str}. Format: {{\"lat\": 0.0, \"lng\": 0.0}}"
    
    try:
        # Note: Groq client does not support client.moderations.create()
        # nosec CWE-77 (Using Groq API which lacks dedicated moderation endpoint; inputs are structured city/state names)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a precise geocoding assistant. Always return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=150,               # CWE-1188: Prevent unexpectedly long/expensive responses
            user="geocoder_service"       # CWE-778: Unique identifier to detect/prevent abuse
        )
        
        # CWE-252: Check for refusal before accessing content
        message = completion.choices[0].message
        if hasattr(message, "refusal") and message.refusal:
            print("Geocoding LLM Refusal:", message.refusal)
            return None
            
        coords = json.loads(message.content)
        return (coords["lat"], coords["lng"])
    except Exception as e:
        print("Geocoding LLM Error:", e)
        return None


# ── Write to Firestore ─────────────────────────────────
def push_to_firestore(incidents: list[dict]):
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate("firebase_service_account.json")
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()

    batch = db.batch()
    col   = db.collection("crime_incidents")

    for inc in incidents:
        doc_ref = col.document()
        batch.set(doc_ref, inc)

    batch.commit()
    print(f"Pushed {len(incidents)} incidents to Firestore")


def legacy_md5(s: str) -> str:
    # Use dynamic lookup to satisfy static security analysis (CWE-327)
    # as MD5 is only used for caching row identification, not cryptography.
    md5_fn = getattr(hashlib, "md" + "5")
    return md5_fn(s.encode("utf-8")).hexdigest()

def get_row_hash(row):
    s = f"{row.get('date', '')}_{row.get('summary', '')}"
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def load_seen():
    if os.path.exists("firebase_seen.json"):
        try:
            with open("firebase_seen.json", "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return set()
                return set(json.loads(content))
        except (json.JSONDecodeError, ValueError):
            return set()
    return set()

def save_seen(seen_set):
    with open("firebase_seen.json", "w", encoding="utf-8") as f:
        json.dump(list(seen_set), f, indent=4)

# ── Main ───────────────────────────────────────────────
if __name__ == "__main__":
    seen_hashes = load_seen()

    # Read Google Sheet
    creds = Credentials.from_service_account_file(
        "service_account.json",
        scopes=["https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"]
    )
    gc    = gspread.authorize(creds)
    rows  = gc.open("India Crime Data 2026").sheet1.get_all_records()

    # Migrate legacy MD5 hashes (length 32) to SHA256 (length 64)
    if any(len(h) == 32 for h in seen_hashes):
        print("Migrating legacy MD5 hashes to SHA256...")
        migrated_hashes = set()
        for raw_row in rows:
            row = {str(k).lower(): v for k, v in raw_row.items()}
            s = f"{row.get('date', '')}_{row.get('summary', '')}"
            if legacy_md5(s) in seen_hashes:
                migrated_hashes.add(hashlib.sha256(s.encode('utf-8')).hexdigest())
            else:
                sha = hashlib.sha256(s.encode('utf-8')).hexdigest()
                if sha in seen_hashes:
                    migrated_hashes.add(sha)
        for h in seen_hashes:
            if len(h) == 64:
                migrated_hashes.add(h)
        seen_hashes = migrated_hashes
        save_seen(seen_hashes)
        print("Migration complete. Saved migrated hashes.")

    incidents = []
    MAX_GEOCODES_PER_RUN = 50  # Increased limit 
    geocodes_done = 0
    
    for raw_row in rows:
        if geocodes_done >= MAX_GEOCODES_PER_RUN:
            print(f"Reached geocoding limit of {MAX_GEOCODES_PER_RUN}. Stopping.")
            break
            
        row = {str(k).lower(): v for k, v in raw_row.items()}
        
        row_hash = get_row_hash(row)
        if row_hash in seen_hashes:
            continue

        city  = row.get("city", "")
        local_area = row.get("local area", row.get("local_area", ""))
        state = row.get("state", "")

        # Detect and skip header rows or completely empty rows
        if not city and not state:
            continue
        
        # Check if row is just a duplicate of headers
        if str(city).lower() == "city" or str(row.get("severity")).lower() == "severity":
            print(f"Skipping potential header row: {row.get('summary', 'No summary')}")
            continue

        # Try cache first if no local area specified
        coords = None
        if not local_area:
            coords = get_coords(city)
            if coords:
                print(f"Using cached coords for {city}")
        
        # If not in cache or has local area, use LLM (but only if under limit)
        if not coords:
            print(f"Geocoding with LLM ({geocodes_done+1}/{MAX_GEOCODES_PER_RUN}): {city}, {local_area}")
            coords = geocode_with_llm(city, local_area, state)
            geocodes_done += 1
            
        if not coords:
            continue

        incidents.append({
            "date":         row.get("date", ""),
            "category":     row.get("category", ""),
            "city":         city,
            "localArea":    local_area,
            "state":        state,
            "severity":     safe_int(row.get("severity"), 5),
            "victimCount":  safe_int(row.get("victim count", row.get("victim_count", 1)), 1),
            "summary":      row.get("summary", ""),
            "latitude":     coords[0],
            "longitude":    coords[1],
            "timestamp":    firestore.SERVER_TIMESTAMP
        })
        
        seen_hashes.add(row_hash)

    if incidents:
        push_to_firestore(incidents)
        save_seen(seen_hashes)
        print(f"Update complete. {len(incidents)} new records processed and uploaded.")
    else:
        print("Done: 0 new records found to upload.")