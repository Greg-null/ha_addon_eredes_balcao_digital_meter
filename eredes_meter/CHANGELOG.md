# Changelog

## 1.0.0 – Initial Release

### Added
- Scrapes energy meter readings from E-REDES Balcão Digital
- Extracts vazio (off-peak), ponta (peak), and cheias (standard) tariff values
- Supports multiple meters via CPE numbers
- Publishes readings to MQTT topics: `eredes/{cpe}/vazio|ponta|cheias|timestamp`
- Configurable daily schedule (comma-separated HH:MM times)
- Optional immediate scrape on add-on startup
- State tracking to prevent duplicate submissions per day
- Multi-arch support: aarch64 (RPi 4/5), amd64 (NUC/x86)
