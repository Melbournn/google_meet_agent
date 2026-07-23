from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/meetings.space.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

CLIENT_SECRET = Path("secrets/client_secret.json")
TOKEN = Path("secrets/token.json")

def get_credentials() -> Credentials:
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request()) #refreshing
        else:
            if not CLIENT_SECRET.exists():
                raise FileNotFoundError("Download the OAuth client to secrets/client_secret.json")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.parent.mkdir(parents=True, exist_ok=True)
        TOKEN.write_text(creds.to_json())
    return creds


# Run:
# !./gma_venv/Scripts/python.exe -c "from capture.google_auth import get_credentials; c=get_credentials(); print('OK, token valid:', c.valid)"