# E-REDES Balcão Digital Meter

[![Home Assistant Add-on](https://img.shields.io/badge/Home%20Assistant-Add--on-blue?logo=home-assistant)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Home Assistant add-on that scrapes energy meter readings from the
[E-REDES Balcão Digital](https://balcaodigital.e-redes.pt) portal and publishes
them to Home Assistant via MQTT.

**Features:**
- Scrapes **vazio** (off-peak), **ponta** (peak), and **cheias** (standard) tariff readings
- Supports **multiple meters** via CPE numbers
- Publishes to MQTT topics — you control the HA entity definitions
- Configurable daily schedule (e.g. `07:00,12:00`)
- State tracking to prevent duplicate submissions
- Multi-arch: `aarch64` (RPi 4/5), `amd64` (NUC/x86)

---

## Requirements

- **Home Assistant OS** (HAOS) or Home Assistant Supervised
- **Mosquitto MQTT Broker** add-on (or any MQTT broker)
- An **E-REDES Balcão Digital** account
- Your **CPE number(s)** — found on your electricity bill or in the E-REDES portal

Playwright and Chromium are bundled inside the add-on container — no manual installation needed.

---

## Installation

### Via Custom Repository (recommended)

1. In Home Assistant: **Settings → Add-ons → Add-on Store**
2. Top right: **⋮ → Repositories**
3. Add: `https://github.com/Greg-null/ha_addon_eredes_balcao_digital`
4. Find **E-REDES Balcão Digital Meter** → **Install**

[![Open your Home Assistant instance and show the add add-on repository dialog with this repository pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FGreg-null%2Fha_addon_eredes_balcao_digital)

### Local Installation

1. Clone this repository into your Home Assistant addons folder:
   ```bash
   cd /addons
   git clone https://github.com/Greg-null/ha_addon_eredes_balcao_digital.git
   ```
2. In Home Assistant: **Settings → Add-ons → Add-on Store**
3. Top right: **⋮ → Check for updates**
4. Find **E-REDES Balcão Digital Meter** under **Local add-ons** → **Install**

---

## Configuration

After installing the add-on, go to its **Configuration** tab and fill in:

| Field | Description | Example |
|---|---|---|
| **NIF** | Your Portuguese tax ID | `123456789` |
| **Password** | E-REDES account password | `••••••••` |
| **Meters** | List of CPE numbers to scrape | `PT0002000012345678XX` |
| **Schedule times** | When to scrape (24h, comma-separated) | `07:00,12:00` |
| **MQTT Host** | MQTT broker hostname | `core-mosquitto` |
| **MQTT Port** | MQTT broker port | `1883` |
| **MQTT Username** | MQTT auth (optional) | |
| **MQTT Password** | MQTT auth (optional) | |
| **Run on startup** | Scrape immediately when add-on starts | `true` |

---

## MQTT Topics

For each configured meter, the add-on publishes to these topics (all retained):

| Topic | Payload | Description |
|---|---|---|
| `eredes/{cpe}/vazio` | `12345.678` | Off-peak reading (kWh) |
| `eredes/{cpe}/ponta` | `6789.012` | Peak reading (kWh) |
| `eredes/{cpe}/cheias` | `3456.789` | Standard reading (kWh) |
| `eredes/{cpe}/timestamp` | `15-03-2025` | Date of the reading |

Where `{cpe}` is the CPE number (e.g. `PT0002000012345678XX`).

---

## Setting Up Home Assistant Entities

Since this add-on uses plain MQTT publishing (no auto-discovery), you need to
define the sensor entities yourself. This gives you full control over entity IDs,
which is important if you have downstream energy meters and statistics depending
on stable entities.

### MQTT Sensors in configuration.yaml

Add the following to your `configuration.yaml` (replace the CPE number):

```yaml
mqtt:
  sensor:
    - name: "E-REDES Vazio"
      state_topic: "eredes/PT0002000012345678XX/vazio"
      unit_of_measurement: "kWh"
      device_class: energy
      state_class: total_increasing
      icon: mdi:moon-waning-crescent

    - name: "E-REDES Ponta"
      state_topic: "eredes/PT0002000012345678XX/ponta"
      unit_of_measurement: "kWh"
      device_class: energy
      state_class: total_increasing
      icon: mdi:flash-alert

    - name: "E-REDES Cheias"
      state_topic: "eredes/PT0002000012345678XX/cheias"
      unit_of_measurement: "kWh"
      device_class: energy
      state_class: total_increasing
      icon: mdi:flash

    - name: "E-REDES Timestamp"
      state_topic: "eredes/PT0002000012345678XX/timestamp"
      icon: mdi:clock-outline
```

After restarting Home Assistant, the sensors will appear under
**Developer Tools → States** as `sensor.e_redes_vazio`, etc.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Login fails | Wrong NIF or password | Check credentials in add-on configuration |
| No readings found | Data not yet available | E-REDES updates in the morning; try later |
| MQTT error | Wrong broker settings | Check Mosquitto add-on logs |
| Meter not found | Wrong CPE number | Verify CPE in E-REDES portal |
| Add-on crashes on start | Missing MQTT broker | Install Mosquitto add-on first |
| Duplicate readings | State file issue | Restart the add-on; it tracks daily submissions |

Check add-on logs: **Settings → Add-ons → E-REDES Balcão Digital Meter → Log**

---

## License

MIT – see [LICENSE](LICENSE)
