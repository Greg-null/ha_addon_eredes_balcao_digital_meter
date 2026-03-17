# E-REDES Balcão Digital Meter – Documentation

Scrapes energy meter readings from the E-REDES Balcão Digital portal
and publishes them to Home Assistant via MQTT.

---

## Prerequisites

- **Mosquitto MQTT Broker** add-on installed and running
- An **E-REDES Balcão Digital** account at https://balcaodigital.e-redes.pt
- Your **CPE number(s)** — found on your electricity bill or in the E-REDES portal

---

## Configuration

### NIF and Password

Your Portuguese tax ID (NIF) and E-REDES account password. These are used to log into the Balcão Digital portal.

### Meter CPE Numbers

A list of CPE numbers to scrape. Each CPE identifies one electricity meter. You can find your CPE number on your electricity bill or in the E-REDES portal under "Os meus locais".

Example: `PT0002000012345678XX`

### Schedule

Comma-separated times in 24h format. E-REDES typically updates readings in the morning for the previous day.

```
07:00,12:00    → twice daily (recommended)
07:00          → once daily
```

### MQTT Settings

- **Host**: Use `core-mosquitto` if you use the built-in Mosquitto add-on
- **Port**: Default is `1883`
- **Username/Password**: Only needed if your MQTT broker requires authentication

---

## MQTT Topics

For each meter, the add-on publishes to these topics (all retained):

| Topic | Value | Unit |
|---|---|---|
| `eredes/{cpe}/vazio` | Off-peak reading | kWh |
| `eredes/{cpe}/ponta` | Peak reading | kWh |
| `eredes/{cpe}/cheias` | Standard reading | kWh |
| `eredes/{cpe}/timestamp` | Date of the reading | Date string |

Where `{cpe}` is the CPE number from your configuration.

---

## Setting Up HA Entities

Since this add-on uses plain MQTT (no auto-discovery), you need to create MQTT sensor entities manually. Add the following to your Home Assistant `configuration.yaml`:

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

Replace `PT0002000012345678XX` with your actual CPE number.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Login fails | Wrong NIF or password | Check credentials in add-on configuration |
| No readings found | Data not yet available | E-REDES updates readings in the morning; try again later |
| MQTT error | Wrong broker settings | Check Mosquitto add-on logs; verify host/port/credentials |
| Meter not found | Wrong CPE number | Verify CPE in E-REDES portal under "Os meus locais" |
| Add-on crashes on start | Missing MQTT broker | Install and start the Mosquitto add-on first |

---

## Support

Open an issue on [GitHub](https://github.com/Greg-null/ha_addon_eredes_balcao_digital_meter/issues).
