# api/index.py

import os
import json
import requests
from groq import Groq
from flask import Flask, request
from datetime import date
from dateutil.relativedelta import relativedelta, MO

# --- 1. INITIALIZE FLASK & GROQ CLIENT ---
app = Flask(__name__)
try:
    groq_client = Groq()
except Exception as e:
    print(f"ERROR: Could not initialize Groq client. Is GROQ_API_KEY set? Details: {e}")
    groq_client = None

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
HYMNBOOKS_DIR = 'hymnbooks'

CLASSES = {"1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search"}
HYMNBOOKS = {"1": {"name": "Nziyo Dzekurumbidza (Shona Hymns)", "file": "shona_hymns.json"}}

# --- 3. HELPER & FORMATTING FUNCTIONS ---
# [ These functions are correct. For brevity, they are not repeated here. ]
# [ Please ensure all the helper/formatting functions from the previous version are included in your file. ]
def get_user_file_path():
    return f'/tmp/{USERS_FILE}' if 'VERCEL' in os.environ else os.path.join(os.path.dirname(__file__), USERS_FILE)
def load_json_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}
def save_json_data(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
def get_current_lesson_index():
    today = date.today(); anchor_week_start = ANCHOR_DATE + relativedelta(weekday=MO(-1)); current_week_start = today + relativedelta(weekday=MO(-1))
    return (current_week_start - anchor_week_start).days // 7
def build_lesson_context(lesson): return json.dumps(lesson)
def format_hymn(hymn):
    if not hymn: return "Sorry, I couldn't find a hymn with that number."; title, num = hymn.get('title', 'No Title'), hymn.get('number', '#'); msg = f"🎶 *Hymn #{num}: {title}*\n\n"; [msg := msg + f"*{i}.*\n" + "\n".join(verse) + "\n\n" for i, verse in enumerate(hymn.get('verses', []), 1)];
    if 'chorus' in hymn and hymn['chorus']: msg += "*Chorus:*\n" + "\n".join(hymn['chorus']) + "\n\n"; return msg.strip()
def format_beginners_lesson(lesson):
    if not lesson: return "Sorry, no 'Beginners' lesson is available for this week."; title = lesson.get('lessonTitle', 'N/A'); refs = ', '.join([f"{r['book']} {r['chapter']}" for r in lesson.get('bibleReference', [])]); msg = f"🖍️ *Beginners Lesson: {title}*\n\n_(Story from: {refs})_\n\n"; [msg := msg + f"{section.get('sectionContent', '')}\n\n" for section in lesson.get('lessonSections', []) if section.get('sectionType') == 'text']; return msg.strip() + "\nHave a blessed week! ☀️"
def format_answer_lesson(lesson):
    if not lesson: return "Sorry, no 'Answer' lesson is available for this week."; title = lesson.get('lessonTitle', 'N/A'); verse = lesson.get('bibleVerse', {}); msg = f"📘 *Lesson: {title}*\n\n✨ *Verse:*\n_{verse.get('text', 'N/A')}_ ({verse.get('reference', '')})\n\n"; [msg := msg + f"{section.get('text', '')}\n\n" for section in lesson.get('contentSections', []) if section.get('type') == 'text']; return msg.strip()
def format_search_lesson(lesson):
    if not lesson: return "Sorry, no 'Search' lesson is available for this week."; title = lesson.get('lessonTitle', 'N/A'); key_verse = lesson.get('keyVerse', 'N/A'); refs = ', '.join([f"{r['book']} {r['chapter']}:{r['verses']}" for r in lesson.get('bibleReference', [])]); msg = f"📚 *Lesson: {title}*\n\n📖 *Bible Text:* {refs}\n";
    if lesson.get('supplementalScripture'): msg += f"📖 *Supplemental:* {lesson.get('supplementalScripture')}\n\n"; msg += f"🔑 *Key Verse:*\n_{key_verse}_\n\n"; [msg := msg + f"*{s.get('sectionTitle')}*\n{s.get('sectionContent')}\n\n" if s.get('sectionType') == 'text' else msg + f"❓ *{s.get('sectionTitle')}:* {s.get('sectionContent')}\n" for s in lesson.get('lessonSections', [])]; return msg.strip()

# --- 4. AI & WHATSAPP SENDER FUNCTIONS ---
def get_ai_response(question, context):
    if not groq_client: return "Sorry, the AI thinking module is currently unavailable."
    system_prompt = "You are a friendly Sunday School assistant. Your answers must be based *only* on the provided lesson text (the context). If the answer is not in the text, politely state that you cannot answer based on the provided material. Keep answers concise."
    user_prompt = f"Based on the following lesson context, please answer the user's question.\n\n--- CONTEXT ---\n{context}\n\n--- QUESTION ---\n{question}"
    try:
        completion = groq_client.chat.completions.create(model="llama3-8b-8192", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], temperature=0.3, max_tokens=150)
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API Error: {e}"); return "I'm having a little trouble thinking. Please try again."
def send_whatsapp_message(recipient_id, message_text):
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]): print("ERROR: WhatsApp credentials not set."); return
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"; headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}; data = {"messaging_product": "whatsapp", "to": recipient_id, "text": {"body": message_text}}
    try:
        response = requests.post(url, headers=headers, json=data); response.raise_for_status(); print(f"Message sent to {recipient_id}: {response.status_code}")
    except requests.exceptions.RequestException as e: print(f"Error sending message: {e}")

# --- 5. RESTRUCTURED MAIN BOT LOGIC HANDLER ---
def handle_bot_logic(user_id, message_text):
    """The main command-based logic handler for the bot."""
    user_file = get_user_file_path()
    users = load_json_data(user_file)
    message_lower = message_text.lower().strip()
    user_profile = users.get(user_id, {})

    # Universal reset command
    if message_lower == 'reset':
        user_profile = {} # Clear the profile
        users[user_id] = user_profile
        save_json_data(users, user_file)
        # Fall through to show the main menu

    # Step 1: Mode Selection (if not already selected)
    if 'mode' not in user_profile:
        if message_lower == '1':
            user_profile['mode'] = 'lessons'
            save_json_data(users, user_file)
            send_whatsapp_message(user_id, "You've selected *Weekly Lessons*. Please choose your class by replying with a number:\n\n*1.* Beginners\n*2.* Primary Pals\n*3.* Answer\n*4.* Search")
        elif message_lower == '2':
            user_profile['mode'] = 'hymnbook'
            save_json_data(users, user_file)
            hymn_menu = "You've selected *Hymnbook*. Please choose a book:\n\n" + "\n".join([f"*{k}.* {v['name']}" for k, v in HYMNBOOKS.items()])
            send_whatsapp_message(user_id, hymn_menu)
        else:
            send_whatsapp_message(user_id, "Welcome! 🙏\n\nPlease choose a section:\n*1.* Weekly Lessons\n*2.* Hymnbook")
        return

    # Step 2: Handle logic within the selected mode
    # Path 1: User is in 'Lessons' mode
    if user_profile.get('mode') == 'lessons':
        # Sub-step: Class selection (if not already selected)
        if 'class' not in user_profile:
            if message_lower in CLASSES:
                class_name = CLASSES[message_lower]
                user_profile['class'] = class_name
                save_json_data(users, user_file)
                send_whatsapp_message(user_id, f"Great! Class set to *{class_name}*.\n\n- Type `lesson` for your material.\n- Type `ask [your question]` for Q&A.\n- Type `reset` to go back.")
            else:
                send_whatsapp_message(user_id, "Sorry, that's not a valid class number. Please try again.")
            return

        # Sub-step: Handle commands now that class is set
        if message_lower == 'lesson':
            lesson_index = get_current_lesson_index()
            user_class = user_profile['class']
            response_text = "Sorry, no lesson is available for your class this week."
            lesson_files = {"Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH}
            formatters = {"Beginners": format_beginners_lesson, "Answer": format_answer_lesson, "Search": format_search_lesson}
            
            for key, filename in lesson_files.items():
                if key in user_class:
                    path = os.path.join(os.path.dirname(__file__), filename)
                    lessons = load_json_data(path)
                    if lessons and 0 <= lesson_index < len(lessons):
                        response_text = formatters[key](lessons[lesson_index])
                    break
            send_whatsapp_message(user_id, response_text)
        elif message_lower.startswith('ask '):
            question = message_text[4:].strip()
            if not question:
                send_whatsapp_message(user_id, "Please type a question after the word `ask`.")
                return
            
            send_whatsapp_message(user_id, "🤔 Thinking...")
            lesson_index = get_current_lesson_index()
            user_class = user_profile['class']
            context = ""
            lesson_files = {"Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH}
            for key, filename in lesson_files.items():
                if key in user_class:
                    path = os.path.join(os.path.dirname(__file__), filename)
                    lessons = load_json_data(path)
                    if lessons and 0 <= lesson_index < len(lessons):
                        context = build_lesson_context(lessons[lesson_index])
                        break
            
            if not context:
                send_whatsapp_message(user_id, "Sorry, I can't find lesson material to answer questions about right now.")
                return
            
            ai_answer = get_ai_response(question, context)
            send_whatsapp_message(user_id, ai_answer)
        else:
            send_whatsapp_message(user_id, "You are in the *Lessons* section.\n- Type `lesson`\n- Type `ask [your question]`\n- Type `reset` to go back")
        return

    # Path 2: User is in 'Hymnbook' mode
    if user_profile.get('mode') == 'hymnbook':
        # Sub-step: Hymnbook selection (if not already selected)
        if 'hymnbook' not in user_profile:
            if message_lower in HYMNBOOKS:
                choice = HYMNBOOKS[message_lower]
                user_profile['hymnbook'] = choice['file']
                save_json_data(users, user_file)
                send_whatsapp_message(user_id, f"Great! Hymnbook set to *{choice['name']}*.\n\nType `hymn [number]` or `reset`.")
            else:
                send_whatsapp_message(user_id, "Sorry, that's not a valid hymnbook number. Please try again.")
            return

        # Sub-step: Handle commands now that hymnbook is set
        if message_lower.startswith('hymn '):
            try:
                hymn_num = int(message_lower.split(' ')[1])
                hymn_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, user_profile['hymnbook'])
                hymns = load_json_data(hymn_path)
                found_hymn = next((h for h in hymns if h.get("number") == hymn_num), None)
                send_whatsapp_message(user_id, format_hymn(found_hymn))
            except (ValueError, IndexError):
                send_whatsapp_message(user_id, "Invalid format. Please use `hymn [number]` (e.g., hymn 15).")
        else:
            send_whatsapp_message(user_id, "You are in the *Hymnbook* section.\n- Type `hymn [number]`\n- Type `reset` to go back")
        return

# --- 6. FLASK WEBHOOK ROUTES ---
# [ This section is correct and remains unchanged. ]
@app.route('/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN: return request.args.get('hub.challenge'), 200
        return 'Verification token mismatch', 403
    if request.method == 'POST':
        data = request.get_json(); print(f"Incoming data: {json.dumps(data, indent=2)}")
        try:
            if data and 'entry' in data:
                for entry in data['entry']:
                    for change in entry['changes']:
                        if 'messages' in change['value']:
                            message = change['value']['messages'][0]
                            if message['type'] == 'text': handle_bot_logic(message['from'], message['text']['body'])
        except Exception as e: print(f"Error processing message: {e}")
        return 'OK', 200

@app.route('/')
def health_check():
    return "SundayBot AI (Groq) is running!", 200