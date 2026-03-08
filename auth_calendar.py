"""
One-time Google Calendar OAuth Setup

Run this script LOCALLY (not on Render) to authorize the agent
to access your Google Calendar.

Prerequisites:
1. Go to https://console.cloud.google.com
2. Create a project (or use existing)
3. Enable "Google Calendar API"
4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"
5. Application type: "Desktop app"
6. Download the JSON → save as "credentials.json" in this folder

Usage:
    python auth_calendar.py

This will:
1. Open a browser for Google login
2. Generate token.json with your access/refresh tokens
3. Print the GOOGLE_CREDENTIALS_JSON env var value
4. Copy that value to your Render environment variables
"""

import os
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.json"
CREDS_FILE = "credentials.json"


def main():
    creds = None

    # Check for existing token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Refresh or create new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                print(f"ERROR: '{CREDS_FILE}' not found!")
                print("Download your OAuth credentials from Google Cloud Console.")
                print("See instructions in the docstring above.")
                return

            print("Opening browser for Google login...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token for future use
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}")

    # Build the env var value for Render
    token_data = json.loads(creds.to_json())

    # Read client_id and client_secret from credentials.json
    with open(CREDS_FILE, "r") as f:
        creds_json = json.load(f)
        installed = creds_json.get("installed", creds_json.get("web", {}))

    env_value = json.dumps({
        "token": token_data.get("token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        "client_id": installed.get("client_id"),
        "client_secret": installed.get("client_secret"),
    })

    print("\n" + "=" * 60)
    print("SUCCESS! Copy the value below to your Render env var:")
    print("Variable name: GOOGLE_CREDENTIALS_JSON")
    print("=" * 60)
    print(env_value)
    print("=" * 60)


if __name__ == "__main__":
    main()
