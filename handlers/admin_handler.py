# handlers/admin_handler.py

import services
import config

def handle_export(user_id, message_text):
    """Handles the 'export' command for admins."""
    parts = message_text.lower().split()
    if len(parts) == 2 and parts[1] in ['youths', 'annual']:
        camp_type = parts[1]
        services.send_text_message(user_id, f"Okay, starting export for *{camp_type} camp*. This may take a moment...")
        result = services.export_registrations_to_sheet(camp_type)
        services.send_text_message(user_id, result)
    else:
        services.send_text_message(user_id, "Invalid export command. Use `export youths` or `export annual`.")

def handle_check_status(user_id, user_profile, message_text):
    """Manages the registration status check flow for users."""
    step = user_profile.get('check_step', 'start')
    message_text_lower = message_text.lower().strip()

    if step == 'start':
        interactive = {
            "type": "button",
            "body": {"text": "Which camp registration would you like to check?"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "check_youths", "title": "Youths Camp"}},
                    {"type": "reply", "reply": {"id": "check_annual", "title": "Annual Camp"}}
                ]
            }
        }
        services.send_interactive_message(user_id, interactive)
        user_profile['check_step'] = 'awaiting_camp_choice'

    elif step == 'awaiting_camp_choice' and message_text_lower.startswith('check_'):
        camp_type = message_text_lower.replace('check_', '', 1)
        user_profile['camp_to_check'] = camp_type
        services.send_text_message(user_id, "Got it. Please enter the *ID/Passport Number* you used to register.")
        user_profile['check_step'] = 'awaiting_identifier'

    elif step == 'awaiting_identifier':
        identifier = message_text.strip()
        camp_type = user_profile.get('camp_to_check')
        services.send_text_message(user_id, f"Checking for '{identifier}'...")
        status = services.check_registration_status(identifier, camp_type)

        if status == "Error":
            services.send_text_message(user_id, "Sorry, a technical error occurred. Please try again later.")
        elif isinstance(status, dict):
            confirm_msg = (
                f"✅ *Registration Found!* ✅\n\n"
                f"Hi *{status.get('first_name', '')} {status.get('last_name', '')}*!\n"
                f"Your registration is confirmed.\n\n"
                f"*ID/Passport:* {status.get('id_passport', '')}\n"
                f"*Phone:* {status.get('phone', '')}"
            )
            services.send_text_message(user_id, confirm_msg)
        else:
            services.send_text_message(user_id, f"❌ *No Registration Found*\n\nI could not find a registration matching '{identifier}'.")
        
        # This flow is complete, signal to router to end the session
        services.delete_user_profile(user_id)
        return None

    return user_profile