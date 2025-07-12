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
        headers = ["Timestamp", "FirstName", "LastName", "DateOfBirth", "Age", "Gender", "ID/Passport", "Phone", "SalvationStatus", "Dependents", "Volunteering", "VolunteerDepartment", "NextOfKinName", "NextOfKinPhone", "CampStay"]
        all_rows.append(headers)

        for doc in docs:
            data = doc.to_dict()
            timestamp_obj = data.get("timestamp")
            timestamp_str = timestamp_obj.strftime("%Y-%m-%d %H:%M:%S") if isinstance(timestamp_obj, datetime) else ""
            
            row = [
                timestamp_str, data.get("first_name", ""), data.get("last_name", ""), data.get("dob", ""),
                data.get("age", ""), data.get("gender", ""), data.get("id_passport", ""), data.get("phone", ""),
                data.get("salvation_status", ""), data.get("dependents", ""), data.get("volunteer_status", ""),
                data.get("volunteer_department", ""), data.get("nok_name", ""), data.get("nok_phone", ""),
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
            message_parts.append(f"✝️ *Bible Reference:* {', '.join(ref_texts)}")
        if lesson.get('supplementalScripture'): message_parts.append(f"*Supplemental Scripture:* {lesson['supplementalScripture']}")
        if lesson.get('keyVerse'): message_parts.append(f"📌 *Key Verse:*\n_{lesson['keyVerse']}_")
        if lesson.get('resourceMaterial'): message_parts.append(f"📚 *Resource Material:*\n{lesson['resourceMaterial']}")
        message_parts.append("---")
        for section in lesson.get('lessonSections', []):
            sec_title = section.get('sectionTitle', '')
            sec_content = section.get('sectionContent', '')
            if section.get('sectionType') == 'text': message_parts.append(f"📝 *{sec_title}*\n{sec_content}")
            elif section.get('sectionType') == 'question':
                q_num = section.get('questionNumber', '')
                message_parts.append(f"❓ *Question {q_num}:*\n{sec_content}")
    elif lesson_class == "Primary Pals":
        title = lesson.get('title', 'No Title')
        message_parts.append(f"🎨 *{title}*")
        parent_guide = lesson.get('parent_guide', {})
        memory_verse = parent_guide.get('memory_verse', {}).get('text', '')
        if memory_verse: message_parts.append(f"📌 *Memory Verse:*\n_{memory_verse}_")
        message_parts.append("---")
        story = lesson.get('story', [])
        if story: message_parts.append("📖 *Story*\n" + "\n\n".join(story))
        activities = lesson.get('activities', [])
        if activities:
            activity_texts = ["🧩 *Activities*"]
            for act in activities:
                act_title = act.get('title', '')
                act_instr = "\n".join(act.get('instructions', [])) if isinstance(act.get('instructions'), list) else act.get('instructions', '')
                activity_texts.append(f"*{act.get('type')}: {act_title}*\n{act_instr}")
            message_parts.append("\n".join(activity_texts))
        if parent_guide:
            guide_texts = ["👨‍👩‍👧 *Parent's Guide*"]
            corner = parent_guide.get('parents_corner', {}).get('text', '')
            if corner: guide_texts.append(f"*Parent's Corner:*\n{corner}")
            devotions = parent_guide.get('family_devotions', {}).get('verses', [])
            if devotions:
                devotion_lines = ["*Family Devotions:*"]
                for dev in devotions: devotion_lines.append(f"  - *{dev.get('day')}:* {dev.get('reference')}")
                guide_texts.append("\n".join(devotion_lines))
            message_parts.append("\n".join(guide_texts))
    else:
        title = lesson.get('title', 'No Title')
        memory_verse = lesson.get('memory_verse', 'N/A')
        main_text = "\n".join(lesson.get('text', []))
        message_parts.append(f"📖 *{title}*\n\n📌 *Memory Verse:*\n_{memory_verse}_\n\n📝 *Lesson Text:*\n{main_text}")
    return "\n\n".join(message_parts)
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

# --- 5. MAIN BOT LOGIC HANDLER ---
def handle_bot_logic(user_id, message_text):
    if not db:
        send_text_message(user_id, "Sorry, the bot is experiencing technical difficulties (Database connection failed). Please try again later.")
        return

    session_ref = db.collection('sessions').document(user_id)
    session_doc = session_ref.get()
    user_profile = session_doc.to_dict() if session_doc.exists else {}
    
    message_text_lower = message_text.lower().strip()

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

    if message_text_lower == 'reset_session':
        session_ref.delete()
        user_profile = {}

    if message_text_lower.startswith("mode_"):
        mode_parts = message_text_lower.split('_')
        mode = mode_parts[1]
        user_profile['mode'] = mode
        if mode == 'camp_reg':
            user_profile['registration_type'] = mode_parts[2]
            user_profile['mode'] = 'camp_registration'
        
        # Clear step data for the new mode
        for key in list(user_profile.keys()):
            if key.endswith('_step') or key.endswith('_data'):
                del user_profile[key]

    mode = user_profile.get('mode')

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
        session_ref.set(user_profile) # Save empty profile to avoid re-triggering
        return

    # --- Module Logic ---
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
            class_key = message_text_lower.split('_')[-1]
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
                interactive = { "type": "button", "body": {"text": "What next?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "lesson_read", "title": "📖 Read Again"}}, {"type": "reply", "reply": {"id": "lesson_ask", "title": "❓ Ask a Question"}}, {"type": "reply", "reply": {"id": "reset_session", "title": "⬅️ Main Menu"}}]} }
                send_interactive_message(user_id, interactive)
            elif message_text_lower == 'lesson_ask':
                send_text_message(user_id, "OK, please type your question about the lesson. To return to the main menu, send 'reset_session'.")
                user_profile['lesson_step'] = 'awaiting_ai_question'

        elif step == 'awaiting_ai_question':
            if message_text_lower not in ['lesson_read', 'lesson_ask']:
                context = format_lesson(user_profile.get('current_lesson_data'), user_profile.get('lesson_class'))
                send_text_message(user_id, "_Thinking..._ 🤔")
                ai_answer = get_ai_response(message_text, context)
                send_text_message(user_id, ai_answer)
                send_text_message(user_id, "You can ask another question, or go back to the main menu by tapping the button below.")
                interactive = { "type": "button", "body": {"text": "Finished asking questions?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "reset_session", "title": "⬅️ Main Menu"}}]} }
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
            hymnbook_key = message_text_lower.split('_')[-1]
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
                interactive = { "type": "button", "body": {"text": "Finished with hymns?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "reset_session", "title": "⬅️ Main Menu"}}]} }
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
            bible_key = message_text_lower.split('_')[-1]
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
            interactive = { "type": "button", "body": {"text": "Finished looking up verses?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "reset_session", "title": "⬅️ Main Menu"}}]} }
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
            age = calculate_age(message_text.strip())
            if not age: send_text_message(user_id, "That doesn't look right. Please use DD/MM/YYYY format.")
            else:
                data.update({'dob': message_text.strip(), 'age': age})
                send_text_message(user_id, "What is your *gender*? (Male / Female)")
                user_profile['registration_step'] = 'awaiting_gender'
        elif step == 'awaiting_gender':
            if message_text_lower not in ['male', 'female']: send_text_message(user_id, "Please just answer with *Male* or *Female*.")
            else:
                data['gender'] = message_text.strip().capitalize()
                send_text_message(user_id, "Please enter your *phone number* (e.g., +263771234567).")
                user_profile['registration_step'] = 'awaiting_phone_number'
        elif step == 'awaiting_phone_number':
            if not re.match(r'^\+\d{9,}$', message_text.strip()): send_text_message(user_id, "Hmm, that doesn't seem like a valid international phone number.")
            else:
                data['phone'] = message_text.strip()
                interactive = {"type": "button", "body": {"text": "Are you saved?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "yes", "title": "Yes"}}, {"type": "reply", "reply": {"id": "no", "title": "No"}}]}}
                send_interactive_message(user_id, interactive)
                user_profile['registration_step'] = 'awaiting_salvation_status'
        elif step == 'awaiting_salvation_status':
            if message_text_lower not in ['yes', 'no']: send_text_message(user_id, "Please tap *Yes* or *No*.")
            else:
                data['salvation_status'] = message_text.strip().capitalize()
                send_text_message(user_id, "How many dependents (e.g., children) will be attending with you? (Enter 0 if none)")
                user_profile['registration_step'] = 'awaiting_dependents'
        elif step == 'awaiting_dependents':
            if not message_text.strip().isdigit(): send_text_message(user_id, "Please enter a number (e.g., 0, 1, 2).")
            else:
                data['dependents'] = message_text.strip()
                send_text_message(user_id, "Who is your *next of kin*? (Full name).")
                user_profile['registration_step'] = 'awaiting_nok_name'
        elif step == 'awaiting_nok_name':
            data['nok_name'] = message_text.strip()
            send_text_message(user_id, "What is your *next of kin's phone number*?")
            user_profile['registration_step'] = 'awaiting_nok_phone'
        elif step == 'awaiting_nok_phone':
            if not re.match(r'^\+\d{9,}$', message_text.strip()): send_text_message(user_id, "That doesn't look like a valid phone number.")
            else:
                data['nok_phone'] = message_text.strip()
                camp_dates_text = "Aug 17 to Aug 24, 2025" if reg_type == 'youths' else "Dec 7 to Dec 21, 2025"
                send_text_message(user_id, f"The camp runs from {camp_dates_text}.\n\nWhat is your *arrival date*? (e.g., Aug 17)")
                user_profile['registration_step'] = 'awaiting_camp_start_date'
        elif step == 'awaiting_camp_start_date':
            data['camp_start'] = message_text.strip()
            send_text_message(user_id, "And your *departure date*?")
            user_profile['registration_step'] = 'awaiting_camp_end_date'
        elif step == 'awaiting_camp_end_date':
            data['camp_end'] = message_text.strip()
            interactive = {"type": "button", "body": {"text": "Are you willing to assist voluntarily?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "yes", "title": "Yes, I'll help"}}, {"type": "reply", "reply": {"id": "no", "title": "No, thanks"}}]}}
            send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_volunteer_status'
        elif step == 'awaiting_volunteer_status':
            if message_text_lower not in ['yes', 'no']: send_text_message(user_id, "Please tap one of the buttons.")
            else:
                data['volunteer_status'] = "Yes" if message_text_lower == 'yes' else "No"
                if message_text_lower == 'yes':
                    interactive = { "type": "list", "header": {"type": "text", "text": "Select Department"}, "body": {"text": "That's wonderful! Please choose a department where you'd like to help."}, "action": { "button": "View Departments", "sections": [{"title": "Departments", "rows": [{"id": f"dept_{key}", "title": name} for key, name in DEPARTMENTS.items()]}]} }
                    send_interactive_message(user_id, interactive)
                    user_profile['registration_step'] = 'awaiting_volunteer_department'
                else:
                    data['volunteer_department'] = 'N/A'
                    _send_confirmation_message(user_id, data, "Camp")
                    user_profile['registration_step'] = 'awaiting_confirmation'
        elif step == 'awaiting_volunteer_department' and message_text_lower.startswith('dept_'):
            dept_key = message_text_lower.split('_')[-1]
            data['volunteer_department'] = DEPARTMENTS[dept_key]
            _send_confirmation_message(user_id, data, "Camp")
            user_profile['registration_step'] = 'awaiting_confirmation'

        elif step == 'awaiting_confirmation':
            if message_text_lower == 'confirm_reg':
                data['timestamp'] = firestore.SERVER_TIMESTAMP
                collection_name = get_firestore_collection_name(reg_type)
                doc_ref = db.collection(collection_name).document(data['id_passport'])
                doc_ref.set(data)
                send_text_message(user_id, "✅ Registration successful! Your details have been saved to our database.")
                session_ref.delete()
                return
            elif message_text_lower == 'restart_reg':
                user_profile['registration_step'] = 'start'
                user_profile['registration_data'] = {}
                handle_bot_logic(user_id, "restart_internal")
                return

    elif mode == 'check_status':
        step = user_profile.get('check_step', 'start')
        if step == 'start':
            interactive = {"type": "button", "body": {"text": "Which camp registration would you like to check?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "check_youths", "title": "Youths Camp"}}, {"type": "reply", "reply": {"id": "check_annual", "title": "Annual Camp"}}]}}
            send_interactive_message(user_id, interactive)
            user_profile['check_step'] = 'awaiting_camp_choice'
        
        elif step == 'awaiting_camp_choice' and message_text_lower.startswith('check_'):
            camp_type = message_text_lower.split('_')[-1]
            user_profile['camp_to_check'] = camp_type
            send_text_message(user_id, "Got it. Please enter the *ID/Passport Number* you used to register.")
            user_profile['check_step'] = 'awaiting_identifier'
        
        elif step == 'awaiting_identifier':
            identifier = message_text.strip()
            camp_type = user_profile.get('camp_to_check')
            send_text_message(user_id, f"Checking for '{identifier}'...")
            status = check_registration_status_firestore(identifier, camp_type)
            
            if status == "Error":
                 send_text_message(user_id, "Sorry, a technical error occurred. Please try again later.")
            elif isinstance(status, dict):
                confirm_msg = (
                    f"✅ *Registration Found!* ✅\n\n"
                    f"Hi *{status.get('first_name', '')} {status.get('last_name', '')}*!\n"
                    f"Your registration is confirmed.\n\n"
                    f"*ID/Passport:* {status.get('id_passport', '')}\n"
                    f"*Phone:* {status.get('phone', '')}"
                )
                send_text_message(user_id, confirm_msg)
            else:
                send_text_message(user_id, f"❌ *No Registration Found*\n\nI could not find a registration matching '{identifier}'.")
            
            session_ref.delete()
            return
    
    session_ref.set(user_profile)

def _send_confirmation_message(user_id, data, camp_name):
    conf_text = (
        f"📝 *Please confirm your details for the {camp_name}:*\n\n"
        f"*Name:* {data.get('first_name', '')} {data.get('last_name', '')}\n"
        f"*Gender:* {data.get('gender', '')}\n"
        f"*Date of Birth:* {data.get('dob', '')} (Age: {data.get('age', 'N/A')})\n"
        f"*ID/Passport:* {data.get('id_passport', '')}\n"
        f"*Phone:* {data.get('phone', '')}\n\n"
        f"*Salvation Status:* {data.get('salvation_status', '')}\n"
        f"*Dependents Attending:* {data.get('dependents', '0')}\n"
        f"*Volunteering:* {data.get('volunteer_status', '')}"
        f"{' (' + data.get('volunteer_department', '') + ')' if data.get('volunteer_status') == 'Yes' else ''}\n\n"
        f"*Next of Kin:* {data.get('nok_name', '')}\n"
        f"*NOK Phone:* {data.get('nok_phone', '')}\n\n"
        f"*Camp Stay:* {data.get('camp_start', '')} to {data.get('camp_end', '')}\n\n"
        "Is everything correct?"
    )
    interactive = {"type": "button", "body": {"text": conf_text}, "action": {"buttons": [{"type": "reply", "reply": {"id": "confirm_reg", "title": "✅ Confirm & Submit"}}, {"type": "reply", "reply": {"id": "restart_reg", "title": "❌ Restart"}}]} }
    send_interactive_message(user_id, interactive)

@app.route('/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        return 'Verification token mismatch', 403
    
    if request.method == 'POST':
        data = request.get_json()
        try:
            if data and 'entry' in data:
                for entry in data['entry']:
                    for change in entry.get('changes', []):
                        if 'messages' in change.get('value', {}):
                            for message in change['value']['messages']:
                                user_id = message['from']
                                msg_text = ''
                                
                                if message.get('type') == 'text':
                                    msg_text = message['text']['body']
                                elif message.get('type') == 'interactive':
                                    interactive_type = message['interactive']['type']
                                    if interactive_type == 'button_reply':
                                        msg_text = message['interactive']['button_reply']['id']
                                    elif interactive_type == 'list_reply':
                                        msg_text = message['interactive']['list_reply']['id']
                                
                                if msg_text:
                                    handle_bot_logic(user_id, msg_text)
        except Exception as e:
            print(f"Error processing webhook message: {e}")
        return 'OK', 200

@app.route('/')
def health_check():
    return "SundayBot Interactive UI with Firebase is running!", 200
