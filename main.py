import io
import os
import re
import datetime
import time
import random
import asyncio
import html
from collections import defaultdict
import concurrent.futures

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from curl_cffi.requests import AsyncSession

from aiogram import Bot, Dispatcher, F, types
from aiogram import BaseMiddleware
from aiogram.filters import Command, or_f
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

import database as db
from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable

# ပုံမှန်အားဖြင့် Maintenance ကို ပိတ်ထားမည်
IS_MAINTENANCE = False 

class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        global IS_MAINTENANCE
        if IS_MAINTENANCE:
            # Owner ကလွဲ၍ ကျန်သော User များကို Block မည်
            if event.from_user.id != OWNER_ID:
                await event.reply("⚠️ ပြုပြင်ဆောင်ရွက်နေပါသဖြင့် Topup ဘော့အား ခနရပ်ထားပါသည်။")
                return # ဤနေရာတွင် ရပ်ပစ်မည် (Command များဆီ ဆက်မသွားတော့ပါ)
        return await handler(event, data)


load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', 1318826936))
FB_EMAIL = os.getenv('FB_EMAIL')
FB_PASS = os.getenv('FB_PASS')

if not BOT_TOKEN:
    print("❌ Error: BOT_TOKEN is missing in the .env file.")
    exit()

MMT = datetime.timezone(datetime.timedelta(hours=6, minutes=30))

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.message.middleware(MaintenanceMiddleware())

user_locks = defaultdict(asyncio.Lock)
api_semaphore = asyncio.Semaphore(3)
auth_lock = asyncio.Lock()
last_login_time = 0
GLOBAL_SCAMMERS = set()

GLOBAL_SCRAPER = None
GLOBAL_COOKIE_STR = ""
GLOBAL_CSRF = {'mlbb_br': None, 'mlbb_ph': None, 'mcc_br': None, 'mcc_ph': None}

async def get_main_scraper():
    global GLOBAL_SCRAPER, GLOBAL_COOKIE_STR, GLOBAL_CSRF
    
    raw_cookie = await db.get_main_cookie() or ""
    
    if GLOBAL_SCRAPER is None or raw_cookie != GLOBAL_COOKIE_STR:
        cookie_dict = {}
        if raw_cookie:
            for item in raw_cookie.split(';'):
                if '=' in item:
                    k, v = item.strip().split('=', 1)
                    cookie_dict[k.strip()] = v.strip()
                    
        GLOBAL_SCRAPER = AsyncSession(impersonate="chrome120", cookies=cookie_dict)
        GLOBAL_COOKIE_STR = raw_cookie
        GLOBAL_CSRF = {'mlbb_br': None, 'mlbb_ph': None, 'mcc_br': None, 'mcc_ph': None}
        
    return GLOBAL_SCRAPER

async def auto_login_and_get_cookie():
    global last_login_time, GLOBAL_SCRAPER, GLOBAL_CSRF
    
    if not FB_EMAIL or not FB_PASS:
        print("❌ FB_EMAIL and FB_PASS are missing in .env.")
        return False
        
    async with auth_lock:
        if time.time() - last_login_time < 120:
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
                    
                    last_login_time = time.time()
                    GLOBAL_SCRAPER = None
                    GLOBAL_CSRF = {'mlbb_br': None, 'mlbb_ph': None, 'mcc_br': None, 'mcc_ph': None}
                    return True
                    
                except Exception as wait_e:
                    print(f"❌ Did not reach the Order page. (Possible Checkpoint): {wait_e}")
                    await browser.close()
                    return False
                
        except Exception as e:
            print(f"❌ Error during Auto-Login: {e}")
            return False

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

async def get_smile_balance(scraper, headers, balance_url='https://www.smile.one/customer/order'):
    balances = {'br_balance': 0.00, 'ph_balance': 0.00}
    try:
        response = await scraper.get(balance_url, headers=headers, timeout=15)
        
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

async def process_smile_one_order(game_id, zone_id, product_id, currency_name, prev_context=None, skip_role_check=False, known_ig_name="Unknown", last_success_order_id=""):
    scraper = await get_main_scraper()
    global GLOBAL_CSRF
    cache_key = f"mlbb_{currency_name.lower()}"

    if currency_name == 'PH':
        main_url = 'https://www.smile.one/ph/merchant/mobilelegends'
        checkrole_url = 'https://www.smile.one/ph/merchant/mobilelegends/checkrole'
        query_url = 'https://www.smile.one/ph/merchant/mobilelegends/query'
        pay_url = 'https://www.smile.one/ph/merchant/mobilelegends/pay'
        order_api_url = 'https://www.smile.one/ph/customer/activationcode/codelist'
    else:
        main_url = 'https://www.smile.one/merchant/mobilelegends'
        checkrole_url = 'https://www.smile.one/merchant/mobilelegends/checkrole'
        query_url = 'https://www.smile.one/merchant/mobilelegends/query'
        pay_url = 'https://www.smile.one/merchant/mobilelegends/pay'
        order_api_url = 'https://www.smile.one/customer/activationcode/codelist'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Requested-With': 'XMLHttpRequest', 
        'Referer': main_url, 
        'Origin': 'https://www.smile.one'
    }

    try:
        csrf_token = prev_context.get('csrf_token') if prev_context else GLOBAL_CSRF.get(cache_key)
        ig_name = known_ig_name

        if not csrf_token:
            response = await scraper.get(main_url, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            meta_tag = soup.find('meta', {'name': 'csrf-token'})
            csrf_token = meta_tag.get('content') if meta_tag else (soup.find('input', {'name': '_csrf'}).get('value') if soup.find('input', {'name': '_csrf'}) else None)
            if not csrf_token: return {"status": "error", "message": "CSRF Token not found. Re-add Cookie."}
            GLOBAL_CSRF[cache_key] = csrf_token

        async def get_flow_id():
            query_data = {'user_id': game_id, 'zone_id': zone_id, 'pid': product_id, 'checkrole': '', 'pay_methond': 'smilecoin', 'channel_method': 'smilecoin', '_csrf': csrf_token}
            return await scraper.post(query_url, data=query_data, headers=headers)

        async def check_role():
            check_data = {'user_id': game_id, 'zone_id': zone_id, '_csrf': csrf_token}
            return await scraper.post(checkrole_url, data=check_data, headers=headers)

        if skip_role_check:
            query_response_raw = await get_flow_id()
        else:
            query_response_raw, role_response_raw = await asyncio.gather(get_flow_id(), check_role())
            try:
                role_result = role_response_raw.json()
                ig_name = role_result.get('username') or role_result.get('data', {}).get('username')
                if not ig_name or str(ig_name).strip() == "":
                    return {"status": "error", "message": "❌ Invalid Account: Account not found."}
            except Exception: 
                return {"status": "error", "message": "Check Role API Error."}

        try: query_result = query_response_raw.json()
        except Exception: return {"status": "error", "message": "Query API Error"}
            
        flowid = query_result.get('flowid') or query_result.get('data', {}).get('flowid')
        
        if not flowid:
            real_error = query_result.get('msg') or query_result.get('message') or ""
            if "login" in str(real_error).lower() or "unauthorized" in str(real_error).lower():
                GLOBAL_CSRF[cache_key] = None
                await notify_owner("⚠️ <b>Order Alert:</b> Cookie expired. Auto-login started...")
                success = await auto_login_and_get_cookie()
                if success: return {"status": "error", "message": "Session renewed. Please try again."}
                else: return {"status": "error", "message": "❌ Auto-Login failed. Please /setcookie."}
            return {"status": "error", "message": f"❌ Query Failed: {real_error}"}

        pay_data = {'_csrf': csrf_token, 'user_id': game_id, 'zone_id': zone_id, 'pay_methond': 'smilecoin', 'product_id': product_id, 'channel_method': 'smilecoin', 'flowid': flowid, 'email': '', 'coupon_id': ''}
        pay_response_raw = await scraper.post(pay_url, data=pay_data, headers=headers)
        pay_text = pay_response_raw.text.lower()
        
        if "saldo insuficiente" in pay_text or "insufficient" in pay_text:
            return {"status": "error", "message": "Insufficient balance in the Main account."}
        
        real_order_id, is_success = "Not found", False
        actual_product_name = ""

        try:
            pay_json = pay_response_raw.json()
            status_val = str(pay_json.get('status', ''))
            code = str(pay_json.get('code', status_val))
            msg = str(pay_json.get('msg', pay_json.get('message', ''))).lower()
            
            if code in ['200', '0', '1'] or 'success' in msg: 
                is_success = True
                _id = str(pay_json.get('data', {}).get('order_id') or pay_json.get('order_id') or pay_json.get('increment_id') or "")
                if not _id or _id == "None":
                    _id = f"FAST_{int(time.time())}_{random.randint(100,999)}"
                real_order_id = _id
        except:
            if 'success' in pay_text or 'sucesso' in pay_text: 
                is_success = True
                real_order_id = f"FAST_{int(time.time())}_{random.randint(100,999)}"

        if not is_success:
            try:
                hist_res_raw = await scraper.get(order_api_url, params={'type': 'orderlist', 'p': '1', 'pageSize': '5'}, headers=headers)
                hist_json = hist_res_raw.json()
                if 'list' in hist_json and len(hist_json['list']) > 0:
                    for order in hist_json['list']:
                        if str(order.get('user_id')) == str(game_id) and str(order.get('server_id')) == str(zone_id):
                            current_order_id = str(order.get('increment_id', ""))
                            if current_order_id != last_success_order_id:
                                if str(order.get('order_status', '')).lower() in ['success', '1'] or str(order.get('status')) == '1':
                                    real_order_id = current_order_id
                                    actual_product_name = str(order.get('product_name', ''))
                                    is_success = True
                                    break
            except: pass

        if is_success:
            return {"status": "success", "ig_name": ig_name, "order_id": real_order_id, "csrf_token": csrf_token, "product_name": actual_product_name}
        else:
            return {"status": "error", "message": "Payment Verification Failed."}

    except Exception as e: return {"status": "error", "message": f"System Error: {str(e)}"}

async def process_mcc_order(game_id, zone_id, product_id, currency_name, prev_context=None, skip_role_check=False, known_ig_name="Unknown", last_success_order_id=""):
    scraper = await get_main_scraper()
    global GLOBAL_CSRF
    cache_key = f"mcc_{currency_name.lower()}"

    if currency_name == 'PH':
        main_url = 'https://www.smile.one/ph/merchant/game/magicchessgogo'
        checkrole_url = 'https://www.smile.one/ph/merchant/game/checkrole'
        query_url = 'https://www.smile.one/ph/merchant/game/query'
        pay_url = 'https://www.smile.one/ph/merchant/game/pay'
        order_api_url = 'https://www.smile.one/ph/customer/activationcode/codelist'
    else:
        main_url = 'https://www.smile.one/br/merchant/game/magicchessgogo'
        checkrole_url = 'https://www.smile.one/br/merchant/game/checkrole'
        query_url = 'https://www.smile.one/br/merchant/game/query'
        pay_url = 'https://www.smile.one/br/merchant/game/pay'
        order_api_url = 'https://www.smile.one/br/customer/activationcode/codelist'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Requested-With': 'XMLHttpRequest', 
        'Referer': main_url, 
        'Origin': 'https://www.smile.one'
    }

    try:
        csrf_token = prev_context.get('csrf_token') if prev_context else GLOBAL_CSRF.get(cache_key)
        ig_name = known_ig_name
        
        if not csrf_token:
            response = await scraper.get(main_url, headers=headers)
            if response.status_code in [403, 503] or "cloudflare" in response.text.lower():
                 return {"status": "error", "message": "Blocked by Cloudflare."}

            soup = BeautifulSoup(response.text, 'html.parser')
            meta_tag = soup.find('meta', {'name': 'csrf-token'})
            csrf_token = meta_tag.get('content') if meta_tag else (soup.find('input', {'name': '_csrf'}).get('value') if soup.find('input', {'name': '_csrf'}) else None)
            if not csrf_token: return {"status": "error", "message": "CSRF Token not found. Add a new Cookie using /setcookie."}
            GLOBAL_CSRF[cache_key] = csrf_token

        async def get_flow_id():
            query_data = {'user_id': game_id, 'zone_id': zone_id, 'pid': product_id, 'checkrole': '', 'pay_methond': 'smilecoin', 'channel_method': 'smilecoin', '_csrf': csrf_token}
            return await scraper.post(query_url, data=query_data, headers=headers)

        async def check_role():
            check_data = {'user_id': game_id, 'zone_id': zone_id, '_csrf': csrf_token}
            return await scraper.post(checkrole_url, data=check_data, headers=headers)

        if skip_role_check:
            query_response_raw = await get_flow_id()
        else:
            query_response_raw, role_response_raw = await asyncio.gather(get_flow_id(), check_role())
            try:
                role_result = role_response_raw.json()
                ig_name = role_result.get('username') or role_result.get('data', {}).get('username')
                if not ig_name or str(ig_name).strip() == "":
                    return {"status": "error", "message": "Account not found."}
            except Exception: 
                return {"status": "error", "message": "⚠️ Check Role API Error."}

        try: query_result = query_response_raw.json()
        except Exception: return {"status": "error", "message": "Query API Error"}
            
        flowid = query_result.get('flowid') or query_result.get('data', {}).get('flowid')
        
        if not flowid:
            real_error = query_result.get('msg') or query_result.get('message') or ""
            if "login" in str(real_error).lower() or "unauthorized" in str(real_error).lower():
                GLOBAL_CSRF[cache_key] = None
                await notify_owner("⚠️ <b>Order Alert:</b> Cookie expired. Auto-login started...")
                success = await auto_login_and_get_cookie()
                if success:
                    return {"status": "error", "message": "Session renewed. Please enter the command again."}
                else: 
                    return {"status": "error", "message": "❌ Auto-Login failed. Please provide /setcookie."}
            return {"status": "error", "message": "Invalid account or unable to purchase."}

        pay_data = {'_csrf': csrf_token, 'user_id': game_id, 'zone_id': zone_id, 'pay_methond': 'smilecoin', 'product_id': product_id, 'channel_method': 'smilecoin', 'flowid': flowid, 'email': '', 'coupon_id': ''}
        pay_response_raw = await scraper.post(pay_url, data=pay_data, headers=headers)
        pay_text = pay_response_raw.text.lower()
        
        if "saldo insuficiente" in pay_text or "insufficient" in pay_text:
            return {"status": "error", "message": "Insufficient balance in the Main account."}
        
        real_order_id, is_success = "Not found", False
        actual_product_name = ""

        try:
            pay_json = pay_response_raw.json()
            status_val = str(pay_json.get('status', ''))
            code = str(pay_json.get('code', status_val))
            msg = str(pay_json.get('msg', pay_json.get('message', ''))).lower()
            
            if code in ['200', '0', '1'] or 'success' in msg: 
                is_success = True
                _id = str(pay_json.get('data', {}).get('order_id') or pay_json.get('order_id') or pay_json.get('increment_id') or "")
                if not _id or _id == "None":
                    _id = f"FAST_{int(time.time())}_{random.randint(100,999)}"
                real_order_id = _id
        except:
            if 'success' in pay_text or 'sucesso' in pay_text: 
                is_success = True
                real_order_id = f"FAST_{int(time.time())}_{random.randint(100,999)}"

        if not is_success:
            try:
                hist_res_raw = await scraper.get(order_api_url, params={'type': 'orderlist', 'p': '1', 'pageSize': '5'}, headers=headers)
                hist_json = hist_res_raw.json()
                if 'list' in hist_json and len(hist_json['list']) > 0:
                    for order in hist_json['list']:
                        if str(order.get('user_id')) == str(game_id) and str(order.get('server_id')) == str(zone_id):
                            current_order_id = str(order.get('increment_id', ""))
                            if current_order_id != last_success_order_id:
                                if str(order.get('order_status', '')).lower() in ['success', '1'] or str(order.get('status')) == '1':
                                    real_order_id = current_order_id
                                    actual_product_name = str(order.get('product_name', ''))
                                    is_success = True
                                    break
            except: pass

        if is_success:
            return {"status": "success", "ig_name": ig_name, "order_id": real_order_id, "csrf_token": csrf_token, "product_name": actual_product_name}
        else:
            return {"status": "error", "message": "Payment Verification Failed."}

    except Exception as e: return {"status": "error", "message": f"System Error: {str(e)}"}

async def is_authorized(user_id: int):
    if user_id == OWNER_ID:
        return True
    user = await db.get_reseller(str(user_id))
    return user is not None

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
    
    global GLOBAL_SCRAPER, GLOBAL_CSRF
    GLOBAL_SCRAPER = None
    GLOBAL_CSRF = {'mlbb_br': None, 'mlbb_ph': None, 'mcc_br': None, 'mcc_ph': None}
    await message.reply("✅ **Main Cookie has been successfully updated securely.**")

@dp.message(F.text.contains("PHPSESSID") & F.text.contains("cf_clearance"))
async def handle_smart_cookie_update(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("❌ You are not authorized.")
    text = message.text
    target_keys = ["PHPSESSID", "cf_clearance", "__cf_bm", "_did", "_csrf"]
    extracted_cookies = {}
    try:
        for key in target_keys:
            pattern = rf"['\"]?{key}['\"]?\s*[:=]\s*['\"]?([^'\",;\s}}]+)['\"]?"
            match = re.search(pattern, text)
            if match:
                extracted_cookies[key] = match.group(1)
        if "PHPSESSID" not in extracted_cookies or "cf_clearance" not in extracted_cookies:
            return await message.reply("❌ <b>Error:</b> `PHPSESSID` နှင့် `cf_clearance` ကို ရှာမတွေ့ပါ။ Format မှန်ကန်ကြောင်း စစ်ဆေးပါ။", parse_mode=ParseMode.HTML)
        formatted_cookie_str = "; ".join([f"{k}={v}" for k, v in extracted_cookies.items()])
        await db.update_main_cookie(formatted_cookie_str)
        
        global GLOBAL_SCRAPER, GLOBAL_CSRF
        GLOBAL_SCRAPER = None
        GLOBAL_CSRF = {'mlbb_br': None, 'mlbb_ph': None, 'mcc_br': None, 'mcc_ph': None}
        
        success_msg = "✅ <b>Cookies Successfully Extracted & Saved!</b>\n\n📦 <b>Extracted Data:</b>\n"
        for k, v in extracted_cookies.items():
            display_v = f"{v[:15]}...{v[-15:]}" if len(v) > 35 else v
            success_msg += f"🔸 <code>{k}</code> : {display_v}\n"
        success_msg += f"\n🍪 <b>Formatted Final String:</b>\n<code>{formatted_cookie_str}</code>"
        await message.reply(success_msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply(f"❌ <b>Parsing Error:</b> {str(e)}", parse_mode=ParseMode.HTML)

@dp.message(or_f(Command("addbal"), F.text.regexp(r"(?i)^\.addbal(?:$|\s+)")))
async def add_balance_command(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("❌ You are not authorized.")
    parts = message.text.strip().split()
    if len(parts) < 3: return await message.reply("⚠️ **Usage format:**\n`.addbal <User_ID> <Amount> [BR/PH]`")
    target_id = parts[1]
    try: amount = float(parts[2])
    except ValueError: return await message.reply("❌ Invalid amount.")
    currency = "BR"
    if len(parts) > 3:
        currency = parts[3].upper()
        if currency not in ['BR', 'PH']: return await message.reply("❌ Invalid currency.")
    target_wallet = await db.get_reseller(target_id)
    if not target_wallet: return await message.reply(f"❌ User ID `{target_id}` not found.")
    if currency == 'BR': await db.update_balance(target_id, br_amount=amount)
    else: await db.update_balance(target_id, ph_amount=amount)
    updated_wallet = await db.get_reseller(target_id)
    new_br = updated_wallet.get('br_balance', 0.0)
    new_ph = updated_wallet.get('ph_balance', 0.0)
    await message.reply(f"✅ **Balance Added Successfully!**\n\n👤 **User ID:** `{target_id}`\n💰 **Added:** `+{amount:,.2f} {currency}`\n\n📊 **Current Balance:**\n🇧🇷 BR: `${new_br:,.2f}`\n🇵🇭 PH: `${new_ph:,.2f}`")

@dp.message(or_f(Command("deduct"), F.text.regexp(r"(?i)^\.deduct(?:$|\s+)")))
async def deduct_balance_command(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("❌ You are not authorized.")
    parts = message.text.strip().split()
    if len(parts) < 3: return await message.reply("⚠️ **Usage format:**\n`.deduct <User_ID> <Amount> [BR/PH]`")
    target_id = parts[1]
    try: amount = abs(float(parts[2]))
    except ValueError: return await message.reply("❌ Invalid amount.")
    currency = "BR"
    if len(parts) > 3:
        currency = parts[3].upper()
        if currency not in ['BR', 'PH']: return await message.reply("❌ Invalid currency.")
    target_wallet = await db.get_reseller(target_id)
    if not target_wallet: return await message.reply(f"❌ User ID `{target_id}` not found.")
    if currency == 'BR': await db.update_balance(target_id, br_amount=-amount)
    else: await db.update_balance(target_id, ph_amount=-amount)
    updated_wallet = await db.get_reseller(target_id)
    new_br = updated_wallet.get('br_balance', 0.0)
    new_ph = updated_wallet.get('ph_balance', 0.0)
    await message.reply(f"✅ **Balance Deducted Successfully!**\n\n👤 **User ID:** `{target_id}`\n💸 **Deducted:** `-{amount:,.2f} {currency}`\n\n📊 **Current Balance:**\n🇧🇷 BR: `${new_br:,.2f}`\n🇵🇭 PH: `${new_ph:,.2f}`")

@dp.message(F.text.regexp(r"(?i)^\.topup\s+([a-zA-Z0-9]+)"))
async def handle_topup(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    match = re.search(r"(?i)^\.topup\s+([a-zA-Z0-9]+)", message.text.strip())
    if not match: return await message.reply("Usage format - `.topup <Code>`")
    activation_code = match.group(1).strip()
    tg_id = str(message.from_user.id)
    user_id_int = message.from_user.id 
    loading_msg = await message.reply(f"Checking Code `{activation_code}`...")
    
    async with user_locks[tg_id]:
        scraper = await get_main_scraper()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept': 'text/html'}
        
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
                res = await scraper.get(page_url, headers=req_headers)
                if "login" in str(res.url).lower() or res.status_code in [403, 503]: return "expired", None

                soup = BeautifulSoup(res.text, 'html.parser')
                csrf_token = soup.find('meta', {'name': 'csrf-token'})
                csrf_token = csrf_token.get('content') if csrf_token else (soup.find('input', {'name': '_csrf'}).get('value') if soup.find('input', {'name': '_csrf'}) else None)
                if not csrf_token: return "expired", None 

                ajax_headers = req_headers.copy()
                ajax_headers.update({'X-Requested-With': 'XMLHttpRequest', 'Origin': base_origin, 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})

                check_res_raw = await scraper.post(check_url, data={'_csrf': csrf_token, 'pin': activation_code}, headers=ajax_headers)
                check_res = check_res_raw.json()
                code_status = str(check_res.get('code', check_res.get('status', '')))
                
                card_amount = 0.0
                try:
                    if 'data' in check_res and isinstance(check_res['data'], dict):
                        val = check_res['data'].get('amount', check_res['data'].get('money', 0))
                        if val: card_amount = float(val)
                except: pass

                if code_status in ['200', '201', '0', '1'] or 'success' in str(check_res.get('msg', '')).lower():
                    old_bal = await get_smile_balance(scraper, headers, balance_check_url)
                    pay_res_raw = await scraper.post(pay_url, data={'_csrf': csrf_token, 'sec': activation_code}, headers=ajax_headers)
                    pay_res = pay_res_raw.json()
                    pay_status = str(pay_res.get('code', pay_res.get('status', '')))
                    
                    if pay_status in ['200', '0', '1'] or 'success' in str(pay_res.get('msg', '')).lower():
                        await asyncio.sleep(5) 
                        anti_cache_url = f"{balance_check_url}?_t={int(time.time())}"
                        new_bal = await get_smile_balance(scraper, headers, anti_cache_url)
                        bal_key = 'br_balance' if api_type == 'BR' else 'ph_balance'
                        added = round(new_bal[bal_key] - old_bal[bal_key], 2)
                        if added <= 0 and card_amount > 0: added = card_amount
                        return "success", added
                    else: return "fail", "Payment failed."
                else: return "invalid", "Invalid Code"
            except Exception as e: return "error", str(e)

        status, result = await try_redeem('BR')
        active_region = 'BR'
        if status in ['invalid', 'fail']: 
            status, result = await try_redeem('PH')
            active_region = 'PH'

        if status == "expired":
            await loading_msg.edit_text("⚠️ <b>Cookies Expired!</b>\n\nAuto-login စတင်နေပါသည်... ခဏစောင့်ပြီး ပြန်လည်ကြိုးစားပါ။", parse_mode=ParseMode.HTML)
            await notify_owner("⚠️ <b>Top-up Alert:</b> Code ဖြည့်သွင်းနေစဉ် Cookie သက်တမ်းကုန်သွားပါသည်။ Auto-login စတင်နေပါသည်...")
            success = await auto_login_and_get_cookie()
            if not success: await notify_owner("❌ <b>Critical:</b> Auto-Login မအောင်မြင်ပါ။ `/setcookie` ဖြင့် အသစ်ထည့်ပေးပါ။")
        elif status == "error": await loading_msg.edit_text(f"❌ Error: {result}")
        elif status in ['invalid', 'fail']: await loading_msg.edit_text("Cʜᴇᴄᴋ Fᴀɪʟᴇᴅ❌\n(Code is invalid or might have been used)")
        elif status == "success":
            added_amount = result
            if added_amount <= 0:
                await loading_msg.edit_text(f"sᴍɪʟᴇ ᴏɴᴇ ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ sᴜᴄᴄᴇss ✅\n(Cannot retrieve exact amount due to System Delay.)")
            else:
                if user_id_int == OWNER_ID: fee_percent = 0.0
                else:
                    if added_amount >= 10000: fee_percent = 0.0
                    elif added_amount >= 5000: fee_percent = 0.0
                    elif added_amount >= 1000: fee_percent = 0.0
                    else: fee_percent = 0.0

                fee_amount = round(added_amount * (fee_percent / 100), 2)
                net_added = round(added_amount - fee_amount, 2)
        
                user_wallet = await db.get_reseller(tg_id)
                if active_region == 'BR':
                    assets = user_wallet.get('br_balance', 0.0) if user_wallet else 0.0
                    await db.update_balance(tg_id, br_amount=net_added)
                else:
                    assets = user_wallet.get('ph_balance', 0.0) if user_wallet else 0.0
                    await db.update_balance(tg_id, ph_amount=net_added)

                total_assets = assets + net_added
                fmt_amount = int(added_amount) if added_amount % 1 == 0 else added_amount

                msg = (f"✅ <b>Code Top-Up Successful</b>\n\n<code>Code   : {activation_code} ({active_region})\nAmount : {fmt_amount:,}\nFee    : -{fee_amount:.1f} ({fee_percent}%)\nAdded  : +{net_added:,.1f} 🪙\nAssets : {assets:,.1f} 🪙\nTotal  : {total_assets:,.1f} 🪙</code>")
                await loading_msg.edit_text(msg, parse_mode=ParseMode.HTML)

@dp.message(or_f(Command("balance"), F.text.regexp(r"(?i)^\.bal(?:$|\s+)")))
async def check_balance_command(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    tg_id = str(message.from_user.id)
    user_wallet = await db.get_reseller(tg_id)
    if not user_wallet: return await message.reply("Yᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ ɪɴғᴏʀᴍᴀᴛɪᴏɴ ᴄᴀɴɴᴏᴛ ʙᴇ ғᴏᴜɴᴅ.")
    
    ICON_EMOJI = "5956330306167376831" 
    BR_EMOJI = "5228878788867142213"   
    PH_EMOJI = "5231361434583049965"   

    report = (f"<blockquote><tg-emoji emoji-id='{ICON_EMOJI}'>💳</tg-emoji> <b>𝗬𝗢𝗨𝗥 𝗪𝗔𝗟𝗟𝗘𝗧 𝗕𝗔𝗟𝗔𝗡𝗖𝗘</b>\n\n<tg-emoji emoji-id='{BR_EMOJI}'>🇧🇷</tg-emoji> 𝗕𝗥 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : ${user_wallet.get('br_balance', 0.0):,.2f}\n<tg-emoji emoji-id='{PH_EMOJI}'>🇵🇭</tg-emoji> 𝗣𝗛 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : ${user_wallet.get('ph_balance', 0.0):,.2f}</blockquote>")
    
    if message.from_user.id == OWNER_ID:
        loading_msg = await message.reply("Fetching real balance from the official account...")
        scraper = await get_main_scraper()
        headers = {'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://www.smile.one'}
        try:
            balances = await get_smile_balance(scraper, headers, 'https://www.smile.one/customer/order')
            report += (f"\n\n<blockquote><tg-emoji emoji-id='{ICON_EMOJI}'>💳</tg-emoji> <b>𝗢𝗙𝗙𝗜𝗖𝗜𝗔𝗟 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗕𝗔𝗟𝗔𝗡𝗖𝗘</b>\n\n<tg-emoji emoji-id='{BR_EMOJI}'>🇧🇷</tg-emoji> 𝗕𝗥 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : ${balances.get('br_balance', 0.00):,.2f}\n<tg-emoji emoji-id='{PH_EMOJI}'>🇵🇭</tg-emoji> 𝗣𝗛 𝗕𝗔𝗟𝗔𝗡𝗖𝗘 : ${balances.get('ph_balance', 0.00):,.2f}</blockquote>")
            await loading_msg.edit_text(report, parse_mode=ParseMode.HTML)
        except Exception as e:
            try: await loading_msg.edit_text(report, parse_mode=ParseMode.HTML)
            except: pass
    else:
        try: await message.reply(report, parse_mode=ParseMode.HTML)
        except: pass

@dp.message(or_f(Command("history"), F.text.regexp(r"(?i)^\.his$")))
async def send_order_history(message: types.Message):
    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    tg_id = str(message.from_user.id)
    user_name = message.from_user.username or message.from_user.first_name
    history_data = await db.get_user_history(tg_id, limit=200)
    if not history_data: return await message.reply("📜 **No Order History Found.**")
    response_text = f"==== Order History for @{user_name} ====\n\n"
    for order in history_data:
        response_text += (f"🆔 Game ID: {order['game_id']}\n🌏 Zone ID: {order['zone_id']}\n💎 Pack: {order['item_name']}\n🆔 Order ID: {order['order_id']}\n📅 Date: {order['date_str']}\n💲 Rate: ${order['price']:,.2f}\n📊 Status: {order['status']}\n────────────────\n")
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

async def execute_buy_process(message, lines, regex_pattern, currency, packages_dict, process_func, title_prefix, is_mcc=False):
    tg_id = str(message.from_user.id)
    telegram_user = message.from_user.username
    username_display = f"@{telegram_user}" if telegram_user else tg_id
    v_bal_key = 'br_balance' if currency == 'BR' else 'ph_balance'
    
    async with user_locks[tg_id]: 
        parsed_orders = []
        
        for line in lines:
            line = line.strip()
            if not line: continue 
            
            # 🟢 ကွင်းအပိတ် ')' ၏ အနောက်တွင် Space မပါခဲ့လျှင် အလိုအလျောက် ခြားပေးမည့်အပိုင်း
            import re
            line = re.sub(r'\)\s*', ') ', line)
            
            match = re.search(regex_pattern, line)
            if not match:
                await message.reply(f"Invalid format: `{line}`\nCheck /help for correct format.")
                continue
                
            game_id = match.group(1)
            zone_id = match.group(2)
            raw_items_str = match.group(3).lower()
            
            requested_packages = raw_items_str.split()
            items_to_buy = []
            not_found_pkgs = []
            
            for pkg in requested_packages:
                active_packages = None
                if isinstance(packages_dict, list):
                    for p_dict in packages_dict:
                        if pkg in p_dict: 
                            active_packages = p_dict
                            break
                else:
                    if pkg in packages_dict: 
                        active_packages = packages_dict
                        
                if active_packages: 
                    items_to_buy.extend(active_packages[pkg])
                else: 
                    not_found_pkgs.append(pkg)
                    
            if not_found_pkgs:
                await message.reply(f"❌ Package(s) not found for ID {game_id}: {', '.join(not_found_pkgs)}")
                continue
            if not items_to_buy: 
                continue
                
            line_price = sum(item['price'] for item in items_to_buy)
            parsed_orders.append({
                'game_id': game_id, 
                'zone_id': zone_id, 
                'raw_items_str': raw_items_str, 
                'items_to_buy': items_to_buy, 
                'line_price': line_price
            })
            
        if not parsed_orders: 
            return

        user_wallet = await db.get_reseller(tg_id)
        user_v_bal = user_wallet.get(v_bal_key, 0.0) if user_wallet else 0.0
            
        start_time = time.time()
        loading_msg = await message.reply(f"Order processing[ {len(parsed_orders)} | 0 ] ● ᥫ᭡")

        current_v_bal = [user_v_bal] 

        async def process_order_line(order):
            game_id = order['game_id']
            zone_id = order['zone_id']
            raw_items_str = order['raw_items_str']
            items_to_buy = order['items_to_buy']
            
            success_count, fail_count, total_spent = 0, 0, 0.0
            order_ids_str, error_msg = "", ""
            actual_names_list = [] 
            failed_names_list = [] 
            
            ig_name = "Unknown"

            async with api_semaphore:
                prev_context = None
                last_success_order = ""
                
                for item in items_to_buy:
                    if current_v_bal[0] < item['price']:
                        fail_count += 1
                        error_msg = "Insufficient balance"
                        failed_names_list.append(item.get('name', raw_items_str))
                        continue

                    current_v_bal[0] -= item['price']

                    skip_check = False 
                    
                    res = await process_func(
                        game_id, zone_id, item['pid'], currency, 
                        prev_context=prev_context, skip_role_check=skip_check, 
                        known_ig_name=ig_name, last_success_order_id=last_success_order
                    )
                    
                    fetched_name = res.get('ig_name') or res.get('username') or res.get('role_name') or res.get('nickname')
                    if fetched_name and str(fetched_name).strip() not in ["", "Unknown", "None"]:
                        ig_name = str(fetched_name).strip()

                    if res.get('status') == 'success':
                        success_count += 1
                        total_spent += item['price']
                        order_ids_str += f"{res.get('order_id', '')}\n"
                        actual_names_list.append(item.get('name', raw_items_str))
                        prev_context = {'csrf_token': res.get('csrf_token')}
                        last_success_order = res.get('order_id', '')
                    else:
                        current_v_bal[0] += item['price']
                        fail_count += 1
                        error_msg = res.get('message', 'Unknown Error')
                        failed_names_list.append(item.get('name', raw_items_str))
                        
            return {
                'game_id': game_id, 'zone_id': zone_id, 'raw_items_str': raw_items_str, 
                'success_count': success_count, 'fail_count': fail_count, 'total_spent': total_spent, 
                'order_ids_str': order_ids_str, 'ig_name': ig_name, 'error_msg': error_msg, 
                'actual_names_list': actual_names_list, 'failed_names_list': failed_names_list
            }

        line_tasks = [process_order_line(order) for order in parsed_orders]
        line_results = await asyncio.gather(*line_tasks)
        time_taken_seconds = int(time.time() - start_time)
        await loading_msg.delete() 

        for res in line_results:
            import datetime
            now = datetime.datetime.now(MMT)
            date_str = now.strftime("%m/%d/%Y, %I:%M:%S %p")
            
            safe_ig_name = html.escape(str(res['ig_name']))
            safe_username = html.escape(str(username_display))
            
            initial_bal_for_receipt = user_v_bal
            new_v_bal = user_v_bal
            
            report = f"<blockquote><pre>{title_prefix} {res['game_id']} ({res['zone_id']}) {res['raw_items_str'].upper()} ({currency})\n"
            report += f"=== TRANSACTION REPORT ===\n\n"

            if res['success_count'] > 0:
                if currency == 'BR': await db.update_balance(tg_id, br_amount=-res['total_spent'])
                else: await db.update_balance(tg_id, ph_amount=-res['total_spent'])
                
                new_wallet = await db.get_reseller(tg_id)
                new_v_bal = new_wallet.get(v_bal_key, 0.0) if new_wallet else 0.0
                initial_bal_for_receipt = new_v_bal + res['total_spent']
                
                final_order_ids = res['order_ids_str'].strip().replace('\n', ', ')
                
                unique_success = list(set(res['actual_names_list']))
                success_item_name = ", ".join(unique_success) if unique_success else res['raw_items_str']
                
                await db.save_order(
                    tg_id=tg_id, game_id=res['game_id'], zone_id=res['zone_id'], item_name=success_item_name, 
                    price=res['total_spent'], order_id=final_order_ids, status="success"
                )

                report += f"ORDER STATUS : ✅ Success\n"
                report += f"GAME ID      : {res['game_id']} {res['zone_id']}\n"
                report += f"IG NAME      : {safe_ig_name}\n"
                report += f"SERIAL       :\n{res['order_ids_str'].strip()}\n"
                report += f"ITEM         : {success_item_name}\n"
                report += f"SPENT        : {res['total_spent']:.2f} 🪙\n\n"

            if res['fail_count'] > 0:
                error_text = str(res['error_msg']).lower()
                
                if "insufficient" in error_text or "saldo" in error_text: 
                    display_err = "Insufficient balance"
                elif "invalid" in error_text or "not found" in error_text:
                    display_err = "Invalid Account"
                elif "limit" in error_text or "exceed" in error_text or "máximo" in error_text or "limite" in error_text:
                    display_err = "Weekly Pass Limit Exceeded"
                elif "zone" in error_text or "region" in error_text or "country" in error_text or "query failed" in error_text:
                    display_err = "Ban Server"
                else: 
                    display_err = res['error_msg'].replace('❌', '').strip()
                    if not display_err: display_err = "Purchase Failed"
                    
                    if res['success_count'] > 0 and "wp" in res['raw_items_str'].lower():
                        if "unable" in error_text or "fail" in error_text or "error" in error_text:
                            display_err = "Weekly Pass Limit Exceeded"
                
                unique_failed = list(set(res['failed_names_list']))
                failed_item_name = ", ".join(unique_failed) if unique_failed else res['raw_items_str']
                
                report += f"ORDER STATUS : ❌ FAILED\n"
                report += f"GAME ID      : {res['game_id']} {res['zone_id']}\n"
                report += f"IG NAME      : {safe_ig_name}\n"
                report += f"ITEM         : {failed_item_name}\n"
                report += f"ERROR        : {display_err}\n\n"

            report += f"DATE         : {date_str}\n"
            report += f"USERNAME     :\n{safe_username}\n"
            report += f"INITIAL      : ${initial_bal_for_receipt:,.2f}\n"
            report += f"FINAL        : ${new_v_bal:,.2f}\n\n"
            report += f"SUCCESS {res['success_count']} / FAIL {res['fail_count']}\n"
            report += f"TIME TAKEN   : {time_taken_seconds} SECONDS</pre></blockquote>"

            await message.reply(report, parse_mode=ParseMode.HTML)

@dp.message(F.text.regexp(r"(?i)^(?:msc|mlb|br|b)\s+\d+"))
async def handle_br_mlbb(message: types.Message):
    if not await is_authorized(message.from_user.id): 
        return await message.reply(f"ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.❌")
    try:
        lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        regex = r"(?i)^(?:b|br|mlb|msc)\s+(\d+)\s*\(?\s*(\d+)\s*\)?\s+(.+)$"
        
        total_pkgs = 0
        for line in lines:
            match = re.search(regex, line)
            if match: total_pkgs += len(match.group(3).split())
            
        if total_pkgs > 3: 
            return await message.reply("❌ 5 Limit Exceeded: တစ်ကြိမ်လျှင် အများဆုံး ၃ ခုသာ ဝယ်ယူနိုင်ပါသည်။")
            
        await execute_buy_process(message, lines, regex, 'BR', [DOUBLE_DIAMOND_PACKAGES, BR_PACKAGES], process_smile_one_order, "MLBB")
    except Exception as e: 
        await message.reply(f"System Error: {str(e)}")

@dp.message(F.text.regexp(r"(?i)^(?:mlp|ph|p)\s+\d+"))
async def handle_ph_mlbb(message: types.Message):
    if not await is_authorized(message.from_user.id): 
        return await message.reply(f"ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.❌")
    try:
        lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        regex = r"(?i)^(?:p|ph|mlp|mcp)\s+(\d+)\s*\(?\s*(\d+)\s*\)?\s+(.+)$"
        
        total_pkgs = 0
        for line in lines:
            match = re.search(regex, line)
            if match: total_pkgs += len(match.group(3).split())
            
        if total_pkgs > 3: 
            return await message.reply("❌ 5 Limit Exceeded: တစ်ကြိမ်လျှင် အများဆုံး ၃ ခုသာ ဝယ်ယူနိုင်ပါသည်။")
            
        await execute_buy_process(message, lines, regex, 'PH', PH_PACKAGES, process_smile_one_order, "MLBB")
    except Exception as e: 
        await message.reply(f"System Error: {str(e)}")

@dp.message(F.text.regexp(r"(?i)^(?:mcc|mcb)\s+\d+"))
async def handle_br_mcc(message: types.Message):
    if not await is_authorized(message.from_user.id): 
        return await message.reply(f"ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.❌")
    try:
        lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        regex = r"(?i)^(?:(?:mcc|mcb|mcp|mcgg)\s+)?(\d+)\s*\(?\s*(\d+)\s*\)?\s*(.+)$"
        
        total_pkgs = 0
        for line in lines:
            match = re.search(regex, line)
            if match: total_pkgs += len(match.group(3).split())
            
        if total_pkgs > 5: 
            return await message.reply("❌ 5 Limit Exceeded: တစ်ကြိမ်လျှင် အများဆုံး ၅ ခုသာ ဝယ်ယူနိုင်ပါသည်။")
            
        await execute_buy_process(message, lines, regex, 'BR', MCC_PACKAGES, process_mcc_order, "MCC", is_mcc=True)
    except Exception as e: 
        await message.reply(f"System Error: {str(e)}")

@dp.message(F.text.regexp(r"(?i)^mcp\s+\d+"))
async def handle_ph_mcc(message: types.Message):
    if not await is_authorized(message.from_user.id): 
        return await message.reply(f"ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.❌")
    try:
        lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        regex = r"(?i)^(?:mcp\s+)?(\d+)\s*\(?\s*(\d+)\s*\)?\s*(.+)$"
        
        total_pkgs = 0
        for line in lines:
            match = re.search(regex, line)
            if match: total_pkgs += len(match.group(3).split())
            
        if total_pkgs > 5: 
            return await message.reply("❌ 5 Limit Exceeded: တစ်ကြိမ်လျှင် အများဆုံး ၅ ခုသာ ဝယ်ယူနိုင်ပါသည်။")
            
        await execute_buy_process(message, lines, regex, 'PH', PH_MCC_PACKAGES, process_mcc_order, "MCC", is_mcc=True)
    except Exception as e: 
        await message.reply(f"System Error: {str(e)}")

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

async def keep_cookie_alive():
    while True:
        try:
            await asyncio.sleep(2 * 60) 
            scraper = await get_main_scraper()
            headers = {'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://www.smile.one'}
            response = await scraper.get('https://www.smile.one/customer/order', headers=headers)
            if "login" not in str(response.url).lower() and response.status_code == 200:
                pass 
            else:
                print(f"[{datetime.datetime.now(MMT).strftime('%I:%M %p')}] ⚠️ Main Cookie expired unexpectedly.")
                await notify_owner("⚠️ <b>System Warning:</b> Cookie သက်တမ်းကုန်သွားသည်ကို တွေ့ရှိရပါသည်။ Auto-Login စတင်နေပါသည်...")
                success = await auto_login_and_get_cookie()
                if not success: await notify_owner("❌ <b>Critical:</b> Auto-Login မအောင်မြင်ပါ။ သင့်အနေဖြင့် `/setcookie` ဖြင့် Cookie အသစ် လာရောက်ထည့်သွင်းပေးရန် လိုအပ်ပါသည်။")
        except Exception: pass

async def schedule_daily_cookie_renewal():
    while True:
        now = datetime.datetime.now(MMT)
        target_time = now.replace(hour=6, minute=30, second=0, microsecond=0)
        if now >= target_time: target_time += datetime.timedelta(days=1)
        wait_seconds = (target_time - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        success = await auto_login_and_get_cookie()
        if success:
            try: await bot.send_message(OWNER_ID, "✅ <b>System:</b> Proactive cookie renewal successful. Ready for the day!", parse_mode=ParseMode.HTML)
            except Exception: pass

async def daily_reconciliation_task():
    while True:
        now = datetime.datetime.now(MMT)
        target_time = now.replace(hour=23, minute=50, second=0, microsecond=0)
        if now >= target_time: target_time += datetime.timedelta(days=1)
        wait_seconds = (target_time - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        
        try:
            db_summary = await db.get_today_orders_summary()
            db_total_spent = db_summary['total_spent']
            db_order_count = db_summary['total_orders']
            
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
        except Exception as e: print(f"Reconciliation Error: {e}")

async def send_broadcast_greeting(text: str):
    users = await db.get_all_resellers()
    for u in users:
        try:
            tg_id = int(u['tg_id'])
            await bot.send_message(chat_id=tg_id, text=text, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.1) 
        except Exception: pass

async def schedule_morning_greeting():
    while True:
        now = datetime.datetime.now(MMT)
        target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if now >= target: target += datetime.timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        await send_broadcast_greeting("🌅 <b>သာယာသောမင်္ဂလာနံနက်ခင်းလေးဖြစ်ပါစေရှင့်🎉</b>")

async def schedule_night_greeting():
    while True:
        now = datetime.datetime.now(MMT)
        target = now.replace(hour=23, minute=30, second=0, microsecond=0)
        if now >= target: target += datetime.timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        await send_broadcast_greeting("🌙 <b>Goodnight sweet dream baby🎉</b>")

async def notify_owner(text: str):
    try: await bot.send_message(chat_id=OWNER_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception as e: print(f" Owner ထံသို့ Message ပို့၍မရပါ: {e}")

@dp.message(or_f(Command("cookies"), F.text.regexp(r"(?i)^\.cookies$")))
async def check_cookie_status(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("❌ You are not authorized.")
    loading_msg = await message.reply("Checking Cookie status...")
    try:
        scraper = await get_main_scraper()
        headers = {'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest', 'Origin': 'https://www.smile.one'}
        response = await scraper.get('https://www.smile.one/customer/order', headers=headers, timeout=15)
        if "login" not in str(response.url).lower() and response.status_code == 200: await loading_msg.edit_text("🟢 Aᴄᴛɪᴠᴇ", parse_mode=ParseMode.HTML)
        else: await loading_msg.edit_text("🔴 Exᴘɪʀᴇᴅ", parse_mode=ParseMode.HTML)
    except Exception as e: await loading_msg.edit_text(f"❌ Error checking cookie: {str(e)}")

@dp.message(or_f(Command("role"), F.text.regexp(r"(?i)^\.role(?:$|\s+)")))
async def handle_check_role(message: types.Message):

    if not await is_authorized(message.from_user.id): return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
    match = re.search(r"(?i)^[./]?role\s+(\d+)\s*[\(]?\s*(\d+)\s*[\)]?", message.text.strip())
    if not match: return await message.reply("❌ Invalid format. Use: `.role 12345678 1234`")
    
    game_id, zone_id = match.group(1).strip(), match.group(2).strip()
    loading_msg = await message.reply("Checking region", parse_mode=ParseMode.HTML)

    url = 'https://coldofficialstore.com/api/name-checker/mlbb'
    params = {
        'user_id': game_id,
        'server_id': zone_id,
    }
    
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Pragma': 'no-cache',
        'Referer': 'https://coldofficialstore.com/name-checker',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    }

    try:
        async with AsyncSession(impersonate="chrome120") as local_scraper:
            res = await local_scraper.get(url, params=params, headers=headers, timeout=15)
        
        try:
            data = res.json()
        except Exception:
            return await loading_msg.edit_text(f"❌ API Error: Invalid Response.\n\n<code>{res.text[:100]}...</code>", parse_mode=ParseMode.HTML)

        user_data = data.get('data', {})
        ig_name = user_data.get('username', 'Unknown')
        
        if not ig_name or str(ig_name).strip() == "" or ig_name == 'Unknown':
            return await loading_msg.edit_text("❌ **Invalid Account:** Game ID or Zone ID is incorrect or not found.", parse_mode=ParseMode.HTML)
            
        country_code = user_data.get('country', 'Unknown')
        country_map = {"MM": "Myanmar", "MY": "Malaysia", "PH": "Philippines", "ID": "Indonesia", "BR": "Brazil", "SG": "Singapore", "KH": "Cambodia", "TH": "Thailand"}
        final_region = country_map.get(str(country_code).upper(), country_code)

        limit_50 = limit_150 = limit_250 = limit_500 = True 
        
        bonus_limits = data.get('data2', {}).get('bonus_limit', [])
        for item in bonus_limits:
            title = str(item.get('title', ''))
            reached_limit = item.get('reached_limit', True) 
            
            if "50+50" in title: limit_50 = reached_limit
            elif "150+150" in title: limit_150 = reached_limit
            elif "250+250" in title: limit_250 = reached_limit
            elif "500+500" in title: limit_500 = reached_limit

        style_50 = "danger" if limit_50 else "success"
        style_150 = "danger" if limit_150 else "success"
        style_250 = "danger" if limit_250 else "success"
        style_500 = "danger" if limit_500 else "success"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Bᴏɴᴜs 50+50", callback_data="ignore", style=style_50),
                InlineKeyboardButton(text="Bᴏɴᴜs 150+150", callback_data="ignore", style=style_150)
            ],
            [
                InlineKeyboardButton(text="Bᴏɴᴜs 250+250", callback_data="ignore", style=style_250),
                InlineKeyboardButton(text="Bᴏɴᴜs 500+500", callback_data="ignore", style=style_500)
            ]
        ])

        final_report = (
            f"<u><b>Mᴏʙɪʟᴇ Lᴇɢᴇɴᴅs Bᴀɴɢ Bᴀɴɢ</b></u>\n\n"
            f"🆔 <code>{'User ID' :<9}:</code> <code>{game_id}</code> (<code>{zone_id}</code>)\n"
            f"👤 <code>{'Nickname':<9}:</code> {ig_name}\n"
            f"🌍 <code>{'Region'  :<9}:</code> {final_region}\n"
            f"────────────────\n\n"
            f"🎁 <b>Fɪʀsᴛ Rᴇᴄʜᴀʀɢᴇ Bᴏɴᴜs Sᴛᴀᴛᴜs</b>"
        )

        await loading_msg.edit_text(final_report, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e: 
        await loading_msg.edit_text(f"❌ System Error: {str(e)}", parse_mode=ParseMode.HTML)

@dp.message(or_f(Command("checkcus"), Command("cus"), F.text.regexp(r"(?i)^\.(?:checkcus|cus)(?:$|\s+)")))
async def check_official_customer(message: types.Message):
    tg_id = str(message.from_user.id)
    is_owner = (message.from_user.id == OWNER_ID)
    user_data = await db.get_reseller(tg_id) 
    
    if not is_owner and not user_data:
        return await message.reply("❌ You are not authorized.")
        
    parts = message.text.strip().split()
    if len(parts) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>.cus <Game_ID></code>", parse_mode=ParseMode.HTML)
        
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
                res = await scraper.get(
                    api_url, 
                    params={'type': 'orderlist', 'p': str(page_num), 'pageSize': '50'}, 
                    headers=headers, timeout=15
                )
                try:
                    data = res.json()
                    if 'list' in data and len(data['list']) > 0:
                        for order in data['list']:
                            current_user_id = str(order.get('user_id') or order.get('role_id') or '')
                            order_id = str(order.get('increment_id') or order.get('id') or '')
                            status_val = str(order.get('order_status', '') or order.get('status', '')).lower()
                            
                            if (current_user_id == search_query or order_id == search_query) and status_val in ['success', '1']:
                                if order_id not in seen_ids:
                                    seen_ids.add(order_id)
                                    found_orders.append(order)
                    else: 
                        break 
                except: 
                    break
                
        if not found_orders: 
            return await loading_msg.edit_text(f"❌ No successful records found for: <code>{search_query}</code>", parse_mode=ParseMode.HTML)
            
        found_orders = found_orders[:1] 
        report = f"🎉<b>Oғғɪᴄɪᴀʟ Rᴇᴄᴏʀᴅs ғᴏʀ {search_query}</b>\n\n"
        
        for order in found_orders:
            serial_id = str(order.get('increment_id') or order.get('id') or 'Unknown Serial')
            date_str = str(order.get('created_at') or order.get('updated_at') or order.get('create_time') or '')
            currency_sym = str(order.get('total_fee_currency') or '$')
            
            date_display = date_str
            if date_str:
                try:
                    dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    mmt_dt = dt_obj + datetime.timedelta(hours=9, minutes=30)
                    mm_time_str = mmt_dt.strftime("%I:%M:%S %p") 
                    date_display = f"{date_str} ( MM - {mm_time_str} )"
                except Exception:
                    date_display = date_str

            raw_item_name = str(order.get('product_name') or order.get('goods_name') or order.get('title') or 'Unknown Item')
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
                final_item_name = f"{raw_item_name}"
            else:
                final_item_name = f"{raw_item_name}"
            
            price = str(order.get('price') or order.get('grand_total') or order.get('real_money') or '0.00')
            if currency_sym != '$':
                price_display = f"{price} {currency_sym}"
            else:
                price_display = f"${price}"
                
            report += f"🏷 <code>{serial_id}</code>\n📅 <code>{date_display}</code>\n💎 {final_item_name} ({price_display})\n📊 Status: ✅ Success\n\n"
            
        await loading_msg.edit_text(report, parse_mode=ParseMode.HTML)
    except Exception as e: 
        await loading_msg.edit_text(f"❌ Search Error: {str(e)}", parse_mode=ParseMode.HTML)

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
    new_status = not current_status 
    await db.set_vip_status(target_id, new_status)
    status_msg = "Granted 🌟" if new_status else "Revoked ❌"
    await message.reply(f"✅ VIP Status for `{target_id}` has been **{status_msg}**.")

@dp.message(or_f(Command("sysbal"), F.text.regexp(r"(?i)^\.sysbal$")))
async def check_system_balance(message: types.Message):
    if message.from_user.id != OWNER_ID: return await message.reply("❌ You are not authorized.")
    loading_msg = await message.reply("📊 စနစ်တစ်ခုလုံး၏ မှတ်တမ်းကို တွက်ချက်နေပါသည်...")
    try:
        sys_balances = await db.get_total_system_balances()
        report = (
            "🏦 <b>System V-Wallet Total Balances</b> 🏦\n━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>User အားလုံးဆီရှိ စုစုပေါင်း ငွေကြေး:</b>\n\n"
            f"🇧🇷 BR Balance : <code>${sys_balances['total_br']:,.2f}</code>\n"
            f"🇵🇭 PH Balance : <code>${sys_balances['total_ph']:,.2f}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n<i>(မှတ်ချက်: ဤပမာဏသည် User အားလုံးထံသို့ Admin မှ ထည့်ပေးထားသော လက်ကျန်ငွေများ၏ စုစုပေါင်းဖြစ်ပါသည်။)</i>"
        )
        await loading_msg.edit_text(report, parse_mode=ParseMode.HTML)
    except Exception as e: await loading_msg.edit_text(f"❌ Error calculating system balance: {e}")

@dp.message(or_f(F.text.regexp(r"^\d{7,}(?:\s+\(?\d+\)?)?\s*.*$"), F.caption.regexp(r"^\d{7,}(?:\s+\(?\d+\)?)?\s*.*$")))
async def format_and_copy_text(message: types.Message):
    raw_text = (message.text or message.caption).strip()
    if re.match(r"^\d{7,}$", raw_text): formatted_raw = raw_text
    elif re.match(r"^\d{7,}\s+\d+", raw_text):
        match = re.match(r"^(\d{7,})\s+(\d+)\s*(.*)$", raw_text)
        if match:
            player_id, zone_id, suffix = match.group(1), match.group(2), match.group(3).strip()
            if suffix:
                clean_suffix = suffix.lower().replace(" ", "")
                wp_match = re.match(r"^(\d*)wp(\d*)$", clean_suffix)
                if wp_match:
                    num_str = wp_match.group(1) + wp_match.group(2)
                    processed_suffix = "wp" if num_str in ["", "1"] else f"wp{num_str}"
                else: processed_suffix = suffix
                formatted_raw = f"{player_id} ({zone_id}) {processed_suffix}"
            else: formatted_raw = f"{player_id} ({zone_id})"
        else: formatted_raw = raw_text
    elif re.match(r"^\d{7,}\s*\(\d+\)", raw_text):
        match = re.match(r"^(\d{7,})\s*\((\d+)\)\s*(.*)$", raw_text)
        if match:
            player_id, zone_id, suffix = match.group(1), match.group(2), match.group(3).strip()
            if suffix:
                clean_suffix = suffix.lower().replace(" ", "")
                wp_match = re.match(r"^(\d*)wp(\d*)$", clean_suffix)
                if wp_match:
                    num_str = wp_match.group(1) + wp_match.group(2)
                    processed_suffix = "wp" if num_str in ["", "1"] else f"wp{num_str}"
                else: processed_suffix = suffix
                formatted_raw = f"{player_id} ({zone_id}) {processed_suffix}"
            else: formatted_raw = f"{player_id} ({zone_id})"
        else: formatted_raw = raw_text
    else: formatted_raw = raw_text

    formatted_text = f"<code>{formatted_raw}</code>"
    try:
        from aiogram.types import CopyTextButton
        copy_btn = InlineKeyboardButton(text="ᴄᴏᴘʏ", copy_text=CopyTextButton(text=formatted_raw), style="primary")
    except ImportError:
        copy_btn = InlineKeyboardButton(text="ᴄᴏᴘʏ", switch_inline_query=formatted_raw, style="primary")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[copy_btn]])
    await message.reply(formatted_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

class ScamAlertMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: dict):
        if event.text:
            text_lower = event.text.lower()
            
            if text_lower.startswith(".scam ") or text_lower.startswith(".unscam ") or text_lower.startswith("/scam") or text_lower.startswith("/unscam"):
                return await handler(event, data)
                
            for scam_id in GLOBAL_SCAMMERS:
                pattern = rf"\b{scam_id}\b"
                if re.search(pattern, event.text):
                    await event.reply(
                        "Scamer game id , Scamer Alert!",
                        parse_mode=ParseMode.HTML
                    )
                    break 
        return await handler(event, data)


@dp.message(or_f(Command("maintenance"), F.text.regexp(r"(?i)^\.maintenance(?:$|\s+)")))
async def toggle_maintenance(message: types.Message):
    # Owner (Admin) သာလျှင် ဤ Command ကို အသုံးပြုနိုင်မည်
    if message.from_user.id != OWNER_ID:
        return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
        
    parts = message.text.strip().lower().split()
    if len(parts) < 2 or parts[1] not in ["enable", "disable"]:
        return await message.reply("⚠️ **Usage:** `.maintenance enable` သို့မဟုတ် `.maintenance disable`")
        
    global IS_MAINTENANCE
    action = parts[1]
    
    if action == "enable":
        IS_MAINTENANCE = True
        await message.reply("✅ **Maintenance Mode ENABLED.**\nယခုအချိန်မှစ၍ Admin မှလွဲ၍ အခြား User များ Bot ကို အသုံးပြု၍ မရတော့ပါ။")
    elif action == "disable":
        IS_MAINTENANCE = False
        await message.reply("✅ **Maintenance Mode DISABLED.**\nBot ကို ပုံမှန်အတိုင်း ပြန်လည်အသုံးပြုနိုင်ပါပြီ။")

# ==========================================
# 🚨 2. SCAMMER MANAGEMENT COMMANDS (AUTHORIZED USERS & OWNER)
# ==========================================
@dp.message(or_f(Command("scam"), F.text.regexp(r"(?i)^\.scam(?:$|\s+)")))
async def add_scam_id(message: types.Message):
    # Owner သာမက Authorized User များပါ အသုံးပြုနိုင်အောင် ပြင်ဆင်ထားသည်
    if not await is_authorized(message.from_user.id): 
        return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
        
    parts = message.text.strip().split()
    if len(parts) < 2:
        return await message.reply("⚠️ **Usage:** `.scam <Game_ID>`\nဥပမာ: `.scam 123456789`")
        
    scam_id = parts[1].strip()
    if not scam_id.isdigit():
        return await message.reply("❌ Invalid Game ID. ဂဏန်းများသာ ရိုက်ထည့်ပါ။")
        
    await db.add_scammer(scam_id)
    GLOBAL_SCAMMERS.add(scam_id)
    
    await message.reply(f"🚨 **Scammer ID Added:** <code>{scam_id}</code>\n✅ ဤ ID ကို Blacklist သို့ ထည့်သွင်းပြီးပါပြီ။ တွေ့တာနဲ့ Bot မှ အလိုအလျောက် သတိပေးပါတော့မည်။", parse_mode=ParseMode.HTML)

@dp.message(or_f(Command("unscam"), F.text.regexp(r"(?i)^\.unscam(?:$|\s+)")))
async def remove_scam_id(message: types.Message):
    if not await is_authorized(message.from_user.id): 
        return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
        
    parts = message.text.strip().split()
    if len(parts) < 2:
        return await message.reply("⚠️ **Usage:** `.unscam <Game_ID>`")
        
    scam_id = parts[1].strip()
    
    removed = await db.remove_scammer(scam_id)
    GLOBAL_SCAMMERS.discard(scam_id)
    
    if removed:
        await message.reply(f"✅ **Scammer ID Removed:** <code>{scam_id}</code>\nBlacklist ထဲမှ အောင်မြင်စွာ ဖယ်ရှားလိုက်ပါပြီ။", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"⚠️ ထို ID သည် Scammer စာရင်းထဲတွင် မရှိပါ။")

@dp.message(or_f(Command("scamlist"), F.text.regexp(r"(?i)^\.scamlist$")))
async def show_scam_list(message: types.Message):
    if not await is_authorized(message.from_user.id): 
        return await message.reply("ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜsᴇʀ.")
        
    if not GLOBAL_SCAMMERS:
        return await message.reply("✅ ယခုလောလောဆယ် Blacklist သွင်းထားသော Scammer မရှိပါ။")
        
    scam_text = "\n".join([f"🔸 <code>{sid}</code>" for sid in GLOBAL_SCAMMERS])
    await message.reply(f"🚨 **Scammer Blacklist (Total: {len(GLOBAL_SCAMMERS)}):**\n\n{scam_text}", parse_mode=ParseMode.HTML)

@dp.message(or_f(Command("help"), F.text.regexp(r"(?i)^\.help$")))
async def send_help_message(message: types.Message):
    is_owner = (message.from_user.id == OWNER_ID)
    
    help_text = (
        f"<blockquote><b>🤖 𝐁𝐎𝐓 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 𝐌𝐄𝐍𝐔</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"<b>💎 𝐌𝐋𝐁Ｂ 𝐃𝐢𝐚𝐦𝐨𝐧𝐝𝐬 (ဝယ်ယူရန်)</b>\n"
        f"🇧🇷 BR MLBB: <code>msc/mlb/br/b ID (Zone) Pack</code>\n"
        f"🇵🇭 PH MLBB: <code>mlp/ph/p ID (Zone) Pack</code>\n\n"
        f"<b>♟️ 𝐌𝐚𝐠𝐢𝐜 𝐂𝐡𝐞𝐬𝐬 (ဝယ်ယူရန်)</b>\n"
        f"🇧🇷 BR MCC: <code>mcc/mcb ID (Zone) Pack</code>\n"
        f"🇵🇭 PH MCC: <code>mcp ID (Zone) Pack</code>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"<b>👤 𝐔𝐬𝐞𝐫 𝐓𝐨𝐨𝐥𝐬 (အသုံးပြုသူများအတွက်)</b>\n"
        f"🔸 <code>.topup Code</code>       : Smile Code ဖြည့်သွင်းရန်\n"
        f"🔹 <code>.bal</code>      : မိမိ Wallet Balance စစ်ရန်\n"
        f"🔹 <code>.role</code>     : Game ID နှင့် Region စစ်ရန်\n"
        f"🔹 <code>.his</code>      : မိမိဝယ်ယူခဲ့သော မှတ်တမ်းကြည့်ရန်\n"
        f"🔹 <code>.clean</code>    : မှတ်တမ်းများ ဖျက်ရန်\n"
        f"🔹 <code>.listb</code>     : BR ဈေးနှုန်းစာရင်း ကြည့်ရန်\n"
        f"🔹 <code>.listp</code>     : PH ဈေးနှုန်းစာရင်း ကြည့်ရန်\n"
        f"🔹 <code>.listmb</code>    : MCC ဈေးနှုန်းစာရင်း ကြည့်ရန်\n"
        f"💡 <i>Tip: 50+50 ဟုရိုက်ထည့်၍ ဂဏန်းပေါင်းစက်အဖြစ် သုံးနိုင်ပါသည်။</i>\n"
    )
    
    if is_owner:
        help_text += (
            f"\n━━━━━━━━━━━━━━━━━\n"
            f"<b>👑 𝐎𝐰𝐧𝐞𝐫 𝐓𝐨𝐨𝐥𝐬 (Admin သီးသန့်)</b>\n\n"
            f"<b>👥 ယူဆာစီမံခန့်ခွဲမှု</b>\n"
            f"🔸 <code>.maintenance [ᴇɴᴀʙʟᴇ/ᴅɪsᴀʙʟᴇ]</code> : ᴇɴᴀʙʟᴇ ᴏʀ ᴅɪsᴀʙʟᴇ ᴛʜᴇ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ ᴏғ ʏᴏᴜʀ ʙᴏᴛ.\n"
            f"🔸 <code>.add ID</code>    : User အသစ်ထည့်ရန်\n"
            f"🔸 <code>.remove ID</code> : User အား ဖယ်ရှားရန်\n"
            f"🔸 <code>.users</code>     : User စာရင်းအားလုံး ကြည့်ရန်\n\n"
            f"🔸 <code>.addbal ID 50 BR</code>  : Balance ပေါင်းထည့်ရန်\n"
            f"🔸 <code>.deduct ID 50 BR</code>  : Balance နှုတ်ယူရန်\n"
            f"<b>💼 VIP နှင့် စာရင်းစစ်</b>\n"
            f"🔸 <code>.checkcus ID</code> : Official မှတ်တမ်း လှမ်းစစ်ရန်\n"
            f"🔸 <code>.topcus</code>      : ငွေအများဆုံးသုံးထားသူများ ကြည့်ရန်\n"
            f"🔸 <code>.setvip ID</code>   : VIP အဖြစ် သတ်မှတ်ရန်/ဖြုတ်ရန်\n\n"
            f"<b>🚨 Scammer စီမံခန့်ခွဲမှု</b>\n"
            f"🔸 <code>.scam ID</code>     : Scammer စာရင်းသွင်းရန်\n"
            f"🔸 <code>.unscam ID</code>   : Scammer စာရင်းမှပယ်ဖျက်ရန်\n"
            f"🔸 <code>.scamlist</code>    : Scammer အားလုံးကြည့်ရန်\n\n"
            f"<b>⚙️ System Setup</b>\n"
            f"🔸 <code>.sysbal</code>      : စနစ်တစ်ခုလုံး၏ Balance စစ်ရန်\n"
            f"🔸 <code>.cookies</code>     : Cookie အခြေအနေ စစ်ဆေးရန်\n"
            f"🔸 <code>/setcookie</code>   : Main Cookie အသစ်ပြောင်းရန်\n"
        )
        
    help_text += f"</blockquote>"
    
    await message.reply(help_text, parse_mode=ParseMode.HTML)

@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    try:
        tg_id = str(message.from_user.id)
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip() or "User"
        safe_full_name = full_name.replace('<', '').replace('>', '')
        username_display = f'<a href="tg://user?id={tg_id}">{safe_full_name}</a>'
        
        EMOJI_1, EMOJI_2, EMOJI_3, EMOJI_4, EMOJI_5 = "5956355397366320202", "5954097490109140119", "5958289678837746828", "5956330306167376831", "5954078884310814346"

        status = "🟢 Aᴄᴛɪᴠᴇ" if await is_authorized(message.from_user.id) else "🔴 Nᴏᴛ Aᴄᴛɪᴠᴇ"
        
        welcome_text = (
            f"<blockquote>ʜᴇʏ ʙᴀʙʏ <tg-emoji emoji-id='{EMOJI_1}'>🥺</tg-emoji>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_2}'>👤</tg-emoji> <code>{'Usᴇʀɴᴀᴍᴇ' :<11}:</code> {username_display}\n"
            f"<tg-emoji emoji-id='{EMOJI_3}'>🆔</tg-emoji> <code>{'𝐈𝐃' :<11}:</code> <code>{tg_id}</code>\n"
            f"<tg-emoji emoji-id='{EMOJI_4}'>📊</tg-emoji> <code>{'Sᴛᴀᴛᴜs' :<11}:</code> {status}\n\n"
            f"<tg-emoji emoji-id='{EMOJI_5}'>📞</tg-emoji> <code>{'Cᴏɴᴛᴀᴄᴛ ᴜs' :<11}:</code> @iwillgoforwardsalone</blockquote>"
        )
        await message.reply(welcome_text, parse_mode=ParseMode.HTML)
    except Exception:
 
        fallback_text = (
            f"<blockquote>ʜᴇʏ ʙᴀʙʏ 🥺\n\n"
            f"👤 <code>{'Usᴇʀɴᴀᴍᴇ' :<11}:</code> {full_name}\n"
            f"🆔 <code>{'𝐈𝐃' :<11}:</code> <code>{tg_id}</code>\n"
            f"📊 <code>{'Sᴛᴀᴛᴜs' :<11}:</code> 🔴 Nᴏᴛ Aᴄᴛɪᴠᴇ\n\n"
            f"📞 <code>{'Cᴏɴᴛᴀᴄᴛ ᴜs' :<11}:</code> @iwillgoforwardsalone</blockquote>"
        )
        await message.reply(fallback_text, parse_mode=ParseMode.HTML)

async def main():
    print("Starting Heartbeat & Auto-login tasks...")
    print("နှလုံးသားမပါရင် ဘယ်အရာမှတရားမဝင်")
    
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=50))
    
    global GLOBAL_SCAMMERS
    try:
        scammer_list = await db.get_all_scammers()
        GLOBAL_SCAMMERS = set(scammer_list)
        print(f"Loaded {len(GLOBAL_SCAMMERS)} Scammer IDs.")
    except Exception as e:
        print(f"Error loading scammers: {e}")

    dp.message.middleware(ScamAlertMiddleware())
    
    asyncio.create_task(keep_cookie_alive())
    asyncio.create_task(schedule_daily_cookie_renewal())
    asyncio.create_task(daily_reconciliation_task())
    asyncio.create_task(schedule_morning_greeting())
    asyncio.create_task(schedule_night_greeting())
    
    await db.setup_indexes()
    await db.init_owner(OWNER_ID)
    print("Bot is successfully running on Aiogram 3 Framework... 🎉")
    
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
