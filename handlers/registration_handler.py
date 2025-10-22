# handlers/registration_handler.py

import re
from firebase_admin import firestore
import services
import utils
import config

# --- HELPER FUNCTION FOR THE CONFIRMATION MESSAGE ---
def _send_confirmation_message(user_id, data):
    """Sends the registration confirmation message with edit options."""
    camp_name = "Annual Camp" # Default name, can be enhanced later if needed
    conf_text = (
        f"📝 *Please confirm your details for the {camp_name}:*\n\n"
        f"∙ *Reference:* {data.get('reference', '')}\n"
        f"∙ *Name:* {data.get('first_name', '')} {data.get('last_name', '')}\n"
        f"∙ *Email:* {data.get('email', '')}\n"
        f"∙ *Age:* {data.get('age', 'N/A')}\n"
        f"∙ *Gender:* {data.get('gender', '')}\n"
        f"∙ *Marital Status:* {data.get('marital_status', '')}\n"
        f"∙ *Country:* {data.get('country', '')}\n"
        f"∙ *Phone:* {data.get('phone', '')}\n"
        f"∙ *Language:* {data.get('language', '')}\n\n"
        f"∙ *Transport Needed:* {data.get('transport_needed', '')}\n"
        f"∙ *Accommodation:* {data.get('accommodation', '')}\n"
        f"∙ *Worker Status:* {data.get('worker_status', '')}\n"
        f"∙ *Arrival Date:* {data.get('arrival_date', '')}\n"
        f"∙ *Departure Date:* {data.get('departure_date', '')}\n"
        f"∙ *Arrival Time:* {data.get('arrival_time', '')}\n"
        f"∙ *Dietary Requirements:* {data.get('dietary_requirements', '')}\n"
        f"∙ *Children:* {data.get('children', '0')}\n"
        f"∙ *Volunteer Roles:* {data.get('volunteer_roles', '')}\n\n"
        "Is everything correct?"
    )
    # Add the "Edit Details" button
    interactive = {
        "type": "button",
        "body": {"text": conf_text},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "confirm_reg", "title": "✅ Confirm & Submit"}},
                {"type": "reply", "reply": {"id": "edit_reg_details", "title": "✏️ Edit Details"}},
                {"type": "reply", "reply": {"id": "restart_reg", "title": "❌ Restart"}}
            ]
        }
    }
    services.send_interactive_message(user_id, interactive)

# --- MAIN REGISTRATION HANDLER ---
def handle_registration(user_id, user_profile, message_text):
    """Manages the entire camp registration flow, including edits."""
    step = user_profile.get('registration_step', 'start')
    data = user_profile.setdefault('registration_data', {})
    reg_type = user_profile.get('registration_type', 'annual')
    message_text_lower = message_text.lower().strip()

    # --- START: NEW EDIT FLOW LOGIC ---
    if step == 'awaiting_confirmation' and message_text_lower == 'edit_reg_details':
        rows = [
            {"id": "edit_field_name", "title": "Name (First & Last)"},
            {"id": "edit_field_email", "title": "Email"},
            {"id": "edit_field_phone", "title": "Phone Number"},
            {"id": "edit_field_country", "title": "Country"},
            {"id": "edit_field_dates", "title": "Camp Stay Dates"}
        ]
        interactive = {
            "type": "list", "header": {"type": "text", "text": "Edit Registration"},
            "body": {"text": "Which information would you like to change?"},
            "action": {"button": "Select Field", "sections": [{"title": "Editable Fields", "rows": rows}]}
        }
        services.send_interactive_message(user_id, interactive)
        user_profile['registration_step'] = 'awaiting_field_to_edit'
        return user_profile

    elif step == 'awaiting_field_to_edit' and message_text_lower.startswith('edit_field_'):
        field_to_edit = message_text_lower.replace('edit_field_', '')
        if field_to_edit == 'name':
            services.send_text_message(user_id, "Okay, please enter your full name (First Last).")
            user_profile['registration_step'] = 'awaiting_edit_name'
        elif field_to_edit == 'email':
            services.send_text_message(user_id, "Okay, please enter your new email address.")
            user_profile['registration_step'] = 'awaiting_edit_email'
        elif field_to_edit == 'phone':
            services.send_text_message(user_id, "Okay, please enter your new phone number.")
            user_profile['registration_step'] = 'awaiting_edit_phone'
        elif field_to_edit == 'country':
            services.send_text_message(user_id, "Okay, please enter your new country of residence.")
            user_profile['registration_step'] = 'awaiting_edit_country'
        elif field_to_edit == 'dates':
            services.send_text_message(user_id, "Okay, what is your new *arrival date*? (e.g., Dec 7)")
            user_profile['registration_step'] = 'awaiting_edit_start_date'
        return user_profile

    # -- Handlers for receiving the new, edited information --
    elif step == 'awaiting_edit_name':
        name_parts = message_text.strip().split()
        data['first_name'] = name_parts[0] if name_parts else ""
        data['last_name'] = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        services.send_text_message(user_id, f"✅ Name updated to: {data['first_name']} {data['last_name']}")
        _send_confirmation_message(user_id, data)
        user_profile['registration_step'] = 'awaiting_confirmation'
        return user_profile

    elif step == 'awaiting_edit_email':
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+, message_text.strip()):
            services.send_text_message(user_id, "That doesn't look like a valid email address. Please try again.")
            return user_profile
        data['email'] = message_text.strip()
        services.send_text_message(user_id, f"✅ Email updated to: {data['email']}")
        _send_confirmation_message(user_id, data)
        user_profile['registration_step'] = 'awaiting_confirmation'
        return user_profile

    elif step == 'awaiting_edit_phone':
        if not re.match(r'^\+?\d{9,}, message_text.strip()): # Allow optional +
            services.send_text_message(user_id, "That doesn't look like a valid phone number. Please try again.")
            return user_profile
        data['phone'] = message_text.strip()
        services.send_text_message(user_id, f"✅ Phone updated to: {data['phone']}")
        _send_confirmation_message(user_id, data)
        user_profile['registration_step'] = 'awaiting_confirmation'
        return user_profile

    elif step == 'awaiting_edit_country':
        data['country'] = message_text.strip()
        services.send_text_message(user_id, f"✅ Country updated to: {data['country']}")
        _send_confirmation_message(user_id, data)
        user_profile['registration_step'] = 'awaiting_confirmation'
        return user_profile

    elif step == 'awaiting_edit_start_date':
        data['arrival_date'] = message_text.strip()
        services.send_text_message(user_id, "And your new *departure date*?")
        user_profile['registration_step'] = 'awaiting_edit_end_date'
        return user_profile

    elif step == 'awaiting_edit_end_date':
        data['departure_date'] = message_text.strip()
        services.send_text_message(user_id, f"✅ Camp stay dates updated.")
        _send_confirmation_message(user_id, data)
        user_profile['registration_step'] = 'awaiting_confirmation'
        return user_profile
    # --- END: NEW EDIT FLOW LOGIC ---

    # --- REGULAR FLOW ---
    if step == 'awaiting_confirmation' and message_text_lower == 'restart_reg':
        user_profile.update({'registration_step': 'start', 'registration_data': {}})
        step = 'start'
        data = {}

    if step == 'start':
        camp_name = "Annual Camp"
        services.send_text_message(user_id, f"🏕️ *{camp_name} Registration*\n\nLet's get you registered. First, what is your *Reference*?")
        user_profile['registration_step'] = 'awaiting_reference'

    elif step == 'awaiting_reference':
        data['reference'] = message_text.strip()
        services.send_text_message(user_id, "Great! Now, what is your *first name*?")
        user_profile['registration_step'] = 'awaiting_first_name'

    elif step == 'awaiting_first_name':
        data['first_name'] = message_text.strip()
        services.send_text_message(user_id, "And your *last name*?")
        user_profile['registration_step'] = 'awaiting_last_name'

    elif step == 'awaiting_last_name':
        data['last_name'] = message_text.strip()
        services.send_text_message(user_id, "What is your *email address*?")
        user_profile['registration_step'] = 'awaiting_email'

    elif step == 'awaiting_email':
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+, message_text.strip()):
            services.send_text_message(user_id, "That doesn't look like a valid email address. Please try again.")
            return user_profile
        data['email'] = message_text.strip()
        services.send_text_message(user_id, "What is your *age*?")
        user_profile['registration_step'] = 'awaiting_age'

    elif step == 'awaiting_age':
        if not message_text.strip().isdigit():
            services.send_text_message(user_id, "Please enter a number for your age.")
            return user_profile
        data['age'] = message_text.strip()
        services.send_text_message(user_id, "What is your *gender*? (Male / Female)")
        user_profile['registration_step'] = 'awaiting_gender'

    elif step == 'awaiting_gender':
        gender = message_text.strip().capitalize()
        if gender not in ['Male', 'Female']:
            services.send_text_message(user_id, "Please just answer with *Male* or *Female*.")
        else:
            data['gender'] = gender
            interactive = {"type": "list", "header": {"type": "text", "text": "Select Your Marital Status"}, "body": {"text": "Please select your marital status."}, "action": { "button": "View Statuses", "sections": [{"title": "Statuses", "rows": [{"id": f"marital_{key}", "title": name} for key, name in config.MARITAL_STATUSES.items()]}]}}
            services.send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_marital_status'

    elif step == 'awaiting_marital_status' and message_text_lower.startswith('marital_'):
        marital_key = message_text_lower.replace('marital_', '', 1)
        data['marital_status'] = config.MARITAL_STATUSES.get(marital_key, "N/A")
        services.send_text_message(user_id, "What is your *country of residence*?")
        user_profile['registration_step'] = 'awaiting_country'

    elif step == 'awaiting_country':
        data['country'] = message_text.strip()
        services.send_text_message(user_id, "Please enter your *phone number* (e.g., +263771234567).")
        user_profile['registration_step'] = 'awaiting_phone_number'

    elif step == 'awaiting_phone_number':
        if not re.match(r'^\+?\d{9,}, message_text.strip()):
            services.send_text_message(user_id, "Hmm, that doesn't seem like a valid phone number.")
        else:
            data['phone'] = message_text.strip()
            interactive = {"type": "list", "header": {"type": "text", "text": "Select Your Language"}, "body": {"text": "Please select your preferred language."}, "action": { "button": "View Languages", "sections": [{"title": "Languages", "rows": [{"id": f"lang_{key}", "title": name} for key, name in config.LANGUAGES.items()]}]}}
            services.send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_language'

    elif step == 'awaiting_language' and message_text_lower.startswith('lang_'):
        lang_key = message_text_lower.replace('lang_', '', 1)
        data['language'] = config.LANGUAGES.get(lang_key, "N/A")
        interactive = {"type": "button", "body": {"text": "Do you require transport assistance upon arrival?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "transport_yes", "title": "Yes"}}, {"type": "reply", "reply": {"id": "transport_no", "title": "No"}}]}}
        services.send_interactive_message(user_id, interactive)
        user_profile['registration_step'] = 'awaiting_transport_needed'

    elif step == 'awaiting_transport_needed':
        if not message_text_lower.startswith('transport_'):
            services.send_text_message(user_id, "Please tap *Yes* or *No*.")
        else:
            data['transport_needed'] = "Yes" if message_text_lower == 'transport_yes' else "No"
            interactive = {"type": "list", "header": {"type": "text", "text": "Select Accommodation"}, "body": {"text": "Please select your accommodation preference."}, "action": { "button": "View Options", "sections": [{"title": "Options", "rows": [{"id": f"accom_{key}", "title": name} for key, name in config.ACCOMMODATION_OPTIONS.items()]}]}}
            services.send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_accommodation'

    elif step == 'awaiting_accommodation' and message_text_lower.startswith('accom_'):
        accom_key = message_text_lower.replace('accom_', '', 1)
        data['accommodation'] = config.ACCOMMODATION_OPTIONS.get(accom_key, "N/A")
        interactive = {"type": "list", "header": {"type": "text", "text": "Select Your Role"}, "body": {"text": "Please select your role in the church, if any."}, "action": { "button": "View Roles", "sections": [{"title": "Roles", "rows": [{"id": f"role_{key}", "title": name} for key, name in config.CHURCH_ROLES.items()]}]}}
        services.send_interactive_message(user_id, interactive)
        user_profile['registration_step'] = 'awaiting_worker_status'

    elif step == 'awaiting_worker_status' and message_text_lower.startswith('role_'):
        role_key = message_text_lower.replace('role_', '', 1)
        data['worker_status'] = config.CHURCH_ROLES.get(role_key, "N/A")
        services.send_text_message(user_id, "What is your *arrival date*? (e.g., Dec 7)")
        user_profile['registration_step'] = 'awaiting_arrival_date'

    elif step == 'awaiting_arrival_date':
        data['arrival_date'] = message_text.strip()
        services.send_text_message(user_id, "And your *departure date*?")
        user_profile['registration_step'] = 'awaiting_departure_date'

    elif step == 'awaiting_departure_date':
        data['departure_date'] = message_text.strip()
        services.send_text_message(user_id, "What is your estimated *arrival time*?")
        user_profile['registration_step'] = 'awaiting_arrival_time'

    elif step == 'awaiting_arrival_time':
        data['arrival_time'] = message_text.strip()
        interactive = {"type": "list", "header": {"type": "text", "text": "Select Dietary Requirements"}, "body": {"text": "Please select any dietary requirements."}, "action": { "button": "View Options", "sections": [{"title": "Options", "rows": [{"id": f"diet_{key}", "title": name} for key, name in config.DIETARY_REQUIREMENTS.items()]}]}}
        services.send_interactive_message(user_id, interactive)
        user_profile['registration_step'] = 'awaiting_dietary_requirements'

    elif step == 'awaiting_dietary_requirements' and message_text_lower.startswith('diet_'):
        diet_key = message_text_lower.replace('diet_', '', 1)
        data['dietary_requirements'] = config.DIETARY_REQUIREMENTS.get(diet_key, "N/A")
        services.send_text_message(user_id, "How many *children* will be attending with you? (Enter 0 if none)")
        user_profile['registration_step'] = 'awaiting_children'

    elif step == 'awaiting_children':
        if not message_text.strip().isdigit():
            services.send_text_message(user_id, "Please enter a number (e.g., 0, 1, 2).")
        else:
            data['children'] = message_text.strip()
            interactive = {"type": "list", "header": {"type": "text", "text": "Select Volunteer Role"}, "body": {"text": "Please select a volunteer role, if you are willing."}, "action": { "button": "View Roles", "sections": [{"title": "Roles", "rows": [{"id": f"volunteer_{key}", "title": name} for key, name in config.VOLUNTEER_ROLES.items()]}]}}
            services.send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_volunteer_roles'

    elif step == 'awaiting_volunteer_roles' and message_text_lower.startswith('volunteer_'):
        volunteer_key = message_text_lower.replace('volunteer_', '', 1)
        data['volunteer_roles'] = config.VOLUNTEER_ROLES.get(volunteer_key, "N/A")
        _send_confirmation_message(user_id, data)
        user_profile['registration_step'] = 'awaiting_confirmation'

    # Confirmation and submission
    elif step == 'awaiting_confirmation':
        if message_text_lower == 'confirm_reg':
            data['submitted_at'] = firestore.SERVER_TIMESTAMP
            if services.save_registration(data, reg_type):
                services.send_text_message(user_id, "✅ Registration successful! Your details have been saved.")
            else:
                services.send_text_message(user_id, "⚠️ There was a problem saving your registration. Please contact an admin.")
            services.delete_user_profile(user_id)
            return None # End session

    return user_profile
