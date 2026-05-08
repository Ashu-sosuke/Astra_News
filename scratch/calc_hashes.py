import hashlib
import json

def get_row_hash(row):
    s = f"{row.get('date', '')}_{row.get('summary', '')}"
    return hashlib.md5(s.encode('utf-8')).hexdigest()

rows = [
    {"date": "2026-03-18", "summary": "Gangster Ravi Pujari arrested by Thane Crime Branch in 2017 extortion case and remanded to police custody."},
    {"date": "2026-04-12", "summary": "A student in Kerala died by suicide, with his family alleging harassment by faculty."},
    {"date": "2026-04-12", "summary": "Remains of an 18-year-old woman found in Bokaro after 8 months; accused plotted murder due to marriage pressure."},
    {"date": "2026-04-12", "summary": "Noida man drowned in a water-filled pit; an FIR registered against three students."},
    {"date": "2026-04-15", "summary": "TCS Nashik woman employee reveals horrors after surviving an incident, leading to staff arrests."}
]

for row in rows:
    print(f"{row['date']}: {get_row_hash(row)}")
