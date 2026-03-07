FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# DrissionPage အတွက် လိုအပ်သော Chromium ကို သွင်းခြင်း
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    chromium \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# သင့်ရဲ့ Run မည့် Python ဖိုင်နာမည် မှန်ကန်ကြောင်း သေချာစစ်ဆေးပါ (ဥပမာ - main.py သို့မဟုတ် test.py)
CMD ["python", "webmain.py"]
