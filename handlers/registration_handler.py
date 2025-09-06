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
        f"∙ *Name:* {data.get('first_name', '')} {data.get('last_name', '')}\n"
        f"∙ *Gender:* {data.get('gender', '')}\n"
        f"∙ *Date of Birth:* {data.get('dob', '')} (Age: {data.get('age', 'N/A')})\n"
        f"∙ *ID/Passport:* {data.get('id_passport', '')}\n"
        f"∙ *Phone:* {data.get('phone', '')}\n\n"
        f"∙ *Salvation Status:* {data.get('salvation_status', '')}\n"
        f"∙ *Dependents:* {data.get('dependents', '0')}\n"
        f"∙ *Worker Status:* {data.get('worker_status', 'N/A')}\n\n"
        f"∙ *Volunteering:* {data.get('volunteer_status', '')}"
        f"{' (' + data.get('volunteer_department', '') + ')' if data.get('volunteer_status') == 'Yes' else ''}\n"
        f"∙ *Transport Assistance:* {data.get('transport_assistance', 'No')}\n\n"
        f"∙ *Next of Kin:* {data.get('nok_name', '')} ({data.get('nok_phone', '')})\n"
        f"∙ *Camp Stay:* {data.get('camp_start', '')} to {data.get('camp_end', '')}\n\n"
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
            {"id": "edit_field_phone", "title": "Phone Number"},
            {"id": "edit_field_nok", "title": "Next of Kin Details"},
            {"id": "edit_field_volunteer", "title": "Volunteer Status"},
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
        elif field_to_edit == 'phone':
            services.send_text_message(user_id, "Okay, please enter your new phone number.")
            user_profile['registration_step'] = 'awaiting_edit_phone'
        elif field_to_edit == 'nok':
            services.send_text_message(user_id, "Okay, please enter the new full name for your next of kin.")
            user_profile['registration_step'] = 'awaiting_edit_nok_name'
        elif field_to_edit == 'dates':
            services.send_text_message(user_id, "Okay, what is your new *arrival date*? (e.g., Dec 7)")
            user_profile['registration_step'] = 'awaiting_edit_start_date'
        elif field_to_edit == 'volunteer':
             interactive = {"type": "button", "body": {"text": "Are you willing to assist voluntarily?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "volunteer_yes", "title": "Yes, I'll help"}}, {"type": "reply", "reply": {"id": "volunteer_no", "title": "No, thanks"}}]}}
             services.send_interactive_message(user_id, interactive)
             user_profile['registration_step'] = 'awaiting_volunteer_status' # Re-use existing step
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

    elif step == 'awaiting_edit_phone':
        if not re.match(r'^\+?\d{9,}$', message_text.strip()): # Allow optional +
            services.send_text_message(user_id, "That doesn't look like a valid phone number. Please try again.")
            return user_profile
        data['phone'] = message_text.strip()
        services.send_text_message(user_id, f"✅ Phone updated to: {data['phone']}")
        _send_confirmation_message(user_id, data)
        user_profile['registration_step'] = 'awaiting_confirmation'
        return user_profile
    
    elif step == 'awaiting_edit_nok_name':
        data['nok_name'] = message_text.strip()
        services.send_text_message(user_id, "Got it. And their new phone number?")
        user_profile['registration_step'] = 'awaiting_edit_nok_phone'
        return user_profile

    elif step == 'awaiting_edit_nok_phone':
        data['nok_phone'] = message_text.strip()
        services.send_text_message(user_id, f"✅ Next of Kin updated.")
        _send_confirmation_message(user_id, data)
        user_profile['registration_step'] = 'awaiting_confirmation'
        return user_profile
        
    elif step == 'awaiting_edit_start_date':
        data['camp_start'] = message_text.strip()
        services.send_text_message(user_id, "And your new *departure date*?")
        user_profile['registration_step'] = 'awaiting_edit_end_date'
        return user_profile

    elif step == 'awaiting_edit_end_date':
        data['camp_end'] = message_text.strip()
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
        services.send_text_message(user_id, f"🏕️ *{camp_name} Registration*\n\nLet's get you registered. First, what is your *ID or Passport number*?")
        user_profile['registration_step'] = 'awaiting_id_passport'

    elif step == 'awaiting_id_passport':
        id_passport = message_text.strip()
        if not id_passport:
            services.send_text_message(user_id, "ID/Passport number cannot be empty. Please try again.")
            return user_profile
        services.send_text_message(user_id, f"Checking if `{id_passport}` is already registered...")
        existing_reg = services.check_registration_status(id_passport, reg_type)
        if isinstance(existing_reg, dict):
            reg_name = f"{existing_reg.get('first_name', '')} {existing_reg.get('last_name', '')}"
            services.send_text_message(user_id, f"It looks like you are already registered under the name *{reg_name}*. No need to register again!")
            services.delete_user_profile(user_id)
            return None
        elif existing_reg == "Error":
            services.send_text_message(user_id, "I'm having trouble checking for duplicates right now. Please contact an admin.")
            services.delete_user_profile(user_id)
            return None
        else:
            data['id_passport'] = id_passport
            services.send_text_message(user_id, "Great! Now, what is your *first name*?")
            user_profile['registration_step'] = 'awaiting_first_name'

    elif step == 'awaiting_first_name':
        data['first_name'] = message_text.strip()
        services.send_text_message(user_id, "And your *last name*?")
        user_profile['registration_step'] = 'awaiting_last_name'

    elif step == 'awaiting_last_name':
        data['last_name'] = message_text.strip()
        services.send_text_message(user_id, "Got it. What is your *date of birth*? (DD/MM/YYYY)")
        user_profile['registration_step'] = 'awaiting_dob'

    elif step == 'awaiting_dob':
        age = utils.calculate_age(message_text.strip())
        if not age:
            services.send_text_message(user_id, "That doesn't look right. Please use DD/MM/YYYY format.")
        else:
            data.update({'dob': message_text.strip(), 'age': age})
            services.send_text_message(user_id, "What is your *gender*? (Male / Female)")
            user_profile['registration_step'] = 'awaiting_gender'
            
    elif step == 'awaiting_gender':
        gender = message_text.strip().capitalize()
        if gender not in ['Male', 'Female']:
            services.send_text_message(user_id, "Please just answer with *Male* or *Female*.")
        else:
            data['gender'] = gender
            services.send_text_message(user_id, "Please enter your *phone number* (e.g., +263771234567).")
            user_profile['registration_step'] = 'awaiting_phone_number'

    elif step == 'awaiting_phone_number':
        if not re.match(r'^\+?\d{9,}$', message_text.strip()):
            services.send_text_message(user_id, "Hmm, that doesn't seem like a valid phone number.")
        else:
            data['phone'] = message_text.strip()
            interactive = {"type": "button", "body": {"text": "Are you saved?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "yes", "title": "Yes"}}, {"type": "reply", "reply": {"id": "no", "title": "No"}}]}}
            services.send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_salvation_status'

    elif step == 'awaiting_salvation_status':
        if message_text_lower not in ['yes', 'no']:
            services.send_text_message(user_id, "Please tap *Yes* or *No*.")
        else:
            data['salvation_status'] = message_text.strip().capitalize()
            services.send_text_message(user_id, "How many dependents (e.g., children) will be attending with you? (Enter 0 if none)")
            user_profile['registration_step'] = 'awaiting_dependents'

    elif step == 'awaiting_dependents':
        if not message_text.strip().isdigit():
            services.send_text_message(user_id, "Please enter a number (e.g., 0, 1, 2).")
        else:
            data['dependents'] = message_text.strip()
            interactive = {"type": "list", "header": {"type": "text", "text": "Select Your Role"}, "body": {"text": "Please select your role in the church, if any."}, "action": { "button": "View Roles", "sections": [{"title": "Roles", "rows": [{"id": f"worker_{key}", "title": name} for key, name in config.WORKER_STATUSES.items()]}]}}
            services.send_interactive_message(user_id, interactive)
            user_profile['registration_step'] = 'awaiting_worker_status'

    elif step == 'awaiting_worker_status' and message_text_lower.startswith('worker_'):
        worker_key = message_text_lower.replace('worker_', '', 1)
        data['worker_status'] = config.WORKER_STATUSES.get(worker_key, "N/A")
        services.send_text_message(user_id, "Who is your *next of kin*? (Full name).")
        user_profile['registration_step'] = 'awaiting_nok_name'

    elif step == 'awaiting_nok_name':
        data['nok_name'] = message_text.strip()
        services.send_text_message(user_id, "What is your *next of kin's phone number*?")
        user_profile['registration_step'] = 'awaiting_nok_phone'

    elif step == 'awaiting_nok_phone':
        data['nok_phone'] = message_text.strip()
        camp_dates_text = "Dec 7 to Dec 21, 2025"
        services.send_text_message(user_id, f"The camp runs from {camp_dates_text}.\n\nWhat is your *arrival date*? (e.g., Dec 7)")
        user_profile['registration_step'] = 'awaiting_camp_start_date'

    elif step == 'awaiting_camp_start_date':
        data['camp_start'] = message_text.strip()
        services.send_text_message(user_id, "And your *departure date*?")
        user_profile['registration_step'] = 'awaiting_camp_end_date'

    elif step == 'awaiting_camp_end_date':
        data['camp_end'] = message_text.strip()
        interactive = {"type": "button", "body": {"text": "Are you willing to assist voluntarily?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "volunteer_yes", "title": "Yes, I'll help"}}, {"type": "reply", "reply": {"id": "volunteer_no", "title": "No, thanks"}}]}}
        services.send_interactive_message(user_id, interactive)
        user_profile['registration_step'] = 'awaiting_volunteer_status'

    elif step == 'awaiting_volunteer_status':
        if not message_text_lower.startswith('volunteer_'):
            services.send_text_message(user_id, "Please tap one of the buttons.")
        else:
            is_volunteering = message_text_lower == 'volunteer_yes'
            data['volunteer_status'] = "Yes" if is_volunteering else "No"
            if is_volunteering:
                interactive = { "type": "list", "header": {"type": "text", "text": "Select Department"}, "body": {"text": "Wonderful! Please choose a department to help in."}, "action": { "button": "View Departments", "sections": [{"title": "Departments", "rows": [{"id": f"dept_{key}", "title": name} for key, name in config.DEPARTMENTS.items()]}]}}
                services.send_interactive_message(user_id, interactive)
                user_profile['registration_step'] = 'awaiting_volunteer_department'
            else:
                data['volunteer_department'] = 'N/A'
                interactive = {"type": "button", "body": {"text": "Do you require transport assistance upon arrival?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "transport_yes", "title": "Yes"}}, {"type": "reply", "reply": {"id": "transport_no", "title": "No"}}]}}
                services.send_interactive_message(user_id, interactive)
                user_profile['registration_step'] = 'awaiting_transport_assistance'

    elif step == 'awaiting_volunteer_department' and message_text_lower.startswith('dept_'):
        dept_key = message_text_lower.replace('dept_', '', 1)
        data['volunteer_department'] = config.DEPARTMENTS.get(dept_key)
        interactive = {"type": "button", "body": {"text": "Do you require transport assistance upon arrival?"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "transport_yes", "title": "Yes"}}, {"type": "reply", "reply": {"id": "transport_no", "title": "No"}}]}}
        services.send_interactive_message(user_id, interactive)
        user_profile['registration_step'] = 'awaiting_transport_assistance'

    elif step == 'awaiting_transport_assistance':
        if not message_text_lower.startswith('transport_'):
            services.send_text_message(user_id, "Please tap *Yes* or *No*.")
        else:
            data['transport_assistance'] = "Yes" if message_text_lower == 'transport_yes' else "No"
            _send_confirmation_message(user_id, data)
            user_profile['registration_step'] = 'awaiting_confirmation'

    # Confirmation and submission
    elif step == 'awaiting_confirmation':
        if message_text_lower == 'confirm_reg':
            if services.save_registration(data, reg_type):
                services.send_text_message(user_id, "✅ Registration successful! Your details have been saved.")
            else:
                services.send_text_message(user_id, "⚠️ There was a problem saving your registration. Please contact an admin.")
            services.delete_user_profile(user_id)
            return None # End session
            
    return user_profile
