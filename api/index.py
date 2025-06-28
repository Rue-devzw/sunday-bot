# api/index.py

import os
import json
import requests
import google.generativeai as genai
import sqlite3
import re
from flask import Flask, request
from datetime import date
from dateutil.relativedelta import relativedelta, MO

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

ANCHOR_DATE = date(2024, 8, 21)
USERS_FILE = 'users.json'
HYMNBOOKS_DIR = 'hymnbooks'
BIBLES_DIR = 'bibles'
LESSONS_FILE_SEARCH = 'search_lessons.json'
LESSONS_FILE_ANSWER = 'answer_lessons.json'
LESSONS_FILE_BEGINNERS = 'beginners_lessons.json'

CLASSES = { "1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search" }
HYMNBOOKS = {
    "1": {"name": "Nziyo Dzekurumbidza (Shona Hymns)", "file": "shona_hymns.json"},
    "2": {"name": "Great Hymns of Faith (English)", "file": "english_hymns.json"}
}
BIBLES = {
    "1": {"name": "Shona Bible", "file": "shona_bible.db"},
    "2": {"name": "English Bible (KJV)", "file": "english_bible.db"}
}

# --- 3. HELPER & FORMATTING FUNCTIONS ---

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
        
        # FIX: Updated table name from 'verses' to 'bible_verses' to match your schema.
        
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

def get_current_lesson_index():
    today = date.today()
    anchor_week_start = ANCHOR_DATE + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    week_difference = (current_week_start - anchor_week_start).days // 7
    return week_difference if week_difference >= 0 else -1

def format_hymn(hymn):
    if not hymn: return "Sorry, I couldn't find a hymn with that number in your selected hymnbook."
    title = hymn.get('title', 'No Title')
    hymn_number = hymn.get('number', '#')
    message = f"🎶 *Hymn #{hymn_number}: {title}*\n\n"
    verses = hymn.get('verses', [])
    chorus = hymn.get('chorus', [])
    parts = hymn.get('parts', [])
    if verses:
        for i, verse_lines in enumerate(verses, 1): message += f"*{i}.*\n" + "\n".join(verse_lines) + "\n\n"
    if chorus: message += "*Chorus:*\n" + "\n".join(chorus) + "\n\n"
    if parts:
        for part in parts:
            message += f"*Part {part['part']}*\n"
            for v_lines in part['verses']: message += "\n".join(v_lines) + "\n\n"
    return message.strip()

def format_beginners_lesson(lesson):
    if not lesson: return "Sorry, no 'Beginners' lesson is available."
    title = lesson.get('lessonTitle', 'N/A')
    bible_refs_list = [f"{ref['book']} {ref['chapter']}" for ref in lesson.get('bibleReference', []) if ref.get('book') and ref.get('chapter')]
    bible_refs = ', '.join(bible_refs_list) if bible_refs_list else "N/A"
    message = f"🖍️ *Beginners Lesson: {title}*\n\n_(Story from: {bible_refs})_\n\n"
    for section in lesson.get('lessonSections', []):
        if section.get('sectionType') == 'text': message += f"{section.get('sectionContent', 'No story available.')}\n\n"
    message += "Have a blessed week! ☀️"
    return message

def format_search_answer_lesson(lesson, lesson_type):
    if not lesson: return f"Sorry, no '{lesson_type}' lesson is available for this week."
    title = lesson.get('lessonTitle', 'N/A')
    memory_verse = lesson.get('keyVerse', 'N/A')
    message = f"📚 *{lesson_type} Lesson: {title}*\n\n"
    message += f"📖 *Key Verse:*\n_{memory_verse}_\n\n"
    message += "----------\n\n"
    for section in lesson.get('lessonSections', []):
        if section.get('sectionType') in ['text', 'question']:
            section_title = section.get('sectionTitle', 'Section')
            section_content = section.get('sectionContent', 'No content available.')
            message += f"📌 *{section_title}*\n{section_content}\n\n"
    message += "Have a blessed week! ✨"
    return message.strip()

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
    user_file = get_user_file_path()
    users = load_json_data(user_file)
    message_text_lower = message_text.lower().strip()
    user_profile = users.get(user_id, {})
    original_profile_state = json.dumps(user_profile)

    if message_text_lower == 'reset':
        user_profile = {}
        send_whatsapp_message(user_id, "Your session has been reset. Welcome! 🙏\n\nPlease choose a section:\n\n*1.* Weekly Lessons\n*2.* Hymnbook\n*3.* Bible Lookup")
        if user_id in users: del users[user_id]
        save_json_data(users, user_file)
        return

    if 'mode' not in user_profile:
        if message_text_lower == '1':
            user_profile['mode'] = 'lessons'
            class_menu = "Please select your Sunday School class:\n\n"
            for k, v in CLASSES.items(): class_menu += f"*{k}.* {v}\n"
            send_whatsapp_message(user_id, class_menu.strip())
        elif message_text_lower == '2':
            user_profile['mode'] = 'hymnbook'
            hymnbook_menu = "Please select your preferred hymnbook:\n\n"
            for k, b in HYMNBOOKS.items(): hymnbook_menu += f"*{k}.* {b['name']}\n"
            send_whatsapp_message(user_id, hymnbook_menu.strip())
        elif message_text_lower == '3':
            user_profile['mode'] = 'bible'
            bible_menu = "Please select a Bible version:\n\n"
            for k, b in BIBLES.items(): bible_menu += f"*{k}.* {b['name']}\n"
            send_whatsapp_message(user_id, bible_menu.strip())
        else:
            send_whatsapp_message(user_id, "Welcome! 🙏\n\nPlease choose a section:\n\n*1.* Weekly Lessons\n*2.* Hymnbook\n*3.* Bible Lookup")
    
    elif user_profile.get('mode') == 'lessons':
        if 'class' not in user_profile:
            if message_text_lower in CLASSES:
                class_name = CLASSES[message_text_lower]; user_profile['class'] = class_name
                send_whatsapp_message(user_id, f"Great! Class set to *{class_name}*.\n\nType `lesson` or `ask [your question]`.\nType `reset` to go back.")
            else: send_whatsapp_message(user_id, "Invalid class number. Please try again.")
        elif message_text_lower.startswith('ask '):
            question = message_text[4:].strip()
            if not question: send_whatsapp_message(user_id, "Please type a question after the word `ask`.")
            else:
                send_whatsapp_message(user_id, "🤔 Thinking...")
                lesson_index = get_current_lesson_index(); user_class = user_profile['class']; context = ""
                lesson_files = {"Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH}
                lesson_file_name = lesson_files.get(user_class)
                if lesson_file_name:
                    lessons_path = os.path.join(os.path.dirname(__file__), lesson_file_name)
                    lessons_data = load_json_data(lessons_path)
                    if lessons_data and 0 <= lesson_index < len(lessons_data): context = json.dumps(lessons_data[lesson_index])
                if not context: send_whatsapp_message(user_id, "Sorry, I can't find this week's lesson material to answer questions about.")
                else: ai_answer = get_ai_response(question, context); send_whatsapp_message(user_id, ai_answer)
        elif message_text_lower == 'lesson':
            send_whatsapp_message(user_id, "Fetching this week's lesson...")
            lesson_index = get_current_lesson_index(); user_class = user_profile.get('class')
            if lesson_index < 0: send_whatsapp_message(user_id, "It seems there are no lessons scheduled for this week.")
            else:
                lesson_files = {"Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH}
                lesson_file_name = lesson_files.get(user_class)
                if not lesson_file_name: send_whatsapp_message(user_id, f"Sorry, lessons for the '{user_class}' class are not available yet.")
                else:
                    lessons_path = os.path.join(os.path.dirname(__file__), lesson_file_name)
                    lessons_data = load_json_data(lessons_path)
                    if lessons_data and 0 <= lesson_index < len(lessons_data):
                        lesson = lessons_data[lesson_index]; formatted_message = ""
                        if user_class == "Beginners": formatted_message = format_beginners_lesson(lesson)
                        elif user_class in ["Search", "Answer"]: formatted_message = format_search_answer_lesson(lesson, user_class)
                        else: formatted_message = f"Sorry, I don't know how to format the lesson for the '{user_class}' class yet."
                        send_whatsapp_message(user_id, formatted_message)
                    else: send_whatsapp_message(user_id, "Sorry, I couldn't find this week's lesson. It might not be uploaded yet.")
        else: send_whatsapp_message(user_id, "In *Lessons* section: type `lesson`, `ask [question]`, or `reset`.")

    elif user_profile.get('mode') == 'hymnbook':
        if 'hymnbook' not in user_profile:
            if message_text_lower in HYMNBOOKS:
                selected_hymnbook = HYMNBOOKS[message_text_lower]; user_profile['hymnbook'] = selected_hymnbook['file']
                send_whatsapp_message(user_id, f"You have selected *{selected_hymnbook['name']}*.\n\nPlease type a hymn number, or `reset` to start over.")
            else: send_whatsapp_message(user_id, "Invalid selection. Please choose a hymnbook from the list.")
        else:
            if message_text.isdigit():
                hymn_number_to_find = int(message_text); hymnbook_file = user_profile['hymnbook']
                hymns_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, hymnbook_file); hymns_data = load_json_data(hymns_path)
                found_hymn = next((hymn for hymn in hymns_data if hymn.get('number') == hymn_number_to_find), None)
                if found_hymn: formatted_hymn = format_hymn(found_hymn); send_whatsapp_message(user_id, formatted_hymn)
                else: send_whatsapp_message(user_id, f"Sorry, I couldn't find hymn #{hymn_number_to_find} in that hymnbook.")
            else: send_whatsapp_message(user_id, "Please type a valid hymn number, or `reset` to start over.")

    elif user_profile.get('mode') == 'bible':
        if 'bible_version_file' not in user_profile:
            if message_text_lower in BIBLES:
                selected_bible = BIBLES[message_text_lower]
                user_profile['bible_version_file'] = selected_bible['file']
                send_whatsapp_message(user_id, f"You have selected *{selected_bible['name']}*.\n\nPlease type a verse reference (e.g., `John 3:16`).\nType `reset` to start over.")
            else:
                send_whatsapp_message(user_id, "Invalid selection. Please choose a Bible version from the list.")
        else:
            passage_text = message_text.strip()
            db_filename = user_profile['bible_version_file']
            send_whatsapp_message(user_id, f"Looking up *{passage_text}*...")
            verse_response = get_verse_from_db(passage_text, db_filename)
            send_whatsapp_message(user_id, verse_response)

    if json.dumps(user_profile) != original_profile_state:
        users[user_id] = user_profile
        save_json_data(users, user_file)

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
    return "SundayBot with Local Bible DBs is running!", 200