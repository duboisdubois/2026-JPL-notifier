# JPL Tour Notifier — Setup Guide

This app checks JPL's tour page every minute and texts you when Educational Group Tour dates become available.

---

## 1. Set Up Twilio (for SMS notifications)

### Create a Twilio Account
1. Go to https://www.twilio.com/try-twilio and sign up for a free trial
2. Verify your email and phone number during sign-up

### Get Your Credentials
1. After sign-up, you'll land on the Twilio Console dashboard
2. Copy your **Account SID** and **Auth Token** from the dashboard (you'll need these later)

### Get a Twilio Phone Number
1. In the Console, go to **Phone Numbers** > **Manage** > **Buy a number**
2. Search for a number with SMS capability and click **Buy**
3. Copy this number (format: +1XXXXXXXXXX)

### Verify Your Personal Phone Number (trial accounts only)
1. Go to **Phone Numbers** > **Manage** > **Verified Caller IDs**
2. Add your personal phone number and complete the verification
3. Note: On a free trial, you can only send SMS to verified numbers

### Test It
You should now have these four values:
- `TWILIO_ACCOUNT_SID` — starts with "AC"
- `TWILIO_AUTH_TOKEN` — a long hex string
- `TWILIO_PHONE_NUMBER` — your Twilio number (+1XXXXXXXXXX)
- `YOUR_PHONE_NUMBER` — your personal cell (+1XXXXXXXXXX)

---

## 2. Set Up Google Cloud

### Create a Google Cloud Account
1. Go to https://console.cloud.google.com
2. Sign up (you get $300 free credit for 90 days)

### Install the gcloud CLI
On Mac:
```bash
brew install google-cloud-sdk
```
Or download from: https://cloud.google.com/sdk/docs/install

### Create a Project
```bash
gcloud auth login
gcloud projects create jpl-tour-notifier --name="JPL Tour Notifier"
gcloud config set project jpl-tour-notifier
```

### Enable Required APIs
```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com
```

### Create an Artifact Registry Repository (for Docker images)
```bash
gcloud artifacts repositories create jpl-notifier \
  --repository-format=docker \
  --location=us-central1
```

---

## 3. Deploy to Google Cloud Run

### Build and Push the Docker Image
From the `JPL-notifier/` directory:

```bash
# Configure Docker for Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build and push (Cloud Build does it remotely — no local Docker needed)
gcloud builds submit --tag us-central1-docker.pkg.dev/jpl-tour-notifier/jpl-notifier/jpl-tour-checker
```

### Deploy to Cloud Run
```bash
gcloud run deploy jpl-tour-checker \
  --image us-central1-docker.pkg.dev/jpl-tour-notifier/jpl-notifier/jpl-tour-checker \
  --region us-central1 \
  --platform managed \
  --memory 1Gi \
  --timeout 120 \
  --allow-unauthenticated \
  --set-env-vars "TWILIO_ACCOUNT_SID=ACxxxxxxxx,TWILIO_AUTH_TOKEN=your_token,TWILIO_PHONE_NUMBER=+1234567890,YOUR_PHONE_NUMBER=+1234567890"
```

Replace the placeholder values with your actual Twilio credentials.

After deployment, you'll get a URL like:
`https://jpl-tour-checker-xxxxx-uc.a.run.app`

### Test the Deployment
```bash
# Health check
curl https://jpl-tour-checker-xxxxx-uc.a.run.app/

# Test SMS delivery
curl https://jpl-tour-checker-xxxxx-uc.a.run.app/test-sms

# Run an actual tour check
curl https://jpl-tour-checker-xxxxx-uc.a.run.app/check
```

---

## 4. Set Up Cloud Scheduler (runs every minute)

### Create a Service Account for the Scheduler
```bash
gcloud iam service-accounts create scheduler-invoker \
  --display-name="Cloud Scheduler Invoker"

gcloud run services add-iam-policy-binding jpl-tour-checker \
  --region=us-central1 \
  --member="serviceAccount:scheduler-invoker@jpl-tour-notifier.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

### Create the Scheduled Job
```bash
gcloud scheduler jobs create http jpl-tour-check \
  --location=us-central1 \
  --schedule="* * * * *" \
  --uri="https://jpl-tour-checker-xxxxx-uc.a.run.app/check" \
  --http-method=GET \
  --oidc-service-account-email="scheduler-invoker@jpl-tour-notifier.iam.gserviceaccount.com"
```

Replace the URI with your actual Cloud Run URL from step 3.

The schedule `* * * * *` means every minute. You can adjust:
- `*/2 * * * *` — every 2 minutes
- `*/5 * * * *` — every 5 minutes

### Test the Scheduler
```bash
gcloud scheduler jobs run jpl-tour-check --location=us-central1
```

---

## 5. Monitor and Manage

### View Logs
```bash
gcloud run services logs read jpl-tour-checker --region=us-central1
```

### Pause the Scheduler (when you've booked your tour)
```bash
gcloud scheduler jobs pause jpl-tour-check --location=us-central1
```

### Resume the Scheduler
```bash
gcloud scheduler jobs resume jpl-tour-check --location=us-central1
```

### Update Twilio Credentials
```bash
gcloud run services update jpl-tour-checker \
  --region=us-central1 \
  --set-env-vars "TWILIO_ACCOUNT_SID=new_sid,TWILIO_AUTH_TOKEN=new_token,TWILIO_PHONE_NUMBER=+1234567890,YOUR_PHONE_NUMBER=+1234567890"
```

---

## Cost Estimate

- **Cloud Run**: Free tier includes 2 million requests/month. This app uses ~43,200/month (1/min). Well within free tier.
- **Cloud Scheduler**: Free tier includes 3 jobs. This uses 1.
- **Twilio**: Free trial gives you ~$15 credit. Each SMS costs ~$0.0079. You'll only be charged when a tour is actually found.
- **Cloud Build**: Free tier includes 120 build-minutes/day.

Total ongoing cost: essentially **$0** until you exceed free tiers or Twilio trial credit.
