# app.py (Final Version)
from flask import Flask, request
import re

import config
import services
from handlers import (
    registration_handler,
    lessons_handler,
    hymnbook_handler,
    bible_handler,
    admin_handler,
)

# --- INITIALIZE FLASK & SERVICES ---
app = Flask(__name__)
services.initialize_services()

# --- HANDLER ROUTING ---
MODE_HANDLERS = {
    'camp_registration': registration_handler.handle_registration,
    'lessons': lessons_handler.handle_lessons,
    'hymnbook': hymnbook_handler.handle_hymnbook,
    'bible': bible_handler.handle_bible,
    'check_status': admin_handler.handle_check_status,
}

# --- MAIN LOGIC ROUTER ---
def handle_bot_logic(user_id, message_text):
    """
    Main router for all incoming messages.
    - Retrieves user session.
    - Determines user's current 'mode'.
    - Routes to the appropriate handler.
    - Saves the updated session.
    """
    user_profile = services.get_user_profile(user_id)
    message_text_lower = message_text.lower().strip()

    # --- Global Commands (can be triggered from any mode) ---
    if message_text_lower == 'reset':
        services.delete_user_profile(user_id)
        user_profile = {}
    
    if message_text_lower.startswith('bible '):
        passage = message_text.strip().replace('bible ', '', 1)
        verse_text = services.get_verse_from_db(passage, config.BIBLES['english']['file'])
        services.send_text_message(user_id, verse_text)
        return # Quick lookup doesn't affect session state

    clean_user_id = re.sub(r'\D', '', user_id)
    if clean_user_id in config.CLEAN_ADMIN_NUMBERS and message_text_lower.startswith('export'):
        admin_handler.handle_export(user_id, message_text_lower)
        return # Admin commands don't affect session state

    # --- Mode Selection ---
    if message_text_lower.startswith("mode_"):
        services.delete_user_profile(user_id) # Reset for new mode
        user_profile = {}
        full_mode_id = message_text_lower.replace('mode_', '', 1)
        if full_mode_id.startswith('camp_reg_'):
            user_profile['mode'] = 'camp_registration'
            user_profile['registration_type'] = full_mode_id.replace('camp_reg_', '', 1)
        else:
            user_profile['mode'] = full_mode_id

    mode = user_profile.get('mode')
    
    # --- Route to handler based on mode ---
    handler = MODE_HANDLERS.get(mode)
    if handler:
        updated_profile = handler(user_id, user_profile, message_text)
        if updated_profile:
            services.save_user_profile(user_id, updated_profile)
    else:
        # If no mode is set or mode is invalid, show main menu
        interactive = {
            "type": "list", "header": {"type": "text", "text": "Welcome to SundayBot 🙏"},
            "body": {"text": "I can help you with lessons, hymns, camp registration, and more. Please choose an option:"},
            "action": { "button": "Choose an option", "sections": [ { "title": "Main Menu", "rows": [
                {"id": "mode_lessons", "title": "📖 Weekly Lessons"}, {"id": "mode_hymnbook", "title": "🎶 Hymnbook"},
                {"id": "mode_bible", "title": "✝️ Bible Lookup"}, {"id": "mode_camp_reg_youths", "title": "🏕️ Youths Camp Reg."},
                {"id": "mode_camp_reg_annual", "title": "🏕️ Annual Camp Reg."}, {"id": "mode_check_status", "title": "✅ Check Registration"}
            ]}]}
        }
        services.send_interactive_message(user_id, interactive)
        if user_profile: services.delete_user_profile(user_id) # Clean up invalid state


# --- WEBHOOK & HEALTH CHECK ---
@app.route('/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == config.VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        return 'Verification token mismatch', 403

    if request.method == 'POST':
        data = request.get_json()
        try:
            if data and 'entry' in data and data['entry'][0]['changes'][0]['value'].get('messages'):
                message = data['entry'][0]['changes'][0]['value']['messages'][0]
                user_id = message['from']
                msg_text = ''

                if message.get('type') == 'text':
                    msg_text = message['text']['body']
                elif message.get('type') == 'interactive':
                    interactive_type = message['interactive']['type']
                    if interactive_type == 'button_reply':
                        msg_text = message['interactive']['button_reply']['id']
                    elif interactive_type == 'list_reply':
                        msg_text = message['interactive']['list_reply']['id']
                
                if msg_text:
                    handle_bot_logic(user_id, msg_text)
        except (IndexError, KeyError) as e:
            print(f"Could not parse webhook payload: {e}")
        return 'OK', 200

@app.route('/')
def health_check():
    return "SundayBot Interactive UI with Firebase is running!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))