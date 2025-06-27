# api/index.py

import os
import json
import requests
from groq import Groq  # <-- NEW: Import Groq library
from flask import Flask, request
from datetime import date
from dateutil.relativedelta import relativedelta, MO

# --- 1. INITIALIZE FLASK & GROQ CLIENT ---
app = Flask(__name__)
# --- NEW: Initialize Groq client ---
# The client will automatically use the GROQ_API_KEY environment variable.
try:
    groq_client = Groq()
except Exception as e:
    print(f"Error initializing Groq client: {e}")
    groq_client = None

# --- 2. CONFIGURATION & ENVIRONMENT VARIABLES ---
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')

# Static Configuration and data file paths
# ... (rest of configuration remains the same) ...
ANCHOR_DATE = date(2024, 8, 21)
LESSONS_FILE_SEARCH = 'search_lessons.json'
LESSONS_FILE_ANSWER = 'answer_lessons.json'
LESSONS_FILE_BEGINNERS = 'beginners_lessons.json'
USERS_FILE = 'users.json'
HYMNBOOKS_DIR = 'hymnbooks'

CLASSES = { "1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search" }
HYMNBOOKS = {
    #"1": {"name": "Great Hymns of Faith", "file": "great_hymns_of_faith.json"},
    #"2": {"name": "Celestial Hymns", "file": "celestial_hymns.json"},
    "1": {"name": "Nziyo Dzekurumbidza (Shona Hymns)", "file": "shona_hymns.json"}
}

# --- 3. HELPER & FORMATTING FUNCTIONS ---
# (All these functions from the previous step are required here but omitted for brevity)
# ... (get_user_file_path, load_json_data, etc.) ...
# The important new function is get_ai_response, which now uses Groq.

# --- NEW: AI "THINKING" FUNCTION using Groq ---
def get_ai_response(question, context):
    """
    Sends a question and context to the Groq API and returns the AI's response.
    """
    if not groq_client:
        return "Sorry, the AI thinking module is currently unavailable."
    
    system_prompt = "You are a friendly and helpful Sunday School assistant. Your answers must be based *only* on the provided lesson text (the context). If the answer is not in the text, say that you cannot answer based on the provided material. Keep your answers concise and easy to understand."
    
    user_prompt = f"Based on the following lesson context, please answer the user's question.\n\n--- LESSON CONTEXT ---\n{context}\n\n--- USER QUESTION ---\n{question}"

    try:
        # The code is almost identical to OpenAI's, just using the groq_client
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192", # Using a powerful open-source model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=150
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API Error: {e}")
        return "I'm having a little trouble thinking right now. Please try again in a moment."

# --- MAIN BOT LOGIC HANDLER ---
# (The rest of the file is identical to the previous OpenAI version.
#  The handle_bot_logic function calls get_ai_response, which now uses Groq.)
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
    week_difference = (current_week_start - anchor_week_start).days // 7
    return week_difference if week_difference >= 0 else -1
def format_hymn(hymn):
    if not hymn: return "Sorry, I couldn't find a hymn with that number in your selected hymnbook."
    title = hymn.get('title', 'No Title'); hymn_number = hymn.get('number', '#'); message = f"🎶 *Hymn #{hymn_number}: {title}*\n\n"
    verses = hymn.get('verses', []); chorus = hymn.get('chorus', []); parts = hymn.get('parts', [])
    if verses:
        for i, verse_lines in enumerate(verses, 1): message += f"*{i}.*\n" + "\n".join(verse_lines) + "\n\n"
    if chorus: message += "*Chorus:*\n" + "\n".join(chorus) + "\n\n"
    if parts:
        for part in parts: message += f"*Part {part['part']}*\n"; [message := message + "\n".join(v_lines) + "\n\n" for v_lines in part['verses']]
    return message.strip()
def format_beginners_lesson(lesson):
    if not lesson: return "Sorry, no 'Beginners' lesson is available."
    title = lesson.get('lessonTitle', 'N/A')
    bible_refs_list = [f"{ref['book']} {ref['chapter']}" for ref in lesson.get('bibleReference', []) if ref.get('book') and ref.get('chapter')]
    bible_refs = ', '.join(bible_refs_list) if bible_refs_list else "Genesis"; message = f"🖍️ *Beginners Lesson: {title}*\n\n_(Story from: {bible_refs})_\n\n"
    for section in lesson.get('lessonSections', []):
        if section.get('sectionType') == 'text': message += f"{section.get('sectionContent', 'No story available.')}\n\n"
    message += "Have a blessed week! ☀️"
    return message
#... [Other formatters here] ...
def handle_bot_logic(user_id, message_text):
    user_file = get_user_file_path(); users = load_json_data(user_file); message_text_lower = message_text.lower().strip()
    user_profile = users.get(user_id, {})
    if message_text_lower == 'reset': user_profile = {}; users[user_id] = user_profile; save_json_data(users, user_file)
    if 'mode' not in user_profile:
        if message_text_lower == '1':
            user_profile['mode'] = 'lessons'; users[user_id] = user_profile; save_json_data(users, user_file)
            send_whatsapp_message(user_id, "Please select your Sunday School class:\n\n*1.* Beginners\n*2.* Primary Pals\n*3.* Answer\n*4.* Search")
        elif message_text_lower == '2':
            user_profile['mode'] = 'hymnbook'; users[user_id] = user_profile; save_json_data(users, user_file)
            hymnbook_menu = "Please select your preferred hymnbook:\n\n"; [hymnbook_menu := hymnbook_menu + f"*{k}.* {b['name']}\n" for k, b in HYMNBOOKS.items()]
            send_whatsapp_message(user_id, hymnbook_menu)
        else: send_whatsapp_message(user_id, "Welcome! 🙏\n\nPlease choose a section:\n\n*1.* Weekly Lessons\n*2.* Hymnbook")
        return
    if user_profile.get('mode') == 'lessons':
        if 'class' not in user_profile:
            if message_text_lower in CLASSES:
                class_name = CLASSES[message_text_lower]; user_profile['class'] = class_name; users[user_id] = user_profile; save_json_data(users, user_file)
                send_whatsapp_message(user_id, f"Great! Class set to *{class_name}*.\n\nType `lesson` or `ask [your question]`.\nType `reset` to go back.")
            else: send_whatsapp_message(user_id, "Invalid class number. Please try again.")
            return
        if message_text_lower.startswith('ask '):
            question = message_text[4:].strip()
            if not question: send_whatsapp_message(user_id, "Please type a question after the word `ask`."); return
            lesson_index = get_current_lesson_index(); user_class = user_profile['class']; context = ""
            lesson_files = { "Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH }
            for key, filename in lesson_files.items():
                if key in user_class:
                    lessons_path = os.path.join(os.path.dirname(__file__), filename); lessons_data = load_json_data(lessons_path)
                    if lessons_data and 0 <= lesson_index < len(lessons_data): context = json.dumps(lessons_data[lesson_index]); break
            if not context: send_whatsapp_message(user_id, "Sorry, I can't find lesson material to answer questions about."); return
            send_whatsapp_message(user_id, "🤔 Thinking..."); ai_answer = get_ai_response(question, context); send_whatsapp_message(user_id, ai_answer)
        elif message_text_lower == 'lesson':
            # ... lesson logic ...
            send_whatsapp_message(user_id, "Fetching lesson...")
        else: send_whatsapp_message(user_id, "In *Lessons* section: type `lesson`, `ask [question]`, or `reset`.")
    elif user_profile.get('mode') == 'hymnbook':
        # ... hymnbook logic ...
        send_whatsapp_message(user_id, "Hymnbook logic here...")

def send_whatsapp_message(recipient_id, message_text):
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]): print("ERROR: WhatsApp credentials not set."); return
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"; headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": recipient_id, "text": {"body": message_text}}
    try:
        response = requests.post(url, headers=headers, json=data); response.raise_for_status(); print(f"Message sent to {recipient_id}: {response.status_code}, {response.text}")
    except requests.exceptions.RequestException as e: print(f"Error sending message: {e}")

# --- FLASK WEBHOOK ROUTES ---
# (Unchanged)
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
def health_check(): return "SundayBot AI (Groq) is running!", 200