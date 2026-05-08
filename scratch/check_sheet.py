import gspread
from google.oauth2.service_account import Credentials
import json

creds = Credentials.from_service_account_file(
    "service_account.json",
    scopes=["https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"]
)
gc = gspread.authorize(creds)
try:
    sheet = gc.open("India Crime Data 2026").sheet1
    rows = sheet.get_all_values()
    print(json.dumps(rows[:10], indent=2))
except Exception as e:
    print(f"Error: {e}")
