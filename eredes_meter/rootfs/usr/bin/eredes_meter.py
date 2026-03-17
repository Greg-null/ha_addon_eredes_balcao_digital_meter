#!/usr/bin/env python3
"""
E-REDES Balcao Digital Meter -> MQTT
=====================================
Reads NIF/password and meter list from /data/options.json (populated by HAOS),
scrapes energy readings from E-REDES Balcao Digital using Selenium,
and publishes vazio/ponta/cheias values to MQTT topics.
"""

import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import paho.mqtt.client as mqtt
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

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


# ── Browser ──────────────────────────────────────────────────────────────────
def create_driver() -> webdriver.Chrome:
    """Create a headless Chrome/Chromium WebDriver using system binaries."""
    options = Options()
    options.binary_location = "/usr/bin/chromium-browser"
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1280,800")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    service = Service(executable_path="/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=options)


# ── Helpers ──────────────────────────────────────────────────────────────────
def wait_and_click(driver, by, value, timeout=60):
    """Wait for element to be clickable and click it."""
    el = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )
    el.click()
    return el


def wait_for_visible(driver, by, value, timeout=60):
    """Wait for element to be visible."""
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, value))
    )


# ── Scraper ──────────────────────────────────────────────────────────────────
def read_latest_reading(driver) -> dict:
    """Extract the newest row from the readings table."""
    first_row = WebDriverWait(driver, 120).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
    )
    cells = first_row.find_elements(By.TAG_NAME, "td")

    raw = {
        "timestamp": cells[2].text.strip(),
        "vazio": cells[5].text.strip(),
        "ponta": cells[6].text.strip(),
        "cheias": cells[7].text.strip(),
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

    driver = create_driver()

    try:
        # Step 1: Login
        log.info("Opening login page: %s", LOGIN_URL)
        driver.set_page_load_timeout(180)
        driver.get(LOGIN_URL)

        # Accept cookies (may not appear every time)
        try:
            cookie_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(., 'Aceitar todos os cookies')]")
                )
            )
            cookie_btn.click()
            log.info("Accepted cookies")
        except TimeoutException:
            log.info("No cookie dialog found, continuing")

        # Select Particular account type
        wait_and_click(driver, By.XPATH, "//*[contains(text(), 'Particular')]", timeout=30)

        # Fill credentials
        nif_field = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//input[@name='nif' or @placeholder='NIF' or @aria-label='NIF']")
            )
        )
        nif_field.clear()
        nif_field.send_keys(nif)

        pwd_field = driver.find_element(
            By.XPATH, "//input[@type='password' or @name='password' or @aria-label='Password']"
        )
        pwd_field.clear()
        pwd_field.send_keys(password)

        wait_and_click(driver, By.XPATH, "//button[contains(., 'Entrar')]")
        log.info("Login submitted")

        # Check for reCAPTCHA
        time.sleep(5)
        try:
            driver.find_element(By.XPATH, "//*[contains(text(), 'Validação de Segurança')]")
            log.error(
                "reCAPTCHA challenge detected. This usually means E-REDES "
                "flagged this IP as suspicious. From a residential IP (e.g. "
                "your Home Assistant), this should not appear."
            )
            raise RuntimeError("reCAPTCHA blocked login")
        except Exception as e:
            if "reCAPTCHA blocked login" in str(e):
                raise
            # Element not found = no reCAPTCHA, good

        # Step 2: Navigate to readings
        wait_and_click(driver, By.XPATH, "//h1[contains(., 'Os meus locais')] | //h2[contains(., 'Os meus locais')] | //h3[contains(., 'Os meus locais')] | //*[contains(@class, 'heading') and contains(., 'Os meus locais')]", timeout=120)
        log.info("Navigated to: Os meus locais")

        wait_and_click(driver, By.XPATH, "//*[contains(text(), 'Leituras')]", timeout=60)
        log.info("Navigated to: Leituras")

        wait_and_click(driver, By.XPATH, "//*[contains(text(), 'Consultar histórico')]", timeout=60)
        log.info("Navigated to: Consultar historico")

        # Step 3: For each meter, select it and read data
        for cpe in meters:
            try:
                log.info("Selecting meter: %s", cpe)
                meter_el = WebDriverWait(driver, 120).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, f"//*[contains(@class, 'alias') and contains(., '{cpe}')]")
                    )
                )
                meter_el.click()

                reading = read_latest_reading(driver)
                log.info(
                    "Reading for %s: vazio=%s ponta=%s cheias=%s (%s)",
                    cpe, reading["vazio"], reading["ponta"],
                    reading["cheias"], reading["timestamp"],
                )
                results[cpe] = reading

                # Navigate back for next meter
                if len(meters) > 1:
                    driver.back()
                    WebDriverWait(driver, 60).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//*[contains(text(), 'Consultar histórico')]")
                        )
                    )

            except Exception as e:
                log.error("Failed to scrape meter %s: %s", cpe, e)
                results[cpe] = None

    except Exception as e:
        log.error("Scrape failed: %s", e, exc_info=True)
        for cpe in meters:
            if cpe not in results:
                results[cpe] = None

    finally:
        driver.quit()

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
