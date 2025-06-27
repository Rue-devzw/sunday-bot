# api/index.py

import os
import json
import requests
from groq import Groq
from flask import Flask, request
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta, MO

# --- 1. INITIALIZE FLASK & GROQ CLIENT ---
app = Flask(__name__)
try:
    groq_client = Groq()
except Exception as e:
    print(f"Error initializing Groq client: {e}")
    groq_client = None

# --- 2. CONFIGURATION & ENVIRONMENT VARIABLES ---
# ... (Configuration remains the same) ...
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')
ANCHOR_DATE = date(2024, 8, 21)
LESSONS_FILE_SEARCH = 'search_lessons.json'
LESSONS_FILE_ANSWER = 'answer_lessons.json'
LESSONS_FILE_BEGINNERS = 'beginners_lessons.json'
USERS_FILE = 'users.json'
HYMNBOOKS_DIR = 'hymnbooks'
CLASSES = { "1": "Beginners", "2": "Primary Pals", "3": "Answer", "4": "Search" }
HYMNBOOKS = {
   # "1": {"name": "Great Hymns of Faith", "file": "great_hymns_of_faith.json"},
    #"2": {"name": "Celestial Hymns", "file": "celestial_hymns.json"},
    "1": {"name": "Nziyo Dzekurumbidza (Shona Hymns)", "file": "shona_hymns.json"}
}

# --- 3. HELPER & FORMATTING FUNCTIONS ---
# (Existing helpers and formatters remain, but we add a new context builder)
def get_user_file_path(): # ...
    return f'/tmp/{USERS_FILE}' if 'VERCEL' in os.environ else os.path.join(os.path.dirname(__file__), USERS_FILE)
def load_json_data(file_path): # ...
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}
def save_json_data(data, file_path): # ...
    with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
def get_current_lesson_index(): # ...
    today = date.today(); anchor_week_start = ANCHOR_DATE + relativedelta(weekday=MO(-1)); current_week_start = today + relativedelta(weekday=MO(-1))
    week_difference = (current_week_start - anchor_week_start).days // 7
    return week_difference if week_difference >= 0 else -1

# --- NEW: Context Builder for the AI ---
def build_lesson_context(lesson, class_name):
    """Creates a clean, readable text context from a lesson object for the AI."""
    if not lesson:
        return ""
    
    # Use the existing formatting functions to generate clean text!
    if "Beginners" in class_name:
        return format_beginners_lesson(lesson)
    elif "Answer" in class_name:
        return format_answer_lesson(lesson)
    elif "Search" in class_name:
        return format_search_lesson(lesson)
    
    return json.dumps(lesson) # Fallback to raw JSON

# (All lesson and hymn formatters are required here, but omitted for brevity)
# ... format_hymn, format_beginners_lesson, format_answer_lesson, format_search_lesson ...

# --- 4. ENHANCED AI "THINKING" FUNCTION ---
def get_ai_response(question, context):
    """Sends a question and context to the Groq API and returns the AI's response."""
    if not groq_client: return "Sorry, the AI thinking module is currently unavailable."
    
    # --- ENHANCED SYSTEM PROMPT ---
    system_prompt = (
        "You are a friendly and helpful Sunday School assistant. Your purpose is to answer questions *strictly* based on the lesson material provided as context. "
        "1. If the user's question can be answered from the text, answer it kindly and concisely. "
        "2. If the user's question cannot be answered from the text, you MUST politely state that the answer is not in the lesson material. Do not use external knowledge. "
        "3. If the user asks a greeting or off-topic question (like 'how are you?' or 'what is the capital of France?'), simply and kindly redirect them back to the lesson by saying something like, 'I am ready to help with your questions about the lesson!'"
    )
    
    user_prompt = f"Here is the lesson material:\n\n--- LESSON CONTEXT ---\n{context}\n\n--- END OF CONTEXT ---\n\nPlease answer this question based only on the lesson material above:\n\nUSER QUESTION: \"{question}\""

    try:
        completion = groq_client.chat.completions.create(model="llama3-8b-8192", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], temperature=0.2, max_tokens=150)
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API Error: {e}")
        return "I'm having a little trouble thinking right now. Please try again in a moment."

# --- 5. WHATSAPP MESSAGING FUNCTION ---
# (Unchanged)
def send_whatsapp_message(recipient_id, message_text):
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]): print("ERROR: WhatsApp credentials not set."); return
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": recipient_id, "text": {"body": message_text}}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status(); print(f"Message sent to {recipient_id}: {response.status_code}, {response.text}")
    except requests.exceptions.RequestException as e: print(f"Error sending message: {e}")

# --- 6. MAIN BOT LOGIC HANDLER (WITH AI CONVERSATION FLOW) ---
def handle_bot_logic(user_id, message_text):
    user_file = get_user_file_path(); users = load_json_data(user_file)
    message_text_lower = message_text.lower().strip()
    user_profile = users.get(user_id, {})

    # Reset command to go back to the main menu
    if message_text_lower == 'reset':
        user_profile = {}; users[user_id] = user_profile
        save_json_data(users, user_file)

    # --- Onboarding: Mode Selection ---
    if 'mode' not in user_profile:
        # ... (mode selection logic is unchanged) ...
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

    # --- Path 1: Lessons Mode ---
    if user_profile.get('mode') == 'lessons':
        if 'class' not in user_profile:
            # ... (class selection logic is unchanged) ...
            if message_text_lower in CLASSES:
                class_name = CLASSES[message_text_lower]; user_profile['class'] = class_name; users[user_id] = user_profile; save_json_data(users, user_file)
                send_whatsapp_message(user_id, f"Great! Class set to *{class_name}*.\n\nType `lesson` for your material or `ask` to start a Q&A session.\nType `reset` to go back.")
            else:
                send_whatsapp_message(user_id, "Sorry, that's not a valid class number. Please try again.")
            return

        # --- NEW: CONVERSATIONAL AI FLOW ---
        # Enter "ask mode"
        if message_text_lower == 'ask':
            user_profile['ask_mode'] = True
            users[user_id] = user_profile
            save_json_data(users, user_file)
            send_whatsapp_message(user_id, "You are now in Q&A mode. Ask me anything about this week's lesson!\n\nType `stop` to exit Q&A.")
            return
            
        # Exit "ask mode"
        if user_profile.get('ask_mode') and message_text_lower == 'stop':
            user_profile.pop('ask_mode', None)
            users[user_id] = user_profile
            save_json_data(users, user_file)
            send_whatsapp_message(user_id, "You have exited Q&A mode.")
            return
            
        # Handle questions while in "ask mode"
        if user_profile.get('ask_mode'):
            send_whatsapp_message(user_id, "🤔 Thinking...")
            
            lesson_index = get_current_lesson_index(); user_class = user_profile['class']; context = ""
            lesson_files = { "Beginners": LESSONS_FILE_BEGINNERS, "Answer": LESSONS_FILE_ANSWER, "Search": LESSONS_FILE_SEARCH }
            
            for key, filename in lesson_files.items():
                if key in user_class:
                    lessons_path = os.path.join(os.path.dirname(__file__), filename)
                    lessons_data = load_json_data(lessons_path)
                    if lessons_data and 0 <= lesson_index < len(lessons_data):
                        context = build_lesson_context(lessons_data[lesson_index], user_class) # Use our new context builder
                    break
            
            if not context:
                send_whatsapp_message(user_id, "Sorry, I can't find lesson material to answer questions about right now.")
                return
            
            ai_answer = get_ai_response(message_text, context) # The user's message IS the question
            send_whatsapp_message(user_id, ai_answer)
            return

        # Handle other commands if not in ask_mode
        if message_text_lower == 'lesson':
            # ... (lesson logic remains the same) ...
            send_whatsapp_message(user_id, "Fetching lesson...")
            lesson_index = get_current_lesson_index(); user_class = user_profile['class']
            response_text = "Sorry, no lesson is available for your class this week."
            formatters = { "Beginners": format_beginners_lesson, "Answer": format_answer_lesson, "Search": format_search_lesson }
            for key, filename in lesson_files.items():
                if key in user_class:
                    lessons_path = os.path.join(os.path.dirname(__file__), filename); lessons_data = load_json_data(lessons_path)
                    if lessons_data and 0 <= lesson_index < len(lessons_data): response_text = formatters[key](lessons_data[lesson_index]); break
            send_whatsapp_message(user_id, response_text)
        else:
            send_whatsapp_message(user_id, "You're in *Lessons*.\n- Type `lesson`\n- Type `ask` to start a Q&A session\n- Type `reset` to go back")
        return

    # --- Path 2: Hymnbook Mode ---
    elif user_profile.get('mode') == 'hymnbook':
        # ... (Hymnbook logic remains unchanged)
        if 'hymnbook' not in user_profile:
            if message_text_lower in HYMNBOOKS:
                hymnbook_choice = HYMNBOOKS[message_text_lower]; user_profile['hymnbook'] = hymnbook_choice['file']; users[user_id] = user_profile; save_json_data(users, user_file)
                send_whatsapp_message(user_id, f"Great! Hymnbook set to *{hymnbook_choice['name']}*.\n\nType `hymn [number]` or `reset`.")
            else:
                hymnbook_menu = "Invalid hymnbook number. Try again.\n\n"; [hymnbook_menu := hymnbook_menu + f"*{k}.* {b['name']}\n" for k, b in HYMNBOOKS.items()]
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
            send_whatsapp_message(user_id, "You're in *Hymnbook*.\n- Type `hymn [number]`\n- Type `reset` to go back")
        return

# --- 7. FLASK WEBHOOK ROUTES ---
# (Unchanged)
# ... (Full Flask routes here) ...