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
# Added gspread for Google Sheets integration
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

def append_to_google_sheet(data_row, sheet_name):
    if not GOOGLE_CREDENTIALS_JSON:
        print("ERROR: Google credentials JSON not set.")
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

def check_registration_status(phone_number, sheet_name):
    if not GOOGLE_CREDENTIALS_JSON:
        print("ERROR: Google credentials JSON not set.")
        return None
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open(sheet_name).sheet1
        
        user_phone_international = f"+{phone_number}"
        
        # Column H (8th column) is assumed to hold the Phone Number
        cell = sheet.find(user_phone_international, in_column=8) 
        if cell:
            row_values = sheet.row_values(cell.row)
            headers = sheet.row_values(1)
            return dict(zip(headers, row_values))
        return None
    except Exception as e:
        print(f"Error checking registration in Google Sheet: {e}")
        return None

def calculate_age(dob_string):
    try:
        birth_date = datetime.strptime(dob_string, "%d/%m/%Y").date()
        today = date.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
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
            book, chap, start, end = range_match.groups()
            q, p = "SELECT verse, text FROM bible_verses WHERE book_name_text LIKE ? AND chapter = ? AND verse >= ? AND verse <= ? ORDER BY verse", (f'%{book.strip()}%', chap, start, end)
        elif single_match:
            book, chap, verse = single_match.groups()
            q, p = "SELECT verse, text FROM bible_verses WHERE book_name_text LIKE ? AND chapter = ? AND verse = ?", (f'%{book.strip()}%', chap, verse)
        elif chapter_match:
            book, chap = chapter_match.groups()
            q, p = "SELECT verse, text FROM bible_verses WHERE book_name_text LIKE ? AND chapter = ? ORDER BY verse", (f'%{book.strip()}%', chap)
        else:
            return f"Sorry, I could not understand the reference '{passage}'. Please use a format like 'John 3:16'."
        cursor.execute(q, p)
        results = cursor.fetchall()
        conn.close()
        if not results: return f"Sorry, I couldn't find the passage '{passage}'. Please check the reference."
        full_text = "".join([f"[{v[0]}] {v[1]} " for v in results])
        return f"📖 *{passage.strip()}*\n\n{full_text.strip()}"
    except Exception as e:
        print(f"SQLite Database Error: {e}")
        return "Sorry, I'm having trouble looking up the Bible verse right now."

def get_user_file_path(): return f'/tmp/{USERS_FILE}' if 'VERCEL' in os.environ else os.path.join(os.path.dirname(__file__), USERS_FILE)
def load_json_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return [] if any(x in file_path for x in ['lessons', 'hymn']) else {}
def save_json_data(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
def get_current_lesson_index(user_class):
    today = date.today()
    anchor_date = PRIMARY_PALS_ANCHOR_DATE if user_class == "Primary Pals" else ANCHOR_DATE
    anchor_week_start = anchor_date + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    week_difference = (current_week_start - anchor_week_start).days // 7
    return week_difference if week_difference >= 0 else -1
def format_hymn(hymn):
    if not hymn: return "Sorry, I couldn't find a hymn with that number."
    title, num = hymn.get('title', 'No Title'), hymn.get('number', '#')
    message = f"🎶 *Hymn #{num}: {title}*\n\n"
    verses, chorus, parts = hymn.get('verses', []), hymn.get('chorus', []), hymn.get('parts', [])
    chorus_text = "*Chorus:*\n" + "\n".join(chorus) + "\n\n" if chorus else ""
    if verses:
        for i, verse_lines in enumerate(verses, 1):
            message += f"*{i}.*\n" + "\n".join(verse_lines) + "\n\n"
            if chorus_text: message += chorus_text
    elif chorus_text: message += chorus_text
    if parts:
        for p in parts:
            part_num = p.get('part', '')
            message += f"*{f'Part {part_num}' if part_num else 'Part'}*\n"
            for i, v_lines in enumerate(p.get('verses', []), 1): message += f"*{i}.*\n" + "\n".join(v_lines) + "\n\n"
    return message.strip()
def format_primary_pals_lesson(lesson):
    if not lesson: return "Sorry, no 'Primary Pals' lesson is available."
    lesson_id, title = lesson.get('lesson_id', ''), lesson.get('title', 'N/A')
    parent_guide = lesson.get('parent_guide', {})
    bible_text = parent_guide.get('bible_text', {}).get('reference', 'N/A')
    memory_verse_info = parent_guide.get('memory_verse', {})
    mv_text, mv_ref = memory_verse_info.get('text', ''), memory_verse_info.get('reference', '')
    memory_verse = f"{mv_text} — {mv_ref}" if mv_text and mv_ref else 'N/A'
    story = "\n\n".join(lesson.get('story', []))
    message = f"🧸 *Primary Pals Lesson {lesson_id.upper()}: {title}*\n\n"
    if bible_text != 'N/A': message += f"📖 *Bible Text:*\n_{bible_text}_\n\n"
    if memory_verse != 'N/A': message += f"🔑 *Memory Verse:*\n_{memory_verse}_\n\n"
    message += "----------\n\n"
    if story: message += f"✨ *Lesson Story*\n{story}\n\n"
    message += "_Type 'ask [question]' or 'reset'_"
    return message.strip()
def format_search_answer_lesson(lesson, lesson_type):
    # This function is now only for Search/Answer, but remains for potential future use
    if not lesson: return f"Sorry, no '{lesson_type}' lesson is available."
    lesson_id = lesson.get('id', '')
    lesson_num_str = ''.join(filter(str.isdigit, lesson_id))
    lesson_number = f" {int(lesson_num_str)}" if lesson_num_str else ""
    title, key_verse, sup_scripture, resource = lesson.get('lessonTitle', 'N/A'), lesson.get('keyVerse'), lesson.get('supplementalScripture'), lesson.get('resourceMaterial')
    raw_refs = lesson.get('bibleReference', [])
    bible_refs_list = [f"{ref.get('book')} {ref.get('chapter')}" + (f":{ref.get('verses')}" if ref.get('verses') else "") for ref in raw_refs]
    bible_refs = ', '.join(bible_refs_list) if bible_refs_list else "N/A"
    message = f"📚 *{lesson_type} Lesson{lesson_number}: {title}*\n\n"
    if bible_refs != 'N/A': message += f"📖 *Bible Reference:*\n_{bible_refs}_\n\n"
    if sup_scripture: message += f"📜 *Supplemental Scripture:*\n_{sup_scripture}_\n\n"
    if resource: message += f"📦 *Resource Material:*\n_{resource}_\n\n"
    if key_verse: message += f"🔑 *Key Verse:*\n_{key_verse}_\n\n"
    message += "----------\n\n"
    for section in lesson.get('lessonSections', []):
        if section.get('sectionType') in ['text', 'question']:
            message += f"📌 *{section.get('sectionTitle', 'Section')}*\n{section.get('sectionContent', 'N/A').strip()}\n\n"
    message += "Have a blessed week! ✨\n_Type 'ask [question]' or 'reset'_"
    return message.strip()

def format_registration_details(data, camp_name):
    volunteer_info = data.get('Volunteer Status', '')
    if volunteer_info == 'Yes': volunteer_info += f" ({data.get('Volunteer Department', '')})"
    return (
        f"✅ *You are registered for the {camp_name}!* ✅\n\n"
        "Here are the details we have on file:\n\n"
        f"*Name:* {data.get('First Name', '')} {data.get('Last Name', '')}\n"
        f"*Gender:* {data.get('Gender', '')}\n"
        f"*Date of Birth:* {data.get('Date of Birth', '')} (Age: {data.get('Age', 'N/A')})\n"
        f"*ID/Passport:* {data.get('ID or Passport Number', '')}\n"
        f"*Phone:* {data.get('Phone Number', '')}\n\n"
        f"*Salvation Status:* {data.get('Salvation Status', '')}\n"
        f"*Dependents:* {data.get('Attending Dependents', '0')}\n"
        f"*Volunteering:* {volunteer_info}\n\n"
        f"*Next of Kin:* {data.get('Next of Kin Name', '')}\n"
        f"*NOK Phone:* {data.get('Next of Kin Phone', '')}\n\n"
        f"*Camp Stay:* {data.get('Camp Stay', '')}"
    )
def get_ai_response(question, context):
    if not gemini_model: return "Sorry, the AI module is unavailable."
    prompt = (f"You are a helpful Sunday School assistant. Answer the user's question based *only* on the following lesson text. If the answer is not in the text, say so. Keep answers concise.\n\n--- CONTEXT ---\n{context}\n\n--- QUESTION ---\n{question}")
    try: return gemini_model.generate_content(prompt).text.strip()
    except Exception as e:
        print(f"Google Gemini API Error: {e}")
        return "I'm having trouble thinking right now. Please try again."

# --- MAIN BOT LOGIC HANDLER ---
def handle_bot_logic(user_id, message_text):
    user_file = get_user_file_path()
    users = load_json_data(user_file)
    message_text_lower = message_text.lower().strip()
    user_profile = users.get(user_id, {})
    original_profile_state = json.dumps(user_profile)

    main_menu_text = ("Welcome! 🙏\n\nPlease choose a section:\n\n*1.* Weekly Lessons\n*2.* Hymnbook\n*3.* Bible Lookup\n*4.* 2025 Regional Youths Camp Registration\n*5.* 2025 Annual Camp Registration\n*6.* Check Registration")

    if message_text_lower == 'reset':
        user_profile = {}
        send_whatsapp_message(user_id, f"Your session has been reset. {main_menu_text}")
    else:
        mode = user_profile.get('mode')
        if not mode:
            if message_text_lower == '1': user_profile['mode'] = 'lessons'
            elif message_text_lower == '2': user_profile['mode'] = 'hymnbook'
            elif message_text_lower == '3': user_profile['mode'] = 'bible'
            elif message_text_lower == '4':
                user_profile['mode'] = 'camp_registration'
                user_profile['registration_type'] = 'youths'
            elif message_text_lower == '5':
                user_profile['mode'] = 'camp_registration'
                user_profile['registration_type'] = 'annual'
            elif message_text_lower == '6':
                user_profile['mode'] = 'check_registration'
            else:
                send_whatsapp_message(user_id, f"Sorry, I didn't understand. {main_menu_text}")
                return
            mode = user_profile.get('mode')
        
        if mode == 'lessons': user_profile = handle_lessons_mode(user_id, user_profile, message_text_lower)
        elif mode == 'hymnbook': user_profile = handle_hymnbook_mode(user_id, user_profile, message_text)
        elif mode == 'bible': user_profile = handle_bible_mode(user_id, user_profile, message_text)
        elif mode == 'camp_registration': user_profile = handle_registration_mode(user_id, user_profile, message_text)
        elif mode == 'check_registration': user_profile = handle_check_status_mode(user_id, user_profile, message_text_lower)
    
    if user_profile != users.get(user_id, {}):
        users[user_id] = user_profile
        save_json_data(users, user_file)

# --- MODE HANDLERS ---
def handle_lessons_mode(user_id, user_profile, message_text_lower):
    if 'class' not in user_profile:
        if message_text_lower in CLASSES:
            user_profile['class'] = CLASSES[message_text_lower]
            send_whatsapp_message(user_id, f"Great! Class set to *{user_profile['class']}*.\n\nType `lesson` to get this week's lesson.")
        else:
            send_whatsapp_message(user_id, "Please select your Sunday School class:\n\n" + "\n".join([f"*{k}.* {v}" for k, v in CLASSES.items()]))
    else:
        user_class = user_profile['class']
        lesson_files = {"Beginners": LESSONS_FILE_BEGINNERS, "Primary Pals": LESSONS_FILE_PRIMARY_PALS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH}
        if message_text_lower.startswith('ask '):
            question = message_text_lower[4:].strip()
            if not question: send_whatsapp_message(user_id, "Please type a question after `ask`.")
            else:
                send_whatsapp_message(user_id, "🤔 Thinking...")
                lesson_index = get_current_lesson_index(user_class)
                lesson_file_name = lesson_files.get(user_class)
                if lesson_file_name:
                    lessons_path = os.path.join(os.path.dirname(__file__), lesson_file_name)
                    raw_data = load_json_data(lessons_path)
                    lessons_list = raw_data.get("primary_pals_lessons", []) if user_class == "Primary Pals" else raw_data
                    if lessons_list and 0 <= lesson_index < len(lessons_list):
                        send_whatsapp_message(user_id, get_ai_response(question, json.dumps(lessons_list[lesson_index])))
                    else: send_whatsapp_message(user_id, "Sorry, I can't find this week's lesson material.")
                else: send_whatsapp_message(user_id, "Sorry, no lesson file found for your class.")
        elif message_text_lower == 'lesson':
            send_whatsapp_message(user_id, "Fetching this week's lesson...")
            lesson_index = get_current_lesson_index(user_class)
            if lesson_index < 0: send_whatsapp_message(user_id, "It seems there are no lessons scheduled for this week.")
            else:
                lesson_file_name = lesson_files.get(user_class)
                if not lesson_file_name: send_whatsapp_message(user_id, f"Sorry, lessons for '{user_class}' are not available yet.")
                else:
                    lessons_path = os.path.join(os.path.dirname(__file__), lesson_file_name)
                    raw_data = load_json_data(lessons_path)
                    lessons_list = raw_data.get("primary_pals_lessons", []) if user_class == "Primary Pals" else raw_data
                    if lessons_list and 0 <= lesson_index < len(lessons_list):
                        lesson = lessons_list[lesson_index]
                        if user_class == "Primary Pals": formatted_message = format_primary_pals_lesson(lesson)
                        elif user_class == "Beginners": formatted_message = format_beginners_lesson(lesson)
                        else: formatted_message = format_search_answer_lesson(lesson, user_class)
                        send_whatsapp_message(user_id, formatted_message)
                    else: send_whatsapp_message(user_id, "Sorry, I couldn't find this week's lesson. It might not be uploaded yet.")
        else: send_whatsapp_message(user_id, "In *Lessons* section: type `lesson`, `ask [question]`, or `reset`.")
    return user_profile

def handle_hymnbook_mode(user_id, user_profile, message_text):
    message_text_lower = message_text.lower()
    if 'hymnbook' not in user_profile:
        if message_text_lower in HYMNBOOKS:
            selected_hymnbook = HYMNBOOKS[message_text_lower]
            user_profile['hymnbook'] = selected_hymnbook['file']
            send_whatsapp_message(user_id, f"You have selected *{selected_hymnbook['name']}*.\n\nPlease type a hymn number.")
        else:
            send_whatsapp_message(user_id, "Please select your preferred hymnbook:\n\n" + "\n".join([f"*{k}.* {b['name']}" for k, b in HYMNBOOKS.items()]))
    else:
        if message_text.isdigit():
            hymns_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, user_profile['hymnbook'])
            hymns_data = load_json_data(hymns_path)
            found_hymn = next((h for h in hymns_data if h.get('number') == int(message_text)), None)
            send_whatsapp_message(user_id, format_hymn(found_hymn) if found_hymn else f"Sorry, hymn #{message_text} not found.")
        else: send_whatsapp_message(user_id, "Please type a valid hymn number.")
    return user_profile

def handle_bible_mode(user_id, user_profile, message_text):
    message_text_lower = message_text.lower()
    if 'bible_version_file' not in user_profile:
        if message_text_lower in BIBLES:
            selected_bible = BIBLES[message_text_lower]
            user_profile['bible_version_file'] = selected_bible['file']
            send_whatsapp_message(user_id, f"You have selected *{selected_bible['name']}*.\n\nPlease type a verse reference (e.g., `John 3:16`).")
        else:
            send_whatsapp_message(user_id, "Please select a Bible version:\n\n" + "\n".join([f"*{k}.* {b['name']}" for k, b in BIBLES.items()]))
    else:
        send_whatsapp_message(user_id, f"Looking up *{message_text.strip()}*...")
        send_whatsapp_message(user_id, get_verse_from_db(message_text.strip(), user_profile['bible_version_file']))
    return user_profile

def handle_registration_mode(user_id, user_profile, message_text):
    step = user_profile.get('registration_step', 'start')
    data = user_profile.setdefault('registration_data', {})
    reg_type = user_profile.get('registration_type', 'annual')
    camp_name, camp_dates_text, arrival_eg, departure_eg = ("2025 Regional Youths Camp", "from Aug 17 to Aug 24, 2025.", "Aug 17", "Aug 24") if reg_type == 'youths' else ("2025 Annual Camp", "from Dec 7 to Dec 21, 2025.", "Dec 7", "Dec 21")
    
    if step == 'start':
        send_whatsapp_message(user_id, f"🏕️ *{camp_name} Registration*\n\nLet's get started. You can type `reset` at any time.\n\nFirst, what is your *first name*?")
        user_profile['registration_step'] = 'awaiting_first_name'
    elif step == 'awaiting_first_name':
        data['first_name'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_last_name'
        send_whatsapp_message(user_id, "Great! What is your *last name*?")
    elif step == 'awaiting_last_name':
        data['last_name'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_dob'
        send_whatsapp_message(user_id, "Got it. What is your *date of birth*?\n(DD/MM/YYYY format)")
    elif step == 'awaiting_dob':
        age = calculate_age(message_text.strip())
        if not age: send_whatsapp_message(user_id, "Please use DD/MM/YYYY format.")
        else:
            data['dob'], data['age'] = message_text.strip(), age; user_profile['registration_step'] = 'awaiting_gender'
            send_whatsapp_message(user_id, "What is your *gender*? (Male / Female)")
    elif step == 'awaiting_gender':
        if message_text.lower().strip() not in ['male', 'female']: send_whatsapp_message(user_id, "Please answer *Male* or *Female*.")
        else:
            data['gender'] = message_text.strip().capitalize(); user_profile['registration_step'] = 'awaiting_id_passport'
            send_whatsapp_message(user_id, "Please enter your *ID or Passport number*.")
    elif step == 'awaiting_id_passport':
        data['id_passport'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_phone_number'
        send_whatsapp_message(user_id, "Please enter your *phone number* in international format (e.g., +263771234567).")
    elif step == 'awaiting_phone_number':
        if not re.match(r'^\+\d{9,}$', message_text.strip()): send_whatsapp_message(user_id, "That doesn't look like a valid international number. Please try again (e.g., `+263771234567`).")
        else:
            data['phone'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_salvation_status'
            send_whatsapp_message(user_id, "Are you saved? (*Yes* or *No*)")
    elif step == 'awaiting_salvation_status':
        if message_text.lower().strip() not in ['yes', 'no']: send_whatsapp_message(user_id, "Please just answer *Yes* or *No*.")
        else:
            data['salvation_status'] = message_text.strip().capitalize(); user_profile['registration_step'] = 'awaiting_dependents'
            send_whatsapp_message(user_id, "How many dependents (e.g., children) will attend with you? (Enter 0 if none)")
    elif step == 'awaiting_dependents':
        if not message_text.strip().isdigit(): send_whatsapp_message(user_id, "Please enter a number (e.g., 0, 1, 2).")
        else:
            data['dependents'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_nok_name'
            send_whatsapp_message(user_id, "Who is your *next of kin*? (Full name)")
    elif step == 'awaiting_nok_name':
        data['nok_name'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_nok_phone'
        send_whatsapp_message(user_id, "What is your *next of kin's phone number*? (International format)")
    elif step == 'awaiting_nok_phone':
        if not re.match(r'^\+\d{9,}$', message_text.strip()): send_whatsapp_message(user_id, "Please provide a valid international number for your next of kin.")
        else:
            data['nok_phone'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_camp_start_date'
            send_whatsapp_message(user_id, f"The camp runs {camp_dates_text}\n\nWhat is your *arrival date*? (e.g., {arrival_eg})")
    elif step == 'awaiting_camp_start_date':
        data['camp_start'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_camp_end_date'
        send_whatsapp_message(user_id, f"And what is your *departure date*? (e.g., {departure_eg})")
    elif step == 'awaiting_camp_end_date':
        data['camp_end'] = message_text.strip(); user_profile['registration_step'] = 'awaiting_volunteer_status'
        send_whatsapp_message(user_id, "Thank you. Are you willing to assist voluntarily during the camp? (*Yes* or *No*)")
    elif step == 'awaiting_volunteer_status':
        if message_text.lower().strip() not in ['yes', 'no']: send_whatsapp_message(user_id, "Please just answer *Yes* or *No*.")
        else:
            data['volunteer_status'] = message_text.strip().capitalize()
            if message_text.lower().strip() == 'yes':
                department_menu = "That's wonderful! Which department would you like to assist in?\n\n" + "\n".join([f"*{k}.* {v}" for k, v in DEPARTMENTS.items()])
                send_whatsapp_message(user_id, department_menu)
                user_profile['registration_step'] = 'awaiting_volunteer_department'
            else:
                data['volunteer_department'] = 'N/A'; user_profile['registration_step'] = 'awaiting_confirmation'
                _send_confirmation_message(user_id, data, camp_name)
    elif step == 'awaiting_volunteer_department':
        if message_text.lower().strip() not in DEPARTMENTS:
            send_whatsapp_message(user_id, "Invalid selection. Please choose a number from the list.")
        else:
            data['volunteer_department'] = DEPARTMENTS[message_text.lower().strip()]
            user_profile['registration_step'] = 'awaiting_confirmation'
            _send_confirmation_message(user_id, data, camp_name)
    elif step == 'awaiting_confirmation':
        if message_text.lower().strip() == 'confirm':
            send_whatsapp_message(user_id, "Thank you! Submitting your registration...")
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data.get('first_name', ''), data.get('last_name', ''),
                data.get('dob', ''), data.get('age', ''), data.get('gender', ''),
                data.get('id_passport', ''), data.get('phone', ''),
                data.get('salvation_status', ''), data.get('dependents', ''),
                data.get('volunteer_status', ''), data.get('volunteer_department', ''),
                data.get('nok_name', ''), data.get('nok_phone', ''),
                f"{data.get('camp_start', '')} to {data.get('camp_end', '')}"
            ]
            sheet_to_use = YOUTH_CAMP_SHEET_NAME if reg_type == 'youths' else ANNUAL_CAMP_SHEET_NAME
            if append_to_google_sheet(row, sheet_to_use):
                send_whatsapp_message(user_id, f"✅ Registration successful for the {camp_name}! We look forward to seeing you.")
            else:
                send_whatsapp_message(user_id, "⚠️ There was a problem submitting your registration. Please contact an administrator.")
            return {}
        elif message_text.lower().strip() == 'restart':
            user_profile['registration_data'] = {}; user_profile['registration_step'] = 'start'
            return handle_registration_mode(user_id, user_profile, "")
        else: send_whatsapp_message(user_id, "Please type *confirm* or *restart*.")
    return user_profile

def handle_check_status_mode(user_id, user_profile, message_text_lower):
    if 'check_step' not in user_profile:
        send_whatsapp_message(user_id, "Which camp registration would you like to check?\n\n*1.* 2025 Regional Youths Camp\n*2.* 2025 Annual Camp")
        user_profile['check_step'] = 'awaiting_camp_choice'
    else:
        sheet_to_check, camp_name = (YOUTH_CAMP_SHEET_NAME, "2025 Regional Youths Camp") if message_text_lower == '1' else (ANNUAL_CAMP_SHEET_NAME, "2025 Annual Camp") if message_text_lower == '2' else (None, None)
        if not sheet_to_check:
            send_whatsapp_message(user_id, "Invalid selection. Please type *1* for Youths Camp or *2* for Annual Camp.")
            return user_profile
        send_whatsapp_message(user_id, f"🔍 Checking your registration for the *{camp_name}*...")
        registration_data = check_registration_status(user_id, sheet_to_check)
        if registration_data:
            send_whatsapp_message(user_id, format_registration_details(registration_data, camp_name))
        else:
            send_whatsapp_message(user_id, f"❌ We couldn't find a registration for your phone number for the *{camp_name}*.")
        send_whatsapp_message(user_id, "You are now back at the main menu. Type `reset` to see all options.")
        return {}
    return user_profile

def _send_confirmation_message(user_id, data, camp_name):
    volunteer_info = data.get('volunteer_status', '')
    if volunteer_info == 'Yes': volunteer_info += f" ({data.get('volunteer_department', '')})"
    confirmation_message = (f"📝 *Please confirm your details for the {camp_name}:*\n\n"
        f"*Name:* {data.get('first_name', '')} {data.get('last_name', '')}\n"
        f"*Gender:* {data.get('gender', '')}\n"
        f"*Date of Birth:* {data.get('dob', '')} (Age: {data.get('age', 'N/A')})\n"
        f"*ID/Passport:* {data.get('id_passport', '')}\n"
        f"*Phone:* {data.get('phone', '')}\n\n"
        f"*Salvation Status:* {data.get('salvation_status', '')}\n"
        f"*Dependents:* {data.get('dependents', '0')}\n"
        f"*Volunteering:* {volunteer_info}\n\n"
        f"*Next of Kin:* {data.get('nok_name', '')}\n"
        f"*NOK Phone:* {data.get('nok_phone', '')}\n\n"
        f"*Camp Stay:* {data.get('camp_start', '')} to {data.get('camp_end', '')}\n\n"
        "Is everything correct? Type *confirm* to submit, or *restart* to enter your details again.")
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
    return "SundayBot with Camp Registration & Check is running!", 200