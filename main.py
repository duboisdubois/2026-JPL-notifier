import os
import time
import logging
from datetime import datetime, timezone

from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from twilio.rest import Client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# --- Configuration (from environment variables) ---
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
YOUR_PHONE_NUMBER = os.environ.get("YOUR_PHONE_NUMBER")

JPL_TOURS_URL = "https://www.jpl.nasa.gov/events/tours/"
TOUR_TYPE = "Educational Group Tour"
NUM_VISITORS = "40"

# Duplicate alert prevention: don't re-notify within this many seconds
COOLDOWN_SECONDS = 1800  # 30 minutes
_last_notified = None


def create_driver():
    """Create a headless Chrome WebDriver."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    # In Docker, chromedriver is on PATH
    service = Service()
    return webdriver.Chrome(service=service, options=opts)


def check_jpl_tours():
    """
    Visit the JPL tours page, select Educational Group Tour with 40 visitors,
    and check if any tour dates are available.

    Returns a tuple: (tours_found: bool, message: str)
    """
    driver = create_driver()
    try:
        log.info("Navigating to JPL tours page...")
        driver.get(JPL_TOURS_URL)

        # Wait for the page to fully render (look for a form or select element)
        wait = WebDriverWait(driver, 30)

        # Step 1: Select the tour type dropdown
        log.info("Waiting for tour type dropdown...")
        tour_select_el = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "select"))
        )

        # Find the right select element — try to match by option text
        selects = driver.find_elements(By.CSS_SELECTOR, "select")
        tour_dropdown = None
        for sel in selects:
            options_text = [o.text for o in sel.find_elements(By.TAG_NAME, "option")]
            if any("educational" in o.lower() for o in options_text):
                tour_dropdown = sel
                break

        if not tour_dropdown:
            # Fallback: use the first select on the page
            log.warning("Could not find tour type dropdown by option text, using first select")
            tour_dropdown = selects[0] if selects else None

        if not tour_dropdown:
            return False, "Could not find any dropdown on the page"

        select = Select(tour_dropdown)
        # Try to select by visible text containing "Educational"
        for option in select.options:
            if "educational" in option.text.lower():
                select.select_by_visible_text(option.text)
                log.info(f"Selected tour type: {option.text}")
                break

        # Step 2: Enter number of visitors
        log.info("Looking for visitors input field...")
        # Look for an input field (number/text) near the form
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='number'], input[type='text']")
        visitor_input = None
        for inp in inputs:
            placeholder = inp.get_attribute("placeholder") or ""
            label_attr = inp.get_attribute("aria-label") or ""
            name = inp.get_attribute("name") or ""
            combined = f"{placeholder} {label_attr} {name}".lower()
            if any(kw in combined for kw in ["visitor", "group", "number", "size", "guests"]):
                visitor_input = inp
                break

        if not visitor_input and inputs:
            # Fallback: use the first number/text input
            visitor_input = inputs[0]

        if visitor_input:
            visitor_input.clear()
            visitor_input.send_keys(NUM_VISITORS)
            log.info(f"Entered {NUM_VISITORS} visitors")
        else:
            log.warning("Could not find visitor count input field")

        # Step 3: Submit the form / click search
        log.info("Looking for submit button...")
        buttons = driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit']")
        submit_btn = None
        for btn in buttons:
            btn_text = (btn.text or btn.get_attribute("value") or "").lower()
            if any(kw in btn_text for kw in ["search", "find", "submit", "check", "next", "go"]):
                submit_btn = btn
                break

        if submit_btn:
            submit_btn.click()
            log.info("Clicked submit button")
        else:
            # Try pressing Enter on the visitor input
            from selenium.webdriver.common.keys import Keys
            if visitor_input:
                visitor_input.send_keys(Keys.RETURN)
                log.info("Pressed Enter to submit")

        # Step 4: Wait for results and check for available dates
        time.sleep(5)  # Let the results load

        page_source = driver.page_source.lower()
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()

        # Check for indicators that NO tours are available
        no_tour_phrases = [
            "no tours available",
            "no dates available",
            "no upcoming tours",
            "currently no tours",
            "there are no tours",
            "tours are not available",
            "no results",
            "check back",
            "sold out",
            "fully booked",
        ]

        for phrase in no_tour_phrases:
            if phrase in page_text:
                return False, f"No tours available (found: '{phrase}')"

        # Check for indicators that tours ARE available (date-like patterns, booking buttons)
        availability_indicators = [
            "reserve",
            "book now",
            "register",
            "sign up",
            "select a date",
            "available dates",
            "choose a date",
        ]

        # Also look for date patterns or calendar elements
        import re
        date_pattern = re.compile(
            r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}"
        )
        has_dates = bool(date_pattern.search(page_text))

        has_availability_text = any(ind in page_text for ind in availability_indicators)

        # Look for clickable date/tour elements
        tour_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='tour'], .tour-date, .available-date")

        if has_dates or has_availability_text or len(tour_links) > 0:
            return True, "Tour dates appear to be available!"

        # If we can't determine either way, log the page content for debugging
        log.info(f"Page text (first 500 chars): {page_text[:500]}")
        return False, "Could not determine availability (no clear indicators found)"

    except Exception as e:
        log.error(f"Error checking JPL tours: {e}")
        return False, f"Error: {e}"
    finally:
        driver.quit()


def send_sms(message):
    """Send an SMS notification via Twilio."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, YOUR_PHONE_NUMBER]):
        log.error("Twilio credentials not configured. Set environment variables.")
        return False

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=YOUR_PHONE_NUMBER,
        )
        log.info(f"SMS sent! SID: {msg.sid}")
        return True
    except Exception as e:
        log.error(f"Failed to send SMS: {e}")
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
        sms_body = (
            "JPL TOUR ALERT! Educational Group Tour dates are now available! "
            "Book immediately: https://www.jpl.nasa.gov/events/tours/"
        )
        send_sms(sms_body)
        _last_notified = now
        return jsonify({"status": "found", "message": message}), 200

    return jsonify({"status": "not_found", "message": message}), 200


@app.route("/test-sms", methods=["GET"])
def test_sms_endpoint():
    """Send a test SMS to verify Twilio is configured correctly."""
    success = send_sms("Test message from JPL Tour Notifier. If you see this, notifications are working!")
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
    if "--test-sms" in sys.argv:
        send_sms("Test from JPL Tour Notifier!")
    else:
        log.info("Running a one-time tour check...")
        found, msg = check_jpl_tours()
        log.info(f"Result: found={found}, message={msg}")
        if found:
            log.info("Tours found! Sending SMS...")
            send_sms(
                "JPL TOUR ALERT! Educational Group Tour dates are now available! "
                "Book immediately: https://www.jpl.nasa.gov/events/tours/"
            )
        else:
            log.info("No tours found at this time.")
