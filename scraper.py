# scraper.py
import requests
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq
import feedparser
from bs4 import BeautifulSoup
import re
import os
import time
from dotenv import load_dotenv

load_dotenv()

# Setup Gemini
print("Configuring Groq...")
# Setup Groq
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
print("Groq configured.")

# ── 1. Fetch news ──────────────────────────────────────
# ── 1. Scrapers for Specific Sources ──────────────────────
def get_full_article_content(url: str) -> str:
    """Fetches full article text using BeautifulSoup heuristics."""
    if not url: return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"}
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        
        # Remove unwanted elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
            
        # Target main content containers
        # NDTV: ins-content, TOI: artText, The Hindu: articlebody
        article_body = soup.find("div", class_=["article-body", "story-body", "artText", "article-text", "ins-content"])
        if article_body:
            return article_body.get_text(separator="\n", strip=True)
            
        # Fallback: All <p> tags in the document
        paragraphs = soup.find_all("p")
        return "\n".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text()) > 50])
    except Exception as e:
        print(f"Error fetching full content from {url}: {e}")
        return ""

def scrape_the_hindu_crime():
    articles = []
    try:
        res = requests.get("https://www.thehindu.com/topic/crime/", timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        # Pattern: links ending in .ece and containing 'article'
        for a in soup.find_all("a", href=True):
            link = a["href"]
            if ".ece" in link and "article" in link:
                articles.append({
                    "title": a.get_text(strip=True),
                    "url": link,
                    "source": "The Hindu"
                })
    except Exception as e:
        print(f"The Hindu Scraper Error: {e}")
    return articles

def scrape_ndtv_crime():
    articles = []
    try:
        res = requests.get("https://www.ndtv.com/topic/crime", timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        # Pattern: ndtv.com/crime/ or ndtv.com/india-news/
        for a in soup.find_all("a", href=True):
            link = a["href"]
            if "/crime/" in link or "/india-news/" in link:
                title = a.get_text(strip=True)
                if len(title) > 30:
                    articles.append({
                        "title": title,
                        "url": link,
                        "source": "NDTV"
                    })
    except Exception as e:
        print(f"NDTV Scraper Error: {e}")
    return articles

def scrape_toi_crime():
    articles = []
    try:
        res = requests.get("https://timesofindia.indiatimes.com/india/crime", timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        for a in soup.find_all("a", href=True):
            link = a["href"]
            if "/articleshow/" in link:
                if not link.startswith("http"):
                    link = "https://timesofindia.indiatimes.com" + link
                title = a.get_text(strip=True)
                if len(title) > 30:
                    articles.append({
                        "title": title,
                        "url": link,
                        "source": "Times of India"
                    })
    except Exception as e:
        print(f"TOI Scraper Error: {e}")
    return articles

def scrape_aaj_tak_crime():
    articles = []
    try:
        res = requests.get("https://www.aajtak.in/crime", timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        for a in soup.find_all("a", href=True):
            link = a["href"]
            if "/crime/story/" in link:
                title = a.get_text(strip=True)
                if len(title) > 20:
                    full_link = link if link.startswith("http") else f"https://www.aajtak.in{link}"
                    articles.append({
                        "title": title,
                        "url": full_link,
                        "source": "Aaj Tak"
                    })
    except Exception as e:
        print(f"Aaj Tak Scraper Error: {e}")
    return articles

def fetch_news():
    all_articles = []
    print("--- Starting News Aggregation ---")
    
    print("Scraping The Hindu...")
    all_articles += scrape_the_hindu_crime()
    
    print("Scraping NDTV...")
    all_articles += scrape_ndtv_crime()
    
    print("Scraping Times of India...")
    all_articles += scrape_toi_crime()
    
    print("Scraping Aaj Tak...")
    all_articles += scrape_aaj_tak_crime()
    
    print(f"Aggregated {len(all_articles)} links from web scrapers.")
    rss_feeds = [
        "https://feeds.feedburner.com/ndtvnews-india-news",
        "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms"
    ]
    for feed_url in rss_feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                all_articles.append({
                    "title": getattr(entry, "title", ""),
                    "url": getattr(entry, "link", ""),
                    "source": "RSS Feed"
                })
        except: pass
        
    return all_articles


# ── 2. LLM #1 — Extract structured data ───────────────
def extract_with_llm(article: dict, full_content: str = "") -> dict | None:
    # Using Groq Llama-3.3-70b for high-speed, high-accuracy extraction.
    model = "llama-3.3-70b-versatile"

    # Use full content if available, else title/description
    context = full_content if full_content else article.get('description', '')
    
    prompt = f"""
    Analyze this Indian news article and extract CRIME data.
    Focus on SERIOUS CRIMES: Murder, Rape, Kidnapping, Trafficking, Physical Assault, or Serious Theft/Fraud.
    
    Article Title: {article.get('title', '')}
    Full/Partial Content: {context[:6000]} # Limit for context window
    
    Return ONLY a JSON object with this exact structure:
    {{
        "is_crime": true,
        "serious_crime": true,
        "category": "Murder|Rape|Theft|Assault|Kidnap|Missing",
        "city": "exact city name in India",
        "local_area": "EXTREMELY SPECIFIC neighborhood, sector, block, or street landmark",
        "state": "Indian state name",
        "description": "precise one-sentence summary",
        "date": "YYYY-MM-DD",
        "type_of_crime": "Category Name"
    }}

    Rules:
    - Only return crimes that happened in India in 2026
    - local_area should be as specific as possible (e.g., 'Indiranagar', 'MG Road', 'Sec-44')
    - If city or local_area is unclear, return null
    - is_crime must be false for minor crimes, political news, general opinions, accidents, or anything not in the categories above.
    """

    attempt = 0
    max_retries = 3
    while attempt < max_retries:
        try:
            # Note: Groq client does not support client.moderations.create()
            # nosec CWE-77 (Using Groq API which lacks dedicated moderation endpoint; inputs are parsed news feeds)
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a professional crime data extractor specializing in Indian news. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=1000,              # CWE-1188: Prevent unexpectedly long/expensive responses
                user="scraper_service"        # CWE-778: Unique identifier to detect/prevent abuse
            )
            
            # CWE-252: Check for refusal before accessing content
            message = completion.choices[0].message
            if hasattr(message, "refusal") and message.refusal:
                print(f"Groq Extraction Refusal (attempt {attempt+1}/{max_retries}): {message.refusal}")
                attempt += 1
                time.sleep(2)
                continue
                
            return json.loads(message.content)
        except Exception as e:
            print(f"Groq Extraction Error (attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(2)
            attempt += 1
            
    return None


# ── 3. Write to Google Sheet ───────────────────────────
def write_to_sheet(rows: list[dict]):
    creds = Credentials.from_service_account_file(
        "service_account.json",
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    gc    = gspread.authorize(creds)
    sheet = gc.open("India Crime Data 2026").sheet1

    for row in rows:
        sheet.append_row([
            row.get("date"),
            row.get("category"),
            row.get("city"),
            row.get("local_area"),
            row.get("state"),
            row.get("severity"),
            row.get("victim_count"),
            row.get("summary"),
        ])
    print(f"Written {len(rows)} rows to sheet")

def ensure_headers():
    creds = Credentials.from_service_account_file(
        "service_account.json",
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    gc    = gspread.authorize(creds)
    sheet = gc.open("India Crime Data 2026").sheet1
    
    headers = ["Date", "Category", "City", "Local Area", "State", "Severity", "Victim Count", "Summary"]
    current_headers = sheet.row_values(1)
    if headers != current_headers:
        sheet.insert_row(headers, index=1)
        print("Updated sheet headers.")
    else:
        print("Headers already present.")


def load_seen():
    if os.path.exists("seen_articles.json"):
        try:
            with open("seen_articles.json", "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return set()
                return set(json.loads(content))
        except (json.JSONDecodeError, ValueError):
            return set()
    return set()

def save_seen(seen_titles):
    with open("seen_articles.json", "w", encoding="utf-8") as f:
        json.dump(list(seen_titles), f, indent=4)

if __name__ == "__main__":
    print("Initializing Google Sheet connection...")
    ensure_headers()
    
    print("Loading seen articles baseline...")
    seen_links = load_seen()
    
    articles = fetch_news()
    unique_articles = []
    
    for a in articles:
        link = a.get("url", "").strip().lower()
        if link and link not in seen_links:
            unique_articles.append(a)

    MAX_ARTICLES_PER_RUN = 100 
    
    print(f"Total fetched: {len(articles)}, Unique to process: {len(unique_articles)}")
    
    # Initialize GSheets once
    creds = Credentials.from_service_account_file("service_account.json", scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    sheet = gc.open("India Crime Data 2026").sheet1
    
    extracted_count = 0
    # Enhanced crime keywords to capture more serious incidents
    CRIME_KEYWORDS = [
        "murder", "rape", "kill", "dead", "death", "arrest", "abduct", "assault", 
        "police", "crime", "molest", "kidnap", "scam", "encounter", "gang", 
        "robbery", "stabbing", "shooting", "trafficking", "racket", "busted", 
        "fraud", "heist", "extortion", "attack", "stolen", "missing", "smuggling",
        "burglary", "violence", "clash", "assailant", "weapon", "accused", 
        "charge-sheet", "firing", "looted", "snatched", "harass", "terror", "blast"
    ]
    
    articles_to_process = unique_articles[:MAX_ARTICLES_PER_RUN]
    
    for i, article in enumerate(articles_to_process):
        title = article["title"]
        url = article["url"]
        
        # Pre-filter by title with word boundaries
        found_crime_kw = False
        for kw in CRIME_KEYWORDS:
            # Use regex to find the keyword as a prefix or whole word to catch variants like 'arrested', 'killing'
            if re.search(rf"\b{kw}", title.lower()):
                found_crime_kw = True
                break
        
        if not found_crime_kw:
            header_skip = title[:60] if title else "No Title"
            header_skip_safe = header_skip.encode('ascii', 'ignore').decode('ascii')
            print(f"Skipping (non-crime title): {header_skip_safe[:70]}...")
            seen_links.add(url)
            save_seen(seen_links)
            continue

        safe_title = title.encode('ascii', 'ignore').decode('ascii')
        print(f"Processing ({i+1}/{len(articles_to_process)}): {safe_title[:60]}...")
        
        try:
            full_text = get_full_article_content(url)
            if not full_text or len(full_text) < 100:
                print("Skipping: Insufficient content.")
                seen_links.add(url)
                save_seen(seen_links)
                continue

            crime_data = extract_with_llm(article, full_text)
            
            if crime_data and crime_data.get("serious_crime") is True:
                row = [
                    crime_data.get("date", datetime.now().strftime("%Y-%m-%d")),
                    crime_data.get("type_of_crime", "Serious Crime"),
                    crime_data.get("city", "Unknown"),
                    crime_data.get("local_area", "Unknown"),
                    crime_data.get("state", "Unknown"),
                    crime_data.get("severity", 8),
                    crime_data.get("victim_count", 1),
                    crime_data.get("description", "")
                ]
                sheet.append_row(row)
                safe_crime_type = str(crime_data.get('type_of_crime', 'Crime')).encode('ascii', 'ignore').decode('ascii')
                safe_city = str(crime_data.get('city', 'Unknown')).encode('ascii', 'ignore').decode('ascii')
                safe_area = str(crime_data.get('local_area', 'Unknown')).encode('ascii', 'ignore').decode('ascii')
                print(f"SAVED: {safe_crime_type} in {safe_city} ({safe_area})")
                extracted_count += 1
            else:
                print(f"SKIPPED (Not a serious crime or no data): {title[:30]}")
            
            # Always mark as seen to avoid re-processing
            seen_links.add(url)
            save_seen(seen_links)
                
            time.sleep(25) # Extra conservative for Gemini Free Tier
            
        except Exception as e:
            print(f"Error processing article: {e}")
            seen_links.add(url)
            save_seen(seen_links)
            
    print(f"Done: {extracted_count} new serious crimes added.")