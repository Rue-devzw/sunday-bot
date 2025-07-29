
import os
import json
import requests
import google.generativeai as genai
import sqlite3
import re
from flask import Flask, request
from datetime import datetime, date
from dateutil.relativedelta import relativedelta, MO
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. INITIALIZE FLASK & API CLIENTS ---
app = Flask(__name__)

# --- FIREBASE INITIALIZATION ---
try:
    firebase_creds_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firebase initialized successfully.")
    else:
        db = None
        print("FIREBASE_SERVICE_ACCOUNT_JSON not set. Firestore is disabled.")
except Exception as e:
    db = None
    print(f"Error initializing Firebase: {e}")

# --- GEMINI INITIALIZATION ---
try:
    gemini_api_key = os.environ.get('GEMINI_API_KEY')
    genai.configure(api_key=gemini_api_key)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    gemini_model = None
    print(f"Error initializing Gemini client: {e}")

# --- 2. CONFIGURATION & ENVIRONMENT VARIABLES ---
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')

GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')
ANNUAL_CAMP_SHEET_NAME = os.environ.get('ANNUAL_CAMP_SHEET_NAME', 'Camp Registrations 2025')
YOUTH_CAMP_SHEET_NAME = os.environ.get('YOUTH_CAMP_SHEET_NAME', 'Youths Camp Registrations 2025')

ADMIN_NUMBERS = ['+263718704505'] 

ANCHOR_DATE = date(2024, 8, 21)
PRIMARY_PALS_ANCHOR_DATE = date(2024, 9, 1)

HYMNBOOKS_DIR = 'hymnbooks'
BIBLES_DIR = 'bibles'
LESSONS_DIR = 'lessons'
LESSONS_FILE_SEARCH = 'search_lessons.json'
LESSONS_FILE_ANSWER = 'answer_lessons.json'
LESSONS_FILE_BEGINNERS = 'beginners_lessons.json'
LESSONS_FILE_PRIMARY_PALS = 'primary_pals_lessons.json'

CLASSES = { "beginners": "Beginners", "primary_pals": "Primary Pals", "answer": "Answer", "search": "Search" }
HYMNBOOKS = { "shona": {"name": "Yellow Hymnbook Shona", "file": "shona_hymns.json"}, "english": {"name": "English Hymns", "file": "english_hymns.json"} }
BIBLES = { "shona": {"name": "Shona Bible", "file": "shona_bible.db"}, "english": {"name": "English Bible (KJV)", "file": "english_bible.db"} }
DEPARTMENTS = { "security": "Security", "media": "Media", "accommodation": "Accommodation", "transport": "Transport", "translation": "Translation", "kitchen": "Kitchen Work", "editorial": "Notes Taking (Editorial)"}
WORKER_TYPES = {"minister": "Minister", "deacon": "Deacon", "sunday_school_teacher": "Sunday School Teacher", "none": "None of the above"}

# --- 3. HELPER & DATABASE FUNCTIONS ---
def get_firestore_collection_name(camp_type):
    return "youth_camp_2025" if camp_type == 'youths' else "annual_camp_2025"

def check_registration_status_firestore(identifier, camp_type):
    if not db: return "Error"
    try:
        collection_name = get_firestore_collection_name(camp_type)
        doc_ref = db.collection(collection_name).document(identifier.strip())
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print(f"Error checking Firestore: {e}")
        return "Error"

def export_registrations_to_sheet(camp_type):
    if not db or not GOOGLE_CREDENTIALS_JSON:
        return "Configuration Error: Firebase or Google Sheets not set up."

    collection_name = get_firestore_collection_name(camp_type)
    sheet_name = YOUTH_CAMP_SHEET_NAME if camp_type == 'youths' else ANNUAL_CAMP_SHEET_NAME
    
    try:
        docs = db.collection(collection_name).stream()
        all_rows = []
        headers = ["Timestamp", "FirstName", "LastName", "DateOfBirth", "Age", "Gender", "ID/Passport", "Phone", "SalvationStatus", "Dependents", "Volunteering", "VolunteerDepartment", "IsWorker", "WorkerType", "TransportAssistance", "NextOfKinName", "NextOfKinPhone", "CampStay"]
        all_rows.append(headers)

        for doc in docs:
            data = doc.to_dict()
            timestamp_obj = data.get("timestamp")
            timestamp_str = timestamp_obj.strftime("%Y-%m-%d %H:%M:%S") if isinstance(timestamp_obj, datetime) else ""
            
            row = [
                timestamp_str, data.get("first_name", ""), data.get("last_name", ""), data.get("dob", ""),
                data.get("age", ""), data.get("gender", ""), data.get("id_passport", ""), data.get("phone", ""),
                data.get("salvation_status", ""), data.get("dependents", ""), data.get("volunteer_status", ""),
                data.get("volunteer_department", ""), data.get("is_worker", ""), data.get("worker_type", ""),
                data.get("transport_assistance", ""), data.get("nok_name", ""), data.get("nok_phone", ""),
                f"{data.get('camp_start', '')} to {data.get('camp_end', '')}"
            ]
            all_rows.append(row)

        if len(all_rows) <= 1:
            return "No registrations found in the database to export."

        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        try:
            sheet = client.open(sheet_name).sheet1
        except gspread.exceptions.SpreadsheetNotFound:
            return f"Error: Spreadsheet named '{sheet_name}' not found. Please create it or check the name."

        sheet.clear()
        sheet.append_rows(all_rows, value_input_option='USER_ENTERED')
        
        return f"✅ Success! Exported {len(all_rows) - 1} registrations to '{sheet_name}'."
    except Exception as e:
        print(f"Error during export: {e}")
        return f"⚠️ An error occurred during the export process: {e}"

def calculate_age(dob_string):
    try:
        birth_date = datetime.strptime(dob_string, "%d/%m/%Y").date()
        today = date.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    except ValueError: return None

def get_verse_from_db(passage, db_filename):
    db_path = os.path.join(os.path.dirname(__file__), BIBLES_DIR, db_filename)
    if not os.path.exists(db_path): return f"Sorry, the selected Bible database file ({db_filename}) is missing."
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
        else: return f"Sorry, I could not understand the reference '{passage}'. Please use a format like 'John 3:16', 'Genesis 1:1-5', or 'Psalm 23'."
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        if not results: return f"Sorry, I couldn't find the passage '{passage}'. Please check the reference."
        full_text = "".join([f"[{v[0]}] {v[1]} " for v in results])
        return f"📖 *{passage.strip()}*\n\n{full_text.strip()}"
    except Exception as e:
        print(f"SQLite Database Error: {e}")
        return "Sorry, I'm having trouble looking up the Bible verse right now."

def load_json_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"DEBUG: Error loading static JSON file '{file_path}': {e}")
        return []

def get_current_lesson_index(user_class):
    today = date.today()
    anchor = PRIMARY_PALS_ANCHOR_DATE if user_class == "Primary Pals" else ANCHOR_DATE
    anchor_week_start = anchor + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    week_diff = (current_week_start - anchor_week_start).days // 7
    return week_diff if week_diff >= 0 else -1

def format_hymn(hymn):
    if not hymn: return "Sorry, I couldn't find a hymn with that number."
    title, hymn_number = hymn.get('title', 'No Title'), hymn.get('number', '#')
    message = f"🎶 *Hymn #{hymn_number}: {title}*\n\n"
    verses, chorus, parts = hymn.get('verses', []), hymn.get('chorus', []), hymn.get('parts', [])
    chorus_text = "*Chorus:*\n" + "\n".join(chorus) + "\n\n" if chorus else ""
    if verses:
        for i, verse_lines in enumerate(verses, 1):
            message += f"*{i}.*\n" + "\n".join(verse_lines) + "\n\n"
            if chorus_text: message += chorus_text
    elif chorus_text: message += chorus_text
    if parts:
        for part in parts:
            part_num = part.get('part', '')
            message += f"*{f'Part {part_num}' if part_num else 'Part'}*\n"
            for i, v_lines in enumerate(part.get('verses', []), 1):
                message += f"*{i}.*\n" + "\n".join(v_lines) + "\n\n"
    return message.strip()

def format_lesson(lesson, lesson_class):
    if not lesson: return "Lesson details could not be found."
    message_parts = []
    
    if lesson_class == "Search":
        title = lesson.get('lessonTitle', 'No Title')
        message_parts.append(f"📖 *{title}*")
        refs = lesson.get('bibleReference', [])
        if refs:
            ref_texts = [f"{r.get('book')} {r.get('chapter')}:{r.get('verses')}" for r in refs]
            message_parts.append(f"✝️ *Bible Reference:* {linkify_bible_verses(', '.join(ref_texts))}")
        
        if lesson.get('supplementalScripture'):
            message_parts.append(f"*Supplemental Scripture:* {linkify_bible_verses(lesson['supplementalScripture'])}")
        
        if lesson.get('keyVerse'):
            message_parts.append(f"📌 *Key Verse:*\n_{linkify_bible_verses(lesson['keyVerse'])}_")
            
        if lesson.get('resourceMaterial'):
            message_parts.append(f"📚 *Resource Material:*\n{linkify_bible_verses(lesson['resourceMaterial'])}")
            
        message_parts.append("---")
        for section in lesson.get('lessonSections', []):
            sec_title = section.get('sectionTitle', '')
            sec_content = linkify_bible_verses(section.get('sectionContent', ''))
            if section.get('sectionType') == 'text': message_parts.append(f"📝 *{sec_title}*\n{sec_content}")
            elif section.get('sectionType') == 'question':
                q_num = section.get('questionNumber', '')
                message_parts.append(f"❓ *Question {q_num}:*\n{sec_content}")

    elif lesson_class == "Primary Pals":
        title = lesson.get('title', 'No Title')
        message_parts.append(f"🎨 *{title}*")
        parent_guide = lesson.get('parent_guide', {})
        memory_verse = linkify_bible_verses(parent_guide.get('memory_verse', {}).get('text', ''))
        if memory_verse: message_parts.append(f"📌 *Memory Verse:*\n_{memory_verse}_")
        message_parts.append("---")
        story = lesson.get('story', [])
        if story: message_parts.append("📖 *Story*\n" + "\n\n".join([linkify_bible_verses(s) for s in story]))
        
        activities = lesson.get('activities', [])
        if activities:
            activity_texts = ["🧩 *Activities*"]
            for act in activities:
                act_title = act.get('title', '')
                act_instr = "\n".join(act.get('instructions', [])) if isinstance(act.get('instructions'), list) else act.get('instructions', '')
                activity_texts.append(f"*{act.get('type')}: {act_title}*\n{linkify_bible_verses(act_instr)}")
            message_parts.append("\n".join(activity_texts))
        
        if parent_guide:
            guide_texts = ["👨‍👩‍👧 *Parent's Guide*"]
            corner = linkify_bible_verses(parent_guide.get('parents_corner', {}).get('text', ''))
            if corner: guide_texts.append(f"*Parent's Corner:*\n{corner}")
            
            devotions = parent_guide.get('family_devotions', {}).get('verses', [])
            if devotions:
                devotion_lines = ["*Family Devotions:*"]
                for dev in devotions: devotion_lines.append(f"  - *{dev.get('day')}:* {linkify_bible_verses(dev.get('reference'))}")
                guide_texts.append("\n".join(devotion_lines))
            message_parts.append("\n".join(guide_texts))
            
    else: # For Beginners and Answer classes
        title = lesson.get('title', 'No Title')
        memory_verse = linkify_bible_verses(lesson.get('memory_verse', 'N/A'))
        main_text = "\n".join([linkify_bible_verses(t) for t in lesson.get('text', [])])
        message_parts.append(f"📖 *{title}*\n\n📌 *Memory Verse:*\n_{memory_verse}_\n\n📝 *Lesson Text:*\n{main_text}")

    return "\n\n".join(message_parts)

def linkify_bible_verses(text):
    if not text or not isinstance(text, str):
        return text

    bible_books = [
        "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth",
        "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
        "Nehemiah", "Esther", "Job", "Psalm", "Proverbs", "Ecclesiastes", "Song of Solomon",
        "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
        "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah",
        "Malachi", "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
        "2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians", "1 Thessalonians",
        "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews", "James",
        "1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude", "Revelation"
    ]

    books_pattern = "|".join(bible_books).replace(" ", r"\s")
    pattern = re.compile(fr'\b({books_pattern})\s+(\d+:\d+(?:-\d+)?)\b', re.IGNORECASE)

    def repl(match):
        return f"`bible {match.group(0)}`"

    return pattern.sub(repl, text)

def get_ai_response(question, context):
    if not gemini_model: return "Sorry, the AI thinking module is currently unavailable."
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

# --- 4. WHATSAPP MESSAGING FUNCTIONS ---
def send_whatsapp_message(recipient_id, message_payload):
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]):
        print("ERROR: WhatsApp credentials not set.")
        return
    
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    
    data = {
        "messaging_product": "whatsapp",
        "to": recipient_id,
        **message_payload
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"Message sent to {recipient_id}: {response.status_code}, {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message: {e}")
        if e.response:
            print(f"Response Body: {e.response.text}")
            print(f"Request Payload: {json.dumps(data, indent=2)}")


def send_text_message(recipient_id, text):
    payload = {"type": "text", "text": {"body": text}}
    send_whatsapp_message(recipient_id, payload)

def send_interactive_message(recipient_id, interactive_payload):
    payload = {"type": "interactive", "interactive": interactive_payload}
    send_whatsapp_message(recipient_id, payload)

# --- 5. MAIN BOT LOGIC HANDLER (RE-ENGINEERED) ---
def handle_bot_logic(user_id, message_text):
    if not db:
        send_text_message(user_id, "Sorry, the bot is experiencing technical difficulties (Database connection failed). Please try again later.")
        return

    session_ref = db.collection('sessions').document(user_id)
    session_doc = session_ref.get()
    user_profile = session_doc.to_dict() if session_doc.exists else {}
    
    message_text_lower = message_text.lower().strip()
    
    if message_text_lower.startswith('bible '):
        passage = message_text.strip().replace('bible ', '', 1)
        default_bible_file = BIBLES.get('english', {}).get('file')

        if default_bible_file:
            send_text_message(user_id, f"_Looking up {passage}..._")
            verse_text = get_verse_from_db(passage, default_bible_file)
            send_text_message(user_id, verse_text)
        else:
            send_text_message(user_id, "Sorry, the default Bible file is not configured correctly.")
        
        return

    # --- Admin Check ---
    clean_user_id = re.sub(r'\D', '', user_id)
    clean_admin_numbers = [re.sub(r'\D', '', num) for num in ADMIN_NUMBERS]
    if clean_user_id in clean_admin_numbers and message_text_lower.startswith('export'):
        parts = message_text_lower.split()
        if len(parts) == 2 and parts[1] in ['youths', 'annual']:
            camp_type = parts[1]
            send_text_message(user_id, f"Okay, starting export for *{camp_type} camp*. This may take a moment...")
            result = export_registrations_to_sheet(camp_type)
            send_text_message(user_id, result)
            return
        else:
            send_text_message(user_id, "Invalid export command. Use `export youths` or `export annual`.")
            return

    # --- Session Reset ---
    if message_text_lower == 'reset':
        session_ref.delete()
        user_profile = {}

    # --- Mode Selection Logic ---
    if message_text_lower.startswith("mode_"):
        full_mode_id = message_text_lower.replace('mode_', '', 1)
        
        user_profile = {} 

        if full_mode_id.startswith('camp_reg_'):
            user_profile['mode'] = 'camp_registration'
            user_profile['registration_type'] = full_mode_id.replace('camp_reg_', '', 1)
        else:
            user_profile['mode'] = full_mode_id

    mode = user_profile.get('mode')

    # --- Main Menu Display ---
    if not mode:
        interactive = {
            "type": "list",
            "header": {"type": "text", "text": "Welcome to SundayBot 🙏"},
            "body": {"text": "I can help you with lessons, hymns, camp registration, and more. Please choose an option:"},
            "footer": {"text": "Select from the list below"},
            "action": {
                "button": "Choose an option",
                "sections": [
                    {
                        "title": "Main Menu",
                        "rows": [
                            {"id": "mode_lessons", "title": "📖 Weekly Lessons"},
                            {"id": "mode_hymnbook", "title": "🎶 Hymnbook"},
                            {"id": "mode_bible", "title": "✝️ Bible Lookup"},
                            {"id": "mode_camp_reg_youths", "title": "🏕️ Youths Camp Reg."},
                            {"id": "mode_camp_reg_annual", "title": "🏕️ Annual Camp Reg."},
                            {"id": "mode_check_status", "title": "✅ Check Registration"}
                        ]
                    }
                ]
            }
        }
        send_interactive_message(user_id, interactive)
        session_ref.set(user_profile)
        return

    # --- Module Execution ---
    if mode == 'lessons':
        step = user_profile.get('lesson_step', 'start')
        if step == 'start':
            interactive = {
                "type": "list", "header": {"type": "text", "text": "Select Your Class"},
                "body": {"text": "Please choose your Sunday School class from the list."},
                "action": { "button": "View Classes", "sections": [{"title": "Classes", "rows": [{"id": f"lesson_class_{key}", "title": name} for key, name in CLASSES.items()]}]}
            }
            send_interactive_message(user_id, interactive)
            user_profile['lesson_step'] = 'awaiting_class_choice'
        
        elif step == 'awaiting_class_choice' and message_text_lower.startswith('lesson_class_'):
            class_key = message_text_lower.replace('lesson_class_', '', 1)
            user_class = CLASSES.get(class_key)
            if not user_class:
                send_text_message(user_id, "Invalid class selection. Please try again.")
                session_ref.delete()
                return

            user_profile['lesson_class'] = user_class
            
            lesson_files = { "Beginners": "beginners_lessons.json", "Primary Pals": "primary_pals_lessons.json", "Answer": "answer_lessons.json", "Search": "search_lessons.json" }
            lesson_file_path = os.path.join(os.path.dirname(__file__), LESSONS_DIR, lesson_files.get(user_class, ''))
            raw_data = load_json_file(lesson_file_path)
            if user_class == "Primary Pals" and isinstance(raw_data, dict): all_lessons = raw_data.get('primary_pals_lessons', [])
            elif isinstance(raw_data, list): all_lessons = raw_data
            else: all_lessons = []
            lesson_index = get_current_lesson_index(user_class)

            if all_lessons and 0 <= lesson_index < len(all_lessons):
                current_lesson = all_lessons[lesson_index]
                user_profile['current_lesson_data'] = current_lesson
                title = current_lesson.get('title') or current_lesson.get('lessonTitle', 'N/A')
                interactive = {
                    "type": "button",
                    "body": {"text": f"This week's lesson for *{user_class}* is:\n\n*{title}*\n\nWhat would you like to do?"},
                    "action": {"buttons": [{"type": "reply", "reply": {"id": "lesson_read", "title": "📖 Read Lesson"}}, {"type": "reply", "reply": {"id": "lesson_ask", "title": "❓ Ask a Question"}}]}
                }
                send_interactive_message(user_id, interactive)
                user_profile['lesson_step'] = 'awaiting_lesson_action'
            else:
                send_text_message(user_id, "Sorry, I couldn't find the current lesson for your class.")
                session_ref.delete()

        elif step == 'awaiting_lesson_action':
            if message_text_lower == 'lesson_read':
                formatted_lesson = format_lesson(user_profile.get('current_lesson_data'), user_profile.get('lesson_class'))
                send_text_message(user_id, formatted_lesson)
                interactive = { "type": "button", "body": {"text": "What next?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "lesson_read", "title": "📖 Read Again"}}, {"type": "reply", "reply": {"id": "lesson_ask", "title": "❓ Ask a Question"}}, {"type": "reply", "reply": {"id": "reset", "title": "⬅️ Main Menu"}}]} }
                send_interactive_message(user_id, interactive)
            elif message_text_lower == 'lesson_ask':
                send_text_message(user_id, "OK, please type your question about the lesson. To return to the main menu, send 'reset'.")
                user_profile['lesson_step'] = 'awaiting_ai_question'

        elif step == 'awaiting_ai_question':
            if message_text_lower not in ['lesson_read', 'lesson_ask']:
                context = format_lesson(user_profile.get('current_lesson_data'), user_profile.get('lesson_class'))
                send_text_message(user_id, "_Thinking..._ 🤔")
                ai_answer = get_ai_response(message_text, context)
                send_text_message(user_id, ai_answer)
                send_text_message(user_id, "You can ask another question, or go back to the main menu by tapping the button below.")
                interactive = { "type": "button", "body": {"text": "Finished asking questions?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "reset", "title": "⬅️ Main Menu"}}]} }
                send_interactive_message(user_id, interactive)
    
    elif mode == 'hymnbook':
        step = user_profile.get('hymn_step', 'start')
        if step == 'start':
            interactive = {
                "type": "list", "header": {"type": "text", "text": "Select Hymnbook"},
                "body": {"text": "Please choose a hymnbook from the list."},
                "action": { "button": "View Hymnbooks", "sections": [{"title": "Hymnbooks", "rows": [{"id": f"hymnbook_{key}", "title": book['name']} for key, book in HYMNBOOKS.items()]}]}
            }
            send_interactive_message(user_id, interactive)
            user_profile['hymn_step'] = 'awaiting_hymnbook_choice'

        elif step == 'awaiting_hymnbook_choice' and message_text_lower.startswith('hymnbook_'):
            hymnbook_key = message_text_lower.replace('hymnbook_', '', 1)
            chosen_book = HYMNBOOKS.get(hymnbook_key)
            if not chosen_book:
                send_text_message(user_id, "Invalid hymnbook selection. Please try again.")
                session_ref.delete()
                return
            
            user_profile['hymnbook_file'] = chosen_book['file']
            send_text_message(user_id, f"You've selected *{chosen_book['name']}*. Please enter a hymn number.")
            user_profile['hymn_step'] = 'awaiting_hymn_number'
        
        elif step == 'awaiting_hymn_number':
            if not message_text.strip().isdigit():
                send_text_message(user_id, "Please enter a valid number.")
            else:
                hymn_file_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, user_profile['hymnbook_file'])
                all_hymns = load_json_file(hymn_file_path)
                found_hymn = next((h for h in all_hymns if str(h.get('number')) == message_text.strip()), None)
                send_text_message(user_id, format_hymn(found_hymn))
                send_text_message(user_id, "You can enter another hymn number or return to the main menu.")
                interactive = { "type": "button", "body": {"text": "Finished with hymns?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "reset", "title": "⬅️ Main Menu"}}]} }
                send_interactive_message(user_id, interactive)

    elif mode == 'bible':
        step = user_profile.get('bible_step', 'start')
        if step == 'start':
            interactive = {
                "type": "list", "header": {"type": "text", "text": "Select Bible Version"},
                "body": {"text": "Please choose a Bible version from the list."},
                "action": { "button": "View Versions", "sections": [{"title": "Bibles", "rows": [{"id": f"bible_{key}", "title": bible['name']} for key, bible in BIBLES.items()]}]}
            }
            send_interactive_message(user_id, interactive)
            user_profile['bible_step'] = 'awaiting_bible_choice'
        
        elif step == 'awaiting_bible_choice' and message_text_lower.startswith('bible_'):
            bible_key = message_text_lower.replace('bible_', '', 1)
            chosen_bible = BIBLES.get(bible_key)
            if not chosen_bible:
                send_text_message(user_id, "Invalid Bible selection. Please try again.")
                session_ref.delete()
                return

            user_profile['bible_file'] = chosen_bible['file']
            send_text_message(user_id, f"You've selected the *{chosen_bible['name']}*. Please enter a passage (e.g., John 3:16).")
            user_profile['bible_step'] = 'awaiting_passage'

        elif step == 'awaiting_passage':
            verse_text = get_verse_from_db(message_text.strip(), user_profile['bible_file'])
            send_text_message(user_id, verse_text)
            send_text_message(user_id, "You can enter another passage or return to the main menu.")
            interactive = { "type": "button", "body": {"text": "Finished looking up verses?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "reset", "title": "⬅️ Main Menu"}}]} }
            send_interactive_message(user_id, interactive)

    elif mode == 'camp_registration':
        step = user_profile.get('registration_step', 'start')
        data = user_profile.setdefault('registration_data', {})
        reg_type = user_profile.get('registration_type', 'annual')
        
        if step == 'start':
            camp_name = "2025 Regional Youths Camp" if reg_type == 'youths' else "2025 Annual Camp"
            send_text_message(user_id, f"🏕️ *{camp_name} Registration*\n\nLet's get you registered. First, what is your *ID or Passport number*?")
            user_profile['registration_step'] = 'awaiting_id_passport'
        
        elif step == 'awaiting_id_passport':
            id_passport = message_text.strip()
            if not id_passport:
                send_text_message(user_id, "ID/Passport number cannot be empty. Please try again.")
                return

            send_text_message(user_id, f"Checking if `{id_passport}` is already registered...")
            existing_reg = check_registration_status_firestore(id_passport, reg_type)
            
            if isinstance(existing_reg, dict):
                reg_name = f"{existing_reg.get('first_name', '')} {existing_reg.get('last_name', '')}"
                send_text_message(user_id, f"It looks like you are already registered under the name *{reg_name}* with this ID. No need to register again!\n\nReturning to the main menu.")
                session_ref.delete()
                return
            elif existing_reg == "Error":
                send_text_message(user_id, "I'm having trouble checking for duplicates right now. Please contact an admin.")
                session_ref.delete()
                return
            else: 
                data['id_passport'] = id_passport
                send_text_message(user_id, "Great, you are not already registered. Now, what is your *first name*?")
                user_profile['registration_step'] = 'awaiting_first_name'

        elif step == 'awaiting_first_name':
            data['first_name'] = message_text.strip()
            send_text_message(user_id, "And your *last name*?")
            user_profile['registration_step'] = 'awaiting_last_name'

        elif step == 'awaiting_last_name':
            data['last_name'] = message_text.strip()
            send_text_message(user_id, "Got it. What is your *date of birth*? (DD/MM/YYYY)")
            user_profile['registration_step'] = 'awaiting_dob'
        
        elif step == 'awaiting_dob':
            dob_string = message_text.strip()
            age = calculate_age(dob_string)
            if age is None:
                send_text_message(user_id, "Invalid date format. Please use DD/MM/YYYY (e.g., 25/12/1990).")
                return
            
            data['dob'] = dob_string
            data['age'] = age
            send_text_message(user_id, "What is your *gender*?")
            interactive = {
                "type": "button",
                "body": {"text": "Please select your gender:"},
                "action": {"buttons": [{"type": "reply", "reply": {"id": "gender_male", "title": "Male"}}, {"type": "reply", "reply": {"id": "gender_female", "title": "Female"}}]}
            }
            send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_gender'
        
        elif step == 'awaiting_gender' and message_text_lower.startswith('gender_'):
            gender = message_text_lower.replace('gender_', '', 1)
            if gender not in ['male', 'female']:
                send_text_message(user_id, "Invalid gender selection. Please use the buttons.")
                return
            data['gender'] = gender.capitalize()
            send_text_message(user_id, "What is your *phone number* (e.g., +263771234567)?")
            user_profile['registration_step'] = 'awaiting_phone'

        elif step == 'awaiting_phone':
            phone_number = message_text.strip()
            if not re.fullmatch(r'^\+\d{1,3}\d{9}$', phone_number):
                send_text_message(user_id, "Invalid phone number format. Please include country code, e.g., +263771234567.")
                return
            data['phone'] = phone_number
            send_text_message(user_id, "What is your *salvation status*?")
            interactive = {
                "type": "button",
                "body": {"text": "Please select your salvation status:"},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": "salvation_born_again", "title": "Born Again"}},
                    {"type": "reply", "reply": {"id": "salvation_not_born_again", "title": "Not Born Again"}}
                ]}
            }
            send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_salvation_status'
            
        elif step == 'awaiting_salvation_status' and message_text_lower.startswith('salvation_'):
            status = message_text_lower.replace('salvation_', '', 1).replace('_', ' ').title()
            data['salvation_status'] = status
            
            if reg_type == 'annual':
                send_text_message(user_id, "Are you registering any *dependents* (children/family under your care)? Reply 'Yes' or 'No'.")
                user_profile['registration_step'] = 'awaiting_dependents_status'
            else: # Youth Camp does not have dependents
                data['dependents'] = 'No'
                send_text_message(user_id, "Are you a *worker* (Minister, Deacon, Sunday school teacher)? Reply 'Yes' or 'No'.")
                user_profile['registration_step'] = 'awaiting_is_worker'

        elif step == 'awaiting_dependents_status':
            response = message_text_lower
            if response in ['yes', 'no']:
                data['dependents'] = response.capitalize()
                send_text_message(user_id, "Are you a *worker* (Minister, Deacon, Sunday school teacher)? Reply 'Yes' or 'No'.")
                user_profile['registration_step'] = 'awaiting_is_worker'
            else:
                send_text_message(user_id, "Invalid response. Please reply 'Yes' or 'No'.")
        
        elif step == 'awaiting_is_worker':
            response = message_text_lower
            if response in ['yes', 'no']:
                data['is_worker'] = response.capitalize()
                if response == 'yes':
                    worker_options = [{"id": f"worker_{key}", "title": name} for key, name in WORKER_TYPES.items() if key != "none"]
                    interactive = {
                        "type": "list", "header": {"type": "text", "text": "Select Worker Type"},
                        "body": {"text": "What type of worker are you?"},
                        "action": { "button": "View Worker Types", "sections": [{"title": "Worker Types", "rows": worker_options}]}
                    }
                    send_interactive_message(user_id, interactive)
                    user_profile['registration_step'] = 'awaiting_worker_type'
                else:
                    data['worker_type'] = 'N/A'
                    send_text_message(user_id, "Do you wish to *volunteer* for any department during the camp? Reply 'Yes' or 'No'.")
                    user_profile['registration_step'] = 'awaiting_volunteer_status'
            else:
                send_text_message(user_id, "Invalid response. Please reply 'Yes' or 'No'.")

        elif step == 'awaiting_worker_type' and message_text_lower.startswith('worker_'):
            worker_key = message_text_lower.replace('worker_', '', 1)
            worker_type_name = WORKER_TYPES.get(worker_key)
            if not worker_type_name or worker_key == 'none':
                send_text_message(user_id, "Invalid worker type selection. Please use the buttons.")
                return
            data['worker_type'] = worker_type_name
            send_text_message(user_id, "Do you wish to *volunteer* for any department during the camp? Reply 'Yes' or 'No'.")
            user_profile['registration_step'] = 'awaiting_volunteer_status'

        elif step == 'awaiting_volunteer_status':
            response = message_text_lower
            if response in ['yes', 'no']:
                data['volunteer_status'] = response.capitalize()
                if response == 'yes':
                    department_options = [{"id": f"dept_{key}", "title": name} for key, name in DEPARTMENTS.items()]
                    interactive = {
                        "type": "list", "header": {"type": "text", "text": "Select Department"},
                        "body": {"text": "Which department would you like to volunteer for?"},
                        "action": { "button": "View Departments", "sections": [{"title": "Departments", "rows": department_options}]}
                    }
                    send_interactive_message(user_id, interactive)
                    user_profile['registration_step'] = 'awaiting_volunteer_department'
                else:
                    data['volunteer_department'] = 'N/A'
                    send_text_message(user_id, "Do you need *transport assistance* upon arrival at the camp? Reply 'Yes' or 'No'.")
                    user_profile['registration_step'] = 'awaiting_transport_assistance'
            else:
                send_text_message(user_id, "Invalid response. Please reply 'Yes' or 'No'.")

        elif step == 'awaiting_volunteer_department' and message_text_lower.startswith('dept_'):
            dept_key = message_text_lower.replace('dept_', '', 1)
            department_name = DEPARTMENTS.get(dept_key)
            if not department_name:
                send_text_message(user_id, "Invalid department selection. Please use the buttons.")
                return
            data['volunteer_department'] = department_name
            send_text_message(user_id, "Do you need *transport assistance* upon arrival at the camp? Reply 'Yes' or 'No'.")
            user_profile['registration_step'] = 'awaiting_transport_assistance'
        
        elif step == 'awaiting_transport_assistance':
            response = message_text_lower
            if response in ['yes', 'no']:
                data['transport_assistance'] = response.capitalize()
                send_text_message(user_id, "What is the *full name of your next of kin*?")
                user_profile['registration_step'] = 'awaiting_nok_name'
            else:
                send_text_message(user_id, "Invalid response. Please reply 'Yes' or 'No'.")

        elif step == 'awaiting_nok_name':
            data['nok_name'] = message_text.strip()
            send_text_message(user_id, "What is your *next of kin's phone number* (e.g., +263771234567)?")
            user_profile['registration_step'] = 'awaiting_nok_phone'

        elif step == 'awaiting_nok_phone':
            nok_phone = message_text.strip()
            if not re.fullmatch(r'^\+\d{1,3}\d{9}$', nok_phone):
                send_text_message(user_id, "Invalid phone number format. Please include country code, e.g., +263771234567.")
                return
            data['nok_phone'] = nok_phone
            
            # Camp Stay Dates
            send_text_message(user_id, "What *date do you plan to arrive* at the camp? (DD/MM/YYYY)")
            user_profile['registration_step'] = 'awaiting_camp_start_date'

        elif step == 'awaiting_camp_start_date':
            camp_start_date_str = message_text.strip()
            try:
                camp_start_date = datetime.strptime(camp_start_date_str, "%d/%m/%Y").date()
                data['camp_start'] = camp_start_date_str
                send_text_message(user_id, "What *date do you plan to leave* the camp? (DD/MM/YYYY)")
                user_profile['registration_step'] = 'awaiting_camp_end_date'
            except ValueError:
                send_text_message(user_id, "Invalid date format. Please use DD/MM/YYYY (e.g., 01/08/2025).")

        elif step == 'awaiting_camp_end_date':
            camp_end_date_str = message_text.strip()
            try:
                camp_end_date = datetime.strptime(camp_end_date_str, "%d/%m/%Y").date()
                data['camp_end'] = camp_end_date_str
                
                # Summary and Confirmation
                summary = (
                    f"📝 *Registration Summary for {reg_type.capitalize()} Camp:*\n\n"
                    f"Name: {data.get('first_name')} {data.get('last_name')}\n"
                    f"ID/Passport: {data.get('id_passport')}\n"
                    f"Date of Birth: {data.get('dob')} (Age: {data.get('age')})\n"
                    f"Gender: {data.get('gender')}\n"
                    f"Phone: {data.get('phone')}\n"
                    f"Salvation Status: {data.get('salvation_status')}\n"
                )
                if reg_type == 'annual':
                    summary += f"Dependents: {data.get('dependents')}\n"
                summary += (
                    f"Worker: {data.get('is_worker')}\n"
                    f"Worker Type: {data.get('worker_type')}\n"
                    f"Volunteering: {data.get('volunteer_status')}\n"
                    f"Department: {data.get('volunteer_department')}\n"
                    f"Transport Assistance: {data.get('transport_assistance')}\n"
                    f"Next of Kin: {data.get('nok_name')} ({data.get('nok_phone')})\n"
                    f"Camp Stay: {data.get('camp_start')} to {data.get('camp_end')}\n\n"
                    "Does this all look correct?"
                )
                
                interactive = {
                    "type": "button",
                    "body": {"text": summary},
                    "action": {"buttons": [{"type": "reply", "reply": {"id": "reg_confirm_yes", "title": "✅ Yes, Confirm"}}, {"type": "reply", "reply": {"id": "reg_confirm_no", "title": "❌ No, Restart"}}]}
                }
                send_interactive_message(user_id, interactive)
                user_profile['registration_step'] = 'awaiting_final_confirmation'
            except ValueError:
                send_text_message(user_id, "Invalid date format. Please use DD/MM/YYYY (e.g., 10/08/2025).")

        elif step == 'awaiting_final_confirmation' and message_text_lower.startswith('reg_confirm_'):
            confirmation = message_text_lower.replace('reg_confirm_', '', 1)
            if confirmation == 'yes':
                try:
                    collection_name = get_firestore_collection_name(reg_type)
                    doc_ref = db.collection(collection_name).document(data['id_passport'])
                    data['timestamp'] = firestore.SERVER_TIMESTAMP
                    doc_ref.set(data)
                    send_text_message(user_id, "🎉 *Registration Complete!* 🎉\n\nThank you for registering. We look forward to seeing you at camp!\n\nReturning to the main menu.")
                except Exception as e:
                    print(f"Firestore save error: {e}")
                    send_text_message(user_id, "There was an error saving your registration. Please try again later or contact an administrator.")
                session_ref.delete()
            else:
                send_text_message(user_id, "Okay, let's restart your registration. To begin, what is your *ID or Passport number*?")
                user_profile['registration_data'] = {}
                user_profile['registration_step'] = 'awaiting_id_passport'
    
    elif mode == 'check_status':
        step = user_profile.get('check_status_step', 'start')
        if step == 'start':
            send_text_message(user_id, "Which camp registration status do you want to check?")
            interactive = {
                "type": "button",
                "body": {"text": "Please choose a camp type:"},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": "check_status_youths", "title": "Youths Camp"}},
                    {"type": "reply", "reply": {"id": "check_status_annual", "title": "Annual Camp"}}
                ]}
            }
            send_interactive_message(user_id, interactive)
            user_profile['check_status_step'] = 'awaiting_camp_type'

        elif step == 'awaiting_camp_type' and message_text_lower.startswith('check_status_'):
            camp_type = message_text_lower.replace('check_status_', '', 1)
            if camp_type not in ['youths', 'annual']:
                send_text_message(user_id, "Invalid camp type. Please use the buttons.")
                session_ref.delete()
                return

            user_profile['check_camp_type'] = camp_type
            send_text_message(user_id, f"You've selected *{camp_type.capitalize()} Camp*. Please enter the *ID or Passport number* you used for registration.")
            user_profile['check_status_step'] = 'awaiting_id_for_check'

        elif step == 'awaiting_id_for_check':
            identifier = message_text.strip()
            if not identifier:
                send_text_message(user_id, "ID/Passport number cannot be empty. Please try again.")
                return
            
            camp_type = user_profile.get('check_camp_type')
            send_text_message(user_id, f"Checking status for `{identifier}` in *{camp_type} camp*...")
            status_data = check_registration_status_firestore(identifier, camp_type)

            if isinstance(status_data, dict):
                summary = (
                    f"✅ *Registration Found for {status_data.get('first_name')} {status_data.get('last_name')}* ✅\n\n"
                    f"Camp Type: {camp_type.capitalize()} Camp\n"
                    f"ID/Passport: {status_data.get('id_passport')}\n"
                    f"Phone: {status_data.get('phone')}\n"
                    f"Registered On: {status_data.get('timestamp').strftime('%Y-%m-%d %H:%M:%S') if status_data.get('timestamp') else 'N/A'}\n"
                    f"Camp Stay: {status_data.get('camp_start', '')} to {status_data.get('camp_end', '')}\n"
                )
                if status_data.get('is_worker'):
                    summary += f"Worker: {status_data.get('is_worker')}\n"
                    summary += f"Worker Type: {status_data.get('worker_type')}\n"
                if status_data.get('transport_assistance'):
                    summary += f"Transport Assistance: {status_data.get('transport_assistance')}\n"
                summary += "\nYou are all set!"
                send_text_message(user_id, summary)
            elif status_data is None:
                send_text_message(user_id, f"❌ No registration found for `{identifier}` in *{camp_type.capitalize()} Camp*.")
            else: # "Error"
                send_text_message(user_id, "I'm having trouble checking the status right now. Please try again later.")
            
            send_text_message(user_id, "Returning to the main menu.")
            session_ref.delete()

    session_ref.set(user_profile) # Save session state


@app.route('/whatsapp/webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode and token:
            if mode == 'subscribe' and token == VERIFY_TOKEN:
                print("WEBHOOK_VERIFIED")
                return challenge, 200
            else:
                return "Verification token mismatch", 403
        return "Missing parameters", 400
    
    elif request.method == 'POST':
        data = request.get_json()
        print(f"Received webhook event: {json.dumps(data, indent=2)}")

        if 'object' in data and 'entry' in data:
            for entry in data['entry']:
                for change in entry['changes']:
                    if 'value' in change and 'messages' in change['value']:
                        for message in change['value']['messages']:
                            if message['type'] == 'text':
                                user_id = message['from']
                                message_text = message['text']['body']
                                handle_bot_logic(user_id, message_text)
                            elif message['type'] == 'interactive':
                                user_id = message['from']
                                if 'button_reply' in message['interactive']:
                                    button_id = message['interactive']['button_reply']['id']
                                    handle_bot_logic(user_id, button_id)
                                elif 'list_reply' in message['interactive']:
                                    list_id = message['interactive']['list_reply']['id']
                                    handle_bot_logic(user_id, list_id)
        return 'OK', 200
