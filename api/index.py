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
    print(f"Error initializing Groq client: {e}")
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

CLASSES = { "1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search" }
HYMNBOOKS = {
   # "1": {"name": "Great Hymns of Faith", "file": "great_hymns_of_faith.json"},
   # "2": {"name": "Celestial Hymns", "file": "celestial_hymns.json"},
    "1": {"name": "Nziyo Dzekurumbidza (Shona Hymns)", "file": "shona_hymns.json"}
}

# --- 3. HELPER & FORMATTING FUNCTIONS ---
# (All these functions are correct and required, but omitted for brevity.
#  Ensure you have them in your file from the previous step.)
# ... get_user_file_path, load_json_data, save_json_data, get_current_lesson_index ...
# ... format_hymn, format_beginners_lesson, format_answer_lesson, format_search_lesson ...
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
# ... [Include other lesson formatters here] ...

# --- AI "THINKING" FUNCTION using Groq ---
def get_ai_response(question, context):
    if not groq_client: return "Sorry, the AI thinking module is currently unavailable."
    system_prompt = "You are a friendly and helpful Sunday School assistant. Your answers must be based *only* on the provided lesson text (the context). If the answer is not in the text, say that you cannot answer based on the provided material. Keep your answers concise and easy to understand."
    user_prompt = f"Based on the following lesson context, please answer the user's question.\n\n--- LESSON CONTEXT ---\n{context}\n\n--- USER QUESTION ---\n{question}"
    try:
        completion = groq_client.chat.completions.create(model="llama3-8b-8192", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], temperature=0.3, max_tokens=150)
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API Error: {e}")
        return "I'm having a little trouble thinking right now. Please try again in a moment."

# --- WHATSAPP MESSAGING FUNCTION ---
def send_whatsapp_message(recipient_id, message_text):
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]): print("ERROR: WhatsApp credentials not set."); return
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": recipient_id, "text": {"body": message_text}}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status(); print(f"Message sent to {recipient_id}: {response.status_code}, {response.text}")
    except requests.exceptions.RequestException as e: print(f"Error sending message: {e}")

# --- RESTRUCTURED MAIN BOT LOGIC HANDLER ---
def handle_bot_logic(user_id, message_text):
    user_file = get_user_file_path()
    users = load_json_data(user_file)
    message_text_lower = message_text.lower().strip()
    
    user_profile = users.get(user_id, {})
    
    # State reset command
    if message_text_lower == 'reset':
        user_profile = {}; users[user_id] = user_profile; save_json_data(users, user_file)

    # --- Step 1: Mode Selection ---
    if 'mode' not in user_profile:
        if message_text_lower == '1':
            user_profile['mode'] = 'lessons'; users[user_id] = user_profile; save_json_data(users, user_file)
            send_whatsapp_message(user_id, "Please select your Sunday School class:\n\n*1.* Beginners\n*2.* Primary Pals\n*3.* Answer\n*4.* Search")
        elif message_text_lower == '2':
            user_profile['mode'] = 'hymnbook'; users[user_id] = user_profile; save_json_data(users, user_file)
            hymnbook_menu = "Please select your preferred hymnbook:\n\n"; [hymnbook_menu := hymnbook_menu + f"*{k}.* {b['name']}\n" for k, b in HYMNBOOKS.items()]
            send_whatsapp_message(user_id, hymnbook_menu)
        else:
            send_whatsapp_message(user_id, "Welcome! 🙏\n\nPlease choose a section:\n\n*1.* Weekly Lessons\n*2.* Hymnbook")
        return

    # --- Step 2: Handle commands within the selected mode ---
    
    # --- PATH 1: USER IS IN 'LESSONS' MODE ---
    if user_profile.get('mode') == 'lessons':
        if 'class' not in user_profile:
            if message_text_lower in CLASSES:
                class_name = CLASSES[message_text_lower]; user_profile['class'] = class_name; users[user_id] = user_profile; save_json_data(users, user_file)
                send_whatsapp_message(user_id, f"Great! Class set to *{class_name}*.\n\nType `lesson` for your material or `ask [your question]`.\nType `reset` to go back.")
            else:
                send_whatsapp_message(user_id, "Sorry, that's not a valid class number. Please try again.")
            return

        # --- FIX IS HERE: Refactored command handling ---
        if message_text_lower == 'lesson':
            send_whatsapp_message(user_id, "Fetching lesson...") # Inform the user
            lesson_index = get_current_lesson_index(); user_class = user_profile['class']
            response_text = "Sorry, no lesson is available for your class this week."
            lesson_files = { "Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH }
            formatters = { "Beginners": format_beginners_lesson, "Answer": format_answer_lesson, "Search": format_search_lesson }
            
            for key, filename in lesson_files.items():
                if key in user_class:
                    lessons_path = os.path.join(os.path.dirname(__file__), filename); lessons_data = load_json_data(lessons_path)
                    if lessons_data and 0 <= lesson_index < len(lessons_data):
                        response_text = formatters[key](lessons_data[lesson_index])
                    break
            send_whatsapp_message(user_id, response_text) # Send the final lesson
        elif message_text_lower.startswith('ask '):
            question = message_text[4:].strip()
            if not question:
                send_whatsapp_message(user_id, "Please type a question after the word `ask`.")
                return
            
            send_whatsapp_message(user_id, "🤔 Thinking...") # Inform the user
            lesson_index = get_current_lesson_index(); user_class = user_profile['class']; context = ""
            lesson_files = { "Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH }
            for key, filename in lesson_files.items():
                if key in user_class:
                    lessons_path = os.path.join(os.path.dirname(__file__), filename); lessons_data = load_json_data(lessons_path)
                    if lessons_data and 0 <= lesson_index < len(lessons_data): context = json.dumps(lessons_data[lesson_index]); break
            
            if not context:
                send_whatsapp_message(user_id, "Sorry, I can't find lesson material to answer questions about right now.")
                return
            
            ai_answer = get_ai_response(question, context)
            send_whatsapp_message(user_id, ai_answer) # Send the final AI answer
        else:
            send_whatsapp_message(user_id, "You are in the *Lessons* section.\n\n- Type `lesson`\n- Type `ask [your question]`\n- Type `reset` to go back")
        return

    # --- PATH 2: USER IS IN 'HYMNBOOK' MODE ---
    elif user_profile.get('mode') == 'hymnbook':
        # ... (Hymnbook logic is refactored similarly)
        if 'hymnbook' not in user_profile:
            if message_text_lower in HYMNBOOKS:
                hymnbook_choice = HYMNBOOKS[message_text_lower]; user_profile['hymnbook'] = hymnbook_choice['file']; users[user_id] = user_profile; save_json_data(users, user_file)
                send_whatsapp_message(user_id, f"Great! Hymnbook set to *{hymnbook_choice['name']}*.\n\nType `hymn [number]` or `reset`.")
            else:
                hymnbook_menu = "Sorry, that's not a valid hymnbook number. Please try again.\n\n"; [hymnbook_menu := hymnbook_menu + f"*{k}.* {b['name']}\n" for k, b in HYMNBOOKS.items()]
                send_whatsapp_message(user_id, hymnbook_menu)
            return
            
        if message_text_lower.startswith('hymn '):
            hymns_path = os.path.join(os.path.dirname(__file__), HYMNBOOKS_DIR, user_profile['hymnbook']); hymns_data = load_json_data(hymns_path)
            try:
                hymn_num_to_find = int(message_text_lower.split(' ')[1])
                found_hymn = next((h for h in hymns_data if h.get("number") == hymn_num_to_find), None)
                send_whatsapp_message(user_id, format_hymn(found_hymn))
            except (ValueError, IndexError):
                send_whatsapp_message(user_id, "Invalid format. Use `hymn [number]`.")
        else:
            send_whatsapp_message(user_id, "You are in the *Hymnbook* section.\n\n- Type `hymn [number]`\n- Type `reset` to go back")
        return

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
                            if message['type'] == 'text':
                                handle_bot_logic(message['from'], message['text']['body'])
        except Exception as e: print(f"Error processing message: {e}")
        return 'OK', 200

@app.route('/')
def health_check():
    return "SundayBot AI (Groq) is running!", 200