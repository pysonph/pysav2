import os
import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# ==========================================
# 📌 SETUP & ASYNC CONNECTION
# ==========================================
load_dotenv()
MONGO_URI = os.getenv('MONGO_URI')

if not MONGO_URI:
    print("❌ Error: .env ဖိုင်ထဲတွင် MONGO_URI မပါဝင်ပါ။")
    exit()

try:
    # 🟢 Motor ကိုသုံး၍ Asynchronous Connection ပြုလုပ်ခြင်း
    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000, maxPoolSize=50)
    db = client['smile_vwallet_db']
    
    resellers_col = db['resellers']
    settings_col = db['settings']
    orders_col = db['orders']
    
    print("✅ Async MongoDB (Motor) ချိတ်ဆက်မှု အောင်မြင်ပါသည်။")
except Exception as e:
    print(f"❌ MongoDB ချိတ်ဆက်မှု မအောင်မြင်ပါ: {e}")
    exit()

# မြန်မာစံတော်ချိန် (MMT) ကို Global အနေဖြင့် သတ်မှတ်ထားသည်
MMT = datetime.timezone(datetime.timedelta(hours=6, minutes=30))

# ==========================================
# 🚀 DATABASE INDEXING (For Speed Optimization)
# ==========================================
async def setup_indexes():
    """ဒေတာများလာသည့်အခါ ရှာဖွေမှုမြန်ဆန်စေရန် Index များ တည်ဆောက်မည်"""
    try:
        await resellers_col.create_index("tg_id", unique=True)
        # Order History ဆွဲထုတ်ရာတွင် မြန်ဆန်စေရန် tg_id နှင့် timestamp ကို ပေါင်း၍ Index လုပ်ထားသည်
        await orders_col.create_index([("tg_id", 1), ("timestamp", -1)])
    except Exception as e:
        print(f"⚠️ Index ဖန်တီးရာတွင် အမှားရှိပါသည်: {e}")

# ==========================================
# 👑 OWNER & COOKIE MANAGEMENT
# ==========================================
async def init_owner(owner_id):
    """Bot စတင်ချိန်တွင် Owner အား Default ထည့်သွင်းပေးမည်"""
    owner_str = str(owner_id)
    existing_owner = await resellers_col.find_one({"tg_id": owner_str})
    if not existing_owner:
        await resellers_col.insert_one({
            "tg_id": owner_str,
            "username": "Owner",
            "br_balance": 0.0,
            "ph_balance": 0.0
        })

async def get_main_cookie():
    """Main Cookie အား Database မှ ယူမည်"""
    doc = await settings_col.find_one({"type": "main_cookie"})
    return doc.get("cookie", "") if doc else ""

async def update_main_cookie(cookie_str):
    """Main Cookie အား Database သို့ သိမ်းမည်"""
    await settings_col.update_one(
        {"type": "main_cookie"},
        {"$set": {"cookie": cookie_str}},
        upsert=True
    )

# ==========================================
# 👥 RESELLER (V-WALLET) MANAGEMENT
# ==========================================
async def get_reseller(tg_id):
    """Reseller တစ်ဦးချင်းစီ၏ အချက်အလက်များကို ယူမည်"""
    return await resellers_col.find_one({"tg_id": str(tg_id)})

async def get_all_resellers():
    """Reseller အားလုံး၏ စာရင်းကို ယူမည်"""
    cursor = resellers_col.find({})
    return await cursor.to_list(length=None)

async def add_reseller(tg_id, username):
    """Reseller အသစ်ထည့်မည်"""
    tg_id_str = str(tg_id)
    existing_user = await resellers_col.find_one({"tg_id": tg_id_str})
    if not existing_user:
        await resellers_col.insert_one({
            "tg_id": tg_id_str,
            "username": username,
            "br_balance": 0.0,
            "ph_balance": 0.0
        })
        return True
    return False

async def remove_reseller(tg_id):
    """Reseller အား စာရင်းမှ ဖျက်မည်"""
    result = await resellers_col.delete_one({"tg_id": str(tg_id)})
    return result.deleted_count > 0

async def update_balance(tg_id, br_amount=0.0, ph_amount=0.0):
    """
    Reseller ၏ Balance အား အတိုး/အလျော့ လုပ်မည်။
    Float Precision Error မဖြစ်စေရန် round() သုံးထားပါသည်။
    """
    await resellers_col.update_one(
        {"tg_id": str(tg_id)},
        {"$inc": {
            "br_balance": round(float(br_amount), 2), 
            "ph_balance": round(float(ph_amount), 2)
        }}
    )

# ==========================================
# 📜 ORDER HISTORY MANAGEMENT
# ==========================================
async def save_order(tg_id, game_id, zone_id, item_name, price, order_id, status="success"):
    """Order အောင်မြင်ပါက Database သို့ မှတ်တမ်းတင်မည်"""
    now = datetime.datetime.now(MMT)
    
    order_data = {
        "tg_id": str(tg_id),
        "game_id": str(game_id),
        "zone_id": str(zone_id),
        "item_name": item_name,
        "price": round(float(price), 2),
        "order_id": str(order_id),
        "status": status,
        "date_str": now.strftime("%I:%M:%S %p %d.%m.%Y"), 
        "timestamp": now 
    }
    await orders_col.insert_one(order_data)

async def get_user_history(tg_id, limit=50):
    """User တစ်ယောက်၏ နောက်ဆုံး Order များကို ဆွဲထုတ်မည်"""
    cursor = orders_col.find(
        {"tg_id": str(tg_id)}, 
        {"_id": 0} 
    ).sort("timestamp", -1).limit(limit)
    
    return await cursor.to_list(length=limit)


async def clear_user_history(tg_id):
    """User တစ်ယောက်၏ Order History အားလုံးကို ဖျက်မည်"""
    result = await orders_col.delete_many({"tg_id": str(tg_id)})
    return result.deleted_count
