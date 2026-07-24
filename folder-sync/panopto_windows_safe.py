#!/usr/bin/env python3
"""
Panopto Folder Synchronization Script with Automatic Token Refresh
Uses OAuth2 with refresh tokens for automated, unattended operation
"""

import requests
import pandas as pd
import logging
from datetime import datetime, timedelta
import sys
import base64
import secrets
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email_template_builder import build_html_report, build_plain_text_report
from dotenv import load_dotenv

load_dotenv(override=True)

# Configuration
PANOPTO_SERVER = os.getenv("PANOPTO_SERVER", "")
PANOPTO_CLIENT_ID = os.getenv("PANOPTO_CLIENT_ID", "")
PANOPTO_CLIENT_SECRET = os.getenv("PANOPTO_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080/callback"
TOKEN_FILE = os.getenv("TOKEN_FILE", "panopto_tokens.json")

LOGGING_LEVEL = logging.INFO  # Change to logging.DEBUG for more details or logging.INFO for less
SEND_EMAIL_REPORTS_ON_ISSUE_ONLY = False  # Only send email if there are issues to report

# Email Configuration - imported from separate config file
try:
    from email_config import (
        SEND_EMAIL_REPORTS, EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT, 
        EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO
    )
except ImportError:
    # Default values if config file doesn't exist
    SEND_EMAIL_REPORTS = False
    EMAIL_SMTP_SERVER = "smtp.gmail.com"
    EMAIL_SMTP_PORT = 587
    EMAIL_FROM = ""
    EMAIL_PASSWORD = ""
    EMAIL_TO = ""

# Global variable for OAuth2 callback
callback_auth_code = None

class CallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth2 callback"""
    def do_GET(self):
        global callback_auth_code
        
        if self.path.startswith('/callback'):
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            
            if 'code' in query_params:
                callback_auth_code = query_params['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h2>Authentication successful! You can close this window.</h2></body></html>')
    
    def log_message(self, format, *args):
        pass

def setup_logging():
    """Setup logging for the script"""
    # Create logs directory if it doesn't exist
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    logging.basicConfig(
        level=LOGGING_LEVEL,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(logs_dir, 'panopto_sync.log'), encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def save_tokens(access_token, refresh_token, expires_in):
    """Save tokens to file for later use"""
    logger = logging.getLogger(__name__)
    
    # Calculate expiration time with 5-minute buffer
    expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
    
    token_data = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_at': expires_at.isoformat(),
        'created_at': datetime.now().isoformat()
    }
    
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_data, f, indent=2)
        logger.info(f"Tokens saved to {TOKEN_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to save tokens: {e}")
        return False

def load_tokens():
    """Load tokens from file"""
    logger = logging.getLogger(__name__)
    
    if not os.path.exists(TOKEN_FILE):
        logger.warning(f"No token file found at {TOKEN_FILE}")
        return None
    
    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
        logger.info("Token file loaded successfully")
        return token_data
    except Exception as e:
        logger.error(f"Failed to load tokens: {e}")
        return None

def refresh_access_token(refresh_token):
    """Use refresh token to get new access token without user interaction"""
    logger = logging.getLogger(__name__)
    
    logger.info("Refreshing access token using refresh token...")
    
    token_url = f"https://{PANOPTO_SERVER}/Panopto/oauth2/connect/token"
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    
    credentials = f"{PANOPTO_CLIENT_ID}:{PANOPTO_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {encoded_credentials}'
    }
    
    try:
        response = requests.post(token_url, data=data, headers=headers, timeout=30)
        if response.status_code == 200:
            token_data = response.json()
            logger.info("Access token refreshed successfully!")
            logger.info(f"  New token expires in: {token_data.get('expires_in', 'Unknown')} seconds")
            
            # Save the new tokens
            access_token = token_data['access_token']
            new_refresh_token = token_data.get('refresh_token', refresh_token)  # Some APIs reuse refresh token
            expires_in = token_data.get('expires_in', 3600)
            
            save_tokens(access_token, new_refresh_token, expires_in)
            
            return access_token
        else:
            logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return None

def oauth2_initial_auth():
    """Initial OAuth2 Authorization Code Flow - Only needed once
    Opens browser for user authentication and saves refresh token
    """
    global callback_auth_code
    logger = logging.getLogger(__name__)
    
    logger.info("Starting initial OAuth2 authentication...")
    logger.info("This will save a refresh token for future automated use")
    
    # Reset callback state
    callback_auth_code = None
    
    # Start callback server
    server = HTTPServer(('localhost', 8080), CallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()
    
    # Generate authorization URL
    nonce = secrets.token_urlsafe(32)
    params = {
        'client_id': PANOPTO_CLIENT_ID,
        'scope': 'openid api offline_access',
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'nonce': nonce
    }
    auth_url = f"https://{PANOPTO_SERVER}/Panopto/oauth2/connect/authorize?" + urllib.parse.urlencode(params)
    
    logger.info("Opening browser for authentication...")
    logger.info("Please complete the login process in your browser")
    
    # Open browser for user authentication
    webbrowser.open(auth_url)
    
    # Wait for callback
    timeout = 120  # 2 minutes
    start_time = time.time()
    
    while callback_auth_code is None:
        time.sleep(1)
        if time.time() - start_time > timeout:
            logger.error("Timeout waiting for authentication")
            return None
    
    logger.info("Authorization code received")
    
    # Exchange code for tokens
    token_url = f"https://{PANOPTO_SERVER}/Panopto/oauth2/connect/token"
    data = {
        'grant_type': 'authorization_code',
        'code': callback_auth_code,
        'redirect_uri': REDIRECT_URI
    }
    
    credentials = f"{PANOPTO_CLIENT_ID}:{PANOPTO_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {encoded_credentials}'
    }
    
    try:
        response = requests.post(token_url, data=data, headers=headers, timeout=30)
        if response.status_code == 200:
            token_data = response.json()
            logger.info("Tokens obtained successfully!")
            logger.info(f"Access token expires in: {token_data.get('expires_in', 'Unknown')} seconds")
            
            # Save tokens for future use
            access_token = token_data['access_token']
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 3600)
            
            if refresh_token:
                save_tokens(access_token, refresh_token, expires_in)
                logger.info("Refresh token saved! Future runs won't need user interaction.")
            else:
                logger.warning("No refresh token received - may need user auth next time")

            return access_token
        else:
            logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return None

def get_panopto_auth():
    """Main authentication method with automatic refresh token handling
    
    Flow:
    1. Try to load existing valid access token
    2. If expired, try to refresh using refresh token
    3. If no refresh token or refresh fails, do initial auth (browser)
    4. Save refresh token for future automated use
    """
    logger = logging.getLogger(__name__)

    logger.info("Starting Panopto authentication...")

    # Try to load existing tokens
    token_data = load_tokens()
    
    if token_data:
        # Check if access token is still valid
        try:
            expires_at = datetime.fromisoformat(token_data['expires_at'])
            if datetime.now() < expires_at:
                logger.info("Using existing valid access token")
                return token_data['access_token']
        except:
            logger.warning("Could not parse token expiration, will refresh")
        
        # Access token expired or invalid, try to refresh
        if 'refresh_token' in token_data:
            logger.info("Access token expired, attempting refresh...")
            refreshed_token = refresh_access_token(token_data['refresh_token'])
            if refreshed_token:
                return refreshed_token
            else:
                logger.error("Refresh failed, will need user authentication")
        else:
            logger.error("No refresh token available")

    # No valid tokens or refresh failed - need initial authentication
    logger.info("🔑 Performing initial authentication (browser required)")
    return oauth2_initial_auth()

def getScheduleOfClasses(ctx=None):
    """Load class groups from Excel file"""
    logger = logging.getLogger(__name__)
    class_groups = pd.read_excel("pt_class_groups.xlsx", sheet_name="Sheet2")
    
    class_groups_dict_li = []
    for index, row in class_groups.iterrows():
        raw_id = row['Class Group ID']
        if pd.isna(raw_id):
            class_group_id = raw_id
        else:
            try:
                class_group_id = str(int(raw_id))
            except (ValueError, TypeError):
                logger.warning(f"Row {index}: Non-numeric Class Group ID '{raw_id}' - skipping row")
                continue
        ioe_folder_id = row['IOE Folder ID']
        bc_folder_id = row['BC Folder ID']

        if pd.isna(ioe_folder_id) and pd.isna(bc_folder_id):
            continue

        class_groups_dict_li.append({
            "Class Group ID": class_group_id,
            "IOE Folder ID": ioe_folder_id,
            "BC Folder ID": bc_folder_id
        })

    return class_groups_dict_li

def get_panopto_folder_recordings(panopto_auth, folder_id, folder_type="Unknown"):
    """Get recordings from a Panopto folder using the correct API v1 endpoint"""
    logger = logging.getLogger(__name__)
    
    logger.debug(f"Getting {folder_type} sessions from folder: {folder_id}")
    
    # Using the correct API v1 endpoint format that we confirmed works
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/folders/{folder_id}/sessions"
    headers = {
        "Authorization": f"Bearer {panopto_auth}"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            sessions = data.get('Results', [])
            
            logger.info(f"Successfully retrieved {len(sessions)} sessions from {folder_type} folder")
            
            # Extract session information
            session_list = []
            for session in sessions:
                # Use StartTime as the unique identifier - this is stable even if the session is renamed
                # The StartTime is unique per recording session and doesn't change
                start_time = session.get('StartTime')
                session_info = {
                    'id': session.get('Id'),
                    'name': session.get('Name'),
                    'description': session.get('Description'),
                    'created_date': start_time,
                    'duration': session.get('Duration'),
                    'folder_id': folder_id,
                    'folder_type': folder_type,
                    'folder_name': session.get('FolderDetails', {}).get('Name', 'Unknown Folder'),
                    # Use StartTime as unique key - stable across renames
                    'unique_key': start_time if start_time else f"Unknown Session: {session.get('Id')}",
                    # Keep the display name for logging
                    'display_name': f"{session.get('Name')}|{start_time}" if session.get('Name') else f"Unknown Session: {session.get('Id')}"
                }
                session_list.append(session_info)
            
            return session_list
            
        elif response.status_code == 403:
            logger.error(f"Access denied to {folder_type} folder {folder_id}")
            return []
        elif response.status_code == 404:
            logger.error(f"{folder_type} folder {folder_id} not found")
            return []
        else:
            logger.error(f"API error for {folder_type} folder: {response.status_code} - {response.text[:200]}")
            return []
            
    except requests.exceptions.Timeout:
        logger.error(f"Timeout accessing {folder_type} folder {folder_id}")
        return []
    except Exception as e:
        logger.error(f"Exception accessing {folder_type} folder {folder_id}: {e}")
        return []

def compare_folder_sessions(ioe_sessions, bc_sessions, class_group_id):
    """Compare sessions between IOE and BC folders
    
    Uses StartTime as the unique identifier since it's stable even when sessions are renamed.
    Also detects renamed sessions (same StartTime but different name) for reporting.
    """
    logger = logging.getLogger(__name__)
    
    logger.info(f"Comparing sessions for Class Group {class_group_id}")
    logger.debug(f"   IOE sessions: {len(ioe_sessions)}")
    logger.debug(f"   BC sessions: {len(bc_sessions)}")

    # Create dictionaries keyed by unique_key (StartTime) for efficient lookup
    ioe_by_key = {session['unique_key']: session for session in ioe_sessions}
    bc_by_key = {session['unique_key']: session for session in bc_sessions}
    
    # Use StartTime-based keys for comparison (stable across renames)
    ioe_keys = set(ioe_by_key.keys())
    bc_keys = set(bc_by_key.keys())

    # Find differences based on unique_key (StartTime)
    only_in_ioe_keys = ioe_keys - bc_keys
    only_in_bc_keys = bc_keys - ioe_keys
    in_both_keys = ioe_keys & bc_keys
    
    # Convert back to display names for logging and reporting
    only_in_ioe = {ioe_by_key[key]['display_name'] for key in only_in_ioe_keys}
    only_in_bc = {bc_by_key[key]['display_name'] for key in only_in_bc_keys}
    in_both = {ioe_by_key[key]['display_name'] for key in in_both_keys}
    
    # Detect renamed sessions (same StartTime but different name in IOE vs BC)
    renamed_sessions = []
    for key in in_both_keys:
        ioe_session = ioe_by_key[key]
        bc_session = bc_by_key[key]
        if ioe_session['name'] != bc_session['name']:
            renamed_sessions.append({
                'unique_key': key,
                'ioe_name': ioe_session['name'],
                'bc_name': bc_session['name'],
                'ioe_session_id': ioe_session['id'],
                'bc_session_id': bc_session['id']
            })
            logger.info(f"   Detected renamed session: '{bc_session['name']}' -> '{ioe_session['name']}'")
    
    comparison_result = {
        'class_group_id': class_group_id,
        'ioe_folder_id': ioe_sessions[0]['folder_id'] if ioe_sessions else None,
        'bc_folder_id': bc_sessions[0]['folder_id'] if bc_sessions else None,
        'ioe_folder_name': ioe_sessions[0]['folder_name'] if ioe_sessions else None,
        'bc_folder_name': bc_sessions[0]['folder_name'] if bc_sessions else None,
        'ioe_session_count': len(ioe_sessions),
        'bc_session_count': len(bc_sessions),
        'sessions_only_in_ioe': list(only_in_ioe),
        'sessions_only_in_ioe_keys': list(only_in_ioe_keys),  # For actual sync operations
        'sessions_only_in_bc': list(only_in_bc),
        'sessions_only_in_bc_keys': list(only_in_bc_keys),  # For reference
        'sessions_in_both': list(in_both),
        'renamed_sessions': renamed_sessions,  # Sessions that exist in both but have different names
        'differences_found': len(only_in_ioe) > 0 or len(only_in_bc) > 0,
        'ioe_by_key': ioe_by_key,  # For lookup during sync
        'bc_by_key': bc_by_key  # For lookup during rename sync
    }
    
    if comparison_result['differences_found']:
        logger.debug(f"Differences found for Class Group {class_group_id}:")
        if only_in_ioe:
            logger.debug(f"   Only in IOE ({len(only_in_ioe)}): {', '.join(list(only_in_ioe)[:3])}{'...' if len(only_in_ioe) > 3 else ''}")
        if only_in_bc:
            logger.warning(f"   Only in BC ({len(only_in_bc)}): {', '.join(list(only_in_bc)[:3])}{'...' if len(only_in_bc) > 3 else ''}")
    elif len(ioe_sessions) != len(bc_sessions):
        logger.warning(f"Session counts differ but unique keys match for Class Group {class_group_id} ???")
        logger.debug(f"   Unique keys match: {ioe_keys == bc_keys}")
        logger.debug(f"   IOE Session Keys: {ioe_keys}")
        logger.debug(f"   BC Session Keys: {bc_keys}")
    else:
        if renamed_sessions:
            logger.info(f"Class Group {class_group_id}: Folders are synchronized ({len(renamed_sessions)} renamed session(s) detected)")
        else:
            logger.info(f"Class Group {class_group_id}: Folders are synchronized")
    
    return comparison_result

def copy_session_to_folder(panopto_auth, session_id, session_name, target_folder_id, copy_type="Full"):
    """Copy a session to a target folder using Panopto API"""
    logger = logging.getLogger(__name__)
    
    logger.info(f"          Copying session '{session_name}' to folder {target_folder_id}")
    
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/sessions/{session_id}/sessioncopy"
    headers = {
        "Authorization": f"Bearer {panopto_auth}",
        "Content-Type": "application/json"
    }
    
    # Prepare copy request payload
    copy_data = {
        "CopyType": copy_type,  # "Full", "Reference", or "Destructive"
        "FolderId": target_folder_id,
        "Name": session_name  # Keep the exact same name as the original
    }
    
    try:
        response = requests.post(url, headers=headers, json=copy_data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"          Successfully copied session '{session_name}'")
            logger.debug(f"          New session ID: {result.get('NewSessionId', f'{result}')}")
            return {
                'success': True,
                'new_session_id': result.get('NewSessionId', 'Unknown'),
                'message': f"Session copied successfully"
            }
        elif response.status_code == 403:
            logger.error(f"         Access denied - insufficient permissions to copy session '{session_name}'")
            return {
                'success': False,
                'error': 'Access denied - insufficient permissions'
            }
        elif response.status_code == 400:
            logger.error(f"         Bad request copying session '{session_name}': {response}")
            return {
                'success': False,
                'error': 'Bad request - invalid parameters'
            }
        else:
            logger.error(f"         Failed to copy session '{session_name}': {response.status_code} - {response.text[:200]}")
            return {
                'success': False,
                'error': f'API error: {response.status_code}'
            }
            
    except requests.exceptions.Timeout:
        logger.error(f"         Timeout copying session '{session_name}'")
        return {
            'success': False,
            'error': 'Request timeout'
        }
    except Exception as e:
        logger.error(f"         Exception copying session '{session_name}': {e}")
        return {
            'success': False,
            'error': str(e)
        }

def rename_session(panopto_auth, session_id, new_name, old_name=None):
    """Rename a session in Panopto using the API"""
    logger = logging.getLogger(__name__)
    
    display_old = f"'{old_name}'" if old_name else f"session {session_id}"
    logger.info(f"          Renaming {display_old} to '{new_name}'")
    
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/sessions/{session_id}"
    headers = {
        "Authorization": f"Bearer {panopto_auth}",
        "Content-Type": "application/json"
    }
    
    # Prepare update payload - only updating the name
    update_data = {
        "Name": new_name
    }
    
    try:
        response = requests.put(url, headers=headers, json=update_data, timeout=60)
        
        if response.status_code == 200:
            logger.info(f"          Successfully renamed session to '{new_name}'")
            return {
                'success': True,
                'message': f"Session renamed successfully"
            }
        elif response.status_code == 403:
            logger.error(f"         Access denied - insufficient permissions to rename session")
            return {
                'success': False,
                'error': 'Access denied - insufficient permissions'
            }
        elif response.status_code == 404:
            logger.error(f"         Session {session_id} not found")
            return {
                'success': False,
                'error': 'Session not found'
            }
        else:
            logger.error(f"         Failed to rename session: {response.status_code} - {response.text[:200]}")
            return {
                'success': False,
                'error': f'API error: {response.status_code}'
            }
            
    except requests.exceptions.Timeout:
        logger.error(f"         Timeout renaming session")
        return {
            'success': False,
            'error': 'Request timeout'
        }
    except Exception as e:
        logger.error(f"         Exception renaming session: {e}")
        return {
            'success': False,
            'error': str(e)
        }

def sync_renamed_sessions(panopto_auth, comparison_result, class_group_id):
    """Sync renamed sessions by updating the name in the destination (BC) folder"""
    logger = logging.getLogger(__name__)
    
    renamed_sessions = comparison_result.get('renamed_sessions', [])
    
    if not renamed_sessions:
        return {'success': True, 'renamed_count': 0, 'results': []}
    
    logger.info(f"  Syncing {len(renamed_sessions)} renamed session(s) for Class Group {class_group_id}")
    
    rename_results = []
    successful_renames = 0
    
    for renamed in renamed_sessions:
        logger.info(f"      Updating: '{renamed['bc_name']}' -> '{renamed['ioe_name']}'")
        
        rename_result = rename_session(
            panopto_auth=panopto_auth,
            session_id=renamed['bc_session_id'],
            new_name=renamed['ioe_name'],
            old_name=renamed['bc_name']
        )
        
        rename_results.append({
            'old_name': renamed['bc_name'],
            'new_name': renamed['ioe_name'],
            'session_id': renamed['bc_session_id'],
            'unique_key': renamed['unique_key'],
            'result': rename_result
        })
        
        if rename_result['success']:
            successful_renames += 1
        
        # Small delay between renames
        time.sleep(1)
    
    logger.info(f"  Renamed {successful_renames}/{len(renamed_sessions)} sessions")
    
    return {
        'success': True,
        'renamed_count': successful_renames,
        'total_to_rename': len(renamed_sessions),
        'results': rename_results
    }

def sync_sessions_for_class_group(panopto_auth, class_group_data, ioe_sessions, bc_sessions, comparison_result):
    """Synchronize sessions from IOE to BC folder for a specific class group"""
    logger = logging.getLogger(__name__)
    
    class_group_id = class_group_data['Class Group ID']
    bc_folder_id = class_group_data['BC Folder ID']
    
    # Only proceed if there are sessions only in IOE and we have a valid BC folder
    if not comparison_result['sessions_only_in_ioe'] or pd.isna(bc_folder_id):
        logger.debug(f"No synchronization needed for Class Group {class_group_id}")
        return {'success': True, 'copied_sessions': 0, 'class_group_id': class_group_id, 'total_sessions': 0, 'results': []}
    
    logger.info(f"Starting synchronization for Class Group {class_group_id}")
    logger.info(f"  Sessions to copy: {len(comparison_result['sessions_only_in_ioe'])}")
    logger.debug(f"  Target BC folder: {bc_folder_id}")
    
    copy_results = []
    successful_copies = 0
    
    # Find sessions in IOE that need to be copied using unique_key (StartTime)
    sessions_to_copy = []
    for session in ioe_sessions:
        if session['unique_key'] in comparison_result['sessions_only_in_ioe_keys']:
            sessions_to_copy.append(session)
    
    # Copy each session
    for session in sessions_to_copy:
        logger.info(f"      Processing session: {session['display_name']}")
        
        copy_result = copy_session_to_folder(
            panopto_auth=panopto_auth,
            session_id=session['id'],
            session_name=session['name'],
            target_folder_id=bc_folder_id,
            copy_type="Reference"  # Create reference copy
        )
        
        copy_results.append({
            'session_name': session['display_name'],
            'session_id': session['id'],
            'class_group_id': class_group_id,
            'created_date': session['created_date'],
            'unique_key': session['unique_key'],
            'copy_result': copy_result
        })
        
        if copy_result['success']:
            successful_copies += 1
            #logger.info(f"          Session '{session['display_name']}' copied successfully") # this was giving a duplicate log message
        else:
            #logger.error(f"         Failed to copy session '{session['display_name']}': {copy_result['error']}")
            pass # this was giving a duplicate log message

        # Add a small delay between copies to avoid overwhelming the API
        time.sleep(2)
    
    logger.info(f"  Synchronization completed for Class Group {class_group_id}")
    logger.info(f"  Successfully copied: {successful_copies}/{len(sessions_to_copy)} sessions")

    return {
        'success': True,
        'copied_sessions': successful_copies,
        'total_sessions': len(sessions_to_copy),
        'class_group_id': class_group_id,
        'ioe_folder_name': comparison_result.get('ioe_folder_name') if comparison_result else None,
        'results': copy_results
    }

def process_all_class_groups(panopto_auth, class_groups):
    """Process all class groups: compare, synchronize new sessions, and update renamed sessions"""
    logger = logging.getLogger(__name__)
    
    all_results = []
    sync_results = []
    rename_results = []  # Track rename operations
    
    logger.info(f"Processing all {len(class_groups)} class groups")
    logger.info("=" * 60)
    
    for i, class_group in enumerate(class_groups, 1):
        class_group_id = class_group['Class Group ID']
        ioe_folder_id = class_group['IOE Folder ID']
        bc_folder_id = class_group['BC Folder ID']
        
        logger.info("-" * 60)
        logger.info(f"Processing Class Group {i}/{len(class_groups)}: {class_group_id}")
        logger.debug(f" IOE Folder ID: {ioe_folder_id}")
        logger.debug(f" BC Folder ID: {bc_folder_id}")

        # Skip if both folder IDs are missing
        if pd.isna(ioe_folder_id) and pd.isna(bc_folder_id):
            logger.warning(f"Skipping - both folder IDs are missing")
            continue
        
        # Skip if only the source (IOE) folder is populated - no destination to sync to
        if not pd.isna(ioe_folder_id) and pd.isna(bc_folder_id):
            logger.info(f"Skipping Class Group {class_group_id} - no BC (destination) folder ID configured")
            all_results.append({
                'class_group_id': class_group_id,
                'ioe_folder_id': ioe_folder_id,
                'bc_folder_id': None,
                'ioe_folder_name': None,
                'bc_folder_name': None,
                'ioe_session_count': 0,
                'bc_session_count': 0,
                'sessions_only_in_ioe': [],
                'sessions_only_in_bc': [],
                'sessions_in_both': [],
                'renamed_sessions': [],
                'differences_found': False,
                'sync_performed': False,
            })
            continue
        
        # Get sessions from both folders
        ioe_sessions = []
        bc_sessions = []
        
        if not pd.isna(ioe_folder_id):
            ioe_sessions = get_panopto_folder_recordings(panopto_auth, ioe_folder_id, "IOE")
        
        if not pd.isna(bc_folder_id):
            bc_sessions = get_panopto_folder_recordings(panopto_auth, bc_folder_id, "BC")
        
        # Compare sessions
        if ioe_sessions is not None and bc_sessions is not None:
            comparison_result = compare_folder_sessions(ioe_sessions, bc_sessions, class_group_id)
            
            # Track if any sync operations were performed
            sync_performed = False
            
            # First, handle renamed sessions (update names in destination to match source)
            if comparison_result.get('renamed_sessions'):
                logger.info(f"Syncing renamed sessions for Class Group {class_group_id}")
                rename_result = sync_renamed_sessions(
                    panopto_auth=panopto_auth,
                    comparison_result=comparison_result,
                    class_group_id=class_group_id
                )
                rename_result['class_group_id'] = class_group_id
                rename_result['ioe_folder_name'] = comparison_result.get('ioe_folder_name')
                rename_results.append(rename_result)
                sync_performed = True
            
            # Then, copy new sessions that only exist in IOE
            if comparison_result['differences_found'] and comparison_result['sessions_only_in_ioe']:
                logger.info(f"Starting session synchronization for Class Group {class_group_id}")
                
                sync_result = sync_sessions_for_class_group(
                    panopto_auth=panopto_auth,
                    class_group_data=class_group,
                    ioe_sessions=ioe_sessions,
                    bc_sessions=bc_sessions,
                    comparison_result=comparison_result
                )
                sync_results.append(sync_result)
                sync_performed = True
            
            # Re-check folders after any synchronization
            if sync_performed:
                logger.info(f"Re-checking folders after synchronization...")
                bc_sessions_updated = get_panopto_folder_recordings(panopto_auth, bc_folder_id, "BC")
                comparison_result_updated = compare_folder_sessions(ioe_sessions, bc_sessions_updated, class_group_id)
                
                
                if comparison_result_updated['differences_found']:
                    logger.warning(f"Post-sync status:")
                    logger.warning(f"  Differences still found for Class Group {class_group_id} | IOE: {comparison_result_updated['ioe_session_count']} sessions | BC: {comparison_result_updated['bc_session_count']} sessions")
                else:
                    logger.info(f"Post-sync status:")
                    logger.info(f"  Folders are now synchronized for Class Group {class_group_id} | IOE: {comparison_result_updated['ioe_session_count']} sessions | BC: {comparison_result_updated['bc_session_count']} sessions")

                # Mark that sync was performed and use updated result
                comparison_result_updated['sync_performed'] = True
                comparison_result_updated['class_group_id'] = class_group_id
                all_results.append(comparison_result_updated)
            else:
                # No synchronization needed, use original comparison result
                logger.debug(f"No synchronization needed for Class Group {class_group_id}")
                comparison_result['sync_performed'] = False
                comparison_result['class_group_id'] = class_group_id
                all_results.append(comparison_result)
            
        else:
            logger.error(f"Failed to retrieve sessions for Class Group {class_group_id}")
        
        # Add a small delay between class groups to avoid overwhelming the API
        if i < len(class_groups):
            #time.sleep(3)
            pass  # No delay for now to speed up processing - can re-add if needed

    logger.info("=" * 60)
    logger.info("All class groups processed")
    return all_results, sync_results, rename_results

def generate_summary_report(all_results, sync_results, rename_results=None):
    """Generate a summary report of the synchronization process"""

    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("PRODUCTION MODE SUMMARY REPORT")
    logger.info("=" * 60)

    total_groups = len(all_results)
    groups_with_differences = sum(1 for result in all_results if result['differences_found'])
    groups_synchronized = total_groups - groups_with_differences
    total_sessions_copied = sum(result['copied_sessions'] for result in sync_results)
    total_sessions_renamed = sum(result.get('renamed_count', 0) for result in (rename_results or []))

    if sync_results:  
        logger.info(f"Copy Synchronization Results:")
        for sync_result in sync_results:
            logger.info("-" * 40)
            logger.info(f" Class Group ID: {sync_result.get('class_group_id', 'Unknown')}")
            logger.info(f"      Total sessions to copy: {sync_result['total_sessions']}")
            logger.info(f"      Sessions copied: {sync_result['copied_sessions']}/{sync_result['total_sessions']}")
        
            # Show individual copy results
            for result in sync_result['results']:
                if result['copy_result']['success']:
                    logger.info(f"          Success: {result['session_name']}")
                else:
                    logger.error(f"         Error: {result['session_name']}")

    if rename_results:
        logger.info(f"Rename Synchronization Results:")
        for rename_result in rename_results:
            if rename_result.get('results'):
                logger.info("-" * 40)
                logger.info(f" Class Group ID: {rename_result.get('class_group_id', 'Unknown')}")
                logger.info(f"      Sessions renamed: {rename_result['renamed_count']}/{rename_result.get('total_to_rename', 0)}")
                
                # Show individual rename results
                for result in rename_result['results']:
                    if result['result']['success']:
                        logger.info(f"          Renamed: '{result['old_name']}' -> '{result['new_name']}'")
                    else:
                        logger.error(f"         Failed: '{result['old_name']}' -> '{result['new_name']}'")

    logger.info("-" * 40)
    logger.info(f"  Groups Processed: {total_groups}")
    logger.info(f"  Groups Synchronized: {len(sync_results)}")
    logger.info(f"  Total Sessions Copied: {total_sessions_copied}")
    logger.info(f"  Total Sessions Renamed: {total_sessions_renamed}")
    logger.info(f"  Groups Now Synchronized: {groups_synchronized}")
    if groups_with_differences > 0:
        logger.warning(f"Groups Still With Differences: {groups_with_differences}")
    else:
        logger.info("All groups are now synchronized!")

    return total_groups, groups_synchronized, total_sessions_copied, groups_with_differences, total_sessions_renamed

def get_differences_summary(all_results, groups_with_differences):
    """Get a summary of remaining differences for email report"""

    logger = logging.getLogger(__name__)

    differences_summary = {}
    if groups_with_differences > 0:
        logger.warning("-" * 40)
        logger.warning("Remaining differences:")
        for result in all_results:
            if result['differences_found']:
                differences_summary[result['class_group_id']] = {
                    'ioe_only': len(result['sessions_only_in_ioe']),
                    'bc_only': len(result['sessions_only_in_bc']),
                    'ioe_folder_link': f"https://{PANOPTO_SERVER}/Panopto/Pages/Sessions/List.aspx#folderID={result.get('ioe_folder_id')}",
                    'bc_folder_link': f"https://{PANOPTO_SERVER}/Panopto/Pages/Sessions/List.aspx#folderID={result.get('bc_folder_id')}",
                    'ioe_folder_name': result.get('ioe_folder_name', 'Unknown Folder'),
                    'bc_folder_name': result.get('bc_folder_name', 'Unknown Folder'),
                }
                logger.warning(f"   {result['class_group_id']}: {len(result['sessions_only_in_ioe'])} IOE-only, {len(result['sessions_only_in_bc'])} BC-only")

    return differences_summary

def save_detailed_results_to_file(all_results, sync_results, total_groups, total_sessions_copied):
    """Save detailed synchronization results to a timestamped log file"""
    logger = logging.getLogger(__name__)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = 'logs'
    results_file = os.path.join(logs_dir, f"panopto_sync_results_{timestamp}.log")

    with open(results_file, 'w') as f:
        f.write("Panopto Folder Synchronization Results (PRODUCTION MODE)\n")
        f.write(f"Generated: {datetime.now()}\n")
        f.write("Authentication: OAuth2 with Refresh Token\n")
        f.write(f"Total Class Groups Processed: {total_groups}\n")
        f.write(f"Groups Synchronized: {len(sync_results)}\n")
        f.write(f"Total Sessions Copied: {total_sessions_copied}\n")
        f.write("=" * 50 + "\n\n")
        
        for result in all_results:
            f.write(f"Class Group: {result['class_group_id']}\n")
            f.write(f"IOE Sessions: {result['ioe_session_count']}\n")
            f.write(f"BC Sessions: {result['bc_session_count']}\n")
            f.write(f"Differences: {'Yes' if result['differences_found'] else 'No'}\n")
            
            if result['sessions_only_in_ioe']:
                f.write(f"Only in IOE: {', '.join(result['sessions_only_in_ioe'])}\n")
            if result['sessions_only_in_bc']:
                f.write(f"Only in BC: {', '.join(result['sessions_only_in_bc'])}\n")
            
            f.write("\n" + "-" * 30 + "\n\n")
        
        # Add synchronization results if available
        if sync_results:
            f.write("SYNCHRONIZATION RESULTS\n")
            f.write("=" * 30 + "\n\n")

            for sync_result in sync_results:
                f.write(f"Class Group ID: {sync_result.get('class_group_id', 'Unknown')}\n")
            f.write(f"Total sessions to copy: {sync_result['total_sessions']}\n")
            f.write(f"Successfully copied: {sync_result['copied_sessions']}\n")
            f.write(f"Success rate: {sync_result['copied_sessions']}/{sync_result['total_sessions']}\n\n")
            
            f.write("Individual copy results:\n")
            for result in sync_result['results']:
                status = "SUCCESS" if result['copy_result']['success'] else "FAILED"
                f.write(f"  {status}: {result['session_name']}\n")
                if not result['copy_result']['success']:
                    f.write(f"    Error: {result['copy_result']['error']}\n")
            
            f.write("\n")
    
    logger.info("=" * 60)
    logger.info(f"Detailed results saved to: {results_file}")

    return results_file

def send_error_email(error_message, error_stage="Unknown"):
    """Send a simple error notification email when the script fails before generating a full report"""
    logger = logging.getLogger(__name__)
    
    if not SEND_EMAIL_REPORTS:
        logger.warning("Email reports disabled - error email not sent")
        return False
    
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        logger.error("Email configuration incomplete - cannot send error email")
        return False
    
    try:
        msg = MIMEText(
            f"The Panopto Sync script encountered a critical error and could not complete.\n\n"
            f"Stage: {error_stage}\n"
            f"Error: {error_message}\n\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Please check the logs for more details.",
            'plain'
        )
        msg['From'] = EMAIL_FROM
        msg['To'] = ", ".join(EMAIL_TO) if isinstance(EMAIL_TO, list) else EMAIL_TO
        msg['Subject'] = f"\u274c Panopto Sync FAILED at {error_stage} - {datetime.now().strftime('%b %d, %Y at %H:%M')}"
        
        server = smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        server.quit()
        
        logger.info(f"Error notification email sent for failure at: {error_stage}")
        return True
    except Exception as e:
        logger.error(f"Failed to send error notification email: {str(e)}")
        return False

def send_email_report(total_groups, sync_results, total_sessions_copied, groups_synchronized, groups_with_differences, differences_summary, results_file_path=None, scheduled_run_log=None, total_sessions_renamed=0, rename_results=None):
    """Send beautifully formatted HTML email report of synchronization results"""
    logger = logging.getLogger(__name__)
    
    if not SEND_EMAIL_REPORTS:
        logger.warning("Email reports disabled (SEND_EMAIL_REPORTS = False)")
        return False
    
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        logger.error("Email configuration incomplete - skipping email report")
        return False
    
    if groups_with_differences == 0 and SEND_EMAIL_REPORTS_ON_ISSUE_ONLY:
        logger.info("No issues detected and SEND_EMAIL_REPORTS_ON_ISSUE_ONLY is True - skipping email report")
        return False  # Not an error, just skipping
    
    try:
        # Create email message
        msg = MIMEMultipart('alternative')
        msg['From'] = EMAIL_FROM
        msg['To'] = ", ".join(EMAIL_TO) if isinstance(EMAIL_TO, list) else EMAIL_TO
        
        # Enhanced subject line with status indicators

        if groups_with_differences == 0:
            status_emoji = "✅"
        elif differences_summary:
            status_emoji = "⚠️" 
        elif total_sessions_copied > 0:
            status_emoji = "🔄"
        else:
            status_emoji = "📊"
        msg['Subject'] = f"{status_emoji} Panopto Sync Report - {datetime.now().strftime('%b %d, %Y at %H:%M')}"
        
        # Build HTML email body from template
        html_body = build_html_report(
            total_groups=total_groups,
            groups_synchronized=groups_synchronized,
            total_sessions_copied=total_sessions_copied,
            total_sessions_renamed=total_sessions_renamed,
            groups_with_differences=groups_with_differences,
            differences_summary=differences_summary,
            sync_results=sync_results,
            rename_results=rename_results,
            panopto_server=PANOPTO_SERVER,
            results_file_path=results_file_path,
            scheduled_run_log=scheduled_run_log
        )
        
        # Build plain text fallback
        plain_text = build_plain_text_report(
            total_groups=total_groups,
            groups_synchronized=groups_synchronized,
            total_sessions_copied=total_sessions_copied,
            total_sessions_renamed=total_sessions_renamed,
            groups_with_differences=groups_with_differences,
            differences_summary=differences_summary,
            panopto_server=PANOPTO_SERVER
        )
        
        # Attach both HTML and plain text versions
        msg.attach(MIMEText(plain_text, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        # Attach log file if provided
        if results_file_path and os.path.exists(results_file_path):
            with open(results_file_path, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {os.path.basename(results_file_path)}'
                )
                msg.attach(part)

        if scheduled_run_log and os.path.exists(scheduled_run_log):
            with open(scheduled_run_log, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {os.path.basename(scheduled_run_log)}'
                )
                msg.attach(part)
        
        # Send email
        logger.info(f"Sending report to {', '.join(EMAIL_TO) if isinstance(EMAIL_TO, list) else EMAIL_TO}...")
        
        server = smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
        server.starttls()  # Enable encryption
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_FROM, EMAIL_TO, text)
        server.quit()
        
        logger.info("Report sent successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email report: {str(e)}")
        # Try to send a minimal fallback error notification email
        try:
            fallback_msg = MIMEText(
                f"The Panopto Sync email report failed to send.\n\n"
                f"Error: {str(e)}\n\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Please check the logs for more details.",
                'plain'
            )
            fallback_msg['From'] = EMAIL_FROM
            fallback_msg['To'] = ", ".join(EMAIL_TO) if isinstance(EMAIL_TO, list) else EMAIL_TO
            fallback_msg['Subject'] = f"❌ Panopto Sync Report FAILED - {datetime.now().strftime('%b %d, %Y at %H:%M')}"

            fallback_server = smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
            fallback_server.starttls()
            fallback_server.login(EMAIL_FROM, EMAIL_PASSWORD)
            fallback_server.sendmail(EMAIL_FROM, EMAIL_TO, fallback_msg.as_string())
            fallback_server.quit()
            logger.info("Fallback error notification email sent successfully")
        except Exception as fallback_e:
            logger.error(f"Fallback error email also failed: {str(fallback_e)}")
        return False

def main():
    """Main function to run the folder synchronization check"""
    logger = setup_logging()
    
    logger.info("Starting Panopto Folder Synchronization Check")
    logger.info("=" * 60)
    
    # Get authentication token (automatic refresh token handling)
    panopto_auth = get_panopto_auth()
    if not panopto_auth:
        logger.error("Failed to authenticate with Panopto")
        send_error_email("Failed to authenticate with Panopto", "Authentication")
        return
    
    # Load class groups
    try:
        class_groups = getScheduleOfClasses()
        logger.info(f"Loaded {len(class_groups)} class groups from Excel file")
    except Exception as e:
        logger.error(f"Failed to load class groups: {e}")
        send_error_email(str(e), "Loading Class Groups")
        return
    
    # Main loop to process each class group
    all_results, sync_results, rename_results = process_all_class_groups(panopto_auth, class_groups)

    if not all_results:
        logger.error("No results to process - exiting")
        send_error_email("No results were returned from processing class groups", "Processing Class Groups")
        return
    
    # Generate summary report
    total_groups, groups_synchronized, total_sessions_copied, groups_with_differences, total_sessions_renamed = generate_summary_report(all_results, sync_results, rename_results)

    if not total_groups:
        logger.error("No class groups were processed - exiting")
        return

    # Collect differences summary for email
    differences_summary = get_differences_summary(all_results, groups_with_differences)
    
    # Save detailed results to file
    results_file = save_detailed_results_to_file(all_results, sync_results, total_groups, total_sessions_copied)
    
    # Get the most recently modified log file in the scheduled_logs directory
    scheduled_run_log = None
    logs_dir = 'scheduled_logs'
    for filename in os.listdir(logs_dir):
        if filename.startswith("scheduled_run_") and filename.endswith(".log"):
            file_path = os.path.join(logs_dir, filename)
            if scheduled_run_log is None or os.path.getmtime(file_path) > os.path.getmtime(scheduled_run_log):
                scheduled_run_log = file_path

    # Send email report
    email_sent = send_email_report(
        total_groups=total_groups,
        sync_results=sync_results,
        total_sessions_copied=total_sessions_copied,
        groups_synchronized=groups_synchronized,
        groups_with_differences=groups_with_differences,
        differences_summary=differences_summary,
        results_file_path=results_file,
        scheduled_run_log=scheduled_run_log,
        total_sessions_renamed=total_sessions_renamed,
        rename_results=rename_results
    )
    
    if email_sent:
        logger.info("Email report sent successfully!")
    
    logger.info("Synchronization check completed successfully!")

if __name__ == "__main__":
    main()