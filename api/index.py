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

# FIX: Reverted the main anchor date to the original for all other classes.
ANCHOR_DATE = date(2024, 8, 21)
# FIX: Added a separate anchor date specifically for the Primary Pals curriculum.
PRIMARY_PALS_ANCHOR_DATE = date(2025, 6, 1)

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

LANGUAGES = {
    "1": "Shona",
    "2": "Ndebele",
    "3": "Tswana",
    "4": "Portuguese",
    "5": "Sesotho",
    "6": "Tonga"
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

# FIX: The function now takes user_class to determine which anchor date to use.
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
    if not hymn:
        return "Sorry, I couldn't find a hymn with that number in your selected hymnbook."
    
    title = hymn.get('title', 'No Title')
    hymn_number = hymn.get('number', '#')
    message = f"🎶 *Hymn #{hymn_number}: {title}*\n\n"
    
    verses = hymn.get('verses', [])
    chorus = hymn.get('chorus', [])
    parts = hymn.get('parts', [])
    
    chorus_text = ""
    if chorus:
        chorus_text = "*Chorus:*\n" + "\n".join(chorus) + "\n\n"
        
    if verses:
        for i, verse_lines in enumerate(verses, 1):
            message += f"*{i}.*\n" + "\n".join(verse_lines) + "\n\n"
            if chorus_text:
                message += chorus_text
    elif chorus_text:
        message += chorus_text

    if parts:
        for part in parts:
            part_num = part.get('part', '')
            message += f"*{f'Part {part_num}' if part_num else 'Part'}*\n"
            for i, v_lines in enumerate(part.get('verses', []), 1):
                message += f"*{i}.*\n" + "\n".join(v_lines) + "\n\n"

    return message.strip()

def format_beginners_lesson(lesson):
    if not lesson:
        return "Sorry, no 'Beginners' lesson is available for this week."
    
    lesson_id = lesson.get('id', '')
    lesson_number_str = ''.join(filter(str.isdigit, lesson_id))
    lesson_number = f" {int(lesson_number_str)}" if lesson_number_str else ""

    title = lesson.get('lessonTitle', 'N/A')
    memory_verse = lesson.get('keyVerse')

    raw_refs = lesson.get('bibleReference', [])
    bible_refs_list = [f"{ref.get('book')} {ref.get('chapter')}" for ref in raw_refs if ref.get('book') and ref.get('chapter')]
    bible_refs = ', '.join(bible_refs_list) if bible_refs_list else "N/A"

    message = f"🖍️ *Beginners Lesson{lesson_number}: {title}*\n\n"
    if bible_refs != "N/A":
        message += f"📖 *Story from:*\n_{bible_refs}_\n\n"
    if memory_verse:
        message += f"🔑 *Memory Verse:*\n_{memory_verse}_\n\n"
    
    message += "----------\n\n"

    has_content = False
    for section in lesson.get('lessonSections', []):
        if section.get('sectionType') == 'text':
            section_title = section.get('sectionTitle', 'Lesson Story')
            section_content = section.get('sectionContent', '').strip()
            if section_content:
                message += f"📌 *{section_title}*\n{section_content}\n\n"
                has_content = True
    
    if not has_content:
        message += "No story content is available for this lesson.\n\n"

    message += "Have a blessed week! ☀️\n"
    message += "_Type 'ask [question]', 'translate', or 'reset'_"
    
    return message.strip()

def format_primary_pals_lesson(lesson):
    if not lesson:
        return "Sorry, no 'Primary Pals' lesson is available for this week."

    lesson_id_str = lesson.get('lesson_id', '')
    title = lesson.get('title', 'N/A')

    parent_guide = lesson.get('parent_guide', {})
    bible_text_info = parent_guide.get('bible_text', {})
    bible_refs = bible_text_info.get('reference', 'N/A')
    
    memory_verse_info = parent_guide.get('memory_verse', {})
    memory_verse_text = memory_verse_info.get('text', '')
    memory_verse_ref = memory_verse_info.get('reference', '')
    memory_verse = f"{memory_verse_text} — {memory_verse_ref}" if memory_verse_text and memory_verse_ref else 'N/A'

    story_paragraphs = lesson.get('story', [])
    story_content = "\n\n".join(story_paragraphs)

    parents_corner_info = parent_guide.get('parents_corner', {})
    parents_corner_title = parents_corner_info.get('title', "Parent's Corner")
    parents_corner_text = parents_corner_info.get('text', 'No guide available.')

    family_devotions_info = parent_guide.get('family_devotions', {})
    family_devotions_title = family_devotions_info.get('title', 'Family Devotions')
    family_devotions_intro = family_devotions_info.get('intro', '')
    devotion_verses = family_devotions_info.get('verses', [])

    message = f"🧸 *Primary Pals Lesson {lesson_id_str.upper()}: {title}*\n\n"
    
    if bible_refs != 'N/A':
        message += f"📖 *Bible Text:*\n_{bible_refs}_\n\n"
    
    if memory_verse != 'N/A':
        message += f"🔑 *Memory Verse:*\n_{memory_verse}_\n\n"
        
    message += "----------\n\n"
    
    message += f"✨ *Lesson Story*\n{story_content}\n\n"
    
    message += "--- *Parent's Guide* ---\n\n"
    message += f"📌 *{parents_corner_title}*\n{parents_corner_text}\n\n"
    
    message += f"📌 *{family_devotions_title}*\n"
    if family_devotions_intro:
        message += f"_{family_devotions_intro}_\n"
    
    devotions_str = ""
    for verse in devotion_verses:
        devotions_str += f"  *{verse.get('day')}:* {verse.get('reference')}\n"
    message += devotions_str
    
    message += "\nHave a blessed week! 🧸\n"
    message += "_Type 'ask [question]', 'translate', or 'reset'_"

    return message.strip()


def format_search_answer_lesson(lesson, lesson_type):
    if not lesson:
        return f"Sorry, no '{lesson_type}' lesson is available for this week."

    lesson_id = lesson.get('id', '')
    lesson_number_str = ''.join(filter(str.isdigit, lesson_id))
    lesson_number = f" {int(lesson_number_str)}" if lesson_number_str else ""

    title = lesson.get('lessonTitle', 'N/A')
    memory_verse = lesson.get('keyVerse')
    supplemental = lesson.get('supplementalScripture')
    resource = lesson.get('resourceMaterial')

    raw_refs = lesson.get('bibleReference', [])
    bible_refs_list = []
    if raw_refs:
        for ref in raw_refs:
            book, chapter, verses = ref.get('book'), ref.get('chapter'), ref.get('verses')
            if book and chapter and verses:
                bible_refs_list.append(f"{book} {chapter}:{verses}")
            elif book and chapter:
                bible_refs_list.append(f"{book} {chapter}")
    bible_refs = ', '.join(bible_refs_list) if bible_refs_list else "N/A"

    message = f"📚 *{lesson_type} Lesson{lesson_number}: {title}*\n\n"
    if bible_refs and bible_refs != 'N/A':
        message += f"📖 *Bible Reference:*\n_{bible_refs}_\n\n"
    if supplemental:
        message += f"📜 *Supplemental Scripture:*\n_{supplemental}_\n\n"
    if resource:
        message += f"📦 *Resource Material:*\n_{resource}_\n\n"
        
    if memory_verse:
        message += f"🔑 *Key Verse:*\n_{memory_verse}_\n\n"

    message += "----------\n\n"

    for section in lesson.get('lessonSections', []):
        if section.get('sectionType') in ['text', 'question']:
            section_title = section.get('sectionTitle', 'Section')
            section_content = section.get('sectionContent', 'No content available.').strip()
            message += f"📌 *{section_title}*\n{section_content}\n\n"

    message += "Have a blessed week! ✨\n"
    message += "_Type 'ask [question]', 'translate', or 'reset'_"

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

def get_ai_translation(text_to_translate, target_language):
    if not gemini_model:
        return "Sorry, the translation module is currently unavailable."

    key_verse_block = ""
    text_for_translation = text_to_translate
    placeholder = "[VERSE_PLACEHOLDER]"

    key_verse_pattern = re.compile(r"(🔑 \*(?:Key|Memory) Verse:\*.*?\n\n)", re.DOTALL)
    match = key_verse_pattern.search(text_to_translate)
    
    if match:
        key_verse_block = match.group(1)
        text_for_translation = text_to_translate.replace(key_verse_block, placeholder)

    prompt = (
        f"You are a professional translator. Translate the following text into {target_language}. "
        "Preserve the original formatting, including WhatsApp markdown like *bold* and _italics_. "
        "Do not add any extra commentary or introductory phrases. Just provide the direct translation.\n\n"
        "--- TEXT TO TRANSLATE ---\n"
        f"{text_for_translation}"
    )
    
    try:
        response = gemini_model.generate_content(prompt)
        translated_text = response.text.strip()
        
        if key_verse_block:
            final_translation = translated_text.replace(placeholder, key_verse_block)
        else:
            final_translation = translated_text
            
        return final_translation

    except Exception as e:
        print(f"Google Gemini API Translation Error: {e}")
        return f"I'm having trouble translating to {target_language} right now. Please try again in a moment."

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
                class_name = CLASSES[message_text_lower]
                user_profile['class'] = class_name
                send_whatsapp_message(user_id, f"Great! Class set to *{class_name}*.\n\nType `lesson` to get this week's lesson.\nType `reset` to go back.")
            else: send_whatsapp_message(user_id, "Invalid class number. Please try again.")
        
        lesson_files = {
            "Beginners": LESSONS_FILE_BEGINNERS, 
            "Primary Pals": LESSONS_FILE_PRIMARY_PALS, 
            "Answer": LESSONS_FILE_ANSWER, 
            "Search": LESSONS_FILE_SEARCH
        }
        
        if message_text_lower.startswith('ask '):
            question = message_text[4:].strip()
            if not question: send_whatsapp_message(user_id, "Please type a question after the word `ask`.")
            else:
                send_whatsapp_message(user_id, "🤔 Thinking...")
                # FIX: Pass user_class to get the correct lesson index
                user_class = user_profile['class']
                lesson_index = get_current_lesson_index(user_class)
                context = ""
                lesson_file_name = lesson_files.get(user_class)
                
                if lesson_file_name:
                    lessons_path = os.path.join(os.path.dirname(__file__), lesson_file_name)
                    raw_lessons_data = load_json_data(lessons_path)
                    lessons_data_list = raw_lessons_data.get("primary_pals_lessons", []) if user_class == "Primary Pals" else raw_lessons_data

                    if lessons_data_list and 0 <= lesson_index < len(lessons_data_list):
                        context = json.dumps(lessons_data_list[lesson_index])
                
                if not context: send_whatsapp_message(user_id, "Sorry, I can't find this week's lesson material to answer questions about.")
                else: 
                    ai_answer = get_ai_response(question, context)
                    send_whatsapp_message(user_id, ai_answer)
        
        elif message_text_lower == 'translate':
            if 'last_lesson_content' in user_profile:
                user_profile['mode'] = 'awaiting_translation_language'
                lang_menu = "Please choose a language to translate to:\n\n"
                for k, v in LANGUAGES.items():
                    lang_menu += f"*{k}.* {v}\n"
                send_whatsapp_message(user_id, lang_menu.strip())
            else:
                send_whatsapp_message(user_id, "Please get a lesson first by typing `lesson`.")

        elif message_text_lower == 'lesson':
            send_whatsapp_message(user_id, "Fetching this week's lesson...")
            # FIX: Pass user_class to get the correct lesson index
            user_class = user_profile.get('class')
            lesson_index = get_current_lesson_index(user_class)
            
            if lesson_index < 0: 
                send_whatsapp_message(user_id, "It seems there are no lessons scheduled for this week.")
            else:
                lesson_file_name = lesson_files.get(user_class)
                if not lesson_file_name: 
                    send_whatsapp_message(user_id, f"Sorry, lessons for the '{user_class}' class are not available yet.")
                else:
                    lessons_path = os.path.join(os.path.dirname(__file__), lesson_file_name)
                    raw_lessons_data = load_json_data(lessons_path)
                    
                    lessons_data_list = []
                    if user_class == "Primary Pals":
                        lessons_data_list = raw_lessons_data.get("primary_pals_lessons", [])
                    else:
                        lessons_data_list = raw_lessons_data
                    
                    if lessons_data_list and 0 <= lesson_index < len(lessons_data_list):
                        lesson = lessons_data_list[lesson_index]
                        formatted_message = ""
                        
                        if user_class == "Beginners": 
                            formatted_message = format_beginners_lesson(lesson)
                        elif user_class == "Primary Pals":
                            formatted_message = format_primary_pals_lesson(lesson)
                        elif user_class in ["Search", "Answer"]: 
                            formatted_message = format_search_answer_lesson(lesson, user_class)
                        else: 
                            formatted_message = f"Sorry, I don't know how to format the lesson for the '{user_class}' class yet."
                        
                        user_profile['last_lesson_content'] = formatted_message
                        send_whatsapp_message(user_id, formatted_message)
                    else: 
                        send_whatsapp_message(user_id, "Sorry, I couldn't find this week's lesson. It might not be uploaded yet.")
        else: 
            send_whatsapp_message(user_id, "In *Lessons* section: type `lesson`, `ask [question]`, `translate`, or `reset`.")

    elif user_profile.get('mode') == 'awaiting_translation_language':
        if message_text_lower in LANGUAGES:
            target_language = LANGUAGES[message_text_lower]
            content_to_translate = user_profile.get('last_lesson_content', '')
            
            if not content_to_translate:
                send_whatsapp_message(user_id, "Something went wrong. Please type `lesson` to get the lesson again.")
                user_profile['mode'] = 'lessons'
            else:
                send_whatsapp_message(user_id, f"Translating to {target_language}...")
                translated_text = get_ai_translation(content_to_translate, target_language)
                send_whatsapp_message(user_id, translated_text)
                
                user_profile['mode'] = 'lessons'
                if 'last_lesson_content' in user_profile:
                    del user_profile['last_lesson_content']
                send_whatsapp_message(user_id, "Translation complete! You are back in the lessons section. Type `reset` to start over.")
        else:
            lang_menu = "Invalid selection. Please choose a number from the list:\n\n"
            for k, v in LANGUAGES.items():
                lang_menu += f"*{k}.* {v}\n"
            send_whatsapp_message(user_id, lang_menu.strip())

    elif user_profile.get('mode') == 'hymnbook':
        if 'hymnbook' not in user_profile:
            if message_text_lower in HYMNBOOKS:
                selected_hymnbook = HYMNBOOKS[message_text_lower]
                user_profile['hymnbook'] = selected_hymnbook['file']
                send_whatsapp_message(user_id, f"You have selected *{selected_hymnbook['name']}*.\n\nPlease type a hymn number, or `reset` to start over.")
            else: send_whatsapp_message(user_id, "Invalid selection. Please choose a hymnbook from the list.")
        else:
            if message_text.isdigit():
                hymn_number_to_find = int(message_text)
                hymnbook_file = user_profile['hymnbook']
                hymns_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, hymnbook_file)
                hymns_data = load_json_data(hymns_path)
                found_hymn = next((hymn for hymn in hymns_data if hymn.get('number') == hymn_number_to_find), None)
                if found_hymn: 
                    formatted_hymn = format_hymn(found_hymn)
                    send_whatsapp_message(user_id, formatted_hymn)
                else: 
                    send_whatsapp_message(user_id, f"Sorry, I couldn't find hymn #{hymn_number_to_find} in that hymnbook.")
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
    return "SundayBot with Full Features is running!", 200