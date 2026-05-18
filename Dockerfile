FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY weeknd_bca_bot.py .

CMD ["python", "weeknd_bca_bot.py", "--no-auto-open"]
