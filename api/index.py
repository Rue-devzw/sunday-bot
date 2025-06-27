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
ANCHOR_DATE = date(2024, 8, 21)
LESSONS_FILE_SEARCH = 'search_lessons.json'
LESSONS_FILE_ANSWER = 'answer_lessons.json'
LESSONS_FILE_BEGINNERS = 'beginners_lessons.json'
USERS_FILE = 'users.json'
HYMNBOOKS_DIR = 'hymnbooks'
CLASSES = {"1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search"}
HYMNBOOKS = {"1": {"name": "Nziyo Dzekurumbidza (Shona Hymns)", "file": "shona_hymns.json"}}

# --- 3. HELPER FUNCTIONS ---
def get_user_file_path():
    return f'/tmp/{USERS_FILE}' if 'VERCEL' in os.environ else os.path.join(os.path.dirname(__file__), USERS_FILE)

def load_json_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"WARNING: Could not load file at {file_path}")
        return {} # Return empty dict instead of None to prevent crashes

def save_json_data(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def get_current_lesson_index():
    today = date.today()
    anchor_week_start = ANCHOR_DATE + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    return (current_week_start - anchor_week_start).days // 7

def build_lesson_context(lesson):
    return json.dumps(lesson) # Simple is best for AI context

# --- 4. CORRECTED FORMATTING FUNCTIONS ---

def format_hymn(hymn):
    if not hymn:
        return "Sorry, I couldn't find a hymn with that number."
    title = hymn.get('title', 'No Title')
    num = hymn.get('number', '#')
    msg = f"🎶 *Hymn #{num}: {title}*\n\n"
    for i, verse in enumerate(hymn.get('verses', []), 1):
        msg += f"*{i}.*\n" + "\n".join(verse) + "\n\n"
    if 'chorus' in hymn and hymn['chorus']:
        msg += "*Chorus:*\n" + "\n".join(hymn['chorus']) + "\n\n"
    return msg.strip()

def format_beginners_lesson(lesson):
    if not lesson:
        return "Sorry, no 'Beginners' lesson is available for this week."
    title = lesson.get('lessonTitle', 'N/A')
    refs = ', '.join([f"{r['book']} {r['chapter']}" for r in lesson.get('bibleReference', [])])
    msg = f"🖍️ *Beginners Lesson: {title}*\n\n_(Story from: {refs})_\n\n"
    for section in lesson.get('lessonSections', []):
        if section.get('sectionType') == 'text':
            msg += f"{section.get('sectionContent', '')}\n\n"
    return msg.strip() + "\nHave a blessed week! ☀️"

def format_answer_lesson(lesson):
    if not lesson:
        return "Sorry, no 'Answer' lesson is available for this week."
    title = lesson.get('lessonTitle', 'N/A')
    verse = lesson.get('bibleVerse', {})
    msg = f"📘 *Lesson: {title}*\n\n✨ *Verse:*\n_{verse.get('text', 'N/A')}_ ({verse.get('reference', '')})\n\n"
    for section in lesson.get('contentSections', []):
        if section.get('type') == 'text':
            msg += f"{section.get('text', '')}\n\n"
    return msg.strip()

def format_search_lesson(lesson):
    if not lesson:
        return "Sorry, no 'Search' lesson is available for this week."
    title = lesson.get('lessonTitle', 'N/A')
    key_verse = lesson.get('keyVerse', 'N/A')
    refs = ', '.join([f"{r['book']} {r['chapter']}:{r['verses']}" for r in lesson.get('bibleReference', [])])
    msg = f"📚 *Lesson: {title}*\n\n📖 *Bible Text:* {refs}\n"
    if lesson.get('supplementalScripture'):
        msg += f"📖 *Supplemental:* {lesson.get('supplementalScripture')}\n\n"
    msg += f"🔑 *Key Verse:*\n_{key_verse}_\n\n"
    for section in lesson.get('lessonSections', []):
        s_title = section.get("sectionTitle")
        s_content = section.get("sectionContent")
        s_type = section.get("sectionType")
        if s_type == 'text':
            msg += f"*{s_title}*\n{s_content}\n\n"
        elif s_type == 'question':
            msg += f"❓ *{s_title}:* {s_content}\n"
    return msg.strip()


# --- [ All other functions (AI, WhatsApp Sender, etc.) remain the same. Ensure they are in your file. ] ---
def get_ai_response(question, context):
    if not groq_client: return "Sorry, the AI thinking module is currently unavailable."
    system_prompt = ("You are a friendly Sunday School assistant. Your purpose is to answer questions *strictly* based on the lesson material provided as context. " "1. If the answer is in the text, answer it kindly and concisely. " "2. If the answer is not in the text, you MUST politely state that the answer is not in the lesson material. Do not use external knowledge. " "3. If the user asks a greeting or off-topic question, kindly redirect them to the lesson.")
    user_prompt = f"Here is the lesson material:\n\n--- LESSON CONTEXT ---\n{context}\n\n--- END OF CONTEXT ---\n\nPlease answer this question based only on the lesson material above:\n\nUSER QUESTION: \"{question}\""
    try:
        completion = groq_client.chat.completions.create(model="llama3-8b-8192", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], temperature=0.2, max_tokens=200)
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API Error: {e}"); return "I'm having a little trouble thinking right now. Please try again."

def send_whatsapp_message(recipient_id, message_text):
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]): print("ERROR: WhatsApp credentials not set."); return
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"; headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}; data = {"messaging_product": "whatsapp", "to": recipient_id, "text": {"body": message_text}}
    try:
        response = requests.post(url, headers=headers, json=data); response.raise_for_status(); print(f"Message sent to {recipient_id}: {response.status_code}")
    except requests.exceptions.RequestException as e: print(f"Error sending message: {e}")


# --- 6. MAIN BOT LOGIC HANDLER (STATE MACHINE) ---
def handle_bot_logic(user_id, message_text):
    # [ The state machine logic from the previous step is correct and remains unchanged. ]
    # [ Please ensure the full 'handle_bot_logic' function from the previous version is included here. ]
    user_file = get_user_file_path(); users = load_json_data(user_file); message_lower = message_text.lower().strip(); user_profile = users.get(user_id, {})
    if message_lower == 'reset': user_profile = {}; users[user_id] = user_profile; save_json_data(users, user_file)
    current_status = user_profile.get('status', 'start')
    if current_status == 'start':
        if message_lower == '1':
            user_profile['mode'] = 'lessons'; user_profile['status'] = 'awaiting_class_selection'; save_json_data(users, user_file); send_whatsapp_message(user_id, "Please select your Sunday School class:\n\n*1.* Beginners\n*2.* Primary Pals\n*3.* Answer\n*4.* Search")
        elif message_lower == '2':
            user_profile['mode'] = 'hymnbook'; user_profile['status'] = 'awaiting_hymnbook_selection'; save_json_data(users, user_file); hymn_menu = "Please select a hymnbook:\n\n" + "\n".join([f"*{k}.* {v['name']}" for k, v in HYMNBOOKS.items()]); send_whatsapp_message(user_id, hymn_menu)
        else:
            send_whatsapp_message(user_id, "Welcome! 🙏\n\nPlease choose a section:\n*1.* Weekly Lessons\n*2.* Hymnbook")
        return
    if current_status == 'awaiting_class_selection':
        if message_lower in CLASSES: class_name = CLASSES[message_lower]; user_profile['class'] = class_name; user_profile['status'] = 'lessons_main'; save_json_data(users, user_file); send_whatsapp_message(user_id, f"Great! Class set to *{class_name}*.\n\nType `lesson` for your material or `ask` to start Q&A.\n(Type `reset` to go back)")
        else: send_whatsapp_message(user_id, "That's not a valid class number. Please try again.")
        return
    if current_status == 'lessons_main':
        user_class = user_profile['class']
        if message_lower == 'ask': user_profile['status'] = 'lessons_ask_mode'; save_json_data(users, user_file); send_whatsapp_message(user_id, "You're in Q&A mode. Ask anything about this week's lesson!\n\n(Type `stop` to exit Q&A)"); return
        if message_lower == 'lesson':
            lesson_index = get_current_lesson_index(); response_text = "Sorry, no lesson is available for your class this week."; lesson_files = {"Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH}; formatters = {"Beginners": format_beginners_lesson, "Answer": format_answer_lesson, "Search": format_search_lesson}
            for key, filename in lesson_files.items():
                if key in user_class:
                    path = os.path.join(os.path.dirname(__file__), filename); lessons = load_json_data(path)
                    if lessons and 0 <= lesson_index < len(lessons): response_text = formatters[key](lessons[lesson_index]); break
            send_whatsapp_message(user_id, response_text)
        else: send_whatsapp_message(user_id, "Type `lesson`, `ask`, or `reset`.")
        return
    if current_status == 'lessons_ask_mode':
        if message_lower == 'stop': user_profile['status'] = 'lessons_main'; save_json_data(users, user_file); send_whatsapp_message(user_id, "Exited Q&A mode. You can type `lesson` or `ask`."); return
        send_whatsapp_message(user_id, "🤔 Thinking..."); lesson_index = get_current_lesson_index(); context = ""; lesson_files = {"Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH}
        for key, filename in lesson_files.items():
            if key in user_profile['class']:
                path = os.path.join(os.path.dirname(__file__), filename); lessons = load_json_data(path)
                if lessons and 0 <= lesson_index < len(lessons): context = build_lesson_context(lessons[lesson_index]); break
        if context: ai_answer = get_ai_response(message_text, context); send_whatsapp_message(user_id, ai_answer)
        else: send_whatsapp_message(user_id, "Sorry, I can't find lesson material to answer questions about right now.")
        return
    if current_status == 'awaiting_hymnbook_selection':
        if message_lower in HYMNBOOKS: choice = HYMNBOOKS[message_lower]; user_profile['hymnbook'] = choice['file']; user_profile['status'] = 'hymnbook_main'; save_json_data(users, user_file); send_whatsapp_message(user_id, f"Hymnbook set to *{choice['name']}*.\n\nType `hymn [number]` or `reset`.")
        else: send_whatsapp_message(user_id, "Invalid hymnbook number. Please try again.")
        return
    if current_status == 'hymnbook_main':
        if message_lower.startswith('hymn '):
            try:
                hymn_num = int(message_lower.split(' ')[1]); hymnbook_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, user_profile['hymnbook']); hymns = load_json_data(hymnbook_path); found_hymn = next((h for h in hymns if h.get("number") == hymn_num), None); send_whatsapp_message(user_id, format_hymn(found_hymn))
            except (ValueError, IndexError): send_whatsapp_message(user_id, "Please use the format: `hymn [number]` (e.g., hymn 15).")
        else: send_whatsapp_message(user_id, "Type `hymn [number]` or `reset`.")
        return

# --- 7. FLASK WEBHOOK ROUTES ---
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