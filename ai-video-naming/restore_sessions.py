#!/usr/bin/env python3
"""
Restore Panopto session names from backup
"""

import requests
import json
import os
from datetime import datetime, timedelta
import base64
from dotenv import load_dotenv

load_dotenv(override=True)

# Configuration
PANOPTO_SERVER = os.getenv("PANOPTO_SERVER", "ioe.cloud.panopto.eu")
PANOPTO_CLIENT_ID = os.getenv("PANOPTO_CLIENT_ID", "")
PANOPTO_CLIENT_SECRET = os.getenv("PANOPTO_CLIENT_SECRET", "")
TOKEN_FILE = os.getenv("TOKEN_FILE", "panopto_tokens.json")


def get_auth_token():
    """Get a valid access token"""
    if not os.path.exists(TOKEN_FILE):
        print("❌ No token file found")
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
    return None


def rename_session(auth_token, session_id, new_name):
    """Rename a session"""
    url = f"https://{PANOPTO_SERVER}/Panopto/api/v1/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    
    response = requests.put(url, headers=headers, json={"Name": new_name}, timeout=30)
    return response.status_code == 200


def main():
    import sys
    
    # Find backup files
    backup_files = [f for f in os.listdir('.') if f.startswith('session_backup_') and f.endswith('.json')]
    
    if not backup_files:
        print("❌ No backup files found")
        return
    
    print("Available backup files:")
    for i, f in enumerate(sorted(backup_files, reverse=True)):
        print(f"  {i+1}. {f}")
    
    if len(sys.argv) > 1:
        backup_file = sys.argv[1]
    else:
        choice = input("\nEnter backup file number to restore (or filename): ").strip()
        if choice.isdigit():
            backup_file = sorted(backup_files, reverse=True)[int(choice)-1]
        else:
            backup_file = choice
    
    if not os.path.exists(backup_file):
        print(f"❌ File not found: {backup_file}")
        return
    
    print(f"\n📂 Loading backup: {backup_file}")
    with open(backup_file, 'r', encoding='utf-8') as f:
        backup_data = json.load(f)
    
    sessions = backup_data.get('sessions', [])
    print(f"   Found {len(sessions)} sessions to restore")
    
    # Show preview
    print("\nFirst 3 sessions to restore:")
    for s in sessions[:3]:
        print(f"  • {s['original_name'][:60]}...")
    
    confirm = input("\nRestore all session names? (y/n): ").strip().lower()
    if confirm not in ['y', 'yes']:
        print("❌ Aborted")
        return
    
    # Get auth
    auth_token = get_auth_token()
    if not auth_token:
        print("❌ Authentication failed")
        return
    
    # Restore sessions
    success = 0
    for i, session in enumerate(sessions):
        session_id = session['session_id']
        original_name = session['original_name']
        
        print(f"[{i+1}/{len(sessions)}] Restoring: {original_name[:50]}...")
        
        if rename_session(auth_token, session_id, original_name):
            print("   ✅ Restored")
            success += 1
        else:
            print("   ❌ Failed")
    
    print(f"\n✅ Restored {success}/{len(sessions)} sessions")


if __name__ == "__main__":
    main()
