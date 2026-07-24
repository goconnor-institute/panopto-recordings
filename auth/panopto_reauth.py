#!/usr/bin/env python3
"""
Panopto Re-Authentication
--------------------------
Opens a browser for OAuth2 login and saves fresh tokens to panopto_tokens.json.
Run this when your refresh token has expired.

Usage:
    python panopto_reauth.py
"""

import requests
import json
import os
import sys
import base64
import secrets
import urllib.parse
import webbrowser
import time
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv(override=True)

PANOPTO_SERVER = os.getenv("PANOPTO_SERVER", "ioe.cloud.panopto.eu")
PANOPTO_CLIENT_ID = os.getenv("PANOPTO_CLIENT_ID", "")
PANOPTO_CLIENT_SECRET = os.getenv("PANOPTO_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080/callback"
TOKEN_FILE = os.getenv("TOKEN_FILE", "panopto_tokens.json")

callback_auth_code = None


class CallbackHandler(BaseHTTPRequestHandler):
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


def main():
    global callback_auth_code
    callback_auth_code = None

    # Start callback server
    server = HTTPServer(('localhost', 8080), CallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    # Build authorization URL
    nonce = secrets.token_urlsafe(32)
    params = {
        'client_id': PANOPTO_CLIENT_ID,
        'scope': 'openid api offline_access',
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'nonce': nonce
    }
    auth_url = f"https://{PANOPTO_SERVER}/Panopto/oauth2/connect/authorize?" + urllib.parse.urlencode(params)

    print("Opening browser for Panopto login...")
    print("Please complete the login in your browser.")
    webbrowser.open(auth_url)

    # Wait for callback (2 minute timeout)
    start_time = time.time()
    while callback_auth_code is None:
        time.sleep(1)
        if time.time() - start_time > 120:
            print("Timeout waiting for authentication.")
            sys.exit(1)

    print("Authorization code received. Exchanging for tokens...")

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

    response = requests.post(token_url, data=data, headers=headers, timeout=30)
    if response.status_code != 200:
        print(f"Token exchange failed: {response.status_code} - {response.text}")
        sys.exit(1)

    token_data = response.json()
    access_token = token_data['access_token']
    refresh_token = token_data.get('refresh_token')
    expires_in = token_data.get('expires_in', 3600)

    if not refresh_token:
        print("Warning: No refresh token received. Future automated runs may fail.")

    save_data = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_at': (datetime.now() + timedelta(seconds=expires_in - 300)).isoformat(),
        'created_at': datetime.now().isoformat()
    }
    with open(TOKEN_FILE, 'w') as f:
        json.dump(save_data, f, indent=2)

    print(f"Tokens saved to {TOKEN_FILE}")
    print(f"Expires in: {expires_in} seconds")
    print("You can now run get_panopto_transcript.py")


if __name__ == "__main__":
    main()
