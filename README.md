# LOLO Mail Bridge

Gmail send/read + Pub/Sub push (auto-save attachments to Drive) for Agent LOLO.

## Deploy options
1. **Cloud Run (needs billing account)** — `provision-gcp.sh`, then:
   `gcloud run deploy lolo-mail-server --source . --region asia-southeast1 --allow-unauthenticated --set-env-vars=...`
2. **Hugging Face Space (Docker SDK, NO card)** — new Space, SDK=Docker; set Secrets:
   `LOLO_API_SECRET`, `GMAIL_TOKEN_B64`, `GDRIVE_FOLDER_ID`, `GCP_PROJECT`, `PUBSUB_TOPIC`.
   Container listens on $PORT (7860 on HF). Gmail push still needs GCP Pub/Sub (free tier ok).

## Security model
- `GMAIL_TOKEN_B64` (base64 of token.json) is written to a runtime temp file only.
  token.json is NEVER copied into the image (fix vs original blueprint).
- Every sensitive endpoint requires the `x-api-key` header matching `LOLO_API_SECRET`.
- `/health` is public and reports configuration state without secrets.

## One-time owner steps (cannot be automated from this device)
1. GCP OAuth consent screen + Desktop client -> credentials.json (browser).
2. `python3 auth_setup.py` -> copy the printed `GMAIL_TOKEN_B64`.
3. (Cloud Run only) create Pub/Sub subscription + Cloud Scheduler POST /watch every 6 days.
   On HF Spaces: POST /watch manually once per 6 days, or expose /watch to a cron you control.
