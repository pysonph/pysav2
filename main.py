import io
import os
import re
import datetime
import time
from aiogram.filters import Command, or_f
from bs4 import BeautifulSoup
import random
from dotenv import load_dotenv
import asyncio
from playwright.async_api import async_playwright
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import types
import html
from collections import defaultdict
import concurrent.futures

# 🟢 curl_cffi ကို Import လုပ်ခြင်း (Cloudflare ကိုကျော်ရန်)
from curl_cffi import requests as cffi_requests

# 🟢 Aiogram 3 Imports
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BufferedInputFile

import database as db

# ==========================================
# 📌 ENVIRONMENT VARIABLES
# ==========================================
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
# API_ID နှင့် API_HASH တို့သည် Aiogram တွင် မလိုအပ်ပါ။
OWNER_ID = int(os.getenv('OWNER_ID', 1318826936)) 
FB_EMAIL = os.getenv('FB_EMAIL')
FB_PASS = os.getenv('FB_PASS')

if not BOT_TOKEN:
    print("❌ Error: BOT_TOKEN is missing in the .env file.")
    exit()

MMT = datetime.timezone(datetime.timedelta(hours=6, minutes=30))

# 🟢 Initialize Aiogram Bot & Dispatcher
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==========================================
# 🚀 ADVANCED CONCURRENCY & LOCK SYSTEM
# ==========================================
user_locks = defaultdict(asyncio.Lock)
api_semaphore = asyncio.Semaphore(3) 
auth_lock = asyncio.Lock()  # 🟢 Auto-login ပြိုင်တူမဝင်စေရန် Lock
last_login_time = 0         # 🟢 နောက်ဆုံး Login ဝင်ခဲ့သည့် အချိန်ကို မှတ်ထားရန်

# ==========================================
# 🍪 MAIN SCRAPER (CURL_CFFI FOR CLOUDFLARE BYPASS)
# ==========================================
async def get_main_scraper():
    raw_cookie = await db.get_main_cookie()
    cookie_dict = {}
    if raw_cookie:
        for item in raw_cookie.split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                cookie_dict[k.strip()] = v.strip()
                
    # 🟢 curl_cffi ဖြင့် Chrome 120 အဖြစ် ဟန်ဆောင်မည် (Cloudflare ကို အလွယ်တကူ ကျော်ဖြတ်နိုင်ရန်)
    scraper = cffi_requests.Session(impersonate="chrome120", cookies=cookie_dict)
    return scraper

# ==========================================
# 🤖 PLAYWRIGHT AUTO-LOGIN (FACEBOOK) [LOCKED & SAFE]
# ==========================================
async def auto_login_and_get_cookie():
    global last_login_time
    
    if not FB_EMAIL or not FB_PASS:
        print("❌ FB_EMAIL and FB_PASS are missing in .env.")
        return False
        
    # 🟢 သော့ခတ်ပါမည် (လူအများ ပြိုင်တူ Login ဝင်ခြင်းကို တားဆီးမည်)
    async with auth_lock:
        # 🟢 Double-Checked Locking (လွန်ခဲ့သော ၂ မိနစ်အတွင်း Login အောင်မြင်ထားလျှင် ထပ်မဝင်ပါ)
        if time.time() - last_login_time < 120:
            print("✅ ရှေ့ကလူ Cookie အသစ်ယူပေးသွားလို့ Login ထပ်ဝင်စရာမလိုတော့ပါ။")
            return True

        print("Logging in with Facebook to fetch new Cookie...")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True, 
                    args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={'width': 1280, 'height': 720}
                )
                page = await context.new_page()
                
                await page.goto("https://www.smile.one/customer/login")
                await asyncio.sleep(5) 
                
                async with context.expect_page() as popup_info:
                    await page.locator("a.login-btn-facebook, a[href*='facebook.com']").first.click()
                
                fb_popup = await popup_info.value
                await fb_popup.wait_for_load_state()
                
                await asyncio.sleep(2)
                await fb_popup.fill('input[name="email"]', FB_EMAIL)
                await asyncio.sleep(1)
                await fb_popup.fill('input[name="pass"]', FB_PASS)
                await asyncio.sleep(1)
                
                await fb_popup.click('button[name="login"], input[name="login"]')
                
                try:
                    await page.wait_for_url("**/customer/order**", timeout=30000)
                    print("✅ Auto-Login successful. Saving Cookie...")
                    
                    cookies = await context.cookies()
                    cookie_dict = {cookie['name']: cookie['value'] for cookie in cookies}
                    raw_cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
                    
                    await db.update_main_cookie(raw_cookie_str)
                    await browser.close()
                    
                    # 🟢 အောင်မြင်သွားလျှင် နောက်ဆုံး Login ဝင်ခဲ့သည့် အချိန်ကို မှတ်ထားပါမည်
                    last_login_time = time.time()
                    return True
                    
                except Exception as wait_e:
                    print(f"❌ Did not reach the Order page. (Possible Facebook Checkpoint): {wait_e}")
                    await browser.close()
                    return False
                
        except Exception as e:
            print(f"❌ Error during Auto-Login: {e}")
            return False

# ==========================================
# 📌 PACKAGES
# ==========================================
DOUBLE_DIAMOND_PACKAGES = {
    '55': [{'pid': '22590', 'price': 39.0, 'name': '50+50 💎'}],
    '165': [{'pid': '22591', 'price': 116.9, 'name': '150+150 💎'}],
    '275': [{'pid': '22592', 'price': 187.5, 'name': '250+250 💎'}],
    '565': [{'pid': '22593', 'price': 385, 'name': '500+500 💎'}],
}

BR_PACKAGES = {
    '86': [{'pid': '13', 'price': 61.5, 'name': '86 💎'}],
    '172': [{'pid': '23', 'price': 122.0, 'name': '172 💎'}],
    '257': [{'pid': '25', 'price': 177.5, 'name': '257 💎'}],
    '343': [{'pid': '13', 'price': 61.5, 'name': '86 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}],
    '429': [{'pid': '23', 'price': 122.0, 'name': '86 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}],
    '514': [{'pid': '25', 'price': 177.5, 'name': '257 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}],
    '600': [{'pid': '13', 'price': 61.5, 'name': '86 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}],
    '706': [{'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '878': [{'pid': '23', 'price': 122.0, 'name': '172 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '963': [{'pid': '25', 'price': 177.5, 'name': '257 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '1049': [{'pid': '13', 'price': 61.5, 'name': '86 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '1135': [{'pid': '23', 'price': 122.0, 'name': '172 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '1412': [{'pid': '26', 'price': 480.0, 'name': '706 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '1584': [{'pid': '23', 'price': 122.0, 'name': '172 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '1755': [{'pid': '13', 'price': 61.5, 'name': '86 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '2195': [{'pid': '27', 'price': 1453.0, 'name': '2195 💎'}],
    '2538': [{'pid': '13', 'price': 61.5, 'name': '86 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}, {'pid': '27', 'price': 1453.0, 'name': '2195 💎'}],
    '2901': [{'pid': '27', 'price': 1453.0, 'name': '2195 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}],
    '3244': [{'pid': '13', 'price': 61.5, 'name': '86 💎'}, {'pid': '25', 'price': 177.5, 'name': '257 💎'}, {'pid': '26', 'price': 480.0, 'name': '706 💎'}, {'pid': '27', 'price': 1453.0, 'name': '2195 💎'}],
    '3688': [{'pid': '28', 'price': 2424.0, 'name': '3688 💎'}],
    '5532': [{'pid': '29', 'price': 3660.0, 'name': '5532 💎'}],
    '9288': [{'pid': '30', 'price': 6079.0, 'name': '9288 💎'}],
    'meb': [{'pid': '26556', 'price': 196.5, 'name': 'Epic Monthly Package'}],
    'tp': [{'pid': '33', 'price': 402.5, 'name': 'Twilight Passage'}],
    'web': [{'pid': '26555', 'price': 39.0, 'name': 'Elite Weekly Paackage'}],
    'wp': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
    'wp2': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
    'wp3': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
    'wp4': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
    'wp5': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
    'wp6': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
    'wp7': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
    'wp8': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
    'wp9': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}],
   'wp10': [{'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}, {'pid': '16642', 'price': 76.0, 'name': 'Weekly Pass'}]
}

PH_PACKAGES = {
    '11': [{'pid': '212', 'price': 9.50, 'name': '11 💎'}],
    '22': [{'pid': '213', 'price': 19.00, 'name': '22 💎'}],
    '33': [{'pid': '213', 'price': 19.00, 'name': '22 💎'}, {'pid': '212', 'price': 9.50, 'name': '11 💎'}],
    '44': [{'pid': '213', 'price': 19.00, 'name': '22 💎'}, {'pid': '213', 'price': 19.00, 'name': '22 💎'}],
    '56': [{'pid': '214', 'price': 47.50, 'name': '56 💎'}],
    '112': [{'pid': '215', 'price': 95.00, 'name': '112 💎'}],
    '223': [{'pid': '216', 'price': 190.00, 'name': '223 💎'}],
    '336': [{'pid': '217', 'price': 285.00, 'name': '336 💎'}],
    '570': [{'pid': '218', 'price': 475.00, 'name': '570 💎'}],
    '1163': [{'pid': '219', 'price': 950.00, 'name': '1163 💎'}],
    '2398': [{'pid': '220', 'price': 1900.00, 'name': '2398 💎'}],
    '6042': [{'pid': '221', 'price': 4750.00, 'name': '6042 💎'}],
    'tp': [{'pid': '214', 'price': 475.00, 'name': 'twilight pass 💎'}],
    'wp': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp2': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp3': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp4': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp5': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp6': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp7': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp8': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp9': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
    'wp10': [{'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}, {'pid': '16641', 'price': 95.00, 'name': 'Weekly Pass'}],
}

MCC_PACKAGES = {
    '86': [{'pid': '23825', 'price': 62.5, 'name': '86 💎'}],
    '172': [{'pid': '23826', 'price': 125.0, 'name': '172 💎'}],
    '257': [{'pid': '23827', 'price': 187.0, 'name': '257 💎'}],
    '343': [{'pid': '23828', 'price': 250.0, 'name': '343 💎'}],
    '429': [{'pid': '23826', 'price': 122.0, 'name': '172 💎'}, {'pid': '23827', 'price': 187.0, 'name': '257 💎'}],
    '516': [{'pid': '23829', 'price': 375.0, 'name': '516 💎'}],
    '600': [{'pid': '23825', 'price': 62.5, 'name': '86 💎'}, {'pid': '23827', 'price': 187.0, 'name': '257 💎'}, {'pid': '23827', 'price': 177.5, 'name': '257 💎'}],
    '706': [{'pid': '23830', 'price': 500.0, 'name': '706 💎'}],
    '878': [{'pid': '23826', 'price': 125.0, 'name': '172 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}],
    '963': [{'pid': '23827', 'price': 187.0, 'name': '257 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}],
    '1049': [{'pid': '23825', 'price': 62.5, 'name': '86 💎'}, {'pid': '23827', 'price': 187.0, 'name': '257 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}],
    '1135': [{'pid': '23826', 'price': 125.0, 'name': '172 💎'}, {'pid': '23827', 'price': 187.0, 'name': '257 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}],
    '1346': [{'pid': '23831', 'price': 937.5, 'name': '1346 💎'}],
    '1412': [{'pid': '23830', 'price': 500.0, 'name': '706 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}],
    '1584': [{'pid': '23826', 'price': 125.0, 'name': '172 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}, {'pid': '23830', 'price': 480.0, 'name': '706 💎'}],
    '1755': [{'pid': '23825', 'price': 62.5, 'name': '86 💎'}, {'pid': '23827', 'price': 187.0, 'name': '257 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}],
    '1825': [{'pid': '23832', 'price': 1250.0, 'name': '1825 💎'}],
    '2195': [{'pid': '23833', 'price': 1500.0, 'name': '2195 💎'}],
    '2538': [{'pid': '23825', 'price': 62.5, 'name': '86 💎'}, {'pid': '23827', 'price': 187.0, 'name': '257 💎'}, {'pid': '23833', 'price': 1500.0, 'name': '2195 💎'}],
    '2901': [{'pid': '23833', 'price': 1500.0, 'name': '2195 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}],
    '3244': [{'pid': '23825', 'price': 62.5, 'name': '86 💎'}, {'pid': '23827', 'price': 187.0, 'name': '257 💎'}, {'pid': '23830', 'price': 500.0, 'name': '706 💎'}, {'pid': '23833', 'price': 1500.0, 'name': '2195 💎'}],
    '3688': [{'pid': '23834', 'price': 2500.0, 'name': '3688 💎'}],
    '5532': [{'pid': '23835', 'price': 3750.0, 'name': '5532 💎'}],
    '9288': [{'pid': '23836', 'price': 6250.0, 'name': '9288 💎'}],
    'b150': [{'pid': '23838', 'price': 120.0, 'name': '150+150 💎'}],
    'b250': [{'pid': '23839', 'price': 200.0, 'name': '250+250 💎'}],
    'b50': [{'pid': '23837', 'price': 40.0, 'name': '50+50 💎'}],
    'b500': [{'pid': '23840', 'price': 400, 'name': '500+500 💎'}],
    'wp': [{'pid': '23841', 'price': 99.90, 'name': 'Weekly Pass'}],
}

PH_MCC_PACKAGES = {
    '5': [{'pid': '23906', 'price': 4.75, 'name': '5 💎'}],
    '11': [{'pid': '23907', 'price': 9.03, 'name': '11 💎'}],
    '22': [{'pid': '23908', 'price': 18.05, 'name': '22 💎'}],
    '56': [{'pid': '23909', 'price': 45.13, 'name': '56 💎'}],
    '112': [{'pid': '23910', 'price': 90.25, 'name': '112 💎'}],
    '223': [{'pid': '23911', 'price': 180.50, 'name': '223 💎'}],
    '339': [{'pid': '23912', 'price': 270.75, 'name': '339 💎'}],
    '570': [{'pid': '23913', 'price': 451.25, 'name': '578 💎'}],
    '1163': [{'pid': '23914', 'price': 902.50, 'name': '1163 💎'}],
    '2398': [{'pid': '23915', 'price': 1805.00, 'name': '2398 💎'}],
    '6042': [{'pid': '23916', 'price': 4512.50, 'name': '6042 💎'}],
    'wp': [{'pid': '23922', 'price': 95.00, 'name': 'wp 💎'}],
    'lukas': [{'pid': '25600', 'price': 47.45, 'name': 'lukas battle bounty💎'}],
    'battlefordiscounts': [{'pid': '25601', 'price': 47.45, 'name': 'battlefordiscounts 💎'}],
}

# ==========================================
# 2. FUNCTION TO GET REAL BALANCE
# ==========================================
async def get_smile_balance(scraper, headers, balance_url='https://www.smile.one/customer/order'):
    balances = {'br_balance': 0.00, 'ph_balance': 0.00}
    try:
        response = await asyncio.to_thread(scraper.get, balance_url, headers=headers, timeout=15)
        
        br_match = re.search(r'(?i)(?:Balance|Saldo)[\s:]*?<\/p>\s*<p>\s*([\d\.,]+)', response.text)
        if br_match: balances['br_balance'] = float(br_match.group(1).replace(',', ''))
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            main_balance_div = soup.find('div', class_='balance-coins')
            if main_balance_div:
                p_tags = main_balance_div.find_all('p')
                if len(p_tags) >= 2: balances['br_balance'] = float(p_tags[1].text.strip().replace(',', ''))
                    
        ph_match = re.search(r'(?i)Saldo PH[\s:]*?<\/span>\s*<span>\s*([\d\.,]+)', response.text)
        if ph_match: balances['ph_balance'] = float(ph_match.group(1).replace(',', ''))
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            ph_balance_container = soup.find('div', id='all-balance')
            if ph_balance_container:
                span_tags = ph_balance_container.find_all('span')
                if len(span_tags) >= 2: balances['ph_balance'] = float(span_tags[1].text.strip().replace(',', ''))
    except Exception as e: 
        print(f"Error fetching balance from site: {e}")
    return balances

# ==========================================
# 3. FAST SMILE.ONE SCRAPER FUNCTION (MLBB) [SPEED OPTIMIZED]
# ==========================================
async def process_smile_one_order(game_id, zone_id, product_id, currency_name, prev_context=None, skip_checkrole=False):
    scraper = await get_main_scraper()

    if currency_name == 'PH':
        main_url = 'https://www.smile.one/ph/merchant/mobilelegends'
        checkrole_url = 'https://www.smile.one/ph/merchant/mobilelegends/checkrole'
        query_url = 'https://www.smile.one/ph/merchant/mobilelegends/query'
        pay_url = 'https://www.smile.one/ph/merchant/mobilelegends/pay'
    else:
        main_url = 'https://www.smile.one/merchant/mobilelegends'
        checkrole_url = 'https://www.smile.one/merchant/mobilelegends/checkrole'
        query_url = 'https://www.smile.one/merchant/mobilelegends/query'
        pay_url = 'https://www.smile.one/merchant/mobilelegends/pay'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Requested-With': 'XMLHttpRequest', 
        'Referer': main_url, 
        'Origin': 'https://www.smile.one'
    }

    try:
        csrf_token = None
        ig_name = "Unknown"
        
        # 🟢 Context ရှိနေပါက Token ကိုသာ ပြန်လည်အသုံးပြုမည်
        if prev_context: csrf_token = prev_context.get('csrf_token')

        if not csrf_token:
            response = await asyncio.to_thread(scraper.get, main_url, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            meta_tag = soup.find('meta', {'name': 'csrf-token'})
            if meta_tag: csrf_token = meta_tag.get('content')
            else:
                csrf_input = soup.find('input', {'name': '_csrf'})
                if csrf_input: csrf_token = csrf_input.get('value')

            if not csrf_token: return {"status": "error", "message": "CSRF Token not found. Re-add Cookie."}

        # 🟢 1. Check Role (skip_checkrole ကို စစ်ဆေးမည်)
        if not skip_checkrole:
            check_data = {'user_id': game_id, 'zone_id': zone_id, '_csrf': csrf_token}
            role_response_raw = await asyncio.to_thread(scraper.post, checkrole_url, data=check_data, headers=headers)
            try:
                role_result = role_response_raw.json()
                ig_name = role_result.get('username') or role_result.get('data', {}).get('username')
                if not ig_name or str(ig_name).strip() == "":
                    return {"status": "error", "message": "❌ Invalid Account: Account not found."}
            except Exception: return {"status": "error", "message": "Check Role API Error: Cannot verify account."}
        else:
            ig_name = "Skipped" # ကျော်သွားပါက အလွတ်သတ်မှတ်မည်

        # 🟢 2. Query (Request Flow ID)
        query_data = {'user_id': game_id, 'zone_id': zone_id, 'pid': product_id, 'checkrole': '', 'pay_methond': 'smilecoin', 'channel_method': 'smilecoin', '_csrf': csrf_token}
        query_response_raw = await asyncio.to_thread(scraper.post, query_url, data=query_data, headers=headers)
        
        try: query_result = query_response_raw.json()
        except Exception: return {"status": "error", "message": "Query API Error"}
            
        flowid = query_result.get('flowid') or query_result.get('data', {}).get('flowid')
        
        if not flowid:
            real_error = query_result.get('msg') or query_result.get('message') or ""
            if "login" in str(real_error).lower() or "unauthorized" in str(real_error).lower():
                await notify_owner("⚠️ <b>Order Alert:</b> Cookie သက်တမ်းကုန်သွားပါပြီ။ အော်ဒါဝယ်နေစဉ် Auto-login စတင်နေပါသည်...")
                success = await auto_login_and_get_cookie()
                if success: return {"status": "error", "message": "Session renewed. Please try again."}
                else: return {"status": "error", "message": "❌ Auto-Login failed. Please /setcookie."}
            return {"status": "error", "message": f"❌ Query Failed: {real_error}"}

        # 🟢 3. Pay (Order History ကို ကျော်ဖြတ်ပြီး တိုက်ရိုက်ပေးချေမည်)
        pay_data = {'_csrf': csrf_token, 'user_id': game_id, 'zone_id': zone_id, 'pay_methond': 'smilecoin', 'product_id': product_id, 'channel_method': 'smilecoin', 'flowid': flowid, 'email': '', 'coupon_id': ''}
        pay_response_raw = await asyncio.to_thread(scraper.post, pay_url, data=pay_data, headers=headers)
        pay_text = pay_response_raw.text.lower()
        
        if "saldo insuficiente" in pay_text or "insufficient" in pay_text:
            return {"status": "error", "message": "Insufficient balance in the Main Smile.one account."}
        
        is_success = False
        # 🟢 Flow ID ကို သုံး၍ အမြန် Order ID ဖန်တီးခြင်း
        real_order_id = f"FAST-{flowid}" 

        try:
            pay_json = pay_response_raw.json()
            code, msg = str(pay_json.get('code', '')), str(pay_json.get('msg', '')).lower()
            if code in ['200', '0', '1'] or 'success' in msg: 
                is_success = True
            else: 
                return {"status": "error", "message": pay_json.get('msg', 'Payment failed.')}
        except:
            if 'success' in pay_text or 'sucesso' in pay_text: 
                is_success = True

        if is_success:
            return {
                "status": "success", 
                "ig_name": ig_name, 
                "order_id": real_order_id, 
                "csrf_token": csrf_token, 
                "product_name": "" 
            }
        else:
            return {"status": "error", "message": "Payment Verification Failed."}

    except Exception as e: return {"status": "error", "message": f"System Error: {str(e)}"}

# 🌟 3.1 FAST MAGIC CHESS SCRAPER FUNCTION [SPEED OPTIMIZED]
async def process_mcc_order(game_id, zone_id, product_id, currency_name, prev_context=None, skip_checkrole=False):
    scraper = await get_main_scraper()

    if currency_name == 'PH':
        main_url = 'https://www.smile.one/ph/merchant/game/magicchessgogo'
        checkrole_url = 'https://www.smile.one/ph/merchant/game/checkrole'
        query_url = 'https://www.smile.one/ph/merchant/game/query'
        pay_url = 'https://www.smile.one/ph/merchant/game/pay'
    else:
        main_url = 'https://www.smile.one/br/merchant/game/magicchessgogo'
        checkrole_url = 'https://www.smile.one/br/merchant/game/checkrole'
        query_url = 'https://www.smile.one/br/merchant/game/query'
        pay_url = 'https://www.smile.one/br/merchant/game/pay'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Requested-With': 'XMLHttpRequest', 
        'Referer': main_url, 
        'Origin': 'https://www.smile.one'
    }

    try:
        csrf_token = None
        ig_name = "Unknown"
        
        # 🟢 Context ရှိနေပါက Token ကိုသာ ပြန်လည်အသုံးပြုမည်
        if prev_context:
            csrf_token = prev_context.get('csrf_token')

        if not csrf_token:
            response = await asyncio.to_thread(scraper.get, main_url, headers=headers)
            if response.status_code in [403, 503] or "cloudflare" in response.text.lower():
                 return {"status": "error", "message": "Blocked by Cloudflare."}

            soup = BeautifulSoup(response.text, 'html.parser')
            meta_tag = soup.find('meta', {'name': 'csrf-token'})
            if meta_tag: csrf_token = meta_tag.get('content')
            else:
                csrf_input = soup.find('input', {'name': '_csrf'})
                if csrf_input: csrf_token = csrf_input.get('value')

            if not csrf_token: return {"status": "error", "message": "CSRF Token not found. Add a new Cookie using /setcookie."}

        # 🟢 1. Check Role (skip_checkrole ကို စစ်ဆေးမည်)
        if not skip_checkrole:
            check_data = {'user_id': game_id, 'zone_id': zone_id, '_csrf': csrf_token}
            role_response_raw = await asyncio.to_thread(scraper.post, checkrole_url, data=check_data, headers=headers)
            try:
                role_result = role_response_raw.json()
                ig_name = role_result.get('username') or role_result.get('data', {}).get('username')
                if not ig_name or str(ig_name).strip() == "":
                    return {"status": "error", "message": " Account not found."}
            except Exception: return {"status": "error", "message": "⚠️ Check Role API Error: Cannot verify account."}
        else:
            ig_name = "Skipped" # ကျော်သွားပါက အလွတ်သတ်မှတ်မည်

        # 🟢 2. Query
        query_data = {'user_id': game_id, 'zone_id': zone_id, 'pid': product_id, 'checkrole': '', 'pay_methond': 'smilecoin', 'channel_method': 'smilecoin', '_csrf': csrf_token}
        query_response_raw = await asyncio.to_thread(scraper.post, query_url, data=query_data, headers=headers)
        
        try: query_result = query_response_raw.json()
        except Exception: return {"status": "error", "message": "Query API Error"}
            
        flowid = query_result.get('flowid') or query_result.get('data', {}).get('flowid')
        
        if not flowid:
            real_error = query_result.get('msg') or query_result.get('message') or ""
            if "login" in str(real_error).lower() or "unauthorized" in str(real_error).lower():
                await notify_owner("⚠️ <b>Order Alert:</b> Cookie သက်တမ်းကုန်သွားပါပြီ။ အော်ဒါဝယ်နေစဉ် Auto-login စတင်နေပါသည်...")
                success = await auto_login_and_get_cookie()
                if success:
                    return {"status": "error", "message": "Session renewed. Please enter the command again."}
                else: 
                    return {"status": "error", "message": "❌ Auto-Login failed. Please provide /setcookie again."}
            return {"status": "error", "message": "Invalid account or unable to purchase."}

        # 🟢 3. Pay (Order History ကို ကျော်ဖြတ်ပြီး တိုက်ရိုက်ပေးချေမည်)
        pay_data = {'_csrf': csrf_token, 'user_id': game_id, 'zone_id': zone_id, 'pay_methond': 'smilecoin', 'product_id': product_id, 'channel_method': 'smilecoin', 'flowid': flowid, 'email': '', 'coupon_id': ''}
        pay_response_raw = await asyncio.to_thread(scraper.post, pay_url, data=pay_data, headers=headers)
        pay_text = pay_response_raw.text.lower()
        
        if "saldo insuficiente" in pay_text or "insufficient" in pay_text:
            return {"status": "error", "message": "Insufficient balance in the Main account."}
        
        is_success = False
        # 🟢 Flow ID ကို သုံး၍ အမြန် Order ID ဖန်တီးခြင်း
        real_order_id = f"FAST-{flowid}"

        try:
            pay_json = pay_response_raw.json()
            code, msg = str(pay_json.get('code', '')), str(pay_json.get('msg', '')).lower()
            if code in ['200', '0', '1'] or 'success' in msg: 
                is_success = True
            else: 
                return {"status": "error", "message": pay_json.get('msg', 'Payment failed.')}
        except:
            if 'success' in pay_text or 'sucesso' in pay_text: 
                is_success = True

        if is_success:
            return {"status": "success", "ig_name": ig_name, "order_id": real_order_id, "csrf_token": csrf_token, "product_name": ""}
        else:
            return {"status": "error", "message": "Payment Verification Failed."}

    except Exception as e: return {"status": "error", "message": f"System Error: {str(e)}"}

# ==========================================
# 4. 🛡️ FUNCTION TO CHECK AUTHORIZATION
# ==========================================
async def is_authorized(user_id: int):
    if user_id == OWNER_ID:
        return True
    user = await db.get_reseller(str(user_id))
    return user is not None

# ==========================================
# 5. RESELLER MANAGEMENT & COMMANDS
# ==========================================
@dp.message(or_f(Command("add"), F.text.regexp(r"(?i)^\.add(?:$|\s+)")))
async def add_reseller(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("You are not the Owner.")
    parts = message.text.split()
    if len(parts) < 2: return await message.reply("`/add <user_id>`")
        
    target_id = parts[1].strip()
    if not target_id.isdigit(): return await message.reply("Please enter the User ID in numbers only.")
        
    if await db.add_reseller(target_id, f"User_{target_id}"):
        await message.reply(f"✅ Reseller ID `{target_id}` has been approved.")
    else:
        await message.reply(f"Reseller ID `{target_id}` is already in the list.")

@dp.message(or_f(Command("remove"), F.text.regexp(r"(?i)^\.remove(?:$|\s+)")))
async def remove_reseller(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("You are not the Owner.")
    parts = message.text.split()
    if len(parts) < 2: return await message.reply("Usage format - `/remove <user_id>`")
        
    target_id = parts[1].strip()
    if target_id == str(OWNER_ID): return await message.reply("The Owner cannot be removed.")
        
    if await db.remove_reseller(target_id):
        await message.reply(f"✅ Reseller ID `{target_id}` has been removed.")
    else:
        await message.reply("That ID is not in the list.")

@dp.message(or_f(Command("users"), F.text.regexp(r"(?i)^\.users$")))
async def list_resellers(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("You are not the Owner.")
    resellers_list = await db.get_all_resellers()
    user_list = []
    
    for r in resellers_list:
        role = "owner" if r["tg_id"] == str(OWNER_ID) else "users"
        user_list.append(f"🟢 ID: `{r['tg_id']}` ({role})\n   BR: ${r.get('br_balance', 0.0)} | PH: ${r.get('ph_balance', 0.0)}")
            
    final_text = "\n\n".join(user_list) if user_list else "No users found."
    await message.reply(f"🟢 **Approved users List (V-Wallet):**\n\n{final_text}")

@dp.message(Command("setcookie"))
async def set_cookie_command(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("❌ Only the Owner can set the Cookie.")
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return await message.reply("⚠️ **Usage format:**\n`/setcookie <Long_Main_Cookie>`")
    
    await db.update_main_cookie(parts[1].strip())
    await message.reply("✅ **Main Cookie has been successfully updated securely.**")

# ==========================================
# 🍪 SMART COOKIE EXTRACTOR FUNCTION
# ==========================================
@dp.message(F.text.contains("PHPSESSID") & F.text.contains("cf_clearance"))
async def handle_smart_cookie_update(message: types.Message):
    # 🟢 Owner သာလျှင် အသုံးပြုခွင့်ရှိမည်
    if message.from_user.id != OWNER_ID: 
        return await message.reply("❌ You are not authorized.")

    text = message.text
    
    # 🟢 ဆွဲထုတ်ရမည့် အဓိက Cookie နာမည်များ (လိုအပ်ပါက ထပ်တိုးနိုင်သည်)
    target_keys = ["PHPSESSID", "cf_clearance", "__cf_bm", "_did", "_csrf"]
    extracted_cookies = {}

    try:
        for key in target_keys:
            # 🟢 Python Dict ('key': 'val') နှင့် Header (key=val;) ပုံစံ နှစ်မျိုးလုံးကို ဖမ်းနိုင်သော Regex
            pattern = rf"['\"]?{key}['\"]?\s*[:=]\s*['\"]?([^'\",;\s}}]+)['\"]?"
            match = re.search(pattern, text)
            if match:
                extracted_cookies[key] = match.group(1)

        # 🟢 PHPSESSID နှင့် cf_clearance သည် မပါမဖြစ် လိုအပ်ပါသည်
        if "PHPSESSID" not in extracted_cookies or "cf_clearance" not in extracted_cookies:
            return await message.reply("❌ <b>Error:</b> `PHPSESSID` နှင့် `cf_clearance` ကို ရှာမတွေ့ပါ။ Format မှန်ကန်ကြောင်း စစ်ဆေးပါ။", parse_mode=ParseMode.HTML)

        # 🟢 Dictionary မှ "key=value; key=value;" ပုံစံ String အဖြစ် ပြောင်းလဲခြင်း
        formatted_cookie_str = "; ".join([f"{k}={v}" for k, v in extracted_cookies.items()])

        # 🟢 Database သို့ သိမ်းဆည်းခြင်း
        await db.update_main_cookie(formatted_cookie_str)
        
        # 🟢 အောင်မြင်ကြောင်းပြသရန် Message ဖန်တီးခြင်း
        success_msg = "✅ <b>Cookies Successfully Extracted & Saved!</b>\n\n"
        success_msg += "📦 <b>Extracted Data:</b>\n"
        
        for k, v in extracted_cookies.items():
            # 🟢 စာသားအရမ်းရှည်နေပါက အလယ်ကိုဖြတ်ပြီး အတိုချုံးပြသမည် (ဥပမာ - cf_clearance)
            display_v = f"{v[:15]}...{v[-15:]}" if len(v) > 35 else v
            success_msg += f"🔸 <code>{k}</code> : {display_v}\n"

        success_msg += f"\n🍪 <b>Formatted Final String:</b>\n<code>{formatted_cookie_str}</code>"

        await message.reply(success_msg, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await message.reply(f"❌ <b>Parsing Error:</b> {str(e)}", parse_mode=ParseMode.HTML)

# ==========================================
# 💰 MANUAL BALANCE ADDITION (OWNER ONLY)
# ==========================================
@dp.message(or_f(Command("addbal"), F.text.regexp(r"(?i)^\.addbal(?:$|\s+)")))
async def add_balance_command(message: types.Message):
    # 🟢 Owner သာလျှင် ဤ Command ကို အသုံးပြုခွင့်ရှိပါမည်
    if message.from_user.id != OWNER_ID:
        return await message.reply("❌ You are not authorized to use this command.")
        
    parts = message.text.strip().split()
    
    # 🟢 Format မှန်/မမှန် စစ်ဆေးခြင်း
    if len(parts) < 3:
        return await message.reply(
            "⚠️ **Usage format:**\n"
            "`.addbal <User_ID> <Amount> [BR/PH]`\n"
            "**Example:** `.addbal 123456789 50 BR`"
        )
        
    target_id = parts[1]
    
    # 🟢 ဂဏန်း ဟုတ်/မဟုတ် စစ်ဆေးခြင်း
    try:
        amount = float(parts[2])
    except ValueError:
        return await message.reply("❌ Invalid amount. Please enter numbers only.")
        
    # 🟢 နိုင်ငံ (Currency) ရွေးချယ်ခြင်း (ပုံသေ BR ဟု သတ်မှတ်ထားမည်)
    currency = "BR"
    if len(parts) > 3:
        currency = parts[3].upper()
        if currency not in ['BR', 'PH']:
            return await message.reply("❌ Invalid currency. Please use 'BR' or 'PH'.")
            
    # 🟢 User ကို Database ထဲတွင် ရှိ/မရှိ စစ်ဆေးခြင်း
    target_wallet = await db.get_reseller(target_id)
    if not target_wallet:
        return await message.reply(f"❌ User ID `{target_id}` not found in the database. Please `/add {target_id}` first.")
        
    # 🟢 Balance ပေါင်းထည့်ပေးခြင်း
    if currency == 'BR':
        await db.update_balance(target_id, br_amount=amount)
    else:
        await db.update_balance(target_id, ph_amount=amount)
        
    # 🟢 ပေါင်းထည့်ပြီးနောက် လက်ရှိ Balance ကို ပြန်ခေါ်ခြင်း
    updated_wallet = await db.get_reseller(target_id)
    new_br = updated_wallet.get('br_balance', 0.0)
    new_ph = updated_wallet.get('ph_balance', 0.0)
    
    # 🟢 Owner ထံသို့ အောင်မြင်ကြောင်း ပြန်လည်အကြောင်းကြားခြင်း
    await message.reply(
        f"✅ **Balance Added Successfully!**\n\n"
        f"👤 **User ID:** `{target_id}`\n"
        f"💰 **Added:** `+{amount:,.2f} {currency}`\n\n"
        f"📊 **Current Balance:**\n"
        f"🇧🇷 BR: `${new_br:,.2f}`\n"
        f"🇵🇭 PH: `${new_ph:,.2f}`"
    )
    
    # 🟢 User ထံသို့ ပိုက်ဆံဝင်ကြောင်း အလိုအလျောက် သွားရောက်အသိပေးခြင်း (Notification)
    try:
        await bot.send_message(
            chat_id=int(target_id),
            text=(
                f"🎉 **Top-Up Alert!**\n\n"
                f"Admin has successfully added `+{amount:,.2f} {currency}` to your V-Wallet.\n\n"
                f"Type `.balance` to check your latest balance."
            )
        )
    except Exception as e:
        print(f"User {target_id} သို့ Noti ပို့၍မရပါ။ (User သည် Bot အား Block ထားခြင်း ဖြစ်နိုင်ပါသည်) - Error: {e}")


# ==========================================
# 💸 MANUAL BALANCE DEDUCTION (OWNER ONLY)
# ==========================================
@dp.message(or_f(Command("deduct"), F.text.regexp(r"(?i)^\.deduct(?:$|\s+)")))
async def deduct_balance_command(message: types.Message):
    # 🟢 Owner သာလျှင် ဤ Command ကို အသုံးပြုခွင့်ရှိပါမည်
    if message.from_user.id != OWNER_ID:
        return await message.reply("❌ You are not authorized to use this command.")
        
    parts = message.text.strip().split()
    
    # 🟢 Format မှန်/မမှန် စစ်ဆေးခြင်း
    if len(parts) < 3:
        return await message.reply(
            "⚠️ **Usage format:**\n"
            "`.deduct <User_ID> <Amount> [BR/PH]`\n"
            "**Example:** `.deduct 123456789 50 BR`"
        )
        
    target_id = parts[1]
    
    # 🟢 ဂဏန်း ဟုတ်/မဟုတ် စစ်ဆေးခြင်း (အနှုတ်လက္ခဏာပါလာလျှင်တောင် အပေါင်းဂဏန်းအဖြစ် အရင်ပြောင်းပါမည်)
    try:
        amount = abs(float(parts[2]))
    except ValueError:
        return await message.reply("❌ Invalid amount. Please enter numbers only.")
        
    # 🟢 နိုင်ငံ (Currency) ရွေးချယ်ခြင်း (ပုံသေ BR ဟု သတ်မှတ်ထားမည်)
    currency = "BR"
    if len(parts) > 3:
        currency = parts[3].upper()
        if currency not in ['BR', 'PH']:
            return await message.reply("❌ Invalid currency. Please use 'BR' or 'PH'.")
            
    # 🟢 User ကို Database ထဲတွင် ရှိ/မရှိ စစ်ဆေးခြင်း
    target_wallet = await db.get_reseller(target_id)
    if not target_wallet:
        return await message.reply(f"❌ User ID `{target_id}` not found in the database.")
        
    # 🟢 Balance နှုတ်ယူခြင်း (Amount ရှေ့တွင် အနှုတ်လက္ခဏာ "-" တပ်၍ ပေးပို့ရပါမည်)
    if currency == 'BR':
        await db.update_balance(target_id, br_amount=-amount)
    else:
        await db.update_balance(target_id, ph_amount=-amount)
        
    # 🟢 နှုတ်ယူပြီးနောက် လက်ရှိ Balance ကို ပြန်ခေါ်ခြင်း
    updated_wallet = await db.get_reseller(target_id)
    new_br = updated_wallet.get('br_balance', 0.0)
    new_ph = updated_wallet.get('ph_balance', 0.0)
    
    # 🟢 Owner ထံသို့ အောင်မြင်ကြောင်း ပြန်လည်အကြောင်းကြားခြင်း
    await message.reply(
        f"✅ **Balance Deducted Successfully!**\n\n"
        f"👤 **User ID:** `{target_id}`\n"
        f"💸 **Deducted:** `-{amount:,.2f} {currency}`\n\n"
        f"📊 **Current Balance:**\n"
        f"🇧🇷 BR: `${new_br:,.2f}`\n"
        f"🇵🇭 PH: `${new_ph:,.2f}`"
    )
    
    # 🟢 User ထံသို့ ပိုက်ဆံနှုတ်ခံရကြောင်း အလိုအလျောက် သွားရောက်အသိပေးခြင်း
    try:
        await bot.send_message(
            chat_id=int(target_id),
            text=(
                f"⚠️ **Balance Deduction Alert!**\n\n"
                f"Admin has deducted `-{amount:,.2f} {currency}` from your V-Wallet.\n\n"
                f"Type `.balance` to check your latest balance."
            )
        )
    except Exception as e:
        print(f"User {target_id} သို့ Noti ပို့၍မရပါ။ (User သည် Bot အား Block ထားခြင်း ဖြစ်နိုင်ပါသည်) - Error: {e}")


# ==========================================
# 💳 SMILE CODE TOP-UP COMMAND (FULLY ASYNC)
# ==========================================
@dp.message(F.text.regexp(r"(?i)^\.topup\s+([a-zA-Z0-9]+)"))
async def handle_topup(message: types.Message):
    if not await is_authorized(message.from_user.id): 
        return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    
    match = re.search(r"(?i)^\.topup\s+([a-zA-Z0-9]+)", message.text.strip())
    if not match: 
        return await message.reply("Usage format - `.topup <Code>`")
    
    activation_code = match.group(1).strip()
    tg_id = str(message.from_user.id)
    user_id_int = message.from_user.id 
    
    loading_msg = await message.reply(f"Checking Code `{activation_code}`...")
    
    # 🟢 Global Lock အစား User တစ်ယောက်ချင်းစီအတွက်သာ Lock ချပါမည် (အခြားသူများ စောင့်ရန်မလိုတော့ပါ)
    async with user_locks[tg_id]:
        scraper = await get_main_scraper()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        }
        
        # 🟢 အတွင်းပိုင်း လုပ်ဆောင်ချက်များကိုလည်း Async Function အဖြစ် ကြေညာခြင်း
        # 🟢 အတွင်းပိုင်း လုပ်ဆောင်ချက်များကိုလည်း Async Function အဖြစ် ကြေညာခြင်း
        async def try_redeem(api_type):
            if api_type == 'PH':
                page_url = 'https://www.smile.one/ph/customer/activationcode'
                check_url = 'https://www.smile.one/ph/smilecard/pay/checkcard'
                pay_url = 'https://www.smile.one/ph/smilecard/pay/payajax'
                base_origin = 'https://www.smile.one'
                base_referer = 'https://www.smile.one/ph/'
                balance_check_url = 'https://www.smile.one/ph/customer/order'
            else:
                page_url = 'https://www.smile.one/customer/activationcode'
                check_url = 'https://www.smile.one/smilecard/pay/checkcard'
                pay_url = 'https://www.smile.one/smilecard/pay/payajax'
                base_origin = 'https://www.smile.one'
                base_referer = 'https://www.smile.one/'
                balance_check_url = 'https://www.smile.one/customer/order'

            req_headers = headers.copy()
            req_headers['Referer'] = base_referer

            try:
                res = await asyncio.to_thread(scraper.get, page_url, headers=req_headers)
                if "login" in res.url.lower() or res.status_code in [403, 503]: return "expired", None

                soup = BeautifulSoup(res.text, 'html.parser')
                csrf_token = soup.find('meta', {'name': 'csrf-token'})
                csrf_token = csrf_token.get('content') if csrf_token else (soup.find('input', {'name': '_csrf'}).get('value') if soup.find('input', {'name': '_csrf'}) else None)
                
                # 🟢 CSRF မရပါက Error မပြတော့ဘဲ Auto-Login ခေါ်ရန် Expired ဟု သတ်မှတ်မည်
                if not csrf_token: return "expired", None 

                ajax_headers = req_headers.copy()
                ajax_headers.update({'X-Requested-With': 'XMLHttpRequest', 'Origin': base_origin, 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})

                check_res_raw = await asyncio.to_thread(scraper.post, check_url, data={'_csrf': csrf_token, 'pin': activation_code}, headers=ajax_headers)
                check_res = check_res_raw.json()
                code_status = str(check_res.get('code', check_res.get('status', '')))
                
                # 🟢 API မှ ကတ်တန်ဖိုး (Face Value) ကို တိုက်ရိုက်ဆွဲထုတ်ခြင်း (System Delay ကို ကျော်ဖြတ်ရန်)
                card_amount = 0.0
                try:
                    if 'data' in check_res and isinstance(check_res['data'], dict):
                        val = check_res['data'].get('amount', check_res['data'].get('money', 0))
                        if val: card_amount = float(val)
                except: pass

                if code_status in ['200', '201', '0', '1'] or 'success' in str(check_res.get('msg', '')).lower():
                    
                    old_bal = await get_smile_balance(scraper, headers, balance_check_url)
                    
                    pay_res_raw = await asyncio.to_thread(scraper.post, pay_url, data={'_csrf': csrf_token, 'sec': activation_code}, headers=ajax_headers)
                    pay_res = pay_res_raw.json()
                    pay_status = str(pay_res.get('code', pay_res.get('status', '')))
                    
                    if pay_status in ['200', '0', '1'] or 'success' in str(pay_res.get('msg', '')).lower():
                        await asyncio.sleep(5) 
                        
                        # 🟢 Cache မိနေခြင်းကို ရှောင်ရှားရန် URL နောက်တွင် Timestamp ထည့်ပေးခြင်း
                        anti_cache_url = f"{balance_check_url}?_t={int(time.time())}"
                        new_bal = await get_smile_balance(scraper, headers, anti_cache_url)
                        
                        bal_key = 'br_balance' if api_type == 'BR' else 'ph_balance'
                        added = round(new_bal[bal_key] - old_bal[bal_key], 2)
                        
                        # 🟢 အကယ်၍ Website က Balance ကြန့်ကြာနေပါက API မှရသော ကတ်တန်ဖိုးကို အသုံးပြုမည်
                        if added <= 0 and card_amount > 0:
                            added = card_amount
                            
                        return "success", added
                    else:
                        return "fail", "Payment failed."
                else:
                    return "invalid", "Invalid Code"
                    
            except Exception as e:
                return "error", str(e)

        # 🟢 Async Function ကို Await ဖြင့် ခေါ်ယူခြင်း
        status, result = await try_redeem('BR')
        active_region = 'BR'
        
        if status in ['invalid', 'fail']: 
            status, result = await try_redeem('PH')
            active_region = 'PH'

        if status == "expired":
            await loading_msg.edit_text("⚠️ <b>Cookies Expired!</b>\n\nAuto-login စတင်နေပါသည်... ခဏစောင့်ပြီး ပြန်လည်ကြိုးစားပါ။", parse_mode=ParseMode.HTML)
            await notify_owner("⚠️ <b>Top-up Alert:</b> Code ဖြည့်သွင်းနေစဉ် Cookie သက်တမ်းကုန်သွားပါသည်။ Auto-login စတင်နေပါသည်...")
            success = await auto_login_and_get_cookie()
            if not success:
                await notify_owner("❌ <b>Critical:</b> Auto-Login မအောင်မြင်ပါ။ `/setcookie` ဖြင့် အသစ်ထည့်ပေးပါ။")
                
        elif status == "error":
            await loading_msg.edit_text(f"❌ Error: {result}")
            
        elif status in ['invalid', 'fail']:
            await loading_msg.edit_text("Cʜᴇᴄᴋ Fᴀɪʟᴇᴅ❌\n(Code is invalid or might have been used)")
            
        elif status == "success":
            added_amount = result
            
            if added_amount <= 0:
                await loading_msg.edit_text(f"sᴍɪʟᴇ ᴏɴᴇ ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ sᴜᴄᴄᴇss ✅\n(Cannot retrieve exact amount due to System Delay.)")
            else:
                if user_id_int == OWNER_ID:
                    fee_percent = 0.0
                    fee_amount = 0.0
                    net_added = added_amount
                else:
                    if added_amount >= 10000:
                        fee_percent = 0.10
                    elif added_amount >= 5000:
                        fee_percent = 0.15
                    elif added_amount >= 1000:
                        fee_percent = 0.20
                    else:
                        fee_percent = 0.30

                fee_amount = round(added_amount * (fee_percent / 100), 2)
                net_added = round(added_amount - fee_amount, 2)
        
                # 🟢 Database ကို Async ဖြင့် ခေါ်ယူ၍ Update လုပ်ခြင်း
                user_wallet = await db.get_reseller(tg_id)
                if active_region == 'BR':
                    assets = user_wallet.get('br_balance', 0.0) if user_wallet else 0.0
                    await db.update_balance(tg_id, br_amount=net_added)
                else:
                    assets = user_wallet.get('ph_balance', 0.0) if user_wallet else 0.0
                    await db.update_balance(tg_id, ph_amount=net_added)

                total_assets = assets + net_added
                fmt_amount = int(added_amount) if added_amount % 1 == 0 else added_amount

                msg = (
                    f"✅ <b>Code Top-Up Successful</b>\n\n"
                    f"<code>"
                    f"Code   : {activation_code} ({active_region})\n"
                    f"Amount : {fmt_amount:,}\n"
                    f"Fee    : -{fee_amount:.1f} ({fee_percent}%)\n"
                    f"Added  : +{net_added:,.1f} 🪙\n"
                    f"Assets : {assets:,.1f} 🪙\n"
                    f"Total  : {total_assets:,.1f} 🪙"
                    f"</code>"
                )
                await loading_msg.edit_text(msg, parse_mode=ParseMode.HTML)

# ==========================================
# 💳 BALANCE COMMAND & TOOLS
# ==========================================
@dp.message(or_f(Command("balance"), F.text.regexp(r"(?i)^\.bal(?:$|\s+)")))
async def check_balance_command(message: types.Message):
    if not await is_authorized(message.from_user.id): 
        return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    
    tg_id = str(message.from_user.id)
    user_wallet = await db.get_reseller(tg_id)
    if not user_wallet: 
        return await message.reply("Yᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ ɪɴғᴏʀᴍᴀᴛɪᴏɴ ᴄᴀɴɴᴏᴛ ʙᴇ ғᴏᴜɴᴅ.")
    
    # 🟢 Aiogram အတွက် မှန်ကန်သော Custom Emoji Tag များကို သုံးထားပါသည် (tg-emoji)
    ICON_EMOJI = "5956330306167376831" 
    BR_EMOJI = "5228878788867142213"   
    PH_EMOJI = "5231361434583049965"   

    report = (
        f"<blockquote><tg-emoji emoji-id='{ICON_EMOJI}'>💳</tg-emoji> <b>𝗬𝗢𝗨𝗥 𝗪𝗔𝗟𝗟𝗘𝗧 𝗕𝗔𝗟𝗔𝗡𝗖𝗘</b>\n\n"
        f"<tg-emoji emoji-id='{BR_EMOJI}'>🇧🇷</tg-emoji> 𝗕𝗥 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : ${user_wallet.get('br_balance', 0.0):,.2f}\n"
        f"<tg-emoji emoji-id='{PH_EMOJI}'>🇵🇭</tg-emoji> 𝗣𝗛 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : ${user_wallet.get('ph_balance', 0.0):,.2f}</blockquote>"
    )
    
    if message.from_user.id == OWNER_ID:
        loading_msg = await message.reply("Fetching real balance from the official account...")
        scraper = await get_main_scraper()
        headers = {'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://www.smile.one'}
        try:
            balances = await get_smile_balance(scraper, headers, 'https://www.smile.one/customer/order')
            
            report += (
                f"\n\n<blockquote><tg-emoji emoji-id='{ICON_EMOJI}'>💳</tg-emoji> <b>𝗢𝗙𝗙𝗜𝗖𝗜𝗔𝗟 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗕𝗔𝗟𝗔𝗡𝗖𝗘</b>\n\n"
                f"<tg-emoji emoji-id='{BR_EMOJI}'>🇧🇷</tg-emoji> 𝗕𝗥 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : ${balances.get('br_balance', 0.00):,.2f}\n"
                f"<tg-emoji emoji-id='{PH_EMOJI}'>🇵🇭</tg-emoji> 𝗣𝗛 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : ${balances.get('ph_balance', 0.00):,.2f}</blockquote>"
            )
            
            await loading_msg.edit_text(report, parse_mode=ParseMode.HTML)
        except Exception as e:
            print(f"Balance Scrape Error: {e}")
            # Scraping Error တက်ခဲ့ရင်တောင် V-Wallet (DB) Balance ကိုတော့ ပြပေးမည်
            try:
                await loading_msg.edit_text(report, parse_mode=ParseMode.HTML)
            except:
                pass
    else:
        try:
            await message.reply(report, parse_mode=ParseMode.HTML)
        except:
            pass

@dp.message(or_f(Command("history"), F.text.regexp(r"(?i)^\.his$")))
async def send_order_history(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    tg_id = str(message.from_user.id)
    user_name = message.from_user.username or message.from_user.first_name
    
    history_data = await db.get_user_history(tg_id, limit=200)
    if not history_data: return await message.reply("📜 **No Order History Found.**")

    response_text = f"==== Order History for @{user_name} ====\n\n"
    for order in history_data:
        response_text += (f"🆔 Game ID: {order['game_id']}\n🌏 Zone ID: {order['zone_id']}\n💎 Pack: {order['item_name']}\n"
                          f"🆔 Order ID: {order['order_id']}\n📅 Date: {order['date_str']}\n💲 Rate: ${order['price']:,.2f}\n"
                          f"📊 Status: {order['status']}\n────────────────\n")
    
    # Send document in Aiogram 3
    file_bytes = response_text.encode('utf-8')
    document = BufferedInputFile(file_bytes, filename=f"History_{tg_id}.txt")
    await message.answer_document(document=document, caption=f"📜 **Order History**\n👤 User: @{user_name}\n📊 Records: {len(history_data)}")

@dp.message(or_f(Command("clean"), F.text.regexp(r"(?i)^\.clean$")))
async def clean_order_history(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    tg_id = str(message.from_user.id)
    deleted_count = await db.clear_user_history(tg_id)
    if deleted_count > 0: await message.reply(f"🗑️ **History Cleaned Successfully.**\nDeleted {deleted_count} order records from your history.")
    else: await message.reply("📜 **No Order History Found to Clean.**")

# ==========================================
# 🛑 CORE ORDER EXECUTION HELPER [UPDATED FOR PRODUCT NAME]
# ==========================================
async def execute_buy_process(message, lines, regex_pattern, currency, packages_dict, process_func, title_prefix, is_mcc=False):
    tg_id = str(message.from_user.id)
    telegram_user = message.from_user.username
    username_display = f"@{telegram_user}" if telegram_user else tg_id
    v_bal_key = 'br_balance' if currency == 'BR' else 'ph_balance'
    
    async with user_locks[tg_id]: 
        for line in lines:
            line = line.strip()
            if not line: continue 
            
            match = re.search(regex_pattern, line)
            if not match:
                await message.reply(f"Invalid format: `{line}`\nCheck /help for correct format.")
                continue
                
            game_id = match.group(1)
            zone_id = match.group(2)
            item_input = match.group(3).lower() 
            
            active_packages = None
            if isinstance(packages_dict, list):
                for p_dict in packages_dict:
                    if item_input in p_dict:
                        active_packages = p_dict
                        break
            else:
                if item_input in packages_dict:
                    active_packages = packages_dict
                    
            if not active_packages:
                await message.reply(f"❌ No Package found for '{item_input}'.")
                continue
                
            items_to_buy = active_packages[item_input]
            total_required_price = sum(item['price'] for item in items_to_buy)
            
            user_wallet = await db.get_reseller(tg_id)
            user_v_bal = user_wallet.get(v_bal_key, 0.0) if user_wallet else 0.0
            
            if user_v_bal < total_required_price:
                await message.reply(f"Nᴏᴛ ᴇɴᴏᴜɢʜ ᴍᴏɴᴇʏ ɪɴ ʏᴏᴜʀ ᴠ-ᴡᴀʟʟᴇᴛ.\nNᴇᴇᴅ ʙᴀʟᴀɴᴄᴇ ᴀᴍᴏᴜɴᴛ: {total_required_price} {currency}\nYᴏᴜʀ ʙᴀʟᴀɴᴄᴇ: {user_v_bal} {currency}")
                continue
            
            loading_msg = await message.reply(f"⏱ Order လက်ခံရရှိပါသည်... ခဏစောင့်ပေးပါ ᥫ᭡")
            
            success_count, fail_count, total_spent = 0, 0, 0.0
            order_ids_str, ig_name, error_msg = "", "Unknown", ""
            
            prev_context = None 
            actual_names_list = [] # 🟢 Official Product Names များကို စုဆောင်းရန် Array
            
            async with api_semaphore:
                await loading_msg.edit_text(f"Recharging Diam͟o͟n͟d͟ ● ᥫ᭡")
                
                # 🟢 ပထမဆုံး Item ဖြစ်ကြောင်း မှတ်သားရန်
                is_first_item = True 
                
                for item in items_to_buy:
                    
                    # 🟢 ဒုတိယ Item မှစ၍ Check Role ကို ကျော်သွားမည်
                    should_skip_checkrole = not is_first_item 
                    
                    if is_mcc:
                        result = await process_func(game_id, zone_id, item['pid'], currency, prev_context=prev_context, skip_checkrole=should_skip_checkrole)
                    else:
                        result = await process_func(game_id, zone_id, item['pid'], currency, prev_context=prev_context, skip_checkrole=should_skip_checkrole)
                    
                    if result['status'] == 'success':
                        prev_context = {'csrf_token': result['csrf_token']}
                        
                        # 🟢 ပထမဆုံး Item ကနေရတဲ့ နာမည်အမှန်ကိုသာ ယူပြီး ကျန်တဲ့ Item တွေအတွက် သိမ်းထားမည်
                        if is_first_item and result.get('ig_name') and result['ig_name'] != "Skipped":
                            ig_name = result['ig_name'] 
                            
                        # 🟢 နောက်ထပ် Item တွေ လာရင် Check Role ကို ကျော်ရန် False အဖြစ် ပြောင်းမည်
                        is_first_item = False 
                        
                        fetched_name = result.get('product_name', '').strip()
                        if not fetched_name:
                            fetched_name = item.get('name', item_input)
                        actual_names_list.append(fetched_name)

                        success_count += 1
                        total_spent += item['price']
                        order_ids_str += f"{result['order_id']}\n" 
                        await asyncio.sleep(0.5) # 🟢 မြန်ဆန်စေရန် Sleep Time ကို 0.5 စက္ကန့်ထိ လျှော့ချထားပါသည်
                    else:
                        fail_count += 1
                        error_msg = result['message']
                        break 
            
            if success_count > 0:
                now = datetime.datetime.now(MMT)
                date_str = now.strftime("%m/%d/%Y, %I:%M:%S %p")
                
                if currency == 'BR': await db.update_balance(tg_id, br_amount=-total_spent)
                else: await db.update_balance(tg_id, ph_amount=-total_spent)
                
                new_wallet = await db.get_reseller(tg_id)
                new_v_bal = new_wallet.get(v_bal_key, 0.0) if new_wallet else 0.0
                final_order_ids = order_ids_str.strip().replace('\n', ', ')
                
                # 🟢 တူညီသော Item များဆိုလျှင် (x2), (x3) စသဖြင့် ပြပေးရန်
                unique_names = list(set(actual_names_list))
                if len(unique_names) == 1:
                    final_item_name = f"{unique_names[0]} (x{success_count})" if success_count > 1 else unique_names[0]
                else:
                    final_item_name = ", ".join(actual_names_list)

                await db.save_order(
                    tg_id=tg_id, game_id=game_id, zone_id=zone_id, item_name=final_item_name,
                    price=total_spent, order_id=final_order_ids, status="success"
                )
             
                safe_ig_name = html.escape(str(ig_name))
                safe_username = html.escape(str(username_display))
                safe_item_name = html.escape(str(final_item_name)) # 🟢 HTML Safe ပြုလုပ်ခြင်း
                
                report = (
                    f"<blockquote><code>**{title_prefix} {game_id} ({zone_id}) {item_input} ({currency})**\n"
                    f"=== ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ʀᴇᴘᴏʀᴛ ===\n\n"
                    f"ᴏʀᴅᴇʀ sᴛᴀᴛᴜs : ✅ Sᴜᴄᴄᴇss\n"
                    f"ɢᴀᴍᴇ ɪᴅ      : {game_id} {zone_id}\n"
                    f"ɪɢ ɴᴀᴍᴇ      : {safe_ig_name}\n"
                    f"sᴇʀɪᴀʟ        :\n{order_ids_str.strip()}\n"
                    f"ɪᴛᴇᴍ         : {safe_item_name}\n" # 🟢 နာမည်အမှန် ထည့်သွင်းပြသခြင်း
                    f"sᴘᴇɴᴛ        : {total_spent:.2f} 🪙\n\n"
                    f"ᴅᴀᴛᴇ         : {date_str}\n"
                    f"ᴜsᴇʀɴᴀᴍᴇ      : {safe_username}\n"
                    f"ɪɴɪᴛɪᴀʟ      : ${user_v_bal:,.2f}\n"
                    f"ғɪɴᴀʟ        : ${new_v_bal:,.2f}\n\n"
                    f"Sᴜᴄᴄᴇss {success_count} / Fᴀɪʟ {fail_count}</code></blockquote>"
                )
                await loading_msg.edit_text(report, parse_mode=ParseMode.HTML)
                if fail_count > 0: await message.reply(f"Only partially successful.\nError: {error_msg}")
            else:
                await loading_msg.edit_text(f"❌ Order failed:\n{error_msg}")

# ==========================================
# 💎 PURCHASE COMMAND HANDLERS
# ==========================================

# 🟢 တစ်ကြောင်းတည်းမှာ Item တွေ အများကြီးရေးခဲ့ရင် သီးသန့်စီ ခွဲထုတ်ပေးမယ့် Helper Function
def parse_multiple_items(lines):
    expanded_lines = []
    regex = r"(?i)^(?:(?:msc|mlb|br|b|mlp|ph|p|mcc|mcb|mcp)\s+)?(\d+)\s*(?:[\(]?\s*(\d+)\s*[\)]?)\s+(.+)"
    for line in lines:
        match = re.search(regex, line)
        if match:
            game_id = match.group(1)
            zone_id = match.group(2)
            items_str = match.group(3)
            # Space ခြားထားတဲ့ Item တစ်ခုချင်းစီကို ယူပြီး သီးသန့် Line တွေအဖြစ် ပြောင်းပါမယ်
            for item in items_str.split():
                expanded_lines.append(f"{game_id} ({zone_id}) {item}")
        else:
            expanded_lines.append(line)
    return expanded_lines


@dp.message(F.text.regexp(r"(?i)^(?:msc|mlb|br|b)\s+\d+"))
async def handle_br_mlbb(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply(f"ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.❌")
    try:
        raw_lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        
        # 🟢 Item တွေကို အရင်ဆုံး ခွဲထုတ်ပါမယ်
        lines = parse_multiple_items(raw_lines)

        # 🟢 ၅ ခုထက်ကျော်ရင် ငြင်းမယ် (စုစုပေါင်း ဝယ်မယ့် Item အရေအတွက်ကို စစ်တာပါ)
        if len(lines) > 5:
            return await message.reply("❌ **5 Limit Exceeded:** တစ်ကြိမ်လျှင် အများဆုံး ၅ ခုသာ ဝယ်ယူနိုင်ပါသည်။")

        regex = r"(?i)^(?:(?:msc|mlb|br|b)\s+)?(\d+)\s*(?:[\(]?\s*(\d+)\s*[\)]?)\s+([a-zA-Z0-9_]+)"
        await execute_buy_process(message, lines, regex, 'BR', [DOUBLE_DIAMOND_PACKAGES, BR_PACKAGES], process_smile_one_order, "MLBB")
    except Exception as e: await message.reply(f"System Error: {str(e)}")

@dp.message(F.text.regexp(r"(?i)^(?:mlp|ph|p)\s+\d+"))
async def handle_ph_mlbb(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply(f"ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.❌")
    try:
        raw_lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        lines = parse_multiple_items(raw_lines)

        if len(lines) > 5:
            return await message.reply("5 Lɪᴍɪᴛ Exᴄᴇᴇᴅᴇᴅ.❌")

        regex = r"(?i)^(?:(?:mlp|ph|p)\s+)?(\d+)\s*(?:[\(]?\s*(\d+)\s*[\)]?)\s+([a-zA-Z0-9_]+)"
        await execute_buy_process(message, lines, regex, 'PH', PH_PACKAGES, process_smile_one_order, "MLBB")
    except Exception as e: await message.reply(f"System Error: {str(e)}")

@dp.message(F.text.regexp(r"(?i)^(?:mcc|mcb)\s+\d+"))
async def handle_br_mcc(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply(f"ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.❌")
    try:
        raw_lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        lines = parse_multiple_items(raw_lines)

        if len(lines) > 5:
            return await message.reply("5 Lɪᴍɪᴛ Exᴄᴇᴇᴅᴇᴅ.❌")

        regex = r"(?i)^(?:(?:mcc|mcb)\s+)?(\d+)\s*(?:[\(]?\s*(\d+)\s*[\)]?)\s+([a-zA-Z0-9_]+)"
        await execute_buy_process(message, lines, regex, 'BR', MCC_PACKAGES, process_mcc_order, "MCC", is_mcc=True)
    except Exception as e: await message.reply(f"System Error: {str(e)}")

@dp.message(F.text.regexp(r"(?i)^mcp\s+\d+"))
async def handle_ph_mcc(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply(f"ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.❌")
    try:
        raw_lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        lines = parse_multiple_items(raw_lines)

        if len(lines) > 5:
            return await message.reply("5 Lɪᴍɪᴛ Exᴄᴇᴇᴅᴇᴅ.❌")

        regex = r"(?i)^(?:mcp\s+)?(\d+)\s*(?:[\(]?\s*(\d+)\s*[\)]?)\s+([a-zA-Z0-9_]+)"
        await execute_buy_process(message, lines, regex, 'PH', PH_MCC_PACKAGES, process_mcc_order, "MCC", is_mcc=True)
    except Exception as e: await message.reply(f"System Error: {str(e)}")

# ==========================================
# 📜 PRICE LIST COMMANDS
# ==========================================
def generate_list(package_dict):
    lines = []
    for key, items in package_dict.items():
        total_price = sum(item['price'] for item in items)
        lines.append(f"{key:<5} : ${total_price:,.2f}")
    return "\n".join(lines)

@dp.message(or_f(Command("listb"), F.text.regexp(r"(?i)^\.listb$")))
async def show_price_list_br(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    response_text = f"🇧🇷 <b>𝘿𝙤𝙪𝙗𝙡𝙚 𝙋𝙖𝙘𝙠𝙖𝙜𝙚𝙨</b>\n<code>{generate_list(DOUBLE_DIAMOND_PACKAGES)}</code>\n\n🇧🇷 <b>𝘽𝙧 𝙋𝙖𝙘𝙠𝙖𝙜𝙚𝙨</b>\n<code>{generate_list(BR_PACKAGES)}</code>"
    await message.reply(response_text, parse_mode=ParseMode.HTML)

@dp.message(or_f(Command("listp"), F.text.regexp(r"(?i)^\.listp$")))
async def show_price_list_ph(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    response_text = f"🇵🇭 <b>𝙋𝙝 𝙋𝙖𝙘𝙠𝙖𝙜𝙚𝙨</b>\n<code>{generate_list(PH_PACKAGES)}</code>"
    await message.reply(response_text, parse_mode=ParseMode.HTML)

@dp.message(or_f(Command("listmb"), F.text.regexp(r"(?i)^\.listmb$")))
async def show_price_list_mcc(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    response_text = f"🇧🇷 <b>𝙈𝘾𝘾 𝙋𝘼𝘾𝙆𝘼𝙂𝙀𝙎</b>\n<code>{generate_list(MCC_PACKAGES)}</code>\n\n🇵🇭 <b>𝙋𝙝 𝙈𝘾𝘾 𝙋𝙖𝙘𝙠𝙖𝙜𝙚𝙨</b>\n<code>{generate_list(PH_MCC_PACKAGES)}</code>"
    await message.reply(response_text, parse_mode=ParseMode.HTML)

# ==========================================
# 🧮 SMART CALCULATOR FUNCTION
# ==========================================
@dp.message(F.text.regexp(r"^[\d\s\.\(\)]+[\+\-\*\/][\d\s\+\-\*\/\(\)\.]+$"))
async def auto_calculator(message: types.Message):
    try:
        expr = message.text.strip()
        if re.match(r"^09[-\s]?\d+", expr): return
        clean_expr = expr.replace(" ", "")
        result = eval(clean_expr, {"__builtins__": None})
        if isinstance(result, float): formatted_result = f"{result:.4f}".rstrip('0').rstrip('.')
        else: formatted_result = str(result)
        await message.reply(f"{expr} = {formatted_result}")
    except Exception: pass

# ==========================================
# 10. 💓 HEARTBEAT FUNCTION
# ==========================================
async def keep_cookie_alive():
    """ Reactive Renewal: (၂) မိနစ်တစ်ခါ စစ်မည်။ """
    while True:
        try:
            await asyncio.sleep(2 * 60) 
            scraper = await get_main_scraper()
            headers = {'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://www.smile.one'}
            response = await asyncio.to_thread(scraper.get, 'https://www.smile.one/customer/order', headers=headers)
            if "login" not in response.url.lower() and response.status_code == 200:
                pass 
            else:
                print(f"[{datetime.datetime.now(MMT).strftime('%I:%M %p')}] ⚠️ Main Cookie expired unexpectedly.")
                
                # 🟢 အသစ်ရေးထားသော Function ဖြင့် Owner ဆီ စာပို့မည်
                await notify_owner("⚠️ <b>System Warning:</b> Cookie သက်တမ်းကုန်သွားသည်ကို တွေ့ရှိရပါသည်။ Auto-Login စတင်နေပါသည်...")

                success = await auto_login_and_get_cookie()
                
                if not success:
                    await notify_owner("❌ <b>Critical:</b> Auto-Login မအောင်မြင်ပါ။ သင့်အနေဖြင့် `/setcookie` ဖြင့် Cookie အသစ် လာရောက်ထည့်သွင်းပေးရန် လိုအပ်ပါသည်။")
        except Exception: pass


async def schedule_daily_cookie_renewal():
    """ Proactive Renewal: နေ့စဉ် မနက် ၆:၃၀ (MMT) တွင် Cookie အသစ်ကို ကြိုတင်ရယူထားမည်။ """
    while True:
        now = datetime.datetime.now(MMT)
        
        # 🟢 ယနေ့ မနက် ၆:၃၀ အချိန်ကို သတ်မှတ်ခြင်း
        target_time = now.replace(hour=6, minute=30, second=0, microsecond=0)
        
        if now >= target_time:
            target_time += datetime.timedelta(days=1)
            
        wait_seconds = (target_time - now).total_seconds()
        print(f"⏰ Proactive Cookie Renewal is scheduled in {wait_seconds / 3600:.2f} hours (at {target_time.strftime('%I:%M %p')} MMT).")
        
        # 🟢 အချိန်ပြည့်သည်အထိ စောင့်နေမည်
        await asyncio.sleep(wait_seconds)
        
        print(f"[{datetime.datetime.now(MMT).strftime('%I:%M %p')}] 🚀 Executing Proactive Cookie Renewal...")
        try: await bot.send_message(OWNER_ID, "🔄 <b>System:</b> Executing daily proactive cookie renewal (6:30 AM)...", parse_mode=ParseMode.HTML)
        except Exception: pass

        success = await auto_login_and_get_cookie()
        
        if success:
            try: await bot.send_message(OWNER_ID, "✅ <b>System:</b> Proactive cookie renewal successful. Ready for the day!", parse_mode=ParseMode.HTML)
            except Exception: pass
        else:
            try: await bot.send_message(OWNER_ID, "❌ <b>System:</b> Proactive cookie renewal failed!", parse_mode=ParseMode.HTML)
            except Exception: pass


async def notify_owner(text: str):
    try:
        # လိုအပ်ပါက Message ကို ပိုမိုလုံခြုံစေရန် - 
        # text = html.escape(text) (မိမိကိုယ်တိုင် HTML tags မသုံးထားသော နေရာများတွင်သာ သုံးရန်)
        await bot.send_message(
            chat_id=OWNER_ID,
            text=text,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f" Owner ထံသို့ Message ပို့၍မရပါ: {e}")

# ==========================================
# 🍪 CHECK COOKIE STATUS COMMAND
# ==========================================
@dp.message(or_f(Command("cookies"), F.text.regexp(r"(?i)^\.cookies$")))
async def check_cookie_status(message: types.Message):
    if message.from_user.id != OWNER_ID: 
        return await message.reply("❌ You are not authorized to check system cookies.")
        
    loading_msg = await message.reply("Checking Cookie status...")
    
    try:
        scraper = await get_main_scraper()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 
            'X-Requested-With': 'XMLHttpRequest', 
            'Origin': 'https://www.smile.one'
        }
        
        response = await asyncio.to_thread(scraper.get, 'https://www.smile.one/customer/order', headers=headers, timeout=15)
        
        if "login" not in response.url.lower() and response.status_code == 200:
            await loading_msg.edit_text("🟢 Aᴄᴛɪᴠᴇ", parse_mode=ParseMode.HTML)
        else:
            await loading_msg.edit_text("🔴 Exᴘɪʀᴇᴅ", parse_mode=ParseMode.HTML)
            
    except Exception as e:
        await loading_msg.edit_text(f"❌ Error checking cookie: {str(e)}")


@dp.message(or_f(Command("role"), F.text.regexp(r"(?i)^\.role(?:$|\s+)")))
async def handle_check_role(message: types.Message):
    if not await is_authorized(message.from_user.id):
        return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")

    match = re.search(r"(?i)^[./]?role\s+(\d+)\s*[\(]?\s*(\d+)\s*[\)]?", message.text.strip())
    if not match:
        return await message.reply("❌ Invalid format:\n(Example - `.role 123456789 12345` or `/role 123456789 (12345)`)")

    game_id = match.group(1).strip()
    zone_id = match.group(2).strip()
    
    loading_msg = await message.reply("Search region")

    scraper = await get_main_scraper()
    
    main_url = 'https://www.smile.one/merchant/mobilelegends'
    checkrole_url = 'https://www.smile.one/merchant/mobilelegends/checkrole'
    headers = {'X-Requested-With': 'XMLHttpRequest', 'Referer': main_url, 'Origin': 'https://www.smile.one'}

    try:
        res = await asyncio.to_thread(scraper.get, main_url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        csrf_token = None
        meta_tag = soup.find('meta', {'name': 'csrf-token'})
        if meta_tag: csrf_token = meta_tag.get('content')
        else:
            csrf_input = soup.find('input', {'name': '_csrf'})
            if csrf_input: csrf_token = csrf_input.get('value')

        if not csrf_token:
            return await loading_msg.edit_text("❌ CSRF Token not found. Add a new Cookie using /setcookie.")

        check_data = {'user_id': game_id, 'zone_id': zone_id, '_csrf': csrf_token}
        role_response_raw = await asyncio.to_thread(scraper.post, checkrole_url, data=check_data, headers=headers)
        
        try: 
            role_result = role_response_raw.json()
        except: 
            return await loading_msg.edit_text("❌ Cannot verify. (Smile API Error)")
            
        ig_name = role_result.get('username') or role_result.get('data', {}).get('username')
        
        if not ig_name or str(ig_name).strip() == "":
            real_error = role_result.get('msg') or role_result.get('message') or "Account not found."
            if "login" in str(real_error).lower() or "unauthorized" in str(real_error).lower():
                return await loading_msg.edit_text("⚠️ Cookie expired. Please add a new one using `/setcookie`.")
            return await loading_msg.edit_text(f"❌ **Invalid Account:**\n{real_error}")

        smile_region = role_result.get('zone') or role_result.get('region') or role_result.get('data', {}).get('zone') or "Unknown"

        pizzo_region = "Unknown"
        try:
            pizzo_headers = {
                'authority': 'pizzoshop.com',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'content-type': 'application/x-www-form-urlencoded',
                'origin': 'https://pizzoshop.com',
                'referer': 'https://pizzoshop.com/mlchecker',
                'user-agent': 'Mozilla/5.0'
            }
            await asyncio.to_thread(scraper.get, "https://pizzoshop.com/mlchecker", headers=pizzo_headers, timeout=10)
            pizzo_res_raw = await asyncio.to_thread(scraper.post, "https://pizzoshop.com/mlchecker/check", data={'user_id': game_id, 'zone_id': zone_id}, headers=pizzo_headers, timeout=15)
            pizzo_soup = BeautifulSoup(pizzo_res_raw.text, 'html.parser')
            table = pizzo_soup.find('table', class_='table-modern')
            
            if table:
                for row in table.find_all('tr'):
                    th, td = row.find('th'), row.find('td')
                    if th and td and ('region id' in th.get_text(strip=True).lower() or 'region' in th.get_text(strip=True).lower()):
                        pizzo_region = td.get_text(strip=True)
        except: pass

        final_region = pizzo_region if pizzo_region != "Unknown" else smile_region

        report = f"ɢᴀᴍᴇ ɪᴅ : {game_id} ({zone_id})\nɪɢɴ ɴᴀᴍᴇ : {ig_name}\nʀᴇɢɪᴏɴ : {final_region}"
        await loading_msg.edit_text(report)

    except Exception as e:
        await loading_msg.edit_text(f"❌ System Error: {str(e)}")


# ==========================================
# 🔍 1. DISPUTE & VERIFICATION COMMAND (GAME ID + ORDER ID SEARCH)
# ==========================================
import datetime 

@dp.message(or_f(Command("checkcus"), Command("cus"), F.text.regexp(r"(?i)^\.(?:checkcus|cus)(?:$|\s+)")))
async def check_official_customer(message: types.Message):
    tg_id = str(message.from_user.id)
    
    is_owner = (message.from_user.id == OWNER_ID)
    user_data = await db.get_reseller(tg_id) 
    
    if not is_owner and not user_data:
        return await message.reply("❌ You are not authorized. Only registered users can use this command.")
        
    parts = message.text.strip().split()
    if len(parts) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>.cus <Game_ID></code> သို့မဟုတ် <code>.cus <Order_ID></code>", parse_mode=ParseMode.HTML)
        
    # 🟢 Game ID ဖြစ်စေ၊ Order ID ဖြစ်စေ လက်ခံမည်
    search_query = parts[1]
    loading_msg = await message.reply(f"Deep Searching Official Records for: <code>{search_query}</code>...", parse_mode=ParseMode.HTML)
    
    scraper = await get_main_scraper()
    headers = {'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://www.smile.one'}
    
    urls_to_check = [
        'https://www.smile.one/customer/activationcode/codelist',
        'https://www.smile.one/ph/customer/activationcode/codelist'
    ]
    
    found_orders = []
    seen_ids = set()
    
    try:
        for api_url in urls_to_check:
            for page_num in range(1, 11): 
                res = await asyncio.to_thread(
                    scraper.get, api_url, 
                    params={'type': 'orderlist', 'p': str(page_num), 'pageSize': '50'}, 
                    headers=headers, timeout=15
                )
                try:
                    data = res.json()
                    if 'list' in data and isinstance(data['list'], list) and len(data['list']) > 0:
                        for order in data['list']:
                            current_user_id = str(order.get('user_id') or order.get('role_id') or '')
                            order_id = str(order.get('increment_id') or order.get('id') or '')
                            status_val = str(order.get('order_status', '') or order.get('status', '')).lower()
                            
                            # 🟢 ရှာဖွေသည့်စာသားသည် Game ID နှင့်ဖြစ်စေ၊ Order ID နှင့်ဖြစ်စေ ကိုက်ညီမှုရှိမရှိ နှစ်မျိုးလုံး စစ်ဆေးမည်
                            if (current_user_id == search_query or order_id == search_query) and status_val in ['success', '1']:
                                if order_id not in seen_ids:
                                    seen_ids.add(order_id)
                                    found_orders.append(order)
                    else:
                        break 
                except:
                    break
                
        if not found_orders:
            return await loading_msg.edit_text(f"❌ No successful records found for: <code>{search_query}</code> in recent transactions.", parse_mode=ParseMode.HTML)
            
        found_orders = found_orders[:1] 
        
        report = f"🔍 <b>Official Records for {search_query}</b>\n\n"
        
        for order in found_orders:
            serial_id = str(order.get('increment_id') or order.get('id') or 'Unknown Serial')
            date_str = str(order.get('created_at') or order.get('updated_at') or order.get('create_time') or order.get('insert_time') or order.get('add_time') or order.get('pay_time') or '')
            currency_sym = str(order.get('total_fee_currency') or '$')
            
            date_display = date_str
            if date_str:
                try:
                    dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    
                    if currency_sym == 'BRL':
                        mmt_dt = dt_obj + datetime.timedelta(hours=9, minutes=30)
                    elif currency_sym == 'PHP':
                        mmt_dt = dt_obj - datetime.timedelta(hours=1, minutes=30)
                    else:
                        mmt_dt = dt_obj + datetime.timedelta(hours=9, minutes=30)
                        
                    mm_time_str = mmt_dt.strftime("%I:%M:%S %p") 
                    date_display = f"{date_str} ( MM - {mm_time_str} )"
                except Exception:
                    date_display = date_str

            raw_item_name = str(order.get('product_name') or order.get('goods_name') or order.get('goods_title') or order.get('title') or order.get('name') or 'Unknown Item')
            raw_item_name = raw_item_name.replace("Mobile Legends BR - ", "").replace("Mobile Legends - ", "").strip()
            
            translations = {
                "Passe Semanal de Diamante": "Weekly Diamond Pass",
                "Passagem do crepúsculo": "Twilight Pass",
                "Passe Crepúsculo": "Twilight Pass",
                "Pacote Semanal Elite": "Elite Weekly Bundle",
                "Pacote Mensal Épico": "Epic Monthly Bundle",
                "Membro Estrela Plus": "Starlight Member Plus",
                "Membro Estrela": "Starlight Member",
                "Diamantes": "Diamonds",
                "Diamante": "Diamond",
                "Bônus": "Bonus",
                "Pacote": "Bundle"
            }
            
            for pt, en in translations.items():
                if pt in raw_item_name:
                    raw_item_name = raw_item_name.replace(pt, en)
                    
            if raw_item_name.endswith(" c") or raw_item_name.endswith(" ("):
                raw_item_name = raw_item_name[:-2]
                
            raw_item_name = raw_item_name.strip()
            
            if currency_sym == 'PHP':
                final_item_name = f"Mobile Legends PH - {raw_item_name}"
            else:
                final_item_name = f"Mobile Legends BR - {raw_item_name}"
            
            price = str(order.get('price') or order.get('grand_total') or order.get('transaction_amount') or order.get('real_money') or order.get('pay_amount') or order.get('money') or order.get('amount') or order.get('total_amount') or '0.00')
            if currency_sym != '$':
                price_display = f"{price} {currency_sym}"
            else:
                price_display = f"${price}"
                
            report += f"🏷 <code>{serial_id}</code>\n📅 <code>{date_display}</code>\n💎 {final_item_name} ({price_display})\n📊 Status: ✅ Success\n\n"
            
        await loading_msg.edit_text(report, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await loading_msg.edit_text(f"❌ Search Error: {str(e)}", parse_mode=ParseMode.HTML)
        

# ==========================================
# 👑 2. VIP & TOP CUSTOMER COMMANDS
# ==========================================
@dp.message(or_f(Command("topcus"), F.text.regexp(r"(?i)^\.topcus$")))
async def show_top_customers(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("❌ Only Owner.")
    
    top_spenders = await db.get_top_customers(limit=10)
    if not top_spenders: return await message.reply("📜 No orders found in database.")
    
    report = "🏆 **Top 10 Customers (By Total Spent)** 🏆\n\n"
    for i, user in enumerate(top_spenders, 1):
        tg_id = user['_id']
        spent = user['total_spent']
        count = user['order_count']
        
        # Database ထဲမှာ VIP ဟုတ်မဟုတ် ပြန်စစ်မည်
        user_info = await db.get_reseller(tg_id)
        vip_tag = "🌟 [VIP]" if user_info and user_info.get('is_vip') else ""
        
        report += f"**{i}.** `ID: {tg_id}` {vip_tag}\n💰 Spent: ${spent:,.2f} ({count} Orders)\n\n"
        
    report += "💡 *Use `.setvip <ID>` to grant VIP status.*"
    await message.reply(report)

@dp.message(or_f(Command("setvip"), F.text.regexp(r"(?i)^\.setvip(?:$|\s+)")))
async def grant_vip_status(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("❌ Only Owner.")
    parts = message.text.strip().split()
    if len(parts) < 2: return await message.reply("⚠️ **Usage:** `.setvip <User_ID>`")
    
    target_id = parts[1]
    user = await db.get_reseller(target_id)
    if not user: return await message.reply("❌ User not found.")
    
    current_status = user.get('is_vip', False)
    new_status = not current_status # ရှိရင် ဖြုတ်မည်၊ မရှိရင် ပေးမည် (Toggle)
    
    await db.set_vip_status(target_id, new_status)
    status_msg = "Granted 🌟" if new_status else "Revoked ❌"
    await message.reply(f"✅ VIP Status for `{target_id}` has been **{status_msg}**.")


# ==========================================
# 📊 3. AUTO-RECONCILIATION TASK
# ==========================================
async def daily_reconciliation_task():
    """ညစဉ် ၁၁:၅၀ မိနစ်တိုင်းတွင် Bot ၏ စာရင်းနှင့် Official စာရင်းကိုက်ညီမှု စစ်ဆေးမည်"""
    while True:
        now = datetime.datetime.now(MMT)
        # ည ၁၁:၅၀ တွင် Run မည်
        target_time = now.replace(hour=23, minute=50, second=0, microsecond=0)
        if now >= target_time:
            target_time += datetime.timedelta(days=1)
            
        wait_seconds = (target_time - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        
        print(f"[{datetime.datetime.now(MMT).strftime('%I:%M %p')}] 🔄 Running Daily Reconciliation...")
        
        try:
            # 1. Bot ၏ Database မှ ယနေ့ Order အနှစ်ချုပ်ကို ယူမည်
            db_summary = await db.get_today_orders_summary()
            db_total_spent = db_summary['total_spent']
            db_order_count = db_summary['total_orders']
            
            # 2. Official Smile.one မှ ယူရန် (Scrape or use /customer/order history)
            # အကယ်၍ Official က Scrape လုပ်၍မရပါက Local စာရင်းကိုသာ Report ပို့မည်
            scraper = await get_main_scraper()
            headers = {'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://www.smile.one'}
            balances = await get_smile_balance(scraper, headers)
            
            report = (
                "📊 **Daily Reconciliation Report** 📊\n\n"
                "**1. Bot System (V-Wallet) Records:**\n"
                f"🔹 Total Orders Today: `{db_order_count}`\n"
                f"🔹 Total Spent Today: `${db_total_spent:,.2f}`\n\n"
                "**2. Official Smile.one Balances:**\n"
                f"🇧🇷 BR: `${balances.get('br_balance', 0.0):,.2f}`\n"
                f"🇵🇭 PH: `${balances.get('ph_balance', 0.0):,.2f}`\n\n"
                "*(Please verify if the balances align with your expected expenses.)*"
            )
            
            await notify_owner(report)
            
        except Exception as e:
            print(f"Reconciliation Error: {e}")


# ==========================================
# 📋 AUTO FORMAT & COPY BUTTON (SMART WP FIX)
# ==========================================
@dp.message(or_f(
    F.text.regexp(r"^\d{7,}(?:\s+\(?\d+\)?)?\s*.*$"),
    F.caption.regexp(r"^\d{7,}(?:\s+\(?\d+\)?)?\s*.*$")
))
async def format_and_copy_text(message: types.Message):
    raw_text = (message.text or message.caption).strip()
    
    if re.match(r"^\d{7,}$", raw_text):
        formatted_raw = raw_text
        
    elif re.match(r"^\d{7,}\s+\d+", raw_text):
        match = re.match(r"^(\d{7,})\s+(\d+)\s*(.*)$", raw_text)
        if match:
            player_id = match.group(1)
            zone_id = match.group(2)
            suffix = match.group(3).strip()
            
            if suffix:
                # wp စစ်တာ အရင်အတိုင်းပဲ
                clean_suffix = suffix.lower().replace(" ", "")
                wp_match = re.match(r"^(\d*)wp(\d*)$", clean_suffix)
                
                if wp_match:
                    num_str = wp_match.group(1) + wp_match.group(2)
                    if num_str == "" or num_str == "1":
                        processed_suffix = "wp"
                    else:
                        processed_suffix = f"wp{num_str}"
                else:
                    processed_suffix = suffix
                    
                formatted_raw = f"{player_id} ({zone_id}) {processed_suffix}"
            else:
                formatted_raw = f"{player_id} ({zone_id})"
        else:
            formatted_raw = raw_text
    
    elif re.match(r"^\d{7,}\s*\(\d+\)", raw_text):
        match = re.match(r"^(\d{7,})\s*\((\d+)\)\s*(.*)$", raw_text)
        if match:
            player_id = match.group(1)
            zone_id = match.group(2)
            suffix = match.group(3).strip()
            
            if suffix:
                clean_suffix = suffix.lower().replace(" ", "")
                wp_match = re.match(r"^(\d*)wp(\d*)$", clean_suffix)
                
                if wp_match:
                    num_str = wp_match.group(1) + wp_match.group(2)
                    if num_str == "" or num_str == "1":
                        processed_suffix = "wp"
                    else:
                        processed_suffix = f"wp{num_str}"
                else:
                    processed_suffix = suffix
                    
                formatted_raw = f"{player_id} ({zone_id}) {processed_suffix}"
            else:
                formatted_raw = f"{player_id} ({zone_id})"
        else:
            formatted_raw = raw_text
            
    else:
        formatted_raw = raw_text

    formatted_text = f"<code>{formatted_raw}</code>"
    
    try:
        from aiogram.types import CopyTextButton
        copy_btn = InlineKeyboardButton(
            text="ᴄᴏᴘʏ",
            copy_text=CopyTextButton(text=formatted_raw),
            style="primary"
        )
    except ImportError:
        copy_btn = InlineKeyboardButton(
            text="ᴄᴏᴘʏ",
            switch_inline_query=formatted_raw,
            style="primary"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[copy_btn]])
    
    await message.reply(formatted_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

##############################################

# ==========================================
# ℹ️ HELP & START COMMANDS
# ==========================================
@dp.message(or_f(Command("help"), F.text.regexp(r"(?i)^\.help$")))
async def send_help_message(message: types.Message):
    is_owner = (message.from_user.id == OWNER_ID)
    
    help_text = (
        f"<b>🤖 𝐁𝐎𝐓 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 𝐌𝐄𝐍𝐔</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"<b>💎 𝐌𝐋𝐁Ｂ 𝐃𝐢𝐚𝐦𝐨𝐧𝐝𝐬 (ဝယ်ယူရန်)</b>\n"
        f"🇧🇷 BR MLBB: <code>msc/mlb/br/b ID (Zone) Pack</code>\n"
        f"🇵🇭 PH MLBB: <code>mlp/ph/p ID (Zone) Pack</code>\n\n"
        f"<b>♟️ 𝐌𝐚𝐠𝐢𝐜 𝐂𝐡𝐞𝐬𝐬 (ဝယ်ယူရန်)</b>\n"
        f"🇧🇷 BR MCC: <code>mcc/mcb ID (Zone) Pack</code>\n"
        f"🇵🇭 PH MCC: <code>mcp ID (Zone) Pack</code>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"<b>👤 𝐔𝐬𝐞𝐫 𝐓𝐨𝐨𝐥𝐬 (အသုံးပြုသူများအတွက်)</b>\n"
        f"🔹 <code>.bal</code>      : မိမိ Wallet Balance စစ်ရန်\n"
        f"🔹 <code>.role</code>     : Game ID နှင့် Region စစ်ရန်\n"
        f"🔹 <code>.his</code>      : မိမိဝယ်ယူခဲ့သော မှတ်တမ်းကြည့်ရန်\n"
        f"🔹 <code>.clean</code>    : မှတ်တမ်းများ ဖျက်ရန်\n"
        f"🔹 <code>.listb</code>     : BR ဈေးနှုန်းစာရင်း ကြည့်ရန်\n"
        f"🔹 <code>.listp</code>     : PH ဈေးနှုန်းစာရင်း ကြည့်ရန်\n"
        f"🔹 <code>.listmb</code>    : MCC ဈေးနှုန်းစာရင်း ကြည့်ရန်\n"
        f"💡 <i>Tip: 50+50 ဟုရိုက်ထည့်၍ ဂဏန်းပေါင်းစက်အဖြစ် သုံးနိုင်ပါသည်။</i>\n"
    )
    
    # 🟢 Owner အတွက်သာ ပေါ်မည့် သီးသန့် Command များ
    if is_owner:
        help_text += (
            f"\n━━━━━━━━━━━━━━━━━\n"
            f"<b>👑 𝐎𝐰𝐧𝐞𝐫 𝐓𝐨𝐨𝐥𝐬 (Admin သီးသန့်)</b>\n\n"
            f"<b>👥 ယူဆာစီမံခန့်ခွဲမှု</b>\n"
            f"🔸 <code>.add ID</code>    : User အသစ်ထည့်ရန်\n"
            f"🔸 <code>.remove ID</code> : User အား ဖယ်ရှားရန်\n"
            f"🔸 <code>.users</code>     : User စာရင်းအားလုံး ကြည့်ရန်\n\n"
            f"<b>💰 ဘာလန်း နှင့် ငွေဖြည့်</b>\n"
            f"🔸 <code>.addbal ID 50 BR</code>  : Balance ပေါင်းထည့်ရန်\n"
            f"🔸 <code>.deduct ID 50 BR</code>  : Balance နှုတ်ယူရန်\n"
            f"🔸 <code>.topup Code</code>       : Smile Code ဖြည့်သွင်းရန်\n\n"
            f"<b>💼 VIP နှင့် စာရင်းစစ်</b>\n"
            f"🔸 <code>.checkcus ID</code> : Official မှတ်တမ်း လှမ်းစစ်ရန်\n"
            f"🔸 <code>.topcus</code>      : ငွေအများဆုံးသုံးထားသူများ ကြည့်ရန်\n"
            f"🔸 <code>.setvip ID</code>   : VIP အဖြစ် သတ်မှတ်ရန်/ဖြုတ်ရန်\n\n"
            f"<b>⚙️ System Setup</b>\n"
            f"🔸 <code>.cookies</code>    : Cookie အခြေအနေ စစ်ဆေးရန်\n"
            f"🔸 <code>/setcookie</code>  : Main Cookie အသစ်ပြောင်းရန်\n"
        )
        
    help_text += f"\n━━━━━━━━━━━━━━━━━"
    await message.reply(help_text, parse_mode=ParseMode.HTML)

@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    try:
        tg_id = str(message.from_user.id)
        
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        if not full_name:
            full_name = "User"
            
        safe_full_name = full_name.replace('<', '').replace('>', '')
        username_display = f'<a href="tg://user?id={tg_id}">{safe_full_name}</a>'
        
        EMOJI_1 = "5956355397366320202" # 🥺
        EMOJI_2 = "5954097490109140119" # 👤
        EMOJI_3 = "5958289678837746828" # 🆔
        EMOJI_4 = "5956330306167376831" # 📊
        EMOJI_5 = "5954078884310814346" # 📞

        if await is_authorized(message.from_user.id):
            status = "🟢 Aᴄᴛɪᴠᴇ"
        else:
            status = "🔴 Nᴏᴛ Aᴄᴛɪᴠᴇ"
            
        welcome_text = (
            f"ʜᴇʏ ʙᴀʙʏ <tg-emoji emoji-id='{EMOJI_1}'>🥺</tg-emoji>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_2}'>👤</tg-emoji> Usᴇʀɴᴀᴍᴇ: {username_display}\n"
            f"<tg-emoji emoji-id='{EMOJI_3}'>🆔</tg-emoji> 𝐈𝐃: <code>{tg_id}</code>\n"
            f"<tg-emoji emoji-id='{EMOJI_4}'>📊</tg-emoji> Sᴛᴀᴛᴜs: {status}\n\n"
            f"<tg-emoji emoji-id='{EMOJI_5}'>📞</tg-emoji> Cᴏɴᴛᴀᴄᴛ ᴜs: @iwillgoforwardsalone"
        )
        
        await message.reply(welcome_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        print(f"Start Cmd Error: {e}")
        
        fallback_text = (
            f"ʜᴇʏ ʙᴀʙʏ 🥺\n\n"
            f"👤 Usᴇʀɴᴀᴍᴇ: {full_name}\n"
            f"🆔 𝐈𝐃: <code>{tg_id}</code>\n"
            f"📊 Sᴛᴀᴛᴜs: 🔴 Nᴏᴛ Aᴄᴛɪᴠᴇ\n\n"
            f"📞 Cᴏɴᴛᴀᴄᴛ ᴜs: @iwillgoforwardsalone"
        )
        await message.reply(fallback_text, parse_mode=ParseMode.HTML)


# ==========================================
# 10. MAIN RUN EXECUTION
# ==========================================
async def main():
    print("Starting Heartbeat & Auto-login tasks...")
    print("နှလုံးသားမပါရင် ဘယ်အရာမှတရားမဝင်.....")
    
    # 🟢 Concurrency အတွက် Thread Pool Limit ကို main() ထဲတွင်သာ သတ်မှတ်ပါ
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=50))
    
    # Background Tasks များကို Event Loop ပေါ်တင်ပေးခြင်း
    asyncio.create_task(keep_cookie_alive())
    asyncio.create_task(schedule_daily_cookie_renewal())
    asyncio.create_task(daily_reconciliation_task())
    
    # Database Initialization
    await db.setup_indexes()
    await db.init_owner(OWNER_ID)

    print("Bot is successfully running on Aiogram 3 Framework... 🎉")
    
    # Aiogram Polling စတင်ခြင်း
    await dp.start_polling(bot)

if __name__ == '__main__':
    
    asyncio.run(main())
