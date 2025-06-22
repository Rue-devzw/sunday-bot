# api/index.py

import os
import json
import requests
from flask import Flask, request
from datetime import date
from dateutil.relativedelta import relativedelta, MO

# --- 1. INITIALIZE FLASK APP ---
# Vercel will look for this 'app' variable.
app = Flask(__name__)

# --- 2. CONFIGURATION & ENVIRONMENT VARIABLES ---
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', 'your_default_verify_token')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')

# ... (all your other configuration and helper functions are here and stay the same) ...
# ... (load_data, save_data, get_current_lesson_index, format_search_lesson) ...
# ... (send_whatsapp_message, handle_bot_logic) ...
# Copy all the functions from the previous app.py here. For brevity, I'll just show the final routes.

def load_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data, file_path):
    # IMPORTANT for Vercel: We can only write to the /tmp directory
    # We will need to adjust this if we want to save user data permanently.
    # For now, this approach won't work on Vercel for saving data. We'll proceed
    # but acknowledge this limitation. A database is the real solution.
    # A quick fix is to check if we are in the Vercel environment.
    if 'VERCEL' in os.environ:
        file_path = f"/tmp/{os.path.basename(file_path)}"
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# ... [PASTE ALL YOUR OTHER HELPER AND LOGIC FUNCTIONS HERE] ...
# Make sure the `load_data` and `save_data` functions from the previous step are here.
# I'm omitting them for space, but they are required. The rest of the code is below.
def send_whatsapp_message(recipient_id, message_text):
    """Sends a message back to the user via the Meta Graph API."""
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": recipient_id,
        "text": {"body": message_text}
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status() # Raise an exception for bad status codes
        print(f"Message sent to {recipient_id}: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message: {e}")

def handle_bot_logic(user_id, message_text):
    """
    Processes the user message and triggers the send function.
    """
    users = load_data(USERS_FILE)
    message_text_lower = message_text.lower().strip()
    response_text = ""

    if user_id not in users or 'class' not in users.get(user_id, {}) or message_text_lower == "switch":
        if message_text_lower in CLASSES:
            class_name = CLASSES[message_text_lower]
            users[user_id] = {'class': class_name}
            save_data(users, USERS_FILE)
            response_text = (f"Great! You're registered for the *{class_name}* class.\n\n"
                             "You can type `lesson` anytime to get the latest lesson, or `menu` for more options.")
        else:
            response_text = ("Welcome to our Sunday School Assistant! 🙏\n\n"
                             "To get started, please select your class by replying with the number:\n\n"
                             "*1.* Beginners (Ages 2-5)\n*2.* Primary Pals (1st - 3rd Grade)\n"
                             "*3.* Answer (4th - 8th Grade)\n*4.* Search (High School - Adults)")
    else:
        user_class = users[user_id]['class']
        if message_text_lower == 'lesson':
            if "Search" in user_class:
                # Vercel needs absolute paths for data files
                lessons_path = os.path.join(os.path.dirname(__file__), '..', LESSONS_FILE)
                lessons_data = load_data(lessons_path)
                if not lessons_data:
                    response_text = "Error: Could not load lesson data. Please contact an admin."
                else:
                    lesson_index = get_current_lesson_index()
                    if 0 <= lesson_index < len(lessons_data):
                        lesson_to_send = lessons_data[lesson_index]
                        response_text = format_search_lesson(lesson_to_send)
                    else:
                        response_text = "There is no lesson scheduled for this week. Please check back later!"
            else:
                response_text = f"Content for the *{user_class}* class is coming soon!"
        elif message_text_lower == 'menu':
            response_text = ("Here are your options:\n\n"
                             "- Type `lesson` to get this week's lesson.\n- Type `switch` to change your class.")
        else:
            response_text = "Sorry, I didn't understand that. Type `lesson` or `menu`."
    
    send_whatsapp_message(user_id, response_text)

# --- FLASK WEBHOOK ROUTES ---
# Vercel routes all requests to this file, which Flask then handles.
@app.route('/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        return 'Verification token mismatch', 403
    
    if request.method == 'POST':
        data = request.get_json()
        if data and 'entry' in data:
            for entry in data['entry']:
                for change in entry['changes']:
                    if 'messages' in change['value']:
                        message = change['value']['messages'][0]
                        if message['type'] == 'text':
                            user_id = message['from']
                            message_text = message['text']['body']
                            handle_bot_logic(user_id, message_text)
        return 'OK', 200

@app.route('/')
def health_check():
    return "SundayBot is running on Vercel!", 200