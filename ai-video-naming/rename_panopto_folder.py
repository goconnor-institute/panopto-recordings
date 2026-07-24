#!/usr/bin/env python3
"""
Panopto Session Renamer
-----------------------
Paste a Panopto folder link to rename all sessions with AI-generated topics.

Format: [Week X] AI Topic | DD/MM/YYYY HH:MM AM/PM

Dates are extracted from (in order of priority):
1. StartTime field (API)
2. Description field (Recording Start: pattern)
3. Session name (DD/MM/YYYY - HH:MM AM/PM pattern)

Week numbers are determined from the schedule Excel file.
"""

import requests
import json
import os
import re
from datetime import datetime, timedelta
import base64
from urllib.parse import unquote
from dotenv import load_dotenv
from openai import OpenAI
import pandas as pd
import argparse
import sys

PROMPT = """Analyze this class transcript from a second-level institution in Ireland, focused on the Junior/Leaving Certificate curriculum, and provide a concise topic title (3-6 words) that captures the main subject matter. 
Focus on the specific educational content being taught.
Make sure to take into account the entire context of the transcript rather than just the first few minutes of the class as there may be introductions / administrative details at the start.
IMPORTANT: Don't state the year group or Leaving/Junior Cert in the title unless you are extremely confident you are correct.
Return ONLY the topic title, nothing else."""

load_dotenv(override=True)

# Configuration (loaded from .env)
PANOPTO_SERVER = os.getenv("PANOPTO_SERVER", "")
PANOPTO_CLIENT_ID = os.getenv("PANOPTO_CLIENT_ID", "")
PANOPTO_CLIENT_SECRET = os.getenv("PANOPTO_CLIENT_SECRET", "")
TOKEN_FILE = os.getenv("TOKEN_FILE", "panopto_tokens.json")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "rename_output")
SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "Eve-Sat 25-26  Weekly Schedule.xlsx")

def load_week_schedule():
    """Load week schedule from Excel file"""
    if not os.path.exists(SCHEDULE_FILE):
        print(f"⚠️ Schedule file not found: {SCHEDULE_FILE}")
        return []
    
    df = pd.read_excel(SCHEDULE_FILE, header=None)
    weeks = []
    
    for _, row in df.iterrows():
        week_num = row[0]
        start_date = row[2]
        end_date = row[4]
        
        # Only process rows with numeric week numbers
        if isinstance(week_num, (int, float)) and not pd.isna(week_num):
            try:
                week_num = int(week_num)
                if isinstance(start_date, pd.Timestamp) and isinstance(end_date, pd.Timestamp):
                    weeks.append({
                        'week': week_num,
                        'start': start_date.date(),
                        'end': end_date.date()
                    })
            except:
                pass
    
    return weeks

def get_week_number(recording_date, weeks):
    """Get week number for a recording date"""
    if not recording_date or not weeks:
        return None
    
    # Parse the date string (DD/MM/YYYY or DD/MM/YYYY HH:MM AM/PM)
    try:
        date_part = recording_date.split()[0]  # Get just the date part
        parts = date_part.split('/')
        rec_date = datetime(int(parts[2]), int(parts[1]), int(parts[0])).date()
        
        for week in weeks:
            if week['start'] <= rec_date <= week['end']:
                return week['week']
    except Exception as e:
        pass
    
    return None

def extract_folder_id(url_or_id):
    """Extract folder ID from Panopto URL or return as-is if already an ID"""
    # Already a GUID?
    if re.match(r'^[a-f0-9-]{36}$', url_or_id, re.IGNORECASE):
        return url_or_id
    
    # Try to extract from URL
    # Format: ...#folderID="xxx" or ...#folderID=%22xxx%22
    match = re.search(r'folderID[=%22"]+([a-f0-9-]{36})', url_or_id, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Try query param: ?folderID=xxx
    match = re.search(r'[?&]folderID=([a-f0-9-]{36})', url_or_id, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return None

def get_auth_token():
    """Get a valid access token, refreshing if needed"""
    if not os.path.exists(TOKEN_FILE):
        print("❌ No token file found. Run the main sync script first to authenticate.")
        return None
    
    with open(TOKEN_FILE, 'r') as f:
        token_data = json.load(f)
    
    try:
        expires_at = datetime.fromisoformat(token_data['expires_at'])
        if datetime.now() < expires_at:
            return token_data['access_token']
    except:
        pass
    
    # Refresh token
    token_url = f"https://{PANOPTO_SERVER}/Panopto/oauth2/connect/token"
    data = {'grant_type': 'refresh_token', 'refresh_token': token_data['refresh_token']}
    credentials = f"{PANOPTO_CLIENT_ID}:{PANOPTO_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': f'Basic {encoded_credentials}'}
    
    response = requests.post(token_url, data=data, headers=headers, timeout=30)
    if response.status_code == 200:
        new_token_data = response.json()
        access_token = new_token_data['access_token']
        
        save_data = {
            'access_token': access_token,
            'refresh_token': new_token_data.get('refresh_token', token_data['refresh_token']),
            'expires_at': (datetime.now() + timedelta(seconds=new_token_data.get('expires_in', 3600) - 300)).isoformat(),
            'created_at': datetime.now().isoformat()
        }
        with open(TOKEN_FILE, 'w') as f:
            json.dump(save_data, f, indent=2)
        
        return access_token
    
    print(f"❌ Token refresh failed: {response.status_code}")
    return None

def get_legacy_auth_cookie(auth_token):
    """Get legacy auth cookie for caption downloads"""
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/auth/legacyLogin"
    headers = {"Authorization": f"Bearer {auth_token}"}
    
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200 and '.ASPXAUTH' in response.cookies:
        return response.cookies
    return None

def get_folder_info(auth_token, folder_id):
    """Get folder name"""
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/folders/{folder_id}"
    headers = {"Authorization": f"Bearer {auth_token}"}
    
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        return response.json()
    return None

def get_sessions_in_folder(auth_token, folder_id):
    """Get all sessions in a folder"""
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/folders/{folder_id}/sessions"
    headers = {"Authorization": f"Bearer {auth_token}"}
    params = {"sortField": "CreatedDate", "sortOrder": "Desc", "pageSize": 100}
    
    response = requests.get(url, headers=headers, params=params, timeout=30)
    if response.status_code == 200:
        return response.json().get("Results", [])
    return []

def get_session_details(auth_token, session_id):
    """Get full session details"""
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {auth_token}"}
    
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        return response.json()
    return None

def download_captions(auth_token, cookies, session_id):
    """Download captions for a session"""
    details = get_session_details(auth_token, session_id)
    if not details:
        return None
    
    caption_url = details.get("Urls", {}).get("CaptionDownloadUrl")
    if not caption_url:
        return None
    
    response = requests.get(caption_url, cookies=cookies, timeout=60)
    if response.status_code == 200:
        return response.text
    return None

def clean_caption_text(vtt_content):
    """Extract plain text from VTT captions"""
    lines = vtt_content.split('\n')
    text_lines = []
    
    for line in lines:
        line = line.strip()
        if not line or line == 'WEBVTT' or '-->' in line or line.isdigit():
            continue
        clean = re.sub(r'<[^>]+>', '', line)
        if clean:
            text_lines.append(clean)
    
    return ' '.join(text_lines)

def _try_ai_provider(provider_name, client, model, prompt, max_retries):
    """Attempt to generate a topic from a single provider, with rate-limit retries.
    Returns the topic string on success, or None if this provider failed outright."""
    import time

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.3
            )
            return response.choices[0].message.content.strip().strip('"')
        except Exception as e:
            error_msg = str(e)
            if "Too many requests" in error_msg or "429" in error_msg:
                wait_time = (attempt + 1) * 10  # 10s, 20s, 30s
                if attempt < max_retries - 1:
                    print(f"  ⏳ [{provider_name}] Rate limited, waiting {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"  ⚠️ [{provider_name}] AI error after {max_retries} retries: Rate limit exceeded")
                    return None
            else:
                print(f"  ⚠️ [{provider_name}] AI error: {e}")
                return None
    return None


def generate_ai_topic(caption_text, max_retries=3):
    """Generate AI topic from captions. Tries OpenAI first, falling back to
    GitHub Models if OpenAI isn't configured or fails."""
    openai_api_key = os.getenv("OPENAI_APIKEY")
    github_token = os.getenv("GITHUB_TOKEN")

    providers = []
    if openai_api_key:
        providers.append(("OpenAI", OpenAI(api_key=openai_api_key), "gpt-4.1-mini"))
    if github_token:
        providers.append((
            "GitHub Models",
            OpenAI(base_url="https://models.github.ai/inference", api_key=github_token),
            "openai/gpt-4.1-mini",
        ))

    if not providers:
        print("  ⚠️ No OPENAI_APIKEY or GITHUB_TOKEN in environment")
        return None

    # Limit text length
    max_chars = 15000
    if len(caption_text) > max_chars:
        caption_text = caption_text[:max_chars] + "..."

    prompt = PROMPT + f"""

    Transcript:
    {caption_text}

    """

    for i, (provider_name, client, model) in enumerate(providers):
        topic = _try_ai_provider(provider_name, client, model, prompt, max_retries)
        if topic:
            return topic
        is_last = i == len(providers) - 1
        print("  ⚠️ All AI providers failed" if is_last else f"  ↪️ Falling back from {provider_name}...")

    return None

def extract_date_from_starttime(start_time):
    """Extract date/time from StartTime field (ISO format)"""
    if not start_time:
        return None
    
    try:
        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        return dt.strftime("%d/%m/%Y %I:%M %p")
    except:
        return None

def extract_date_from_description(description):
    """Extract date and time from session description"""
    if not description:
        return None
    
    # Format: "Recording Start: DD/MM/YYYY @ H:MM PM" or "Recording Start: DD/MM/YYYY HH:MM:SS"
    match = re.search(r'Recording Start:\s*(\d{1,2}/\d{1,2}/\d{4})\s*[@\s]+(\d{1,2}:\d{2}(?::\d{2})?\s*[AP]?M?)', description, re.IGNORECASE)
    if match:
        date = match.group(1)
        time_part = match.group(2).strip()
        
        # If already has AM/PM, use as-is
        if re.search(r'[AP]M', time_part, re.IGNORECASE):
            return f"{date} {time_part}"
        
        # Convert 24h to 12h format
        try:
            parts = time_part.replace(':', ' ').split()
            t = datetime.strptime(f"{parts[0]}:{parts[1]}", '%H:%M')
            time_12h = t.strftime('%I:%M %p')
            return f"{date} {time_12h}"
        except:
            return date
    
    # Try just date
    match = re.search(r'Recording Start:\s*(\d{1,2}/\d{1,2}/\d{4})', description)
    if match:
        return match.group(1)
    
    return None

def extract_date_from_name(name):
    """Extract date/time from session name like '... - 10/01/2026 - 12:00 PM'"""
    # Pattern: DD/MM/YYYY - HH:MM AM/PM
    match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)', name, re.IGNORECASE)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    
    # Just date: DD/MM/YYYY
    match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', name)
    if match:
        return match.group(1)
    
    return None

def get_best_date(details, session_name, session_list_data=None):
    """Get the best available date from multiple sources"""
    # Priority 1: StartTime from session list (more reliable than details endpoint)
    if session_list_data:
        date = extract_date_from_starttime(session_list_data.get("StartTime"))
        if date:
            return date, "StartTime (list)"
    
    # Priority 2: StartTime from details API
    if details:
        date = extract_date_from_starttime(details.get("StartTime"))
        if date:
            return date, "StartTime"
    
    # Priority 3: Description field
    if details:
        date = extract_date_from_description(details.get("Description", ""))
        if date:
            return date, "Description"
    
    # Priority 4: Session name itself
    date = extract_date_from_name(session_name)
    if date:
        return date, "Name"
    
    return "Unknown", None

def extract_base_name(name):
    """Extract the base name without date/time and without our formatting"""
    # Remove our [date] prefix if present
    name = re.sub(r'^\[.*?\]\s*', '', name)
    
    # Remove | AI topic suffix if present
    name = re.sub(r'\s*\|.*$', '', name)
    
    # Remove date/time suffix like "- 10/01/2026 - 12:00 PM"
    name = re.sub(r'\s*-\s*\d{1,2}/\d{1,2}/\d{4}\s*(-\s*\d{1,2}:\d{2}\s*[AP]M)?\s*$', '', name, flags=re.IGNORECASE)
    
    return name.strip()

def rename_session(auth_token, session_id, new_name):
    """Rename a session via API"""
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    
    response = requests.put(url, headers=headers, json={"Name": new_name}, timeout=30)
    return response.status_code == 200

def main():
    parser = argparse.ArgumentParser(description='Rename Panopto sessions with AI-generated topics')
    parser.add_argument('--force', '-f', action='store_true', 
                        help='Force re-rename sessions that were already renamed')
    parser.add_argument('--use-week-nums', '-w', action='store_true',
                        help='Look up week numbers from schedule (default: use date only)')
    parser.add_argument('--non-interactive', '-n', action='store_true',
                        help='Skip confirmation prompts (for automation)')
    parser.add_argument('--same-day-same-topic', '-s', action='store_true',
                        help='Reuse AI topic for all recordings on the same date')
    parser.add_argument('--max-days', '-m', type=int, default=None,
                        help='Reset day counter after this many days (for repeated course deliveries)')
    parser.add_argument('--folder-url', '-u', type=str,
                        help='Panopto folder URL or ID')
    parser.add_argument('folder', nargs='?', help='Panopto folder URL or ID (optional, will prompt if not provided)')
    args = parser.parse_args()
    
    force_rename = args.force
    use_week_nums = args.use_week_nums
    non_interactive = args.non_interactive
    same_day_same_topic = args.same_day_same_topic
    
    print("=" * 70)
    print("🎬 PANOPTO SESSION RENAMER")
    if force_rename:
        print("🔄 FORCE MODE: Will re-rename already processed sessions")
    if use_week_nums:
        print("📆 WEEK MODE: Will look up week numbers from schedule")
    else:
        print("📅 DATE MODE: Will use date only (no week numbers)")
    if same_day_same_topic:
        max_days_msg = f" (resets every {args.max_days} days)" if args.max_days else ""
        print(f"🔁 SAME-DAY MODE: Reusing AI topic for recordings on the same date{max_days_msg}")
    if non_interactive:
        print("🤖 NON-INTERACTIVE: Skipping confirmation prompts")
    print("=" * 70)
    
    # Get folder input from --folder-url, positional arg, or prompt
    if args.folder_url:
        user_input = args.folder_url
    elif args.folder:
        user_input = args.folder
    elif non_interactive:
        print("❌ No folder provided in non-interactive mode")
        return
    else:
        print("\nPaste a Panopto folder link or folder ID:")
        user_input = input("> ").strip()
    
    if not user_input:
        print("❌ No input provided")
        return
    
    folder_id = extract_folder_id(user_input)
    if not folder_id:
        print(f"❌ Could not extract folder ID from: {user_input}")
        return
    
    print(f"\n📂 Folder ID: {folder_id}")
    
    # Authenticate
    auth_token = get_auth_token()
    if not auth_token:
        sys.exit(1)
    print("✅ Authenticated")
    
    # Get folder info
    folder_info = get_folder_info(auth_token, folder_id)
    if folder_info:
        print(f"📁 Folder: {folder_info.get('Name', 'Unknown')}")
    
    # Get legacy auth for captions
    cookies = get_legacy_auth_cookie(auth_token)
    if not cookies:
        print("⚠️ Could not get legacy auth - captions may fail")
    
    # Load week schedule (only if using week numbers)
    weeks = []
    if use_week_nums:
        weeks = load_week_schedule()
        if weeks:
            print(f"📅 Loaded {len(weeks)} weeks from schedule")
        else:
            print("⚠️ No week schedule loaded - will fall back to date format")
    
    # Get sessions
    sessions = get_sessions_in_folder(auth_token, folder_id)
    print(f"📹 Found {len(sessions)} sessions")
    
    if not sessions:
        print("❌ No sessions found")
        sys.exit(1)
    
    # Confirm
    if non_interactive:
        print(f"\n✅ Processing {len(sessions)} sessions (non-interactive)...")
    else:
        print(f"\n⚠️  This will rename all {len(sessions)} sessions.")
        confirm = input("Continue? (y/n): ").strip().lower()
        if confirm != 'y':
            print("❌ Cancelled")
            return
    
    # Create output directory if needed
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = {
        "folder_id": folder_id,
        "timestamp": timestamp,
        "sessions": [{"id": s["Id"], "name": s["Name"]} for s in sessions]
    }
    backup_file = os.path.join(OUTPUT_DIR, f"session_backup_{folder_id[:8]}_{timestamp}.json")
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(backup, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Backup saved: {backup_file}")
    
    # Pre-compute day numbers if using same-day-same-topic
    day_numbers = {}  # date_key -> day number
    cycle_numbers = {}  # date_key -> cycle (week) number (only with --max-days)
    if same_day_same_topic:
        all_date_keys = set()
        for s in sessions:
            d, _ = get_best_date(None, s["Name"], s)
            if d and d != "Unknown":
                all_date_keys.add(d.split()[0])
        # Parse and sort dates chronologically
        def parse_date_key(dk):
            parts = dk.split('/')
            return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
        sorted_dates = sorted(all_date_keys, key=parse_date_key)
        max_days = args.max_days
        if max_days:
            day_numbers = {dk: (idx % max_days) + 1 for idx, dk in enumerate(sorted_dates)}
            cycle_numbers = {dk: (idx // max_days) + 1 for idx, dk in enumerate(sorted_dates)}
        else:
            day_numbers = {dk: idx + 1 for idx, dk in enumerate(sorted_dates)}
        if day_numbers:
            print(f"📆 Computed {len(day_numbers)} day numbers from session dates")
    
    # Process each session
    results = []
    moodle_data = {}
    week_topics = {}  # Cache AI topics by week number
    date_topics = {}  # Cache AI topics by date (for --same-day-same-topic)
    day_topics = {}  # Cache AI topics by day number (for --max-days cross-cycle reuse)
    fallback_sessions = []  # Sessions that used base_name fallback (for same-day fixup)
    
    for i, session in enumerate(sessions):
        session_id = session["Id"]
        current_name = session["Name"]
        
        print(f"\n[{i+1}/{len(sessions)}] {current_name[:50]}...")
        
        # Check if already renamed (has our format - date, Week, or Day format)
        if not force_rename and re.match(r'^\[(Week \d+|Day \d+|\d{1,2}/\d{1,2}/\d{4}).*?\].*\|', current_name):
            print("  ⏭️ Already renamed, skipping (use --force to re-rename)")
            # Still extract topic from existing name to populate caches for reuse
            pipe_match = re.match(r'^\[.*?\]\s*(.+?)\s*\|\s*(.+)$', current_name)
            if pipe_match:
                existing_topic = pipe_match.group(1).strip()
                existing_date_str = pipe_match.group(2).strip()
                existing_date_key = existing_date_str.split()[0] if existing_date_str else None
                # Populate date_topics cache
                if same_day_same_topic and existing_date_key and existing_date_key not in date_topics:
                    date_topics[existing_date_key] = existing_topic
                # Populate day_topics cache
                if same_day_same_topic and existing_date_key:
                    existing_day_num = day_numbers.get(existing_date_key)
                    if existing_day_num and existing_day_num not in day_topics:
                        day_topics[existing_day_num] = existing_topic
                # Populate week_topics cache
                if use_week_nums and existing_date_key:
                    existing_week = get_week_number(existing_date_str, weeks)
                    if existing_week and existing_week not in week_topics:
                        week_topics[existing_week] = existing_topic
            continue
        
        # If forcing, extract the original date from the existing format
        if force_rename and re.match(r'^\[', current_name):
            print("  🔄 Force mode: re-processing...")
        
        # Get full details
        details = get_session_details(auth_token, session_id)
        
        # Get best date (pass session list data which has StartTime)
        date_str, date_source = get_best_date(details, current_name, session)
        if date_source:
            print(f"  📅 Date: {date_str} (from {date_source})")
        else:
            print(f"  ⚠️ No date found")
        
        # Extract base name
        base_name = extract_base_name(current_name)
        
        # Get week number early (needed to check cache)
        week_num = None
        if use_week_nums:
            week_num = get_week_number(date_str, weeks)
            if week_num:
                print(f"  📆 Week {week_num}")
        
        # Extract just the date part for same-day caching
        date_key = date_str.split()[0] if date_str and date_str != "Unknown" else None
        
        # Check if we already have an AI topic for this day number, date, or week
        ai_topic = None
        day_num = day_numbers.get(date_key) if same_day_same_topic and date_key else None
        if same_day_same_topic and day_num and day_num in day_topics:
            ai_topic = day_topics[day_num]
            print(f"  ♻️ Reusing AI topic from Day {day_num}: {ai_topic}")
        elif same_day_same_topic and date_key and date_key in date_topics:
            ai_topic = date_topics[date_key]
            print(f"  ♻️ Reusing AI topic from {date_key}: {ai_topic}")
        elif week_num and week_num in week_topics:
            ai_topic = week_topics[week_num]
            print(f"  ♻️ Reusing AI topic from Week {week_num}: {ai_topic}")
        elif cookies:
            # Download and process captions for AI topic
            captions = download_captions(auth_token, cookies, session_id)
            if captions:
                clean_text = clean_caption_text(captions)
                word_count = len(clean_text.split())
                print(f"  📝 Captions: {word_count} words")
                
                if word_count > 100:
                    ai_topic = generate_ai_topic(clean_text)
                    if ai_topic:
                        print(f"  🤖 AI Topic: {ai_topic}")
                        # Cache the topic for this week and/or date/day
                        if week_num:
                            week_topics[week_num] = ai_topic
                        if same_day_same_topic and date_key:
                            date_topics[date_key] = ai_topic
                        if same_day_same_topic and day_num:
                            day_topics[day_num] = ai_topic
        
        if not ai_topic:
            ai_topic = base_name
            used_fallback = True
            print(f"  ⚠️ No AI topic - using original name")
        else:
            used_fallback = False
            # Only delay if we actually made a new AI call (not cached)
            if week_num not in week_topics:
                import time
                time.sleep(2)
        
        # Build new name
        cycle_num = cycle_numbers.get(date_key) if date_key else None
        if week_num:
            new_name = f"[Week {week_num}] {ai_topic} | {date_str}"
        elif day_num and cycle_num:
            new_name = f"[Week {cycle_num} \u00b7 Day {day_num}] {ai_topic} | {date_str}"
        elif day_num:
            new_name = f"[Day {day_num}] {ai_topic} | {date_str}"
        else:
            new_name = f"[{date_str}] {ai_topic} | {base_name}"
        
        # Rename
        if rename_session(auth_token, session_id, new_name):
            print(f"  ✅ Renamed!")
            results.append({
                "session_id": session_id,
                "original_name": current_name,
                "new_name": new_name,
                "date": date_str,
                "date_source": date_source,
                "week": week_num,
                "ai_topic": ai_topic,
                "success": True
            })
            
            # Track fallback sessions for same-day fixup
            if same_day_same_topic and used_fallback and date_key:
                fallback_sessions.append({
                    "session_id": session_id,
                    "date_key": date_key,
                    "date_str": date_str,
                    "week_num": week_num,
                    "base_name": base_name,
                    "results_idx": len(results) - 1
                })
            
            moodle_data[session_id] = {
                "date": date_str,
                "week": week_num,
                "original": base_name,
                "topic": ai_topic
            }
        else:
            print(f"  ❌ Rename failed")
            results.append({
                "session_id": session_id,
                "original_name": current_name,
                "success": False
            })
    
    # Same-day fixup pass: re-rename fallback sessions that now have a cached topic
    if same_day_same_topic and fallback_sessions:
        def get_fixup_topic(fb):
            if fb["date_key"] in date_topics:
                return date_topics[fb["date_key"]]
            day_num = day_numbers.get(fb["date_key"])
            if day_num and day_num in day_topics:
                return day_topics[day_num]
            return None
        fixup_candidates = [(fb, get_fixup_topic(fb)) for fb in fallback_sessions]
        fixup_candidates = [(fb, t) for fb, t in fixup_candidates if t]
        if fixup_candidates:
            print(f"\n🔁 Same-day fixup: {len(fixup_candidates)} session(s) to update with sibling AI topic")
            for fb, ai_topic in fixup_candidates:
                day_num = day_numbers.get(fb["date_key"])
                cycle_num = cycle_numbers.get(fb["date_key"])
                if fb["week_num"]:
                    new_name = f"[Week {fb['week_num']}] {ai_topic} | {fb['date_str']}"
                elif day_num and cycle_num:
                    new_name = f"[Week {cycle_num} \u00b7 Day {day_num}] {ai_topic} | {fb['date_str']}"
                elif day_num:
                    new_name = f"[Day {day_num}] {ai_topic} | {fb['date_str']}"
                else:
                    new_name = f"[{fb['date_str']}] {ai_topic} | {fb['base_name']}"
                
                if rename_session(auth_token, fb["session_id"], new_name):
                    print(f"  ✅ Fixed: {new_name[:60]}...")
                    results[fb["results_idx"]]["new_name"] = new_name
                    results[fb["results_idx"]]["ai_topic"] = ai_topic
                    if fb["session_id"] in moodle_data:
                        moodle_data[fb["session_id"]]["topic"] = ai_topic
                else:
                    print(f"  ❌ Fixup rename failed for {fb['session_id']}")
    
    # Save results
    results_file = os.path.join(OUTPUT_DIR, f"rename_results_{folder_id[:8]}_{timestamp}.json")
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump({
            "folder_id": folder_id,
            "timestamp": timestamp,
            "sessions": results
        }, f, indent=2, ensure_ascii=False)
    print(f"\n📊 Results saved: {results_file}")
    
    # Update Moodle metadata
    moodle_file = os.path.join(OUTPUT_DIR, "panopto_session_metadata.json")
    existing_moodle = {}
    if os.path.exists(moodle_file):
        with open(moodle_file, 'r', encoding='utf-8') as f:
            existing_moodle = json.load(f)
    existing_moodle.update(moodle_data)
    with open(moodle_file, 'w', encoding='utf-8') as f:
        json.dump(existing_moodle, f, indent=2, ensure_ascii=False)
    print(f"📋 Moodle metadata updated: {moodle_file}")
    
    # Summary
    success_count = sum(1 for r in results if r.get("success"))
    print(f"\n{'=' * 70}")
    print(f"✅ Successfully renamed: {success_count}/{len(results)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
