The app is a lightweight Cloud Run service that polls JPL's internal tour availability API every 2 minutes via Cloud Scheduler. When the API returns available dates, it triggers a Twilio voice call for immediate notification.

The architecture is intentionally minimal — a single Python process making a POST request, with a 30-minute cooldown to prevent duplicate alerts. No database, no queue, no frontend. The entire Docker image is just a Python slim base with requests, flask, and twilio. It runs on 256MB of memory and stays well within GCP's free tier.

We initially built it with Selenium and headless Chrome to scrape the JPL page, but by reverse-engineering their frontend we discovered an undocumented JSON API. Switching to a direct API call cut response time from ~30 seconds to under 400ms, reduced the container image size by an order of magnitude, and eliminated an entire class of failure modes around browser rendering and DOM parsing.
