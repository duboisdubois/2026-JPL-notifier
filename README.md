The JPL notifier I built with a friend in 2024 stopped working. I wanted to experiment with Claude Code and I wanted to use Google Cloud instead of AWS so I started from scratch. 

This app is a lightweight Cloud Run service that polls JPL's internal tour availability API every 2 minutes via Cloud Scheduler. When the API returns available dates, it triggers a Twilio voice call for immediate notification.

The architecture is intentionally minimal — a single Python process making a POST request, with a 30-minute cooldown to prevent duplicate alerts. No database, no queue, no frontend. The entire Docker image is just a Python slim base with requests, flask, and twilio. It runs on 256MB of memory and stays well within GCP's free tier.
