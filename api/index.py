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

# --- ADMIN CONFIGURATION ---
# IMPORTANT: Add your WhatsApp number(s) here in international format
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

CLASSES = { "1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search" }
HYMNBOOKS = { "1": {"name": "Yellow Hymnbook Shona", "file": "shona_hymns.json"}, "2": {"name": "Sing Praises Unto Our King", "file": "english_hymns.json"} }
BIBLES = { "1": {"name": "Shona Bible", "file": "shona_bible.db"}, "2": {"name": "English Bible (KJV)", "file": "english_bible.db"} }
DEPARTMENTS = { "1": "Security", "2": "Media", "3": "Accommodation", "4": "Transport", "5": "Translation", "6": "Kitchen Work", "7": "Notes Taking (Editorial)"}

# --- 3. HELPER & DATABASE FUNCTIONS ---

def get_firestore_collection_name(camp_type):
    return "youth_camp_2025" if camp_type == 'youths' else "annual_camp_2025"

def check_registration_status_firestore(identifier, camp_type):
    """
    Checks for an existing registration in Firestore using the ID/Passport as the document ID.
    """
    if not db: return "Error"
    try:
        collection_name = get_firestore_collection_name(camp_type)
        # Use the identifier directly as the document ID
        doc_ref = db.collection(collection_name).document(identifier.strip())
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"Error checking Firestore: {e}")
        return "Error"

def export_registrations_to_sheet(camp_type):
    """
    Fetches all registrations from a Firestore collection and overwrites the
    corresponding Google Sheet with the data.
    """
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
            # --- FIX: Convert Firestore timestamp to a readable string ---
            timestamp_obj = data.get("timestamp")
            timestamp_str = timestamp_obj.strftime("%Y-%m-%d %H:%M:%S") if isinstance(timestamp_obj, datetime) else ""
            
            row = [
                timestamp_str,
                data.get("first_name", ""),
                data.get("last_name", ""),
                data.get("dob", ""),
                data.get("age", ""),
                data.get("gender", ""),
                data.get("id_passport", ""),
                data.get("phone", ""),
                data.get("salvation_status", ""),
                data.get("dependents", ""),
                data.get("volunteer_status", ""),
                data.get("volunteer_department", ""),
                data.get("nok_name", ""),
                data.get("nok_phone", ""),
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


# --- MAIN BOT LOGIC HANDLER ---
def handle_bot_logic(user_id, message_text):
    if not db:
        send_whatsapp_message(user_id, "Sorry, the bot is experiencing technical difficulties (Database connection failed). Please try again later.")
        return

    session_ref = db.collection('sessions').document(user_id)
    session_doc = session_ref.get()
    user_profile = session_doc.to_dict() if session_doc.exists else {}
    
    message_text_lower = message_text.lower().strip()

    # --- FIX: NORMALIZED ADMIN CHECK ---
    # This removes all non-digit characters for a reliable comparison
    clean_user_id = re.sub(r'\D', '', user_id)
    clean_admin_numbers = [re.sub(r'\D', '', num) for num in ADMIN_NUMBERS]

    if clean_user_id in clean_admin_numbers:
        if message_text_lower.startswith('export'):
            parts = message_text_lower.split()
            if len(parts) == 2 and parts[1] in ['youths', 'annual']:
                camp_type = parts[1]
                send_whatsapp_message(user_id, f"Okay, starting export for *{camp_type} camp*. This may take a moment...")
                result = export_registrations_to_sheet(camp_type)
                send_whatsapp_message(user_id, result)
                return
            else:
                send_whatsapp_message(user_id, "Invalid export command. Use `export youths` or `export annual`.")
                return

    main_menu_text = (
        "Welcome! 🙏\n\nPlease choose a section:\n\n"
        "*1.* Weekly Lessons\n*2.* Hymnbook\n*3.* Bible Lookup\n"
        "*4.* 2025 Regional Youths Camp Registration\n*5.* 2025 Annual Camp Registration\n"
        "*6.* Check Registration Status"
    )

    if (message_text_lower == 'reset') or (user_profile.get('mode') and message_text_lower == 'm'):
        session_ref.delete()
        msg = f"Your session has been reset. {main_menu_text}" if message_text_lower == 'reset' else f"OK, returning to the main menu. {main_menu_text}"
        send_whatsapp_message(user_id, msg)
        return

    if 'mode' not in user_profile:
        modes = {'1': 'lessons', '2': 'hymnbook', '3': 'bible', '4': 'camp_registration', '5': 'camp_registration', '6': 'check_status'}
        if message_text_lower in modes:
            user_profile['mode'] = modes[message_text_lower]
            if message_text_lower == '4': user_profile['registration_type'] = 'youths'
            if message_text_lower == '5': user_profile['registration_type'] = 'annual'
        else:
            send_whatsapp_message(user_id, main_menu_text)
            return

    # --- Module Logic ---
    if user_profile.get('mode') == 'lessons':
        step = user_profile.get('lesson_step', 'start')
        if step == 'start':
            class_menu = "Please select your class:\n\n" + "\n".join([f"*{k}.* {v}" for k, v in CLASSES.items()])
            send_whatsapp_message(user_id, class_menu)
            user_profile['lesson_step'] = 'awaiting_class_choice'
        elif step == 'awaiting_class_choice':
            if message_text_lower not in CLASSES:
                send_whatsapp_message(user_id, "Invalid selection. Please choose a number from the list.")
            else:
                user_class = CLASSES[message_text_lower]
                user_profile['lesson_class'] = user_class
                lesson_files = { "Beginners": LESSONS_FILE_BEGINNERS, "Primary Pals": LESSONS_FILE_PRIMARY_PALS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH }
                lesson_file_path = os.path.join(os.path.dirname(__file__), LESSONS_DIR, lesson_files.get(user_class))
                raw_data = load_json_file(lesson_file_path)
                if user_class == "Primary Pals" and isinstance(raw_data, dict):
                    all_lessons = raw_data.get('primary_pals_lessons', [])
                elif isinstance(raw_data, list):
                    all_lessons = raw_data
                else: all_lessons = []
                lesson_index = get_current_lesson_index(user_class)
                if all_lessons and 0 <= lesson_index < len(all_lessons):
                    current_lesson = all_lessons[lesson_index]
                    user_profile['current_lesson_data'] = current_lesson
                    title = current_lesson.get('title') or current_lesson.get('lessonTitle', 'N/A')
                    lesson_action_menu = (f"This week's lesson for *{user_class}* is: *{title}*\n\nWhat would you like to do?\n*1.* Read the full lesson\n*2.* Ask a question\n\nType *m* to return.")
                    send_whatsapp_message(user_id, lesson_action_menu)
                    user_profile['lesson_step'] = 'awaiting_lesson_action'
                else:
                    send_whatsapp_message(user_id, "Sorry, I couldn't find the current lesson for your class.")
                    session_ref.delete()
        elif step == 'awaiting_lesson_action':
            if message_text_lower == '1':
                formatted_lesson = format_lesson(user_profile.get('current_lesson_data'), user_profile.get('lesson_class'))
                send_whatsapp_message(user_id, formatted_lesson)
                send_whatsapp_message(user_id, "What next?\n*1.* Read again\n*2.* Ask a question\n\nType *m* to return.")
            elif message_text_lower == '2':
                send_whatsapp_message(user_id, "OK, please type your question about the lesson.\n\n(Type *m* to return to the lesson menu).")
                user_profile['lesson_step'] = 'awaiting_ai_question'
            else:
                send_whatsapp_message(user_id, "Invalid choice. Please enter *1* or *2*.")
        elif step == 'awaiting_ai_question':
            context = format_lesson(user_profile.get('current_lesson_data'), user_profile.get('lesson_class'))
            send_whatsapp_message(user_id, "_Thinking..._ 🤔")
            ai_answer = get_ai_response(message_text, context)
            send_whatsapp_message(user_id, ai_answer)
            send_whatsapp_message(user_id, "You can ask another question, or type *m* to return to the lesson menu.")

    elif user_profile.get('mode') == 'hymnbook':
        step = user_profile.get('hymn_step', 'start')
        if step == 'start':
            hymnbook_menu = "Please select a hymnbook:\n\n" + "\n".join([f"*{k}.* {v['name']}" for k,v in HYMNBOOKS.items()])
            send_whatsapp_message(user_id, hymnbook_menu)
            user_profile['hymn_step'] = 'awaiting_hymnbook_choice'
        elif step == 'awaiting_hymnbook_choice':
            if message_text_lower not in HYMNBOOKS:
                send_whatsapp_message(user_id, "Invalid selection. Please choose a number from the list.")
            else:
                chosen_book = HYMNBOOKS[message_text_lower]
                user_profile['hymnbook_file'] = chosen_book['file']
                send_whatsapp_message(user_id, f"Great! You've selected *{chosen_book['name']}*. Please enter a hymn number.\n\nType *m* to return.")
                user_profile['hymn_step'] = 'awaiting_hymn_number'
        elif step == 'awaiting_hymn_number':
            if not message_text.strip().isdigit():
                send_whatsapp_message(user_id, "Please enter a valid number.")
            else:
                hymn_file_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, user_profile['hymnbook_file'])
                all_hymns = load_json_file(hymn_file_path)
                found_hymn = next((h for h in all_hymns if str(h.get('number')) == message_text.strip()), None)
                send_whatsapp_message(user_id, format_hymn(found_hymn))
                send_whatsapp_message(user_id, "You can enter another hymn number, or type *m* to go back.")

    elif user_profile.get('mode') == 'bible':
        step = user_profile.get('bible_step', 'start')
        if step == 'start':
            bible_menu = "Please select a Bible version:\n\n" + "\n".join([f"*{k}.* {v['name']}" for k,v in BIBLES.items()])
            send_whatsapp_message(user_id, bible_menu)
            user_profile['bible_step'] = 'awaiting_bible_choice'
        elif step == 'awaiting_bible_choice':
            if message_text_lower not in BIBLES:
                send_whatsapp_message(user_id, "Invalid selection. Please choose a number from the list.")
            else:
                chosen_bible = BIBLES[message_text_lower]
                user_profile['bible_file'] = chosen_bible['file']
                send_whatsapp_message(user_id, f"You've selected the *{chosen_bible['name']}*. Please enter a passage (e.g., John 3:16).\n\nType *m* to return.")
                user_profile['bible_step'] = 'awaiting_passage'
        elif step == 'awaiting_passage':
            verse_text = get_verse_from_db(message_text.strip(), user_profile['bible_file'])
            send_whatsapp_message(user_id, verse_text)
            send_whatsapp_message(user_id, "You can enter another passage, or type *m* to go back.")
    
    elif user_profile.get('mode') == 'camp_registration':
        step = user_profile.get('registration_step', 'start')
        data = user_profile.setdefault('registration_data', {})
        reg_type = user_profile.get('registration_type', 'annual')
        
        if step == 'start':
            camp_name = "2025 Regional Youths Camp" if reg_type == 'youths' else "2025 Annual Camp"
            send_whatsapp_message(user_id, f"🏕️ *{camp_name} Registration*\n\nLet's get you registered. First, what is your *ID or Passport number*?")
            user_profile['registration_step'] = 'awaiting_id_passport'
        
        elif step == 'awaiting_id_passport':
            id_passport = message_text.strip()
            if not id_passport:
                send_whatsapp_message(user_id, "ID/Passport number cannot be empty. Please try again.")
                return

            send_whatsapp_message(user_id, f"Checking if `{id_passport}` is already registered...")
            existing_reg = check_registration_status_firestore(id_passport, reg_type)
            
            if isinstance(existing_reg, dict):
                reg_name = f"{existing_reg.get('first_name', '')} {existing_reg.get('last_name', '')}"
                send_whatsapp_message(user_id, f"It looks like you are already registered under the name *{reg_name}* with this ID. No need to register again!\n\nReturning to the main menu.")
                session_ref.delete()
                return
            elif existing_reg == "Error":
                send_whatsapp_message(user_id, "I'm having trouble checking for duplicates right now. Please contact an admin.")
                session_ref.delete()
                return
            else: # Not a duplicate
                data['id_passport'] = id_passport
                send_whatsapp_message(user_id, "Great, you are not already registered. Now, what is your *first name*?")
                user_profile['registration_step'] = 'awaiting_first_name'

        elif step == 'awaiting_first_name':
            data['first_name'] = message_text.strip()
            send_whatsapp_message(user_id, "And your *last name*?")
            user_profile['registration_step'] = 'awaiting_last_name'

        elif step == 'awaiting_last_name':
            data['last_name'] = message_text.strip()
            send_whatsapp_message(user_id, "Got it. What is your *date of birth*? (DD/MM/YYYY)")
            user_profile['registration_step'] = 'awaiting_dob'
        
        elif step == 'awaiting_dob':
            age = calculate_age(message_text.strip())
            if not age: send_whatsapp_message(user_id, "That doesn't look right. Please use DD/MM/YYYY format.")
            else:
                data.update({'dob': message_text.strip(), 'age': age})
                send_whatsapp_message(user_id, "What is your *gender*? (Male / Female)")
                user_profile['registration_step'] = 'awaiting_gender'
        elif step == 'awaiting_gender':
            if message_text_lower not in ['male', 'female']: send_whatsapp_message(user_id, "Please just answer with *Male* or *Female*.")
            else:
                data['gender'] = message_text.strip().capitalize()
                send_whatsapp_message(user_id, "Please enter your *phone number* (e.g., +263771234567).")
                user_profile['registration_step'] = 'awaiting_phone_number'
        elif step == 'awaiting_phone_number':
            if not re.match(r'^\+\d{9,}$', message_text.strip()): send_whatsapp_message(user_id, "Hmm, that doesn't seem like a valid international phone number.")
            else:
                data['phone'] = message_text.strip()
                send_whatsapp_message(user_id, "Are you saved? (*Yes* or *No*)")
                user_profile['registration_step'] = 'awaiting_salvation_status'
        elif step == 'awaiting_salvation_status':
            if message_text_lower not in ['yes', 'no']: send_whatsapp_message(user_id, "Please just answer *Yes* or *No*.")
            else:
                data['salvation_status'] = message_text.strip().capitalize()
                send_whatsapp_message(user_id, "How many dependents (e.g., children) will be attending with you? (Enter 0 if none)")
                user_profile['registration_step'] = 'awaiting_dependents'
        elif step == 'awaiting_dependents':
            if not message_text.strip().isdigit(): send_whatsapp_message(user_id, "Please enter a number (e.g., 0, 1, 2).")
            else:
                data['dependents'] = message_text.strip()
                send_whatsapp_message(user_id, "Who is your *next of kin*? (Full name).")
                user_profile['registration_step'] = 'awaiting_nok_name'
        elif step == 'awaiting_nok_name':
            data['nok_name'] = message_text.strip()
            send_whatsapp_message(user_id, "What is your *next of kin's phone number*?")
            user_profile['registration_step'] = 'awaiting_nok_phone'
        elif step == 'awaiting_nok_phone':
            if not re.match(r'^\+\d{9,}$', message_text.strip()): send_whatsapp_message(user_id, "That doesn't look like a valid phone number.")
            else:
                data['nok_phone'] = message_text.strip()
                camp_dates_text = "Aug 17 to Aug 24, 2025" if reg_type == 'youths' else "Dec 7 to Dec 21, 2025"
                send_whatsapp_message(user_id, f"The camp runs from {camp_dates_text}.\n\nWhat is your *arrival date*? (e.g., Aug 17)")
                user_profile['registration_step'] = 'awaiting_camp_start_date'
        elif step == 'awaiting_camp_start_date':
            data['camp_start'] = message_text.strip()
            send_whatsapp_message(user_id, "And your *departure date*?")
            user_profile['registration_step'] = 'awaiting_camp_end_date'
        elif step == 'awaiting_camp_end_date':
            data['camp_end'] = message_text.strip()
            send_whatsapp_message(user_id, "Are you willing to assist voluntarily? (Yes / No)")
            user_profile['registration_step'] = 'awaiting_volunteer_status'
        elif step == 'awaiting_volunteer_status':
            if message_text_lower not in ['yes', 'no']: send_whatsapp_message(user_id, "Please just answer *Yes* or *No*.")
            else:
                data['volunteer_status'] = message_text.strip().capitalize()
                if message_text_lower == 'yes':
                    dept_menu = "That's wonderful! Which department?\n\n" + "\n".join([f"*{k}.* {v}" for k,v in DEPARTMENTS.items()])
                    send_whatsapp_message(user_id, dept_menu)
                    user_profile['registration_step'] = 'awaiting_volunteer_department'
                else:
                    data['volunteer_department'] = 'N/A'
                    _send_confirmation_message(user_id, data, "Camp")
                    user_profile['registration_step'] = 'awaiting_confirmation'
        elif step == 'awaiting_volunteer_department':
            if message_text_lower not in DEPARTMENTS: send_whatsapp_message(user_id, "Invalid selection. Please choose a number from the list.")
            else:
                data['volunteer_department'] = DEPARTMENTS[message_text_lower]
                _send_confirmation_message(user_id, data, "Camp")
                user_profile['registration_step'] = 'awaiting_confirmation'

        elif step == 'awaiting_confirmation':
            if message_text_lower == 'confirm':
                data['timestamp'] = firestore.SERVER_TIMESTAMP
                collection_name = get_firestore_collection_name(reg_type)
                doc_ref = db.collection(collection_name).document(data['id_passport'])
                doc_ref.set(data)
                
                send_whatsapp_message(user_id, "✅ Registration successful! Your details have been saved to our database.")
                session_ref.delete()
                return
            elif message_text_lower == 'restart':
                user_profile['registration_step'] = 'start'
                user_profile['registration_data'] = {}
            else:
                send_whatsapp_message(user_id, "Please type *confirm* or *restart*.")

    elif user_profile.get('mode') == 'check_status':
        step = user_profile.get('check_step', 'start')
        if step == 'start':
            send_whatsapp_message(user_id, "Which camp registration would you like to check?\n\n*1.* Youths Camp\n*2.* Annual Camp")
            user_profile['check_step'] = 'awaiting_camp_choice'
        elif step == 'awaiting_camp_choice':
            if message_text_lower not in ['1', '2']:
                send_whatsapp_message(user_id, "Invalid choice. Please enter *1* for Youths Camp or *2* for Annual Camp.")
            else:
                user_profile['camp_to_check'] = 'youths' if message_text_lower == '1' else 'annual'
                send_whatsapp_message(user_id, "Got it. Please enter the *ID/Passport Number* you used to register.")
                user_profile['check_step'] = 'awaiting_identifier'
        elif step == 'awaiting_identifier':
            identifier = message_text.strip()
            camp_type = user_profile.get('camp_to_check')
            send_whatsapp_message(user_id, f"Checking for '{identifier}'...")
            status = check_registration_status_firestore(identifier, camp_type)
            
            if status == "Error":
                 send_whatsapp_message(user_id, "Sorry, a technical error occurred. Please try again later.")
            elif isinstance(status, dict):
                confirm_msg = (
                    f"✅ *Registration Found!* ✅\n\n"
                    f"Hi *{status.get('first_name', '')} {status.get('last_name', '')}*!\n"
                    f"Your registration is confirmed.\n\n"
                    f"*ID/Passport:* {status.get('id_passport', '')}\n"
                    f"*Phone:* {status.get('phone', '')}"
                )
                send_whatsapp_message(user_id, confirm_msg)
            else:
                send_whatsapp_message(user_id, f"❌ *No Registration Found*\n\nI could not find a registration matching '{identifier}'.")
            
            session_ref.delete()
            return
    
    session_ref.set(user_profile)

def _send_confirmation_message(user_id, data, camp_name):
    confirmation_message = (
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
        "Is everything correct? Type *confirm* to submit, or *restart* to enter your details again."
    )
    send_whatsapp_message(user_id, confirmation_message)

def send_whatsapp_message(recipient_id, message_text):
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]):
        print("ERROR: WhatsApp credentials not set.")
        return
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": recipient_id, "text": {"body": message_text}}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"Message sent to {recipient_id}: {response.status_code}, {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message: {e}")

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
                                if message.get('type') == 'text':
                                    handle_bot_logic(message['from'], message['text']['body'])
        except Exception as e:
            print(f"Error processing webhook message: {e}")
        return 'OK', 200

@app.route('/')
def health_check():
    return "SundayBot with Firebase is running!", 200
