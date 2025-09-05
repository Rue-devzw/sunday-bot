# services.py
import os
import json
import requests
import google.generativeai as genai
import sqlite3
import re  # Import 're' for bible verse parsing
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

import config
import utils  # Import utils for the asset path helper

# --- INITIALIZATION ---
db = None
gemini_model = None

def initialize_services():
    """Initializes all external service clients."""
    global db, gemini_model

    # Firebase
    try:
        if config.FIREBASE_SERVICE_ACCOUNT_JSON:
            creds_dict = json.loads(config.FIREBASE_SERVICE_ACCOUNT_JSON)
            cred = credentials.Certificate(creds_dict)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            print("Firebase initialized successfully.")
        else:
            print("FIREBASE_SERVICE_ACCOUNT_JSON not set. Firestore is disabled.")
    except Exception as e:
        print(f"Error initializing Firebase: {e}")

    # Gemini
    try:
        if config.GEMINI_API_KEY:
            genai.configure(api_key=config.GEMINI_API_KEY)
            gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            print("GEMINI_API_KEY not set. Gemini AI is disabled.")
    except Exception as e:
        print(f"Error initializing Gemini client: {e}")

# --- WHATSAPP MESSAGING SERVICES ---
def send_whatsapp_message(recipient_id, message_payload):
    """Sends a message payload to the WhatsApp API with detailed logging."""
    if not all([config.WHATSAPP_TOKEN, config.PHONE_NUMBER_ID]):
        print("ERROR: WhatsApp credentials not set in environment variables.")
        return

    clean_recipient_id = recipient_id.replace('+', '')
    url = f"https://graph.facebook.com/v19.0/{config.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": clean_recipient_id,
        **message_payload
    }
    print("--- Attempting to send message to WhatsApp API ---")
    print(f"Recipient: {clean_recipient_id}")
    print(f"Request Payload: {json.dumps(data, indent=2)}")
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"Message successfully sent to {recipient_id}. Status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print("--- FAILED TO SEND MESSAGE ---")
        if e.response is not None:
            print(f"Response Status Code: {e.response.status_code}")
            print(f"Response Body: {e.response.text}")
        else:
            print(f"Error Details: {e}")
        print("------------------------------")

def send_text_message(recipient_id, text):
    payload = {"type": "text", "text": {"body": text}}
    send_whatsapp_message(recipient_id, payload)

def send_interactive_message(recipient_id, interactive_payload):
    payload = {"type": "interactive", "interactive": interactive_payload}
    send_whatsapp_message(recipient_id, payload)

# --- FIRESTORE (DATABASE) SERVICES ---
def get_user_profile(user_id):
    if not db: return {}
    try:
        session_ref = db.collection('sessions').document(user_id)
        session_doc = session_ref.get()
        return session_doc.to_dict() if session_doc.exists else {}
    except Exception as e:
        print(f"Error getting user profile: {e}")
        return {}

def save_user_profile(user_id, profile_data):
    if not db: return
    try:
        session_ref = db.collection('sessions').document(user_id)
        session_ref.set(profile_data)
    except Exception as e:
        print(f"Error saving user profile: {e}")

def delete_user_profile(user_id):
    if not db: return
    try:
        db.collection('sessions').document(user_id).delete()
    except Exception as e:
        print(f"Error deleting user profile: {e}")

def get_firestore_collection_name(camp_type):
    return "youth_camp_2025" if camp_type == 'youths' else "annual_camp_2025"

def check_registration_status(identifier, camp_type):
    if not db: return "Error"
    try:
        collection_name = get_firestore_collection_name(camp_type)
        doc_ref = db.collection(collection_name).document(identifier.strip())
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print(f"Error checking Firestore: {e}")
        return "Error"

def save_registration(reg_data, camp_type):
    if not db: return False
    try:
        collection_name = get_firestore_collection_name(camp_type)
        doc_ref = db.collection(collection_name).document(reg_data['id_passport'])
        reg_data['timestamp'] = firestore.SERVER_TIMESTAMP
        doc_ref.set(reg_data)
        return True
    except Exception as e:
        print(f"Error saving registration: {e}")
        return False

# --- BIBLE (SQLITE) SERVICES ---
def get_verse_from_db(passage, db_filename):
    """Fetches a Bible verse from the SQLite database using a reliable path."""
    db_path = utils.get_asset_path(config.BIBLES_DIR, db_filename)
    if not os.path.exists(db_path):
        print(f"CRITICAL: Bible database not found. Looked for it at: {db_path}")
        return f"Sorry, the selected Bible database file ({db_filename}) is missing from the server."
    
    range_match = re.match(r'(.+?)\s*(\d+):(\d+)-(\d+)', passage, re.IGNORECASE)
    single_match = re.match(r'(.+?)\s*(\d+):(\d+)', passage, re.IGNORECASE)
    chapter_match = re.match(r'(.+?)\s*(\d+)$', passage, re.IGNORECASE)
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        cursor = conn.cursor()
        if range_match:
            book_name, chapter, start_verse, end_verse = range_match.groups()
            query = "SELECT verse, text FROM bible_verses WHERE book_name_text LIKE ? AND chapter = ? AND verse >= ? AND verse <= ? ORDER BY verse"
            params = (f'%{book_name.strip()}%', chapter, start_verse, end_verse)
        elif single_match:
            book_name, chapter, verse = single_match.groups()
            query = "SELECT verse, text FROM bible_verses WHERE book_name_text LIKE ? AND chapter = ? AND verse = ?"
            params = (f'%{book_name.strip()}%', chapter, verse)
        elif chapter_match:
            book_name, chapter = chapter_match.groups()
            query = "SELECT verse, text FROM bible_verses WHERE book_name_text LIKE ? AND chapter = ? ORDER BY verse"
            params = (f'%{book_name.strip()}%', chapter)
        else:
            return f"Sorry, I could not understand the reference '{passage}'. Please use a format like 'John 3:16', 'Genesis 1:1-5', or 'Psalm 23'."
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        if not results:
            return f"Sorry, I couldn't find the passage '{passage}'. Please check the reference."
        full_text = "".join([f"[{v[0]}] {v[1]} " for v in results])
        return f"📖 *{passage.strip()}*\n\n{full_text.strip()}"
    except Exception as e:
        print(f"CRITICAL: SQLite Database Error: {e}")
        return "Sorry, I'm having trouble looking up the Bible verse right now."

# --- GOOGLE SHEETS SERVICES ---
def export_registrations_to_sheet(camp_type):
    """Exports all registrations from Firestore to Google Sheets."""
    if not db or not config.GOOGLE_CREDENTIALS_JSON:
        return "Configuration Error: Firebase or Google Sheets not set up."

    collection_name = get_firestore_collection_name(camp_type)
    sheet_name = config.YOUTH_CAMP_SHEET_NAME if camp_type == 'youths' else config.ANNUAL_CAMP_SHEET_NAME

    try:
        docs = db.collection(collection_name).stream()
        all_rows = []
        headers = [
            "Timestamp", "FirstName", "LastName", "DateOfBirth", "Age", "Gender",
            "ID/Passport", "Phone", "SalvationStatus", "Dependents", "WorkerStatus",
            "Volunteering", "VolunteerDepartment", "TransportAssistance", "NextOfKinName",
            "NextOfKinPhone", "CampStay"
        ]
        all_rows.append(headers)

        for doc in docs:
            data = doc.to_dict()
            timestamp_obj = data.get("timestamp")
            timestamp_str = timestamp_obj.strftime("%Y-%m-%d %H:%M:%S") if isinstance(timestamp_obj, datetime) else str(timestamp_obj)
            row = [
                timestamp_str, data.get("first_name", ""), data.get("last_name", ""),
                data.get("dob", ""), data.get("age", ""), data.get("gender", ""),
                data.get("id_passport", ""), data.get("phone", ""),
                data.get("salvation_status", ""), str(data.get("dependents", "")),
                data.get("worker_status", "N/A"), data.get("volunteer_status", ""),
                data.get("volunteer_department", ""), data.get("transport_assistance", "No"),
                data.get("nok_name", ""), data.get("nok_phone", ""),
                f"{data.get('camp_start', '')} to {data.get('camp_end', '')}"
            ]
            all_rows.append(row)

        if len(all_rows) <= 1:
            return "No registrations found in the database to export."

        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(config.GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        try:
            sheet = client.open(sheet_name).sheet1
        except gspread.exceptions.SpreadsheetNotFound:
            return f"Error: Spreadsheet named '{sheet_name}' not found. Please create it or check the name."

        sheet.clear()
        sheet.update('A1', all_rows)
        return f"✅ Success! Exported {len(all_rows) - 1} registrations to '{sheet_name}'."
    except Exception as e:
        print(f"Error during export: {e}")
        return f"⚠️ An error occurred during the export process: {e}"

# --- GEMINI (AI) SERVICES ---
def get_ai_response(question, context):
    """Gets a response from the Gemini AI model."""
    if not gemini_model:
        return "Sorry, the AI thinking module is currently unavailable."
    prompt = (
        "You are a friendly and helpful Sunday School assistant. "
        "Your primary role is to answer questions based *only* on the provided lesson material. "
        "Do not use any external knowledge or information outside of this context. "
        "If the answer cannot be found in the lesson, politely state that the information "
        "is not available in the provided text. Keep your answers clear, concise, "
        "and appropriate for the lesson's age group.\n\n"
        f"--- START OF LESSON CONTEXT ---\n{context}\n--- END OF LESSON CONTEXT ---\n\n"
        f"Based on the lesson above, please answer the following question:\n"
        f"Question: \"{question}\""
    )
    try:
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Google Gemini API Error: {e}")
        return "I'm having a little trouble thinking right now. Please try again in a moment."