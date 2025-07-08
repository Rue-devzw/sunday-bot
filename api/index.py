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

# Anchor date for Beginners, Answer, and Search classes.
ANCHOR_DATE = date(2024, 8, 21)
# A separate anchor date specifically for the Primary Pals curriculum.
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

def check_registration_status(phone_number, sheet_name):
    if not GOOGLE_CREDENTIALS_JSON:
        print("ERROR: Google credentials JSON not set in environment variables.")
        return None
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open(sheet_name).sheet1
        
        user_phone_international = f"+{phone_number}"
        
        records = sheet.get_all_records()
        for record in records:
            if str(record.get('Phone Number')) == user_phone_international:
                return record
        return None
    except Exception as e:
        print(f"Error checking registration in Google Sheet: {e}")
        return None

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

def load_json_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if any(x in file_path for x in ['lessons', 'hymn']) else {}

def save_json_data(data, file_path):
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

def format_primary_pals_lesson(lesson):
    if not lesson: return "Sorry, no 'Primary Pals' lesson is available for this week."
    lesson_id_str, title = lesson.get('lesson_id', ''), lesson.get('title', 'N/A')
    parent_guide = lesson.get('parent_guide', {})
    bible_text_info = parent_guide.get('bible_text', {})
    bible_refs = bible_text_info.get('reference', 'N/A')
    memory_verse_info = parent_guide.get('memory_verse', {})
    memory_verse_text, memory_verse_ref = memory_verse_info.get('text', ''), memory_verse_info.get('reference', '')
    memory_verse = f"{memory_verse_text} — {memory_verse_ref}" if memory_verse_text and memory_verse_ref else 'N/A'
    story_paragraphs = lesson.get('story', [])
    story_content = "\n\n".join(story_paragraphs) if story_paragraphs else ""
    parents_corner_info = parent_guide.get('parents_corner', {})
    parents_corner_title = parents_corner_info.get('title', "Parent's Corner")
    parents_corner_text = parents_corner_info.get('text', 'No guide available.')
    family_devotions_info = parent_guide.get('family_devotions', {})
    family_devotions_title, family_devotions_intro = family_devotions_info.get('title', 'Family Devotions'), family_devotions_info.get('intro', '')
    devotion_verses = family_devotions_info.get('verses', [])
    message = f"🧸 *Primary Pals Lesson {lesson_id_str.upper()}: {title}*\n\n"
    if bible_refs != 'N/A': message += f"📖 *Bible Text:*\n_{bible_refs}_\n\n"
    if memory_verse != 'N/A': message += f"🔑 *Memory Verse:*\n_{memory_verse}_\n\n"
    message += "----------\n\n"
    if story_content: message += f"✨ *Lesson Story*\n{story_content}\n\n"
    message += f"--- *Parent's Guide* ---\n\n📌 *{parents_corner_title}*\n{parents_corner_text}\n\n"
    message += f"📌 *{family_devotions_title}*\n"
    if family_devotions_intro: message += f"_{family_devotions_intro}_\n"
    message += "".join([f"  *{v.get('day')}:* {v.get('reference')}\n" for v in devotion_verses])
    message += "\nHave a blessed week! 🧸\n_Type 'ask [question]' or 'reset'_"
    return message.strip()

def format_registration_details(data, camp_name):
    message = (
        f"✅ *You are registered for the {camp_name}!* ✅\n\n"
        "Here are the details we have on file:\n\n"
        f"*Name:* {data.get('First Name', '')} {data.get('Last Name', '')}\n"
        f"*Gender:* {data.get('Gender', '')}\n"
        f"*Date of Birth:* {data.get('Date of Birth', '')} (Age: {data.get('Age', 'N/A')})\n"
        f"*ID/Passport:* {data.get('ID or Passport Number', '')}\n"
        f"*Phone:* {data.get('Phone Number', '')}\n\n"
        f"*Salvation Status:* {data.get('Salvation Status', '')}\n"
        f"*Dependents Attending:* {data.get('Attending Dependents', '0')}\n"
        f"*Volunteering:* {data.get('Volunteer Status', '')}"
        f"{' (' + data.get('Volunteer Department', '') + ')' if data.get('Volunteer Status') == 'Yes' else ''}\n\n"
        f"*Next of Kin:* {data.get('Next of Kin Name', '')}\n"
        f"*NOK Phone:* {data.get('Next of Kin Phone', '')}\n\n"
        f"*Camp Stay:* {data.get('Camp Stay', '')}"
    )
    return message

# --- MAIN BOT LOGIC HANDLER ---
def handle_bot_logic(user_id, message_text):
    user_file = get_user_file_path()
    users = load_json_data(user_file)
    message_text_lower = message_text.lower().strip()
    user_profile = users.get(user_id, {})
    original_profile_state = json.dumps(user_profile)

    main_menu_text = (
        "Welcome! 🙏\n\nPlease choose a section:\n\n"
        "*1.* Weekly Lessons\n"
        "*2.* Hymnbook\n"
        "*3.* Bible Lookup\n"
        "*4.* 2025 Regional Youths Camp Registration\n"
        "*5.* 2025 Annual Camp Registration\n"
        "*6.* Check Registration"
    )

    if message_text_lower == 'reset':
        user_profile = {}
        send_whatsapp_message(user_id, f"Your session has been reset. {main_menu_text}")
        if user_id in users: del users[user_id]
        save_json_data(users, user_file)
        return

    # FIX: Refactored state machine to prevent recursion and handle all modes correctly.
    # If the user has no mode, they are at the main menu.
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
        elif message_text_lower == '6':
            user_profile['mode'] = 'check_registration'
        else:
            send_whatsapp_message(user_id, main_menu_text)
            return # Stop here if input is invalid

    # --- Mode Handler: Lessons ---
    if user_profile.get('mode') == 'lessons':
        if 'class' not in user_profile:
            class_menu = "Please select your Sunday School class:\n\n"
            for k, v in CLASSES.items(): class_menu += f"*{k}.* {v}\n"
            send_whatsapp_message(user_id, class_menu.strip())
            user_profile['mode'] = 'awaiting_class_selection' # Set a temporary state
        else:
            # This block handles users who have already selected a class.
            user_class = user_profile.get('class')
            lesson_files = { "Beginners": LESSONS_FILE_BEGINNERS, "Primary Pals": LESSONS_FILE_PRIMARY_PALS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH }
            
            if message_text_lower.startswith('ask '):
                # ... ask logic ...
                pass
            elif message_text_lower == 'lesson':
                send_whatsapp_message(user_id, "Fetching this week's lesson...")
                lesson_index = get_current_lesson_index(user_class)
                if lesson_index < 0: send_whatsapp_message(user_id, "It seems there are no lessons scheduled for this week.")
                else:
                    lesson_file_name = lesson_files.get(user_class)
                    if not lesson_file_name: send_whatsapp_message(user_id, f"Sorry, lessons for the '{user_class}' class are not available yet.")
                    else:
                        lessons_path = os.path.join(os.path.dirname(__file__), lesson_file_name)
                        raw_data = load_json_data(lessons_path)
                        lessons_list = raw_data.get("primary_pals_lessons", []) if user_class == "Primary Pals" else raw_data
                        if lessons_list and 0 <= lesson_index < len(lessons_list):
                            lesson = lessons_list[lesson_index]
                            formatted_message = ""
                            if user_class == "Beginners": formatted_message = format_beginners_lesson(lesson)
                            elif user_class == "Primary Pals": formatted_message = format_primary_pals_lesson(lesson)
                            elif user_class in ["Search", "Answer"]: formatted_message = format_search_answer_lesson(lesson, user_class)
                            else: formatted_message = f"Sorry, I don't know how to format the lesson for the '{user_class}' class yet."
                            send_whatsapp_message(user_id, formatted_message)
                        else:
                            send_whatsapp_message(user_id, "Sorry, I couldn't find this week's lesson. It might not be uploaded yet.")
            else: 
                send_whatsapp_message(user_id, "In *Lessons* section: type `lesson`, `ask [question]`, or `reset`.")
    
    elif user_profile.get('mode') == 'awaiting_class_selection':
        if message_text_lower in CLASSES:
            class_name = CLASSES[message_text_lower]
            user_profile['class'] = class_name
            user_profile['mode'] = 'lessons' # Transition back to the main lessons mode
            send_whatsapp_message(user_id, f"Great! Class set to *{class_name}*.\n\nType `lesson` to get this week's lesson.\nType `reset` to go back.")
        else:
            send_whatsapp_message(user_id, "Invalid class number. Please try again.")

    # --- Mode Handler: Camp Registration ---
    elif user_profile.get('mode') == 'camp_registration':
        step = user_profile.get('registration_step', 'start')
        data = user_profile.setdefault('registration_data', {})
        reg_type = user_profile.get('registration_type', 'annual')
        camp_name, camp_dates_text = ("2025 Regional Youths Camp", "The camp runs from Aug 17 to Aug 24, 2025.") if reg_type == 'youths' else ("2025 Annual Camp", "The camp runs from Dec 7 to Dec 21, 2025.")
        
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
            if not age: send_whatsapp_message(user_id, "That doesn't look right. Please enter your date of birth in DD/MM/YYYY format.")
            else:
                data['dob'], data['age'] = message_text.strip(), age
                send_whatsapp_message(user_id, "What is your *gender*? (Male / Female)")
                user_profile['registration_step'] = 'awaiting_gender'
        elif step == 'awaiting_gender':
            if message_text_lower not in ['male', 'female']: send_whatsapp_message(user_id, "Please just answer with *Male* or *Female*.")
            else:
                data['gender'] = message_text.strip().capitalize()
                send_whatsapp_message(user_id, "Thanks. Now, please enter your *ID or Passport number*.")
                user_profile['registration_step'] = 'awaiting_id_passport'
        elif step == 'awaiting_id_passport':
            data['id_passport'] = message_text.strip()
            send_whatsapp_message(user_id, "Please enter your *phone number* in international format (e.g., +263771234567).")
            user_profile['registration_step'] = 'awaiting_phone_number'
        elif step == 'awaiting_phone_number':
            if not re.match(r'^\+\d{9,}$', message_text.strip()): send_whatsapp_message(user_id, "Hmm, that doesn't seem like a valid international phone number. Please try again (e.g., `+263771234567`).")
            else:
                data['phone'] = message_text.strip()
                send_whatsapp_message(user_id, "Are you saved? (Please answer *Yes* or *No*)")
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
                send_whatsapp_message(user_id, "Who is your *next of kin*? (Please provide their full name).")
                user_profile['registration_step'] = 'awaiting_nok_name'
        elif step == 'awaiting_nok_name':
            data['nok_name'] = message_text.strip()
            send_whatsapp_message(user_id, "What is your *next of kin's phone number*? (International format, e.g., +263771234567).")
            user_profile['registration_step'] = 'awaiting_nok_phone'
        elif step == 'awaiting_nok_phone':
            if not re.match(r'^\+\d{9,}$', message_text.strip()): send_whatsapp_message(user_id, "That doesn't look like a valid phone number. Please provide the next of kin's number in international format.")
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
            if message_text_lower not in ['yes', 'no']: send_whatsapp_message(user_id, "Please just answer *Yes* or *No*.")
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
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data.get('first_name', ''), data.get('last_name', ''),
                    data.get('dob', ''), data.get('age', ''), data.get('gender', ''),
                    data.get('id_passport', ''), data.get('phone', ''),
                    data.get('salvation_status', ''), data.get('dependents', ''),
                    data.get('volunteer_status', ''), data.get('volunteer_department', ''),
                    data.get('nok_name', ''), data.get('nok_phone', ''),
                    f"{data.get('camp_start', '')} to {data.get('camp_end', '')}"
                ]
                sheet_to_use = YOUTH_CAMP_SHEET_NAME if reg_type == 'youths' else ANNUAL_CAMP_SHEET_NAME
                success = append_to_google_sheet(row, sheet_to_use)
                if success: send_whatsapp_message(user_id, f"✅ Registration successful for the {camp_name}! We look forward to seeing you.")
                else: send_whatsapp_message(user_id, "⚠️ There was a problem submitting your registration. Please contact an administrator.")
                user_profile = {}
                if user_id in users: del users[user_id]
            elif message_text_lower == 'restart':
                user_profile['registration_step'] = 'start'
                handle_bot_logic(user_id, message_text)
                return
            else:
                send_whatsapp_message(user_id, "Please type *confirm* or *restart*.")

    elif user_profile.get('mode') == 'check_registration':
        if 'check_step' not in user_profile:
            send_whatsapp_message(user_id, "Which camp registration would you like to check?\n\n*1.* 2025 Regional Youths Camp\n*2.* 2025 Annual Camp")
            user_profile['check_step'] = 'awaiting_camp_choice'
        else:
            sheet_to_check, camp_name = None, None
            if message_text_lower == '1': sheet_to_check, camp_name = YOUTH_CAMP_SHEET_NAME, "2025 Regional Youths Camp"
            elif message_text_lower == '2': sheet_to_check, camp_name = ANNUAL_CAMP_SHEET_NAME, "2025 Annual Camp"
            else:
                send_whatsapp_message(user_id, "Invalid selection. Please type *1* for Youths Camp or *2* for Annual Camp.")
                return

            send_whatsapp_message(user_id, f"🔍 Checking your registration for the *{camp_name}*...")
            registration_data = check_registration_status(user_id, sheet_to_check)
            if registration_data:
                send_whatsapp_message(user_id, format_registration_details(registration_data, camp_name))
            else:
                send_whatsapp_message(user_id, f"❌ We couldn't find a registration for your phone number for the *{camp_name}*.\n\nIf you believe this is an error, please contact an administrator. Otherwise, you can register from the main menu.")
            user_profile = {}
            if user_id in users: del users[user_id]
            send_whatsapp_message(user_id, "You are now back at the main menu. Type `reset` to see all options.")
            
    # ... (other modes like hymnbook, bible, etc.) ...

    if json.dumps(user_profile) != original_profile_state:
        users[user_id] = user_profile
        save_json_data(users, user_file)

def _send_confirmation_message(user_id, data, camp_name):
    """Helper function to build and send the confirmation message."""
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
    return "SundayBot with Full Features is running!", 200