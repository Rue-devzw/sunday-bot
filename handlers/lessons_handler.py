# handlers/lessons_handler.py

import services
import utils  # Ensure utils is imported for the path helper
import config

def handle_lessons(user_id, user_profile, message_text):
    """Manages the weekly lessons flow."""
    step = user_profile.get('lesson_step', 'start')
    message_text_lower = message_text.lower().strip()

    if step == 'start':
        rows = [{"id": f"lesson_class_{key}", "title": name} for key, name in config.CLASSES.items()]
        interactive = {
            "type": "list",
            "header": {"type": "text", "text": "Select Your Class"},
            "body": {"text": "Please choose your Sunday School class from the list."},
            "action": {"button": "View Classes", "sections": [{"title": "Classes", "rows": rows}]}
        }
        services.send_interactive_message(user_id, interactive)
        user_profile['lesson_step'] = 'awaiting_class_choice'

    elif step == 'awaiting_class_choice' and message_text_lower.startswith('lesson_class_'):
        class_key = message_text_lower.replace('lesson_class_', '', 1)
        user_class = config.CLASSES.get(class_key)
        if not user_class:
            services.send_text_message(user_id, "Invalid class selection. Please try again.")
            services.delete_user_profile(user_id)
            return None # End session

        user_profile['lesson_class'] = user_class
        
        lesson_file_name = config.LESSON_FILES.get(user_class, '')
        
        # --- BEFORE (Incorrect for Vercel) ---
        # lesson_file_path = os.path.join(os.path.dirname(__file__), '..', config.LESSONS_DIR, lesson_file_name)
        
        # --- AFTER (Corrected using the asset path helper) ---
        lesson_file_path = utils.get_asset_path(config.LESSONS_DIR, lesson_file_name)
        
        raw_data = utils.load_json_file(lesson_file_path)
        if raw_data is None:
            services.send_text_message(user_id, "Sorry, the lesson file for your class could not be loaded from the server.")
            services.delete_user_profile(user_id)
            return None

        all_lessons = []
        if user_class == "Primary Pals" and isinstance(raw_data, dict):
            all_lessons = raw_data.get('primary_pals_lessons', [])
        elif isinstance(raw_data, list):
            all_lessons = raw_data

        lesson_index = utils.get_current_lesson_index(user_class)

        if all_lessons and 0 <= lesson_index < len(all_lessons):
            current_lesson = all_lessons[lesson_index]
            user_profile['current_lesson_data'] = current_lesson
            title = current_lesson.get('title') or current_lesson.get('lessonTitle', 'N/A')
            interactive = {
                "type": "button",
                "body": {"text": f"This week's lesson for *{user_class}* is:\n\n*{title}*\n\nWhat would you like to do?"},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "lesson_read", "title": "📖 Read Lesson"}},
                        {"type": "reply", "reply": {"id": "lesson_ask", "title": "❓ Ask a Question"}}
                    ]
                }
            }
            services.send_interactive_message(user_id, interactive)
            user_profile['lesson_step'] = 'awaiting_lesson_action'
        else:
            services.send_text_message(user_id, "Sorry, I couldn't find the current lesson for your class.")
            services.delete_user_profile(user_id)
            return None

    elif step == 'awaiting_lesson_action':
        if message_text_lower == 'lesson_read':
            formatted_lesson = utils.format_lesson(user_profile.get('current_lesson_data'), user_profile.get('lesson_class'))
            services.send_text_message(user_id, formatted_lesson)
            interactive = {
                "type": "button",
                "body": {"text": "What next?"},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "lesson_read", "title": "📖 Read Again"}},
                        {"type": "reply", "reply": {"id": "lesson_ask", "title": "❓ Ask a Question"}},
                        {"type": "reply", "reply": {"id": "reset", "title": "⬅️ Main Menu"}}
                    ]
                }
            }
            services.send_interactive_message(user_id, interactive)
        elif message_text_lower == 'lesson_ask':
            services.send_text_message(user_id, "OK, please type your question about the lesson. To return to the main menu, send 'reset'.")
            user_profile['lesson_step'] = 'awaiting_ai_question'

    elif step == 'awaiting_ai_question':
        # Avoid re-triggering on the action buttons
        if message_text_lower not in ['lesson_read', 'lesson_ask']:
            context = utils.format_lesson(user_profile.get('current_lesson_data'), user_profile.get('lesson_class'))
            services.send_text_message(user_id, "_Thinking..._ 🤔")
            ai_answer = services.get_ai_response(message_text, context)
            services.send_text_message(user_id, ai_answer)
            
            interactive = {
                "type": "button",
                "body": {"text": "You can ask another question or go back to the main menu."},
                "action": {"buttons": [{"type": "reply", "reply": {"id": "reset", "title": "⬅️ Main Menu"}}]}
            }
            services.send_interactive_message(user_id, interactive)
            # The step remains 'awaiting_ai_question' for the next question

    return user_profile