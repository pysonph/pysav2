# 🟢 မြန်ဆန်ပြီး ပေါ့ပါးသော Python 3.11 Slim Version ကို အသုံးပြုပါမည်
FROM python:3.11-slim

# 🟢 Python Output များကို Render Log တွင် ချက်ချင်းမြင်ရစေရန်
ENV PYTHONUNBUFFERED=1

# 🟢 Container အတွင်းရှိ အလုပ်လုပ်မည့် နေရာ (Folder) ကို သတ်မှတ်ခြင်း
WORKDIR /app

# 🟢 System Updates နှင့် အခြေခံ Packages များ ထည့်သွင်းခြင်း
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 🟢 Requirements ဖိုင်ကို အရင် Copy ကူးပြီး Python Libraries များကို Install လုပ်ခြင်း
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 🟢 Playwright အတွက် Chromium Browser နှင့် လိုအပ်သော OS Dependencies များ အားလုံးကို Install လုပ်ခြင်း
RUN playwright install chromium --with-deps

# 🟢 ကျန်ရှိသော Bot Code များအားလုံးကို Container ထဲသို့ Copy ကူးထည့်ခြင်း
COPY . .

# 🟢 Bot ကို စတင် Run မည့် Command
CMD ["python3", "pysav2.py"]
