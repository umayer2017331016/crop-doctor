# ফসল ডাক্তার — Hugging Face Spaces (Docker) হোস্টিং-এর জন্য
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# হোস্ট নিজেই https দেয়, তাই অ্যাপ http-তে চলবে
ENV NO_HTTPS=1
# Hugging Face Spaces 7860 পোর্ট ব্যবহার করে
ENV PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]
