"""LOLO Mail Bridge — Gmail send/read + Pub/Sub push + Drive attachments.

Runs on Cloud Run (with billing) OR any Docker host (HF Space/VPS, NO card).
Token handling (SECURITY FIX vs the original blueprint):
  token.json is NEVER baked into the image. Supply GMAIL_TOKEN_B64 (base64 of
  token.json) as an env/secret; it is written to a runtime-only file at startup.
Gmail push uses historyId from the Pub/Sub envelope (fixes the blueprint's
"latest message only" reprocess/miss bug).
"""
import base64, json, os, tempfile
from email.message import EmailMessage

import requests
from fastapi import FastAPI, Request, Header, HTTPException
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from pydantic import BaseModel

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(tempfile.gettempdir(), "lolo_gmail_token.json")

API_SECRET = os.environ.get("LOLO_API_SECRET", "")
LOLO_WEBHOOK_URL = os.environ.get("LOLO_WEBHOOK_URL", "")
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "")
GCP_PROJECT = os.environ.get("GCP_PROJECT", "")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC", "lolo-gmail-push")
SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/drive.file"]

app = FastAPI(title="Agent Lolo Email Server")


def _load_token():
    b64 = os.environ.get("GMAIL_TOKEN_B64", "")
    if b64 and not os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "wb") as f:
            f.write(base64.b64decode(b64))


def get_services():
    _load_token()
    if not os.path.exists(TOKEN_PATH):
        raise HTTPException(503, "GMAIL_TOKEN_B64 not configured — run the one-time OAuth step first")
    with open(TOKEN_PATH) as f:
        creds = Credentials.from_authorized_user_info(json.load(f), SCOPES)
    if not creds.valid:
        if not creds.refresh_token:
            raise HTTPException(503, "token.json has no refresh_token — redo OAuth with access_type=offline")
        try:
            creds.refresh(GoogleRequest())
        except Exception as e:
            raise HTTPException(502, f"token refresh failed (re-run OAuth?): {e}")
    return build("gmail", "v1", credentials=creds), build("drive", "v3", credentials=creds)


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str


@app.get("/health")
def health():
    return {"ok": True, "token_configured": bool(os.environ.get("GMAIL_TOKEN_B64")),
            "secret_configured": bool(API_SECRET)}


@app.post("/send")
def send_email(req: SendEmailRequest, x_api_key: str = Header(None)):
    if not API_SECRET or x_api_key != API_SECRET:
        raise HTTPException(401, "invalid api key")
    gmail, _ = get_services()
    msg = EmailMessage()
    msg.set_content(req.body)
    msg["To"], msg["Subject"] = req.to, req.subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"status": "sent", "message_id": sent["id"]}


@app.get("/inbox")
def read_inbox(limit: int = 5, x_api_key: str = Header(None)):
    if not API_SECRET or x_api_key != API_SECRET:
        raise HTTPException(401, "invalid api key")
    gmail, _ = get_services()
    res = gmail.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=limit).execute()
    emails = []
    for m in res.get("messages", []):
        d = gmail.users().messages().get(userId="me", id=m["id"], format="metadata").execute()
        h = {x["name"]: x["value"] for x in d["payload"]["headers"]}
        emails.append({"id": m["id"], "from": h.get("From"), "subject": h.get("Subject"),
                       "snippet": d.get("snippet")})
    return {"emails": emails}


@app.post("/watch")
def start_watch(x_api_key: str = Header(None)):
    if not API_SECRET or x_api_key != API_SECRET:
        raise HTTPException(401, "invalid api key")
    gmail, _ = get_services()
    body = {"labelIds": ["INBOX"], "topicName": f"projects/{GCP_PROJECT}/topics/{PUBSUB_TOPIC}"}
    return gmail.users().watch(userId="me", body=body).execute()


@app.post("/webhook/pubsub")
async def pubsub_push(request: Request):
    envelope = await request.json()
    msg_env = envelope.get("message", {})
    if not msg_env:
        return {"status": "ignored"}
    data = json.loads(base64.b64decode(msg_env.get("data", "e30=")).decode() or "{}")
    history_id = data.get("historyId")

    gmail, drive = get_services()
    ids = []
    if history_id:
        try:
            hist = gmail.users().history().list(userId="me", startHistoryId=history_id - 1).execute()
            ids = sorted({m["message"]["id"] for r in hist.get("history", [])
                          for m in r.get("messagesAdded", [])})
        except Exception:
            ids = []
    if not ids:
        latest = gmail.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=1).execute()
        ids = [m["id"] for m in latest.get("messages", [])]

    processed = []
    for msg_id in ids:
        msg = gmail.users().messages().get(userId="me", id=msg_id).execute()
        h = {x["name"]: x["value"] for x in msg["payload"]["headers"]}
        saved_files = []
        for part in (msg.get("payload") or {}).get("parts", []) or []:
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                att = gmail.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=part["body"]["attachmentId"]).execute()
                meta = {"name": part["filename"]}
                if GDRIVE_FOLDER_ID:
                    meta["parents"] = [GDRIVE_FOLDER_ID]
                media = MediaInMemoryUpload(
                    base64.urlsafe_b64decode(att["data"]), mimetype=part.get("mimeType", "text/plain"))
                saved_files.append(drive.files().create(body=meta, media_body=media,
                                                        fields="id,webViewLink").execute())
        payload = {"event": "new_email", "id": msg_id, "from": h.get("From"),
                   "subject": h.get("Subject"), "snippet": msg.get("snippet"),
                   "drive_attachments": saved_files}
        if LOLO_WEBHOOK_URL:
            requests.post(LOLO_WEBHOOK_URL, json=payload, timeout=5)
        processed.append(payload)
    return {"status": "processed", "count": len(processed), "messages": processed}
