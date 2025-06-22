# app.py

import os
import json
import requests
from flask import Flask, request, jsonify
from datetime import date
from dateutil.relativedelta import relativedelta, MO

# --- 1. INITIALIZE FLASK APP ---
app = Flask(__name__)

# --- 2. CONFIGURATION & ENVIRONMENT VARIABLES ---
# Load credentials from environment variables for security
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', 'your_default_verify_token')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')

# Static Configuration
ANCHOR_DATE = date(2024, 8, 21) 
LESSONS_FILE = 'search_lessons.json'
USERS_FILE = 'users.json'
CLASSES = {
    "1": "Beginners (Ages 2-5)",
    "2": "Primary Pals (1st - 3rd Grade)",
    "3": "Answer (4th - 8th Grade)",
    "4": "Search (High School - Adults)"
}

# --- 3. HELPER FUNCTIONS (UNCHANGED) ---
def load_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def get_current_lesson_index():
    today = date.today()
    anchor_week_start = ANCHOR_DATE + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    days_difference = (current_week_start - anchor_week_start).days
    week_difference = days_difference // 7
    return week_difference if week_difference >= 0 else -1

def format_search_lesson(lesson):
    if not lesson:
        return "I'm sorry, I couldn't find the lesson for this week. Please check back later."
    title = lesson.get('lessonTitle', 'N/A')
    key_verse = lesson.get('keyVerse', 'N/A')
    bible_refs = ', '.join([f"{ref['book']} {ref['chapter']}:{ref['verses']}" for ref in lesson.get('bibleReference', [])])
    message = f"📚 *Lesson: {title}*\n\n"
    message += f"📖 *Bible Text:* {bible_refs}\n"
    if lesson.get('supplementalScripture'):
        message += f"📖 *Supplemental:* {lesson.get('supplementalScripture')}\n\n"
    message += f"🔑 *Key Verse:*\n_{key_verse}_\n\n"
    for section in lesson.get('lessonSections', []):
        section_title = section.get("sectionTitle")
        section_content = section.get("sectionContent")
        section_type = section.get("sectionType")
        if section_type == 'text':
            message += f"*{section_title}*\n{section_content}\n\n"
        elif section_type == 'question':
            message += f"❓ *{section_title}:* {section_content}\n"
    message += "\n"
    return message

# --- 4. NEW: FUNCTION TO SEND MESSAGES VIA WHATSAPP API ---
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

# --- 5. BOT LOGIC FUNCTION (MODIFIED) ---
def handle_bot_logic(user_id, message_text):
    """
    Processes the user message and triggers the send function.
    This function no longer returns text, it calls `send_whatsapp_message`.
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
                lessons_data = load_data(LESSONS_FILE)
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
    
    # Send the determined response back to the user
    send_whatsapp_message(user_id, response_text)

# --- 6. FLASK WEBHOOK ROUTES ---
@app.route('/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    """Main webhook endpoint to receive events from WhatsApp."""
    if request.method == 'GET':
        # This is the verification challenge from Meta
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        return 'Verification token mismatch', 403
    
    if request.method == 'POST':
        # This is an incoming message from a user
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

# Health check route
@app.route('/')
def health_check():
    return "SundayBot is running!", 200

# This part is optional but good for local testing of the web server
if __name__ == '__main__':
    app.run(debug=True, port=os.environ.get('PORT', 5001))