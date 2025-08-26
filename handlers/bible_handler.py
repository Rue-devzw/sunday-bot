# handlers/bible_handler.py

import services
import config

def handle_bible(user_id, user_profile, message_text):
    """Manages the interactive Bible lookup flow."""
    step = user_profile.get('bible_step', 'start')
    message_text_lower = message_text.lower().strip()

    if step == 'start':
        rows = [{"id": f"bible_{key}", "title": bible['name']} for key, bible in config.BIBLES.items()]
        interactive = {
            "type": "list",
            "header": {"type": "text", "text": "Select Bible Version"},
            "body": {"text": "Please choose a Bible version from the list."},
            "action": {"button": "View Versions", "sections": [{"title": "Bibles", "rows": rows}]}
        }
        services.send_interactive_message(user_id, interactive)
        user_profile['bible_step'] = 'awaiting_bible_choice'

    elif step == 'awaiting_bible_choice' and message_text_lower.startswith('bible_'):
        bible_key = message_text_lower.replace('bible_', '', 1)
        chosen_bible = config.BIBLES.get(bible_key)
        if not chosen_bible:
            services.send_text_message(user_id, "Invalid Bible selection. Please try again.")
            services.delete_user_profile(user_id)
            return None # End session

        user_profile['bible_file'] = chosen_bible['file']
        services.send_text_message(user_id, f"You've selected the *{chosen_bible['name']}*. Please enter a passage (e.g., John 3:16).")
        user_profile['bible_step'] = 'awaiting_passage'

    elif step == 'awaiting_passage':
        passage = message_text.strip()
        bible_file = user_profile.get('bible_file')
        if not bible_file:
             services.send_text_message(user_id, "Something went wrong. Please start over.")
             services.delete_user_profile(user_id)
             return None

        services.send_text_message(user_id, f"_Looking up {passage}..._")
        verse_text = services.get_verse_from_db(passage, bible_file)
        services.send_text_message(user_id, verse_text)
        
        # Ask for another passage or let them go back to the menu
        interactive = {
            "type": "button",
            "body": {"text": "Enter another passage or go back to the main menu."},
            "action": {"buttons": [{"type": "reply", "reply": {"id": "reset", "title": "⬅️ Main Menu"}}]}
        }
        services.send_interactive_message(user_id, interactive)
        # The step remains 'awaiting_passage' for the next input

    return user_profile