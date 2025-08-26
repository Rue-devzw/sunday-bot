# utils.py
import json
import re
from datetime import datetime, date
from dateutil.relativedelta import relativedelta, MO
import config

def calculate_age(dob_string):
    """Calculates age from a DD/MM/YYYY string."""
    try:
        birth_date = datetime.strptime(dob_string, "%d/%m/%Y").date()
        today = date.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    except ValueError:
        return None

def load_json_file(file_path):
    """Loads a JSON file safely."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"DEBUG: Error loading static JSON file '{file_path}': {e}")
        return None

def get_current_lesson_index(user_class):
    """Calculates the current lesson index based on the week number."""
    today = date.today()
    anchor = config.PRIMARY_PALS_ANCHOR_DATE if user_class == "Primary Pals" else config.ANCHOR_DATE
    anchor_week_start = anchor + relativedelta(weekday=MO(-1))
    current_week_start = today + relativedelta(weekday=MO(-1))
    week_diff = (current_week_start - anchor_week_start).days // 7
    return week_diff if week_diff >= 0 else -1

def linkify_bible_verses(text):
    """Wraps Bible references in text with markdown for quick lookups."""
    if not text or not isinstance(text, str):
        return text
    bible_books = [
        "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth",
        "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
        "Nehemiah", "Esther", "Job", "Psalm", "Proverbs", "Ecclesiastes", "Song of Solomon",
        "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
        "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah",
        "Malachi", "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
        "2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians", "1 Thessalonians",
        "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews", "James",
        "1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude", "Revelation"
    ]
    books_pattern = "|".join(bible_books).replace(" ", r"\s")
    pattern = re.compile(fr'\b({books_pattern})\s+(\d+:\d+(?:-\d+)?)\b', re.IGNORECASE)
    def repl(match):
        return f"`bible {match.group(0)}`"
    return pattern.sub(repl, text)

def format_hymn(hymn):
    """Formats hymn data into a user-friendly string."""
    if not hymn: return "Sorry, I couldn't find a hymn with that number."
    title, hymn_number = hymn.get('title', 'No Title'), hymn.get('number', '#')
    message = f"🎶 *Hymn #{hymn_number}: {title}*\n\n"
    verses, chorus, parts = hymn.get('verses', []), hymn.get('chorus', []), hymn.get('parts', [])
    chorus_text = "*Chorus:*\n" + "\n".join(chorus) + "\n\n" if chorus else ""
    if verses:
        for i, verse_lines in enumerate(verses, 1):
            message += f"*{i}.*\n" + "\n".join(verse_lines) + "\n\n"
            if chorus_text: message += chorus_text
    elif chorus_text: message += chorus_text
    if parts:
        for part in parts:
            part_num = part.get('part', '')
            message += f"*{f'Part {part_num}' if part_num else 'Part'}*\n"
            for i, v_lines in enumerate(part.get('verses', []), 1):
                message += f"*{i}.*\n" + "\n".join(v_lines) + "\n\n"
    return message.strip()

def format_lesson(lesson, lesson_class):
    """Formats lesson data into a user-friendly string."""
    if not lesson: return "Lesson details could not be found."
    message_parts = []
    # (The entire logic of format_lesson is moved here)
    if lesson_class == "Search":
        title = lesson.get('lessonTitle', 'No Title')
        message_parts.append(f"📖 *{title}*")
        # ... rest of Search formatting
    elif lesson_class == "Primary Pals":
        title = lesson.get('title', 'No Title')
        message_parts.append(f"🎨 *{title}*")
        # ... rest of Primary Pals formatting
    else: # For Beginners and Answer classes
        title = lesson.get('title', 'No Title')
        # ... rest of other formatting
    return "\n\n".join(message_parts)