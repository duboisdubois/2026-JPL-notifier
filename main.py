import os
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify
from twilio.rest import Client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# --- Configuration (from environment variables) ---
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
YOUR_PHONE_NUMBER = os.environ.get("YOUR_PHONE_NUMBER")

JPL_TOURS_API = "https://www.jpl.nasa.gov/events/tours/api/tours/search"
TOUR_CATEGORY_ID = "1"  # Educational Group Tour
GROUP_SIZE = "40"

# Duplicate alert prevention: don't re-notify within this many seconds
COOLDOWN_SECONDS = 1800  # 30 minutes
_last_notified = None


def check_jpl_tours():
    """
    Query the JPL tours API for Educational Group Tour availability (40 visitors).

    Returns a tuple: (tours_found: bool, message: str)
    """
    try:
        log.info("Querying JPL tours API...")
        resp = requests.post(
            JPL_TOURS_API,
            json={
                "category_id": TOUR_CATEGORY_ID,
                "group_size": GROUP_SIZE,
                "pendingReservationId": None,
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        tours = data.get("public_tours", [])
        if tours:
            return True, f"{len(tours)} tour date(s) available!"

        return False, "No tours available"

    except Exception as e:
        log.error(f"Error checking JPL tours: {e}")
        return False, f"Error: {e}"


def send_call(message):
    """Place a voice call via Twilio that reads a message aloud."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, YOUR_PHONE_NUMBER]):
        log.error("Twilio credentials not configured. Set environment variables.")
        return False

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        twiml = f'<Response><Say voice="alice" loop="2">{message}</Say></Response>'
        call = client.calls.create(
            twiml=twiml,
            from_=TWILIO_PHONE_NUMBER,
            to=YOUR_PHONE_NUMBER,
        )
        log.info(f"Call placed! SID: {call.sid}")
        return True
    except Exception as e:
        log.error(f"Failed to place call: {e}")
        return False


@app.route("/check", methods=["GET", "POST"])
def check_endpoint():
    """Endpoint triggered by Cloud Scheduler to check for tours."""
    global _last_notified

    # Cooldown check
    now = datetime.now(timezone.utc)
    if _last_notified and (now - _last_notified).total_seconds() < COOLDOWN_SECONDS:
        log.info("Skipping check — still within notification cooldown period")
        return jsonify({"status": "skipped", "reason": "cooldown"}), 200

    tours_found, message = check_jpl_tours()
    log.info(f"Check result: tours_found={tours_found}, message={message}")

    if tours_found:
        call_message = (
            "Hi Alice! JPL Educational Group Tour dates are now available! "
            "Go to the JPL tours page and book immediately. Good luck!"
        )
        send_call(call_message)
        _last_notified = now
        return jsonify({"status": "found", "message": message}), 200

    return jsonify({"status": "not_found", "message": message}), 200


@app.route("/test-call", methods=["GET"])
def test_call_endpoint():
    """Place a test call to verify Twilio is configured correctly."""
    success = send_call("This is a test call from your JPL Tour Notifier. If you hear this, notifications are working!")
    if success:
        return jsonify({"status": "sent"}), 200
    return jsonify({"status": "failed"}), 500


@app.route("/", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "jpl-tour-notifier"}), 200


if __name__ == "__main__":
    # For local testing, run a single check
    import sys
    if "--test-call" in sys.argv:
        send_call("Test call from JPL Tour Notifier!")
    else:
        log.info("Running a one-time tour check...")
        found, msg = check_jpl_tours()
        log.info(f"Result: found={found}, message={msg}")
        if found:
            log.info("Tours found! Calling you...")
            send_call(
                "Hi Alice! JPL Educational Group Tour dates are now available! "
                "Go to the JPL tours page and book immediately. Good luck!"
            )
        else:
            log.info("No tours found at this time.")
