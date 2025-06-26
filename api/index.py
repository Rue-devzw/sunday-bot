# api/index.py

import os
import json
import requests
from flask import Flask, request
from datetime import date
from dateutil.relativedelta import relativedelta, MO

# --- 1. INITIALIZE FLASK APP ---
app = Flask(__name__)

# --- 2. CONFIGURATION & ENVIRONMENT VARIABLES ---
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')

# Static Configuration
ANCHOR_DATE = date(2024, 8, 21)
LESSONS_FILE_SEARCH = 'search_lessons.json'
LESSONS_FILE_ANSWER = 'answer_lessons.json'
LESSONS_FILE_BEGINNERS = 'beginners_lessons.json'
USERS_FILE = 'users.json'

CLASSES = { "1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search" }

# --- UPDATED: Hymnbook Configuration ---
# We've added a third option for the Shona Hymnbook.
HYMNBOOKS = {
    "1": {"name": "Great Hymns of Faith", "file": "great_hymns_of_faith.json"},
    "2": {"name": "Celestial Hymns", "file": "celestial_hymns.json"},
    "3": {"name": "Nziyo Dzekurumbidza (Shona Hymns)", "file": "shona_hymns.json"} # <-- NEW
}

# --- 3. HELPER FUNCTIONS ---
def get_user_file_path():
    return f'/tmp/{USERS_FILE}' if 'VERCEL' in os.environ else os.path.join(os.path.dirname(__file__), USERS_FILE)

def load_json_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_json_data(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

def get_current_lesson_index():
    today = date.today()
    anchor_week_start = ANCHOR_DATE + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    week_difference = (current_week_start - anchor_week_start).days // 7
    return week_difference if week_difference >= 0 else -1

# --- FORMATTING FUNCTIONS ---

# --- UPDATED: Hymn Formatter to handle verses and chorus ---
def format_hymn(hymn):
    """Formats a hymn, including chorus and verses, into a WhatsApp message."""
    if not hymn:
        return "Sorry, I couldn't find a hymn with that number in your selected hymnbook."
    
    title = hymn.get('title', 'No Title')
    hymn_number = hymn.get('number', '#')
    
    message = f"🎶 *Hymn #{hymn_number}: {title}*\n\n"
    
    # Check for verses and format them
    verses = hymn.get('verses', [])
    if verses:
        for i, verse_lines in enumerate(verses, 1):
            message += f"*{i}.*\n"
            message += "\n".join(verse_lines)
            message += "\n\n"
            
    # Check for a chorus and add it
    chorus = hymn.get('chorus', [])
    if chorus:
        message += "*Chorus:*\n"
        message += "\n".join(chorus)
        message += "\n\n"

    # Handle the special case for hymn 123 with parts
    parts = hymn.get('parts', [])
    if parts:
        for part in parts:
            message += f"*Part {part['part']}*\n"
            for verse_lines in part['verses']:
                message += "\n".join(verse_lines)
                message += "\n\n"

    return message.strip()


# (Lesson formatting functions remain unchanged)
def format_beginners_lesson(lesson):
    if not lesson: return "Sorry, no 'Beginners' lesson is available."
    title = lesson.get('lessonTitle', 'N/A')
    bible_refs_list = [f"{ref['book']} {ref['chapter']}" for ref in lesson.get('bibleReference', []) if ref.get('book') and ref.get('chapter')]
    bible_refs = ', '.join(bible_refs_list) if bible_refs_list else "Genesis"
    message = f"🖍️ *Beginners Lesson: {title}*\n\n_(Story from: {bible_refs})_\n\n"
    for section in lesson.get('lessonSections', []):
        if section.get('sectionType') == 'text': message += f"{section.get('sectionContent', 'No story available.')}\n\n"
    message += "Have a blessed week! ☀️"
    return message
def format_answer_lesson(lesson):
    if not lesson: return "Sorry, no 'Answer' lesson is available."
    title = lesson.get('lessonTitle', 'N/A'); verse_text = lesson.get('bibleVerse', {}).get('text', 'N/A'); verse_ref = lesson.get('bibleVerse', {}).get('reference', '')
    message = f"📘 *Lesson: {title}*\n\n✨ *Verse of the Week:*\n_{verse_text}_ ({verse_ref})\n\n--- LESSON CONTENT ---\n\n"
    for section in lesson.get('contentSections', []):
        s_type = section.get('type')
        if s_type == 'text': message += f"{section.get('text')}\n\n"
        elif s_type == 'image': message += f"[ 🖼️ Image: _{section.get('alt', 'An illustration.')}_ ]\n\n"
        elif s_type == 'activity':
            a_type = section.get('activityType')
            if a_type == 'multipleChoice':
                message += f"🤔 *Quiz Time!*\nQuestion: {section.get('question')}\n"; [message := message + f"{i}. {opt}\n" for i, opt in enumerate(section.get('options', []), 1)]; message += "\n"
            elif a_type == 'crossword':
                message += "🧩 *Crossword Puzzle Clues*\n\n"
                if section.get('across'): message += "*Across:*\n"; [message := message + f"{c['number']}. {c['clue']}\n" for c in section['across']]
                if section.get('down'): message += "\n*Down:*\n"; [message := message + f"{c['number']}. {c['clue']}\n" for c in section['down']]; message += "\n"
    return message
def format_search_lesson(lesson):
    if not lesson: return "Sorry, no 'Search' lesson is available."
    title = lesson.get('lessonTitle', 'N/A'); key_verse = lesson.get('keyVerse', 'N/A')
    bible_refs = ', '.join([f"{ref['book']} {ref['chapter']}:{ref['verses']}" for ref in lesson.get('bibleReference', [])])
    message = f"📚 *Lesson: {title}*\n\n📖 *Bible Text:* {bible_refs}\n"
    if lesson.get('supplementalScripture'): message += f"📖 *Supplemental:* {lesson.get('supplementalScripture')}\n\n"
    message += f"🔑 *Key Verse:*\n_{key_verse}_\n\n"
    for section in lesson.get('lessonSections', []):
        s_title, s_content, s_type = section.get("sectionTitle"), section.get("sectionContent"), section.get("sectionType")
        if s_type == 'text': message += f"*{s_title}*\n{s_content}\n\n"
        elif s_type == 'question': message += f"❓ *{s_title}:* {s_content}\n"
    message += "\n"
    return message

# --- WHATSAPP MESSAGING FUNCTION ---
# (send_whatsapp_message remains unchanged)
def send_whatsapp_message(recipient_id, message_text):
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]): print("ERROR: WhatsApp credentials not set."); return
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": recipient_id, "text": {"body": message_text}}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status(); print(f"Message sent to {recipient_id}: {response.status_code}, {response.text}")
    except requests.exceptions.RequestException as e: print(f"Error sending message: {e}")

# --- MAIN BOT LOGIC HANDLER (UNCHANGED, BUT SHOWING FULLY) ---
def handle_bot_logic(user_id, message_text):
    user_file = get_user_file_path()
    users = load_json_data(user_file)
    message_text_lower = message_text.lower().strip()
    response_text = ""

    # State management
    if message_text_lower == "switch":
        if user_id in users and 'class' in users[user_id]:
            del users[user_id]['class']; save_json_data(users, user_file)
    if message_text_lower == "hymnbook":
        if user_id in users and 'hymnbook' in users[user_id]:
            del users[user_id]['hymnbook']; save_json_data(users, user_file)

    user_profile = users.get(user_id, {})

    # Onboarding flow
    if 'class' not in user_profile:
        if message_text_lower in CLASSES:
            user_profile['class'] = CLASSES[message_text_lower]; users[user_id] = user_profile; save_json_data(users, user_file)
            hymnbook_menu = "Great! Now, please select your preferred hymnbook:\n\n"
            for key, book in HYMNBOOKS.items(): hymnbook_menu += f"*{key}.* {book['name']}\n"
            response_text = hymnbook_menu
        else:
            response_text = "Welcome! Please select your class by replying with the number:\n\n*1.* Beginners\n*2.* Primary Pals\n*3.* Answer\n*4.* Search"
    elif 'hymnbook' not in user_profile:
        if message_text_lower in HYMNBOOKS:
            hymnbook_choice = HYMNBOOKS[message_text_lower]
            user_profile['hymnbook'] = hymnbook_choice['file']; users[user_id] = user_profile; save_json_data(users, user_file)
            response_text = (f"Perfect! Your hymnbook is set to *{hymnbook_choice['name']}*.\n\n"
                             "You're all set! Type `menu` to see what you can do.")
        else:
            hymnbook_menu = "Please select your preferred hymnbook:\n\n"
            for key, book in HYMNBOOKS.items(): hymnbook_menu += f"*{key}.* {book['name']}\n"
            response_text = hymnbook_menu
    else: # Registered user logic
        user_class = user_profile['class']; user_hymnbook_file = user_profile.get('hymnbook')

        if message_text_lower == 'lesson':
            lesson_index = get_current_lesson_index(); response_text = "Sorry, no lesson is available for your class this week."
            lesson_files = { "Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH }
            formatters = { "Beginners": format_beginners_lesson, "Answer": format_answer_lesson, "Search": format_search_lesson }
            
            for key, filename in lesson_files.items():
                if key in user_class:
                    lessons_path = os.path.join(os.path.dirname(__file__), filename)
                    lessons_data = load_json_data(lessons_path)
                    if lessons_data and 0 <= lesson_index < len(lessons_data):
                        response_text = formatters[key](lessons_data[lesson_index])
                    break
        
        elif message_text_lower.startswith('hymn '):
            if not user_hymnbook_file:
                response_text = "Please set your hymnbook first by typing `hymnbook`."
            else:
                hymns_path = os.path.join(os.path.dirname(__file__), 'hymnbooks', user_hymnbook_file)
                hymns_data = load_json_data(hymns_path)
                try:
                    hymn_num_to_find = int(message_text_lower.split(' ')[1])
                    found_hymn = next((h for h in hymns_data if h.get("number") == hymn_num_to_find), None)
                    response_text = format_hymn(found_hymn)
                except (ValueError, IndexError):
                    response_text = "Invalid format. Please use `hymn` followed by a number (e.g., `hymn 103`)."
        
        elif message_text_lower == 'menu':
            response_text = ("*MENU*\n\n"
                             "- Type `lesson` for this week's lesson.\n"
                             "- Type `hymn [number]` for a hymn from your selected book.\n"
                             "- Type `switch` to change your class.\n"
                             "- Type `hymnbook` to change your hymnbook.")
        else:
            response_text = "Sorry, I didn't understand. Type `menu` to see the available commands."
    
    send_whatsapp_message(user_id, response_text)

# --- FLASK WEBHOOK ROUTES ---
# (Unchanged)
@app.route('/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN: return request.args.get('hub.challenge'), 200
        return 'Verification token mismatch', 403
    if request.method == 'POST':
        data = request.get_json()
        print(f"Incoming data: {json.dumps(data, indent=2)}")
        try:
            if data and 'entry' in data:
                for entry in data['entry']:
                    for change in entry['changes']:
                        if 'messages' in change['value']:
                            message = change['value']['messages'][0]
                            if message['type'] == 'text':
                                handle_bot_logic(message['from'], message['text']['body'])
        except Exception as e: print(f"Error processing message: {e}")
        return 'OK', 200

@app.route('/')
def health_check():
    return "SundayBot with Hymnbooks is running!", 200