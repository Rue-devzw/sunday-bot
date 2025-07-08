# api/index.py

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

# --- 1. INITIALIZE FLASK & API CLIENTS ---
app = Flask(__name__)
try:
    gemini_api_key = os.environ.get('GEMINI_API_KEY')
    genai.configure(api_key=gemini_api_key)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    print(f"Error initializing Gemini client: {e}")
    gemini_model = None

# --- 2. CONFIGURATION & ENVIRONMENT VARIABLES ---
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')

GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')
ANNUAL_CAMP_SHEET_NAME = os.environ.get('ANNUAL_CAMP_SHEET_NAME', 'Camp Registrations 2025')
YOUTH_CAMP_SHEET_NAME = os.environ.get('YOUTH_CAMP_SHEET_NAME', 'Youths Camp Registrations 2025')

ANCHOR_DATE = date(2024, 8, 21)
PRIMARY_PALS_ANCHOR_DATE = date(2024, 9, 1)

USERS_FILE = 'users.json'
HYMNBOOKS_DIR = 'hymnbooks'
BIBLES_DIR = 'bibles'
# --- NEW: Added a dedicated directory for lesson files ---
LESSONS_DIR = 'lessons' 
LESSONS_FILE_SEARCH = 'search_lessons.json'
LESSONS_FILE_ANSWER = 'answer_lessons.json'
LESSONS_FILE_BEGINNERS = 'beginners_lessons.json'
LESSONS_FILE_PRIMARY_PALS = 'primary_pals_lessons.json'


CLASSES = { "1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search" }
HYMNBOOKS = {
    "1": {"name": "Yellow Hymnbook Shona", "file": "shona_hymns.json"},
    "2": {"name": "Sing Praises Unto Our King", "file": "english_hymns.json"}
}
BIBLES = {
    "1": {"name": "Shona Bible", "file": "shona_bible.db"},
    "2": {"name": "English Bible (KJV)", "file": "english_bible.db"}
}

DEPARTMENTS = {
    "1": "Security", "2": "Media", "3": "Accommodation", "4": "Transport",
    "5": "Translation", "6": "Kitchen Work", "7": "Notes Taking (Editorial)"
}


# --- 3. HELPER & FORMATTING FUNCTIONS ---
# All helper functions are here and unchanged, omitting for brevity.
# ... (append_to_google_sheet, calculate_age, get_verse_from_db, etc.) ...
def append_to_google_sheet(data_row, sheet_name):
    if not GOOGLE_CREDENTIALS_JSON:
        print("ERROR: Google credentials JSON not set in environment variables.")
        return False
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open(sheet_name).sheet1
        sheet.append_row(data_row)
        return True
    except Exception as e:
        print(f"Error appending to Google Sheet: {e}")
        return False

def calculate_age(dob_string):
    try:
        birth_date = datetime.strptime(dob_string, "%d/%m/%Y").date()
        today = date.today()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        return age
    except ValueError:
        return None
        
def get_verse_from_db(passage, db_filename):
    db_path = os.path.join(os.path.dirname(__file__), BIBLES_DIR, db_filename)
    if not os.path.exists(db_path):
        return f"Sorry, the selected Bible database file ({db_filename}) is missing."
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
        if not results: return f"Sorry, I couldn't find the passage '{passage}'. Please check the reference."
        full_text = "".join([f"[{v[0]}] {v[1]} " for v in results])
        return f"📖 *{passage.strip()}*\n\n{full_text.strip()}"
    except Exception as e:
        print(f"SQLite Database Error: {e}")
        return "Sorry, I'm having trouble looking up the Bible verse right now."

def get_user_file_path():
    return f'/tmp/{USERS_FILE}' if 'VERCEL' in os.environ else os.path.join(os.path.dirname(__file__), USERS_FILE)

def load_json_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # --- MODIFIED: Add logging to see the error ---
        print(f"DEBUG: Error loading JSON file '{file_path}': {e}")
        return [] if any(x in file_path for x in ['lessons', 'hymn']) else {}

def save_json_file(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def get_current_lesson_index(user_class):
    today = date.today()
    if user_class == "Primary Pals":
        anchor_date = PRIMARY_PALS_ANCHOR_DATE
    else:
        anchor_date = ANCHOR_DATE
    anchor_week_start = anchor_date + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    week_difference = (current_week_start - anchor_week_start).days // 7
    return week_difference if week_difference >= 0 else -1

def format_hymn(hymn):
    if not hymn: return "Sorry, I couldn't find a hymn with that number in your selected hymnbook."
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

def format_lesson(lesson):
    if not lesson: return "Lesson details could not be found."
    title = lesson.get('title', 'No Title')
    lesson_num = lesson.get('lesson', '#')
    memory_verse = lesson.get('memory_verse', 'N/A')
    main_text = "\n".join(lesson.get('text', []))

    message = (
        f"📖 *Lesson {lesson_num}: {title}*\n\n"
        f"📌 *Memory Verse:*\n_{memory_verse}_\n\n"
        f"📝 *Lesson Text:*\n{main_text}"
    )
    return message

def get_ai_response(question, context):
    if not gemini_model: return "Sorry, the AI thinking module is currently unavailable."
    prompt = ( "You are a friendly and helpful Sunday School assistant. Your answers must be based *only* on the provided lesson text (the context). If the answer is not in the text, say that you cannot answer based on the provided material. Keep your answers concise and easy to understand.\n\n" f"--- LESSON CONTEXT ---\n{context}\n\n" f"--- USER QUESTION ---\n{question}" )
    try:
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Google Gemini API Error: {e}")
        return "I'm having a little trouble thinking right now. Please try again in a moment."


# --- MAIN BOT LOGIC HANDLER ---
def handle_bot_logic(user_id, message_text):
    user_file_path = get_user_file_path()
    users = load_json_file(user_file_path)
    
    message_text_lower = message_text.lower().strip()
    user_profile = users.get(user_id, {})
    original_profile_state = json.dumps(user_profile)

    main_menu_text = (
        "Welcome! 🙏\n\nPlease choose a section:\n\n"
        "*1.* Weekly Lessons\n"
        "*2.* Hymnbook\n"
        "*3.* Bible Lookup\n"
        "*4.* 2025 Regional Youths Camp Registration\n"
        "*5.* 2025 Annual Camp Registration"
    )

    if message_text_lower == 'reset':
        user_profile = {}
        send_whatsapp_message(user_id, f"Your session has been reset. {main_menu_text}")
        if user_id in users: del users[user_id]
        save_json_file(users, user_file_path)
        return
        
    if message_text_lower == 'm' and 'mode' in user_profile:
        user_profile = {}
        send_whatsapp_message(user_id, f"OK, returning to the main menu. {main_menu_text}")
        if user_id in users: del users[user_id]
        save_json_file(users, user_file_path)
        return

    if 'mode' not in user_profile:
        if message_text_lower == '1': user_profile['mode'] = 'lessons'
        elif message_text_lower == '2': user_profile['mode'] = 'hymnbook'
        elif message_text_lower == '3': user_profile['mode'] = 'bible'
        elif message_text_lower == '4':
            user_profile['mode'] = 'camp_registration'
            user_profile['registration_type'] = 'youths'
        elif message_text_lower == '5':
            user_profile['mode'] = 'camp_registration'
            user_profile['registration_type'] = 'annual'
        else:
            send_whatsapp_message(user_id, main_menu_text)
            return

    # --- LOGIC FILLED IN: Mode Handler: Lessons ---
    if user_profile.get('mode') == 'lessons':
        step = user_profile.get('lesson_step', 'start')

        if step == 'start':
            class_menu = "Please select your class:\n\n"
            for key, name in CLASSES.items():
                class_menu += f"*{key}.* {name}\n"
            send_whatsapp_message(user_id, class_menu.strip())
            user_profile['lesson_step'] = 'awaiting_class_choice'
        
        elif step == 'awaiting_class_choice':
            if message_text_lower not in CLASSES:
                send_whatsapp_message(user_id, "Invalid selection. Please choose a number from the list.")
            else:
                user_class = CLASSES[message_text_lower]
                user_profile['lesson_class'] = user_class
                
                lesson_files = {
                    "Beginners": LESSONS_FILE_BEGINNERS, "Primary Pals": LESSONS_FILE_PRIMARY_PALS,
                    "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH
                }
                lesson_file = lesson_files.get(user_class)
                
                # --- MODIFIED: Build the correct path using LESSONS_DIR ---
                lesson_file_path = os.path.join(os.path.dirname(__file__), LESSONS_DIR, lesson_file)
                
                # --- DIAGNOSTIC LOGGING ---
                print(f"DEBUG: Attempting to load lesson file from: {lesson_file_path}")
                all_lessons = load_json_file(lesson_file_path)
                print(f"DEBUG: Loaded {len(all_lessons)} lessons from the file.")
                
                lesson_index = get_current_lesson_index(user_class)
                print(f"DEBUG: Calculated current lesson index as: {lesson_index}")
                # --- END DIAGNOSTIC LOGGING ---

                if all_lessons and 0 <= lesson_index < len(all_lessons):
                    current_lesson = all_lessons[lesson_index]
                    user_profile['current_lesson_data'] = current_lesson
                    
                    lesson_action_menu = (
                        f"This week's lesson for the *{user_class}* class is: *{current_lesson.get('title', 'N/A')}*\n\n"
                        "What would you like to do?\n"
                        "*1.* Read the full lesson\n"
                        "*2.* Ask a question about the lesson\n\n"
                        "Type *m* to return to the main menu."
                    )
                    send_whatsapp_message(user_id, lesson_action_menu)
                    user_profile['lesson_step'] = 'awaiting_lesson_action'
                else:
                    # This is the error path. The debug logs above will tell us why we're here.
                    send_whatsapp_message(user_id, "Sorry, I couldn't find the current lesson for your class. Please contact an administrator.")
                    user_profile = {} # Reset
        
        elif step == 'awaiting_lesson_action':
            if message_text_lower == '1':
                lesson_data = user_profile.get('current_lesson_data')
                formatted_lesson = format_lesson(lesson_data)
                send_whatsapp_message(user_id, formatted_lesson)
                lesson_action_menu = (
                    "What would you like to do next?\n"
                    "*1.* Read the full lesson again\n"
                    "*2.* Ask a question about the lesson\n\n"
                    "Type *m* to return to the main menu."
                )
                send_whatsapp_message(user_id, lesson_action_menu)
            elif message_text_lower == '2':
                send_whatsapp_message(user_id, "OK, please type your question about the lesson.")
                user_profile['lesson_step'] = 'awaiting_ai_question'
            else:
                send_whatsapp_message(user_id, "Invalid choice. Please enter *1* or *2*.")
        
        elif step == 'awaiting_ai_question':
            question = message_text
            lesson_data = user_profile.get('current_lesson_data')
            context = format_lesson(lesson_data)
            
            ai_answer = get_ai_response(question, context)
            send_whatsapp_message(user_id, f"🤔 *Answer:*\n{ai_answer}")
            
            user_profile['lesson_step'] = 'awaiting_lesson_action'
            lesson_action_menu = (
                "You can ask another question, or choose an option:\n"
                "*1.* Read the full lesson\n"
                "*2.* Ask another question\n\n"
                "Type *m* to return to the main menu."
            )
            send_whatsapp_message(user_id, lesson_action_menu)
            
    # --- Other modes (Hymnbook, Bible, Camp Registration) are here and unchanged ---
    # ... I am omitting them for brevity, but they should be in the final file ...
    # --- LOGIC FILLED IN: Mode Handler: Hymnbook ---
    elif user_profile.get('mode') == 'hymnbook':
        step = user_profile.get('hymn_step', 'start')

        if step == 'start':
            hymnbook_menu = "Please select a hymnbook:\n\n"
            for key, book in HYMNBOOKS.items():
                hymnbook_menu += f"*{key}.* {book['name']}\n"
            send_whatsapp_message(user_id, hymnbook_menu.strip())
            user_profile['hymn_step'] = 'awaiting_hymnbook_choice'
            
        elif step == 'awaiting_hymnbook_choice':
            if message_text_lower not in HYMNBOOKS:
                send_whatsapp_message(user_id, "Invalid selection. Please choose a number from the list.")
            else:
                chosen_book = HYMNBOOKS[message_text_lower]
                user_profile['hymnbook_file'] = chosen_book['file']
                send_whatsapp_message(user_id, f"Great! You've selected *{chosen_book['name']}*. Please enter a hymn number.\n\nType *m* to return to the main menu.")
                user_profile['hymn_step'] = 'awaiting_hymn_number'
                
        elif step == 'awaiting_hymn_number':
            hymn_number = message_text.strip()
            if not hymn_number.isdigit():
                send_whatsapp_message(user_id, "Please enter a valid number.")
            else:
                hymn_file_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, user_profile['hymnbook_file'])
                all_hymns = load_json_file(hymn_file_path)
                
                found_hymn = next((h for h in all_hymns if str(h.get('number')) == hymn_number), None)
                
                if found_hymn:
                    send_whatsapp_message(user_id, format_hymn(found_hymn))
                else:
                    send_whatsapp_message(user_id, f"Sorry, I couldn't find hymn #{hymn_number} in this hymnbook.")
                
                send_whatsapp_message(user_id, "You can enter another hymn number, or type *m* to go back.")

    # --- LOGIC FILLED IN: Mode Handler: Bible ---
    elif user_profile.get('mode') == 'bible':
        step = user_profile.get('bible_step', 'start')

        if step == 'start':
            bible_menu = "Please select a Bible version:\n\n"
            for key, bible in BIBLES.items():
                bible_menu += f"*{key}.* {bible['name']}\n"
            send_whatsapp_message(user_id, bible_menu.strip())
            user_profile['bible_step'] = 'awaiting_bible_choice'
            
        elif step == 'awaiting_bible_choice':
            if message_text_lower not in BIBLES:
                send_whatsapp_message(user_id, "Invalid selection. Please choose a number from the list.")
            else:
                chosen_bible = BIBLES[message_text_lower]
                user_profile['bible_file'] = chosen_bible['file']
                send_whatsapp_message(user_id, f"You've selected the *{chosen_bible['name']}*. Please enter a passage to look up (e.g., John 3:16).\n\nType *m* to return to the main menu.")
                user_profile['bible_step'] = 'awaiting_passage'

        elif step == 'awaiting_passage':
            passage = message_text.strip()
            verse_text = get_verse_from_db(passage, user_profile['bible_file'])
            send_whatsapp_message(user_id, verse_text)
            send_whatsapp_message(user_id, "You can enter another passage, or type *m* to go back.")

    # --- Mode Handler: Camp Registration ---
    elif user_profile.get('mode') == 'camp_registration':
        step = user_profile.get('registration_step', 'start')
        data = user_profile.setdefault('registration_data', {})
        reg_type = user_profile.get('registration_type', 'annual')

        if reg_type == 'youths':
            camp_name = "2025 Regional Youths Camp"
            camp_dates_text = "The camp runs from Aug 17 to Aug 24, 2025."
        else:
            camp_name = "2025 Annual Camp"
            camp_dates_text = "The camp runs from Dec 7 to Dec 21, 2025."
        
        if step == 'start':
            send_whatsapp_message(user_id, f"🏕️ *{camp_name} Registration*\n\nLet's get you registered. I'll ask you a few questions one by one. You can type `reset` at any time to cancel.\n\nFirst, what is your *first name*?")
            user_profile['registration_step'] = 'awaiting_first_name'
        
        elif step == 'awaiting_first_name':
            data['first_name'] = message_text.strip()
            send_whatsapp_message(user_id, "Great! What is your *last name*?")
            user_profile['registration_step'] = 'awaiting_last_name'

        elif step == 'awaiting_last_name':
            data['last_name'] = message_text.strip()
            send_whatsapp_message(user_id, "Got it. What is your *date of birth*?\n\nPlease use DD/MM/YYYY format (e.g., 25/12/1998).")
            user_profile['registration_step'] = 'awaiting_dob'

        elif step == 'awaiting_dob':
            age = calculate_age(message_text.strip())
            if not age:
                send_whatsapp_message(user_id, "That doesn't look right. Please enter your date of birth in DD/MM/YYYY format.")
            else:
                data['dob'] = message_text.strip()
                data['age'] = age
                send_whatsapp_message(user_id, "What is your *gender*? (Male / Female)")
                user_profile['registration_step'] = 'awaiting_gender'
        
        elif step == 'awaiting_gender':
            if message_text_lower not in ['male', 'female']:
                send_whatsapp_message(user_id, "Please just answer with *Male* or *Female*.")
            else:
                data['gender'] = message_text.strip().capitalize()
                send_whatsapp_message(user_id, "Thanks. Now, please enter your *ID or Passport number*.")
                user_profile['registration_step'] = 'awaiting_id_passport'

        elif step == 'awaiting_id_passport':
            data['id_passport'] = message_text.strip()
            send_whatsapp_message(user_id, "Please enter your *phone number* in international format (e.g., +263771234567).")
            user_profile['registration_step'] = 'awaiting_phone_number'

        elif step == 'awaiting_phone_number':
            if not re.match(r'^\+\d{9,}$', message_text.strip()):
                 send_whatsapp_message(user_id, "Hmm, that doesn't seem like a valid international phone number. Please try again (e.g., `+263771234567`).")
            else:
                data['phone'] = message_text.strip()
                send_whatsapp_message(user_id, "Are you saved? (Please answer *Yes* or *No*)")
                user_profile['registration_step'] = 'awaiting_salvation_status'
        
        elif step == 'awaiting_salvation_status':
            if message_text_lower not in ['yes', 'no']:
                send_whatsapp_message(user_id, "Please just answer *Yes* or *No*.")
            else:
                data['salvation_status'] = message_text.strip().capitalize()
                send_whatsapp_message(user_id, "How many dependents (e.g., children) will be attending with you? (Enter 0 if none)")
                user_profile['registration_step'] = 'awaiting_dependents'

        elif step == 'awaiting_dependents':
            if not message_text.strip().isdigit():
                send_whatsapp_message(user_id, "Please enter a number (e.g., 0, 1, 2).")
            else:
                data['dependents'] = message_text.strip()
                send_whatsapp_message(user_id, "Who is your *next of kin*? (Please provide their full name).")
                user_profile['registration_step'] = 'awaiting_nok_name'
        
        elif step == 'awaiting_nok_name':
            data['nok_name'] = message_text.strip()
            send_whatsapp_message(user_id, "What is your *next of kin's phone number*? (International format, e.g., +263771234567).")
            user_profile['registration_step'] = 'awaiting_nok_phone'

        elif step == 'awaiting_nok_phone':
            if not re.match(r'^\+\d{9,}$', message_text.strip()):
                 send_whatsapp_message(user_id, "That doesn't look like a valid phone number. Please provide the next of kin's number in international format.")
            else:
                data['nok_phone'] = message_text.strip()
                send_whatsapp_message(user_id, f"{camp_dates_text}\n\nWhat is your *arrival date*? (e.g., Aug 17)")
                user_profile['registration_step'] = 'awaiting_camp_start_date'
        
        elif step == 'awaiting_camp_start_date':
            data['camp_start'] = message_text.strip()
            send_whatsapp_message(user_id, "And what is your *departure date*? (e.g., Aug 24)")
            user_profile['registration_step'] = 'awaiting_camp_end_date'
            
        elif step == 'awaiting_camp_end_date':
            data['camp_end'] = message_text.strip()
            send_whatsapp_message(user_id, "Thank you. Are you willing to assist voluntarily during the camp? (Please answer *Yes* or *No*)")
            user_profile['registration_step'] = 'awaiting_volunteer_status'

        elif step == 'awaiting_volunteer_status':
            if message_text_lower not in ['yes', 'no']:
                send_whatsapp_message(user_id, "Please just answer *Yes* or *No*.")
            else:
                data['volunteer_status'] = message_text.strip().capitalize()
                if message_text_lower == 'yes':
                    department_menu = "That's wonderful! Which department would you like to assist in?\n\n"
                    for k, v in DEPARTMENTS.items(): department_menu += f"*{k}.* {v}\n"
                    send_whatsapp_message(user_id, department_menu.strip())
                    user_profile['registration_step'] = 'awaiting_volunteer_department'
                else:
                    data['volunteer_department'] = 'N/A'
                    _send_confirmation_message(user_id, data, camp_name)
                    user_profile['registration_step'] = 'awaiting_confirmation'

        elif step == 'awaiting_volunteer_department':
            if message_text_lower not in DEPARTMENTS:
                department_menu = "Invalid selection. Please choose a number from the list:\n\n"
                for k, v in DEPARTMENTS.items(): department_menu += f"*{k}.* {v}\n"
                send_whatsapp_message(user_id, department_menu.strip())
            else:
                data['volunteer_department'] = DEPARTMENTS[message_text_lower]
                _send_confirmation_message(user_id, data, camp_name)
                user_profile['registration_step'] = 'awaiting_confirmation'
                
        elif step == 'awaiting_confirmation':
            if message_text_lower == 'confirm':
                send_whatsapp_message(user_id, "Thank you! Submitting your registration...")
                row = [
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    data.get('first_name', ''), data.get('last_name', ''),
                    data.get('dob', ''), data.get('age', ''), data.get('gender', ''),
                    data.get('id_passport', ''), data.get('phone', ''),
                    data.get('salvation_status', ''), data.get('dependents', ''),
                    data.get('volunteer_status', ''), data.get('volunteer_department', ''),
                    data.get('nok_name', ''), data.get('nok_phone', ''),
                    f"{data.get('camp_start', '')} to {data.get('camp_end', '')}"
                ]
                
                sheet_to_use = YOUTH_CAMP_SHEET_NAME if reg_type == 'youths' else ANNUAL_CAMP_SHEET_NAME
                success = append_to_google_sheet(row, sheet_to_use)
                
                if success:
                    send_whatsapp_message(user_id, f"✅ Registration successful for the {camp_name}! We look forward to seeing you.")
                else:
                    send_whatsapp_message(user_id, "⚠️ There was a problem submitting your registration. Please contact an administrator.")
                
                user_profile = {}
                if user_id in users: del users[user_id]
            
            elif message_text_lower == 'restart':
                user_profile['registration_data'] = {}
                user_profile['registration_step'] = 'start'
                handle_bot_logic(user_id, message_text)
                return
            else:
                send_whatsapp_message(user_id, "Please type *confirm* or *restart*.")

    if json.dumps(user_profile) != original_profile_state:
        users[user_id] = user_profile
        save_json_file(users, user_file_path)

# --- All remaining functions are here and unchanged ---
# ... (_send_confirmation_message, send_whatsapp_message, webhook, health_check) ...
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
        print(f"Incoming data: {json.dumps(data, indent=2)}")
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
    return "SundayBot with Camp Registration is running!", 200