FROM python:3.12-slim-bookworm

# System deps for Playwright + pdftotext + curl (used by Revolut auth)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    poppler-utils \
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright chromium (skip system deps - we installed fonts manually)
RUN playwright install chromium

# Copy API code
COPY api.py .
COPY config.py .
COPY patch_scripts.py .

# Copy finance scripts (originals)
COPY revolut/ /app/revolut/

# Patch scripts for server paths at build time
ENV FINANCE_DATA_DIR=/data
ENV FINANCE_SRC_DIR=/app/revolut
ENV FINANCE_SCRIPTS_DIR=/app/scripts
RUN python patch_scripts.py

# Runtime
ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
