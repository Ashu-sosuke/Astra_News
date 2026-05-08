import requests
print("Requests imported")
import json
print("JSON imported")
from bs4 import BeautifulSoup
print("BS4 imported")
import gspread
print("GSpread imported")
import google.generativeai as genai
print("GenAI imported")
import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
load_dotenv()

def ensure_headers():
    print("Connecting to Google Sheets...")
    creds = Credentials.from_service_account_file(
        "service_account.json",
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    gc    = gspread.authorize(creds)
    print("Authorized. Opening sheet...")
    sheet = gc.open("India Crime Data 2026").sheet1
    print("Sheet opened.")
    headers = ["Date", "Category", "City", "Local Area", "State", "Severity", "Victim Count", "Summary"]
    current_headers = sheet.row_values(1)
    print(f"Current headers: {current_headers}")
    if headers != current_headers:
        print("Mismatch. Updating headers...")
    else:
        print("Headers match.")

ensure_headers()
print("All tests successful")
