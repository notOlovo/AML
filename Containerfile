FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 AWS_REGION=eu-central-1
EXPOSE 8501
# real data is mounted at /app/data/real (see README); the synthetic sample is baked in
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
