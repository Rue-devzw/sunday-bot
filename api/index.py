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
ANCHOR_DATE = date(2024, 9, 1) 
USERS_FILE = 'users.json'
CLASSES = {
    "1": "Beginners (Ages 2-5)",
    "2": "Primary Pals (1st - 3rd Grade)",
    "3": "Answer (4th - 8th Grade)",
    "4": "Search (High School - Adults)"
}

# New Scalable Configuration: Maps class names to their data and formatting functions
CLASS_CONFIG = {
    "Beginners (Ages 2-5)": {
        "file": "beginners_lessons.json",
        "formatter": "format_beginners_lesson"
    },
    "Primary Pals (1st - 3rd Grade)": {
        "file": "primary_pals_lessons.json",
        "formatter": "format_primary_pals_lesson"
    },
    "Answer (4th - 8th Grade)": {
        "file": "answer_lessons.json",
        "formatter": "format_answer_lesson"
    },
    "Search (High School - Adults)": {
        "file": "search_lessons.json",
        "formatter": "format_search_lesson"
    }
}


# --- 3. HELPER FUNCTIONS ---

def get_user_file_path():
    """Returns the correct path for users.json depending on the environment."""
    if 'VERCEL' in os.environ:
        return f'/tmp/{USERS_FILE}'
    else:
        return os.path.join(os.path.dirname(__file__), USERS_FILE)

def load_json_data(file_path):
    """Loads JSON data from a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_json_data(data, file_path):
    """Saves data to a JSON file."""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def get_current_lesson_index():
    """Calculates which lesson index to use based on the current date."""
    today = date.today()
    anchor_week_start = ANCHOR_DATE + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    week_difference = (current_week_start - anchor_week_start).days // 7
    return week_difference if week_difference >= 0 else -1

# --- 4. LESSON FORMATTING FUNCTIONS ---

def format_beginners_lesson(lesson):
    """Formats a lesson for the Beginners class."""
    if not lesson: return "I'm sorry, I couldn't find the lesson for this week."
    title = lesson.get('lessonTitle', 'N/A')
    story = lesson.get('simpleStory', 'No story available.')
    activity = lesson.get('keyActivity', 'No activity available.')
    verse = lesson.get('memoryVerse', 'No verse available.')
    message = f"🎨 *Beginners Lesson: {title}*\n\n"
    message += f"📖 *Story Time:*\n{story}\n\n"
    message += f"🖍️ *Activity Idea:*\n{activity}\n\n"
    message += f"✝️ *Memory Verse:*\n_{verse}_"
    return message

def format_primary_pals_lesson(lesson):
    """Formats a lesson for the Primary Pals class."""
    if not lesson: return "I'm sorry, I couldn't find the lesson for this week."
    title = lesson.get('lessonTitle', 'N/A')
    story = lesson.get('mainStory', 'No story available.')
    question = lesson.get('discussionQuestion', 'No question available.')
    craft = lesson.get('craftIdea', 'No craft idea available.')
    message = f"🧩 *Primary Pals Lesson: {title}*\n\n"
    message += f"📖 *The Story:*\n{story}\n\n"
    message += f"🤔 *Let's Talk About It:*\n{question}\n\n"
    message += f"✂️ *Craft Time:*\n{craft}"
    return message

def format_answer_lesson(lesson):
    """Formats a lesson for the Answer class."""
    if not lesson: return "I'm sorry, I couldn't find the lesson for this week."
    title = lesson.get('lessonTitle', 'N/A')
    key_text = lesson.get('keyText', 'N/A')
    challenge = lesson.get('weeklyChallenge', 'N/A')
    message = f"💡 *Answer Class Lesson: {title}*\n\n"
    message += f"📜 *Key Text:*\n{key_text}\n\n"
    message += f"🎯 *Weekly Challenge:*\n{challenge}"
    return message

def format_search_lesson(lesson):
    """Formats a lesson from the 'Search' class."""
    if not lesson: return "I'm sorry, I couldn't find the lesson for this week."
    title = lesson.get('lessonTitle', 'N/A')
    key_verse = lesson.get('keyVerse', 'N/A')
    bible_refs = ', '.join([f"{ref['book']} {ref['chapter']}:{ref['verses']}" for ref in lesson.get('bibleReference', [])])
    message = f"📚 *Lesson: {title}*\n\n📖 *Bible Text:* {bible_refs}\n"
    if lesson.get('supplementalScripture'):
        message += f"📖 *Supplemental:* {lesson.get('supplementalScripture')}\n\n"
    message += f"🔑 *Key Verse:*\n_{key_verse}_\n\n"
    for section in lesson.get('lessonSections', []):
        section_title, section_content, section_type = section.get("sectionTitle"), section.get("sectionContent"), section.get("sectionType")
        if section_type == 'text':
            message += f"*{section_title}*\n{section_content}\n\n"
        elif section_type == 'question':
            message += f"❓ *{section_title}:* {section_content}\n"
    message += "\n"
    return message


# --- 5. WHATSAPP MESSAGING FUNCTION ---
def send_whatsapp_message(recipient_id, message_text):
    """Sends a message back to the user via the Meta Graph API."""
    if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID]):
        print("ERROR: WhatsApp credentials are not set in environment variables.")
        return
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": recipient_id, "text": {"body": message_text}}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"Message sent to {recipient_id}: {response.status_code}, {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message: {e}")


# --- 6. MAIN BOT LOGIC HANDLER ---
def handle_bot_logic(user_id, message_text):
    """Processes the user message and triggers the send function."""
    user_file = get_user_file_path()
    users = load_json_data(user_file)
    
    message_text_lower = message_text.lower().strip()
    response_text = ""

    # State management for 'switch' command
    if message_text_lower == "switch":
        if user_id in users and 'class' in users[user_id]:
            del users[user_id]['class']
            save_json_data(users, user_file)
    
    # Onboarding Logic
    if user_id not in users or 'class' not in users.get(user_id, {}):
        if message_text_lower in CLASSES:
            class_name = CLASSES[message_text_lower]
            users[user_id] = {'class': class_name}
            save_json_data(users, user_file)
            response_text = (f"Great! You're registered for the *{class_name}* class.\n\n"
                             "You can type `lesson` anytime to get the latest lesson, or `menu` for more options.")
        else:
            response_text = ("Welcome to our Sunday School Assistant! 🙏\n\n"
                             "To get started, please select your class by replying with the number:\n\n"
                             "*1.* Beginners (Ages 2-5)\n*2.* Primary Pals (1st - 3rd Grade)\n"
                             "*3.* Answer (4th - 8th Grade)\n*4.* Search (High School - Adults)")
    
    # Registered User Logic
    else:
        user_class = users[user_id]['class']
        if message_text_lower == 'lesson':
            config = CLASS_CONFIG.get(user_class)
            if not config:
                response_text = "Sorry, there's an issue with your class configuration. Please contact an admin."
            else:
                lesson_file = config["file"]
                formatter_function_name = config["formatter"]
                lessons_path = os.path.join(os.path.dirname(__file__), lesson_file)
                lessons_data = load_json_data(lessons_path)

                if not lessons_data:
                    response_text = f"Sorry, I couldn't find any lessons for the *{user_class}* class. Please check back later."
                else:
                    lesson_index = get_current_lesson_index()
                    if 0 <= lesson_index < len(lessons_data):
                        lesson_to_send = lessons_data[lesson_index]
                        formatter_function = globals().get(formatter_function_name)
                        if formatter_function:
                            response_text = formatter_function(lesson_to_send)
                        else:
                            response_text = "Error: Could not format the lesson. Contact an admin."
                    else:
                        response_text = "There is no lesson scheduled for this week. Please check back later!"
        elif message_text_lower == 'menu':
            response_text = ("Here are your options:\n\n"
                             "- Type `lesson` to get this week's lesson.\n- Type `switch` to change your class.")
        else:
            response_text = "Sorry, I didn't understand that. Type `lesson` or `menu`."
    
    send_whatsapp_message(user_id, response_text)

# --- 7. FLASK WEBHOOK ROUTES ---
@app.route('/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    """Main webhook endpoint to receive all events from WhatsApp."""
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            print("Webhook verified successfully!")
            return request.args.get('hub.challenge'), 200
        print("Verification token mismatch!")
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
                                user_id = message['from']
                                message_text = message['text']['body']
                                handle_bot_logic(user_id, message_text)
        except Exception as e:
            print(f"Error processing message: {e}")
        return 'OK', 200

@app.route('/')
def health_check():
    """A simple route to check if the server is running."""
    return "SundayBot is running live on Vercel!", 200