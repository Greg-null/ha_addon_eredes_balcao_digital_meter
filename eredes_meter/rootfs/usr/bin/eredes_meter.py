#!/usr/bin/env python3
"""
E-REDES Balcao Digital Meter -> MQTT
=====================================
Reads NIF/password and meter list from /data/options.json (populated by HAOS),
scrapes energy readings from E-REDES Balcao Digital using Playwright + Stealth,
and publishes vazio/ponta/cheias values to MQTT topics.
"""

import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import paho.mqtt.client as mqtt
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("eredes_meter")

OPTIONS_FILE = "/data/options.json"
STATE_FILE = Path("/data/last_success.json")
LOGIN_URL = "https://balcaodigital.e-redes.pt/login"
TARIFFS = ("vazio", "ponta", "cheias")


# ── Config ───────────────────────────────────────────────────────────────────
def load_options() -> dict:
    try:
        with open(OPTIONS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        log.error("Options file not found: %s", OPTIONS_FILE)
        sys.exit(1)
    except json.JSONDecodeError as e:
        log.error("Invalid JSON in options file: %s", e)
        sys.exit(1)


# ── State tracking ───────────────────────────────────────────────────────────
def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state))


def already_sent_today(state: dict, cpe: str) -> bool:
    return state.get(cpe) == date.today().isoformat()


def mark_sent_today(state: dict, cpe: str) -> dict:
    state[cpe] = date.today().isoformat()
    save_state(state)
    return state


# ── MQTT ─────────────────────────────────────────────────────────────────────
def mqtt_connect(cfg: dict) -> mqtt.Client:
    client = mqtt.Client(client_id="eredes_meter", clean_session=True)

    if cfg.get("mqtt_username"):
        client.username_pw_set(cfg["mqtt_username"], cfg.get("mqtt_password", ""))

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT connected successfully.")
        else:
            log.error("MQTT connection failed with code %d", rc)

    def on_disconnect(client, userdata, rc):
        if rc != 0:
            log.warning("Unexpected MQTT disconnect (rc=%d), will retry...", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    retries = 5
    for attempt in range(1, retries + 1):
        try:
            client.connect(cfg["mqtt_host"], cfg.get("mqtt_port", 1883), keepalive=60)
            client.loop_start()
            time.sleep(1)
            return client
        except Exception as e:
            log.warning("MQTT connect attempt %d/%d failed: %s", attempt, retries, e)
            if attempt < retries:
                time.sleep(5)

    log.error("Could not connect to MQTT broker after %d attempts.", retries)
    sys.exit(1)


def publish_readings(client: mqtt.Client, cpe: str, readings: dict):
    for key in TARIFFS:
        topic = f"eredes/{cpe}/{key}"
        value = readings.get(key, "unavailable")
        client.publish(topic, str(value), retain=True)
        log.info("  MQTT -> %s = %s", topic, value)

    topic = f"eredes/{cpe}/timestamp"
    client.publish(topic, readings.get("timestamp", ""), retain=True)
    log.info("  MQTT -> %s = %s", topic, readings.get("timestamp", ""))


# ── Scraper ──────────────────────────────────────────────────────────────────
def read_latest_reading(page) -> dict:
    """Extract the newest row from the readings table."""
    first_row = page.locator("table tbody tr").first
    first_row.wait_for(timeout=120_000)
    cells = first_row.locator("td")

    raw = {
        "timestamp": cells.nth(2).inner_text().strip(),
        "vazio": cells.nth(5).inner_text().strip(),
        "ponta": cells.nth(6).inner_text().strip(),
        "cheias": cells.nth(7).inner_text().strip(),
    }

    # Normalize decimal separators (Portuguese uses comma)
    for key in TARIFFS:
        raw[key] = raw[key].replace(",", ".").replace("\u00a0", "").replace(" ", "")

    return raw


def scrape_all_meters(cfg: dict) -> dict:
    """
    Login to E-REDES, navigate to readings, and scrape each meter.
    Returns {cpe: {timestamp, vazio, ponta, cheias}} or {cpe: None} on failure.
    """
    nif = cfg["nif"]
    password = cfg["password"]
    meters = cfg["meters"]

    log.info("Starting scrape run for %d meter(s)", len(meters))
    results = {}

    stealth = Stealth()
    with stealth.use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        try:
            # Step 1: Login
            log.info("Opening login page: %s", LOGIN_URL)
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=180_000)
            page.wait_for_timeout(3_000)

            # Accept cookies (may not appear every time)
            try:
                cookie_btn = page.get_by_role("button", name="Aceitar todos os cookies")
                cookie_btn.wait_for(timeout=10_000)
                cookie_btn.click()
                log.info("Accepted cookies")
            except PlaywrightTimeout:
                log.info("No cookie dialog found, continuing")

            # Select Particular account type
            page.get_by_text("Particular").wait_for(timeout=30_000)
            page.get_by_text("Particular").click()
            page.wait_for_timeout(3_000)

            # Fill credentials
            page.get_by_role("textbox", name="NIF").wait_for(timeout=30_000)
            page.get_by_role("textbox", name="NIF").fill(nif)
            page.get_by_role("textbox", name="Password").fill(password)
            page.get_by_role("button", name="Entrar").click()
            log.info("Login submitted")

            # Check for reCAPTCHA
            page.wait_for_timeout(5_000)
            if page.locator("text=Validação de Segurança").is_visible():
                log.error("reCAPTCHA challenge detected. This usually means E-REDES "
                          "flagged this IP as suspicious. From a residential IP (e.g. "
                          "your Home Assistant), this should not appear.")
                raise RuntimeError("reCAPTCHA blocked login")

            log.info("Login successful, URL: %s", page.url)

            # Step 2: Navigate to readings
            page.get_by_role("heading", name="Os meus locais").wait_for(timeout=120_000)
            page.get_by_role("heading", name="Os meus locais").click()
            log.info("Navigated to: Os meus locais")

            page.get_by_text("Leituras").wait_for(timeout=60_000)
            page.get_by_text("Leituras").click()
            log.info("Navigated to: Leituras")

            page.get_by_text("Consultar histórico").wait_for(timeout=60_000)
            page.get_by_text("Consultar histórico").click()
            log.info("Navigated to: Consultar historico")

            # Step 3: For each meter, select it and read data
            for cpe in meters:
                try:
                    log.info("Selecting meter: %s", cpe)
                    meter_elem = page.locator(f".alias:has-text('{cpe}')")
                    meter_elem.wait_for(timeout=120_000)
                    meter_elem.click()

                    reading = read_latest_reading(page)
                    log.info("Reading for %s: vazio=%s ponta=%s cheias=%s (%s)",
                             cpe, reading["vazio"], reading["ponta"],
                             reading["cheias"], reading["timestamp"])
                    results[cpe] = reading

                    # Navigate back for next meter
                    if len(meters) > 1:
                        page.go_back()
                        page.get_by_text("Consultar histórico").wait_for(timeout=60_000)

                except Exception as e:
                    log.error("Failed to scrape meter %s: %s", cpe, e)
                    results[cpe] = None

        except Exception as e:
            log.error("Scrape failed: %s", e, exc_info=True)
            try:
                log.error("Page URL at failure: %s", page.url)
            except Exception:
                pass
            for cpe in meters:
                if cpe not in results:
                    results[cpe] = None

        finally:
            context.close()
            browser.close()

    return results


# ── Scheduler ────────────────────────────────────────────────────────────────
def parse_times(times_str: str) -> list[tuple[int, int]]:
    result = []
    for t in times_str.split(","):
        h, m = t.strip().split(":")
        result.append((int(h), int(m)))
    return result


def next_run_at(targets: list[tuple[int, int]]) -> datetime:
    now = datetime.now().replace(second=0, microsecond=0)
    candidates = []
    for h, m in targets:
        candidate = now.replace(hour=h, minute=m)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return min(candidates)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("  E-REDES Balcao Digital Meter starting")
    log.info("=" * 60)

    cfg = load_options()

    # Connect to MQTT
    log.info("Connecting to MQTT at %s:%d...",
             cfg["mqtt_host"], cfg.get("mqtt_port", 1883))
    client = mqtt_connect(cfg)

    # Parse schedule
    schedule_times = parse_times(cfg["schedule_times"])
    log.info("Scheduled scrape times: %s", cfg["schedule_times"])

    def run_scrape():
        state = load_state()
        results = scrape_all_meters(cfg)
        for cpe, reading in results.items():
            if reading is None:
                log.warning("No data for meter %s, skipping publish", cpe)
                continue
            if already_sent_today(state, cpe):
                log.info("Already sent today for %s, skipping", cpe)
                continue
            publish_readings(client, cpe, reading)
            state = mark_sent_today(state, cpe)

    # Optional immediate run at startup
    if cfg.get("run_on_startup", True):
        log.info("Running immediate scrape on startup...")
        run_scrape()

    # Main scheduling loop
    while True:
        next_run = next_run_at(schedule_times)
        wait_secs = (next_run - datetime.now()).total_seconds()
        log.info("Next run: %s (in %dh %dm)",
                 next_run.strftime("%Y-%m-%d %H:%M"),
                 int(wait_secs // 3600),
                 int((wait_secs % 3600) // 60))
        time.sleep(max(wait_secs, 1))

        log.info("-" * 40)
        log.info("Scheduled scrape run starting...")
        run_scrape()


if __name__ == "__main__":
    main()
