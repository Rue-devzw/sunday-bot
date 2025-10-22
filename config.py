# config.py
import os
import re
from datetime import date

# --- FLASK & WHATSAPP API CONFIG ---
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')

# --- EXTERNAL API KEYS ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')

# --- GOOGLE SHEETS CONFIG ---
ANNUAL_CAMP_SHEET_NAME = os.environ.get('ANNUAL_CAMP_SHEET_NAME', 'Camp Registrations 2025')
YOUTH_CAMP_SHEET_NAME = os.environ.get('YOUTH_CAMP_SHEET_NAME', 'Youths Camp Registrations 2025')

# --- BOT ADMIN & CONSTANTS ---
ADMIN_NUMBERS = ['+263718704505', '+263789990580', '+263774960029', '+263717059994']
CLEAN_ADMIN_NUMBERS = [re.sub(r'\D', '', num) for num in ADMIN_NUMBERS] # Pre-processed for efficiency

# --- LESSONS CONFIG ---
ANCHOR_DATE = date(2024, 9, 1)
PRIMARY_PALS_ANCHOR_DATE = date(2024, 9, 1)
CLASSES = { "beginners": "Beginners", "primary_pals": "Primary Pals", "answer": "Answer", "search": "Search" }
LESSON_FILES = {
    "Beginners": "beginners_lessons.json",
    "Primary Pals": "primary_pals_lessons.json",
    "Answer": "answer_lessons.json",
    "Search": "search_lessons.json"
}

# --- HYMNBOOK & BIBLE CONFIG ---
HYMNBOOKS = {
    "shona": {"name": "Yellow Hymnbook Shona", "file": "shona_hymns.json"},
    "english": {"name": "English Hymns", "file": "english_hymns.json"}
}
BIBLES = {
    "shona": {"name": "Shona Bible", "file": "shona_bible.db"},
    "english": {"name": "English Bible (KJV)", "file": "english_bible.db"}
}

# --- REGISTRATION CONFIG ---
MARITAL_STATUSES = {
    "single": "Single", "married": "Married", "divorced": "Divorced", "widowed": "Widowed"
}
ACCOMMODATION_OPTIONS = {
    "hotel": "Hotel", "hostel": "Hostel", "guesthouse": "Guesthouse", "apartment": "Apartment", "other": "Other"
}
DIETARY_REQUIREMENTS = {
    "none": "None", "vegetarian": "Vegetarian", "vegan": "Vegan", "gluten_free": "Gluten-Free"
}
LANGUAGES = {
    "english": "English", "shona": "Shona", "ndebele": "Ndebele"
}
VOLUNTEER_ROLES = {
    "cleaning_and_hygiene": "Cleaning and Hygiene",
    "waste_management": "Waste Management",
    "kitchen": "Kitchen",
    "deacon_duties": "Deacon duties",
    "transportation": "Transportation",
    "script_sermon_secretariat": "Script Sermon (Secretariat)",
    "accommodation_hosting": "Accommodation/Hosting",
    "reception": "Reception",
    "officer_security": "Officer/Security",
    "digital_presence": "Digital Presence",
    "multimedia": "Multimedia",
    "maintenance": "Maintenance",
    "other": "Other"
}
CHURCH_ROLES = {
    "minister": "Minister", "deacon": "Deacon", "teacher": "Sunday School Teacher",
    "none": "None of the above"
}

# --- DIRECTORY PATHS ---
HYMNBOOKS_DIR = 'hymnbooks'
BIBLES_DIR = 'bibles'
LESSONS_DIR = 'lessons'