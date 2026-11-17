# One-time, on YOUR machine (browser available). Prints the base64 to hand to deploy.
from google_auth_oauthlib.flow import InstalledAppFlow
import base64, json

SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/drive.file"]
flow = InstalledAppFlow.from_client_secrets_file(
    "credentials.json", SCOPES,
    access_type="offline", prompt="consent")   # offline+consent => refresh_token present
creds = flow.run_local_server(port=0)
tok = json.loads(creds.to_json())
assert "refresh_token" in tok, "no refresh_token — re-run with access_type=offline"
print("GMAIL_TOKEN_B64=" + base64.b64encode(creds.to_json().encode()).decode())
