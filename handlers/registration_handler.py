# handlers/registration_handler.py
import re
from firebase_admin import firestore
import services
import utils
import config

def handle_registration(user_id, user_profile, message_text):
    """Manages the entire camp registration flow."""
    step = user_profile.get('registration_step', 'start')
    data = user_profile.setdefault('registration_data', {})
    reg_type = user_profile.get('registration_type', 'annual')
    message_text_lower = message_text.lower().strip()

    # Handle the restart command
    if step == 'awaiting_confirmation' and message_text_lower == 'restart_reg':
        user_profile.update({'registration_step': 'start', 'registration_data': {}})
        step = 'start'
        data = {}

    if step == 'start':
        camp_name = "2025 Regional Youths Camp" if reg_type == 'youths' else "2025 Annual Camp"
        services.send_text_message(user_id, f"🏕️ *{camp_name} Registration*\n\nLet's get you registered. First, what is your *ID or Passport number*?")
        user_profile['registration_step'] = 'awaiting_id_passport'

    elif step == 'awaiting_id_passport':
        id_passport = message_text.strip()
        if not id_passport:
            services.send_text_message(user_id, "ID/Passport number cannot be empty. Please try again.")
            return user_profile # Return early, wait for new input
            
        services.send_text_message(user_id, f"Checking if `{id_passport}` is already registered...")
        existing_reg = services.check_registration_status(id_passport, reg_type)

        if isinstance(existing_reg, dict):
            reg_name = f"{existing_reg.get('first_name', '')} {existing_reg.get('last_name', '')}"
            services.send_text_message(user_id, f"It looks like you are already registered under the name *{reg_name}*. No need to register again!")
            services.delete_user_profile(user_id) # End session
            return None # Signal to router to stop processing

        elif existing_reg == "Error":
            services.send_text_message(user_id, "I'm having trouble checking for duplicates right now. Please contact an admin.")
            services.delete_user_profile(user_id)
            return None

        else:
            data['id_passport'] = id_passport
            services.send_text_message(user_id, "Great! Now, what is your *first name*?")
            user_profile['registration_step'] = 'awaiting_first_name'

    # ... (ALL OTHER ELIF BLOCKS FOR REGISTRATION GO HERE) ...
    
    elif step == 'awaiting_confirmation':
        if message_text_lower == 'confirm_reg':
            if services.save_registration(data, reg_type):
                services.send_text_message(user_id, "✅ Registration successful! Your details have been saved.")
            else:
                services.send_text_message(user_id, "⚠️ There was a problem saving your registration. Please contact an admin.")
            services.delete_user_profile(user_id)
            return None
    
    return user_profile