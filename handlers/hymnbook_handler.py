# handlers/hymnbook_handler.py

import os
import services
import utils
import config

def handle_hymnbook(user_id, user_profile, message_text):
    """Manages the hymnbook lookup flow."""
    step = user_profile.get('hymn_step', 'start')
    message_text_lower = message_text.lower().strip()

    if step == 'start':
        rows = [{"id": f"hymnbook_{key}", "title": book['name']} for key, book in config.HYMNBOOKS.items()]
        interactive = {
            "type": "list",
            "header": {"type": "text", "text": "Select Hymnbook"},
            "body": {"text": "Please choose a hymnbook from the list."},
            "action": {"button": "View Hymnbooks", "sections": [{"title": "Hymnbooks", "rows": rows}]}
        }
        services.send_interactive_message(user_id, interactive)
        user_profile['hymn_step'] = 'awaiting_hymnbook_choice'

    elif step == 'awaiting_hymnbook_choice' and message_text_lower.startswith('hymnbook_'):
        hymnbook_key = message_text_lower.replace('hymnbook_', '', 1)
        chosen_book = config.HYMNBOOKS.get(hymnbook_key)
        if not chosen_book:
            services.send_text_message(user_id, "Invalid hymnbook selection. Please try again.")
            services.delete_user_profile(user_id)
            return None # End session

        user_profile['hymnbook_file'] = chosen_book['file']
        services.send_text_message(user_id, f"You've selected *{chosen_book['name']}*. Please enter a hymn number.")
        user_profile['hymn_step'] = 'awaiting_hymn_number'

    elif step == 'awaiting_hymn_number':
        hymn_number = message_text.strip()
        if not hymn_number.isdigit():
            services.send_text_message(user_id, "Please enter a valid number.")
            return user_profile # Wait for a valid number

        hymn_file_path = os.path.join(os.path.dirname(__file__), '..', config.HYMNBOOKS_DIR, user_profile['hymnbook_file'])
        all_hymns = utils.load_json_file(hymn_file_path)

        found_hymn = None
        if all_hymns:
            found_hymn = next((h for h in all_hymns if str(h.get('number')) == hymn_number), None)
        
        formatted_hymn = utils.format_hymn(found_hymn)
        services.send_text_message(user_id, formatted_hymn)
        
        # Ask for another number or let them go back to the menu
        interactive = {
            "type": "button",
            "body": {"text": "Enter another hymn number or go back to the main menu."},
            "action": {"buttons": [{"type": "reply", "reply": {"id": "reset", "title": "⬅️ Main Menu"}}]}
        }
        services.send_interactive_message(user_id, interactive)
        # The step remains 'awaiting_hymn_number' for the next input

    return user_profile