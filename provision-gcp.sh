#!/bin/bash
# NOTE CORRECTION vs original blueprint: gmailmcp.googleapis.com and
# drivemcp.googleapis.com are NOT real Google APIs — leaving them in makes the
# whole `services enable` step fail. Removed. gmail+drive+pubsub+run+cloudbuild suffice.
set -euo pipefail
export PROJECT_ID="agent-lolo-mail-$(date +%s)"
export REGION="asia-southeast1"
export TOPIC_NAME="lolo-gmail-push"

gcloud projects create "$PROJECT_ID" --name="Agent Lolo Mail"
gcloud config set project "$PROJECT_ID"
gcloud billing projects link "$PROJECT_ID" --billing-account="YOUR_BILLING_ACCOUNT_ID"  # Cloud Build/Run need billing on
gcloud services enable \
  gmail.googleapis.com \
  drive.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com

gcloud pubsub topics create "$TOPIC_NAME"
gcloud pubsub topics add-iam-policy-binding "$TOPIC_NAME" \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
echo "Project Ready: $PROJECT_ID"
