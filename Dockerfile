# AML Triage Copilot. Works with Docker and Podman, see README.md ("Run with Docker or Podman").
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AWS_REGION=eu-central-1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# code + the synthetic sample; the ČNB files (data/real) are mounted at run time, never baked in
COPY . .

EXPOSE 8501
# no --server.address: Streamlit then listens on IPv4 and IPv6, so both localhost and 127.0.0.1 work
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
