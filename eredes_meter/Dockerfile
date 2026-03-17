ARG BUILD_FROM
FROM $BUILD_FROM

# Required OCI labels for HA Add-on Store
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Greg" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.source="https://github.com/Greg-null/ha_addon_eredes_balcao_digital_meter" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}

# System dependencies for Playwright on Debian
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Python packages
RUN pip3 install --no-cache-dir --break-system-packages \
    playwright==1.49.1 \
    playwright-stealth==2.0.2 \
    paho-mqtt==1.6.1

# Install Playwright's bundled Chromium + dependencies
RUN playwright install --with-deps chromium

# Add-on files
COPY rootfs /

RUN chmod a+x /etc/services.d/eredes_meter/run \
              /etc/services.d/eredes_meter/finish \
              /usr/bin/eredes_meter.py
