# services.py
import os
import json
import requests
import google.generativeai as genai
import sqlite3
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

import config

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
    """Sends a message payload to the WhatsApp API."""
    if not all([config.WHATSAPP_TOKEN, config.PHONE_NUMBER_ID]):
        print("ERROR: WhatsApp credentials not set.")
        return
    url = f"https://graph.facebook.com/v23.0/{config.PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": recipient_id, **message_payload}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"Message sent to {recipient_id}: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message: {e}")
        if e.response: print(f"Response Body: {e.response.text}")

def send_text_message(recipient_id, text):
    payload = {"type": "text", "text": {"body": text}}
    send_whatsapp_message(recipient_id, payload)

def send_interactive_message(recipient_id, interactive_payload):
    payload = {"type": "interactive", "interactive": interactive_payload}
    send_whatsapp_message(recipient_id, payload)

# --- FIRESTORE (DATABASE) SERVICES ---
def get_user_profile(user_id):
    """Retrieves a user's session profile from Firestore."""
    if not db: return {}
    try:
        session_ref = db.collection('sessions').document(user_id)
        session_doc = session_ref.get()
        return session_doc.to_dict() if session_doc.exists else {}
    except Exception as e:
        print(f"Error getting user profile: {e}")
        return {}

def save_user_profile(user_id, profile_data):
    """Saves a user's session profile to Firestore."""
    if not db: return
    try:
        session_ref = db.collection('sessions').document(user_id)
        session_ref.set(profile_data)
    except Exception as e:
        print(f"Error saving user profile: {e}")

def delete_user_profile(user_id):
    """Deletes a user's session profile from Firestore."""
    if not db: return
    try:
        db.collection('sessions').document(user_id).delete()
    except Exception as e:
        print(f"Error deleting user profile: {e}")

def get_firestore_collection_name(camp_type):
    return "youth_camp_2025" if camp_type == 'youths' else "annual_camp_2025"

def check_registration_status(identifier, camp_type):
    """Checks registration status in Firestore."""
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
    """Saves registration data to Firestore."""
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
    """Fetches a Bible verse from the SQLite database."""
    # (The entire logic of get_verse_from_db is moved here)
    # ...
    pass # Placeholder for brevity

# --- GOOGLE SHEETS SERVICES ---
def export_registrations_to_sheet(camp_type):
    """Exports all registrations from Firestore to Google Sheets."""
    if not db or not config.GOOGLE_CREDENTIALS_JSON:
        return "Configuration Error: Firebase or Google Sheets not set up."
    # (The entire logic of export_registrations_to_sheet is moved here)
    # ...
    pass # Placeholder for brevity

# --- GEMINI (AI) SERVICES ---
def get_ai_response(question, context):
    """Gets a response from the Gemini AI model."""
    if not gemini_model: return "Sorry, the AI thinking module is currently unavailable."
    prompt = (
        # (The entire prompt logic is moved here)
    )
    try:
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Google Gemini API Error: {e}")
        return "I'm having a little trouble thinking right now. Please try again in a moment."