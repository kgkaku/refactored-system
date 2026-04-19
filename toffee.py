# ===================================================
# Toffee Live TV Playlist Generator - FINAL FIX
# সমস্ত চ্যানেলের জন্য কুকি সহ (বাংলা সংস্করণ)
# ===================================================

import requests
import json
import time
import re
import os
import hashlib
import secrets
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from Crypto.Cipher import AES

# ========== কনফিগারেশন ==========
SECRET_KEY = "06e63248b1b56d5789ba0b047f548eba"
SECRET_KEY_BYTES = SECRET_KEY.encode('utf-8')

DEVICE_REGISTER_URL = "https://prod-services.toffeelive.com/sms/v1/device/register"
CONTENT_BASE = "https://content-prod.services.toffeelive.com/toffee/BD/DK/android-mobile"
PLAYBACK_BASE = "https://entitlement-prod.services.toffeelive.com/toffee/BD/DK/android-mobile/playback"
ALL_LIVE_TV_URL = f"{CONTENT_BASE}/rail/generic/editorial-dynamic?filters=v_type:channels;subType:Live_TV&page={{page}}"

SLUG_FILE = "slug.txt"
OUTPUT_FILES = ["ottnavigator.m3u", "nsplayer.m3u", "toffee.json"]

SPORTS_PATTERNS = ["match-", "bdvsnz", "epl", "bfl", "sports", "cricket", "icc", "vs"]
SPORTS_USER_AGENT = "Toffee/8.8.0 (Linux;Android 7.1.2) ExoPlayerLib/2.18.6"
NORMAL_USER_AGENT = "okhttp/5.1.0"

# ========== গ্লোবাল ভেরিয়েবল ==========
slug_mapping = {}
COOKIE_BLDCMPROD = None
COOKIE_MPROD = None

# ========== ইউটিলিটি ফাংশন ==========
def generate_random_hex(bytes_count: int = 16) -> str:
    return secrets.token_hex(bytes_count)

def md5_hash(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()

def generate_device_id() -> str:
    return md5_hash(SECRET_KEY + generate_random_hex(16))[:32]

def generate_nonce() -> str:
    return generate_random_hex(16)

def aes_ecb_encrypt(plain_text: str) -> str:
    plain_bytes = plain_text.encode('utf-8')
    pad_len = 16 - (len(plain_bytes) % 16)
    plain_bytes += bytes([pad_len]) * pad_len
    cipher = AES.new(SECRET_KEY_BYTES, AES.MODE_ECB)
    return cipher.encrypt(plain_bytes).hex()

def generate_hash(payload: dict) -> str:
    return aes_ecb_encrypt(json.dumps(payload, separators=(',', ':')))

def is_sports_channel(title: str, slug: str = "") -> bool:
    text = (title + " " + slug).lower()
    return any(p in text for p in SPORTS_PATTERNS)

def get_logo(channel: Dict) -> str:
    images = channel.get("images", [])
    for img in images:
        if img.get("ratio") == "1:1":
            path = img.get("path", "")
            if path:
                if path.startswith("http"):
                    return path
                return f"https://assets-prod.services.toffeelive.com/f_png,w_300,q_85/{path}"
    if images:
        path = images[0].get("path", "")
        if path:
            return f"https://assets-prod.services.toffeelive.com/f_png,w_300,q_85/{path}"
    return ""

def get_user_agent(title: str, slug: str) -> str:
    return SPORTS_USER_AGENT if is_sports_channel(title, slug) else NORMAL_USER_AGENT

# ========== Slug ফাইল ম্যানেজমেন্ট ==========
def load_slug_mapping() -> Dict:
    mapping = {}
    if os.path.exists(SLUG_FILE):
        with open(SLUG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    parts = line.split('=', 1)
                    channel = parts[0].strip()
                    slug = parts[1].strip()
                    if channel and slug:
                        mapping[channel] = slug
    return mapping

def save_slug_mapping(mapping: Dict):
    with open(SLUG_FILE, 'w', encoding='utf-8') as f:
        f.write("# Toffee চ্যানেল স্লাগ ম্যাপিং\n")
        f.write("# ফরম্যাট: চ্যানেলের নাম = স্লাগ\n\n")
        for channel, slug in sorted(mapping.items()):
            f.write(f"{channel} = {slug}\n")

# ========== ডিভাইস রেজিস্ট্রেশন ==========
def register_device() -> Optional[str]:
    device_id = generate_device_id()
    nonce = generate_nonce()
    
    payload = {
        "provider": "toffee", "device_id": device_id, "type": "mobile",
        "os": "android", "os_version": "10", "app_version": "8.8.0", "country": "BD"
    }
    hash_value = generate_hash(payload)
    
    headers = {
        "Host": "prod-services.toffeelive.com", "Content-Type": "application/json; charset=utf-8",
        "Accept-Encoding": "gzip", "User-Agent": "okhttp/5.1.0", "Connection": "Keep-Alive"
    }
    
    try:
        resp = requests.post(f"{DEVICE_REGISTER_URL}?nonce={nonce}&hash={hash_value}", 
                            headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and "data" in data:
                return data["data"]["access"]
    except Exception as e:
        print(f"রেজিস্ট্রেশন ত্রুটি: {e}")
    return None

def get_headers(access_token: str) -> Dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "okhttp/5.1.0",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

def get_playback_data(content_id: str, access_token: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    global COOKIE_BLDCMPROD, COOKIE_MPROD
    try:
        resp = requests.post(f"{PLAYBACK_BASE}/{content_id}", headers=get_headers(access_token), json={}, timeout=15)
        if resp.status_code != 200:
            return None, COOKIE_BLDCMPROD, COOKIE_MPROD
        
        data = resp.json()
        stream_url = None
        if "playbackDetails" in data and data["playbackDetails"].get("data"):
            stream_url = data["playbackDetails"]["data"][0].get("url")
        elif "stream_url" in data:
            stream_url = data["stream_url"]
        elif "url" in data:
            stream_url = data["url"]
        
        if not stream_url:
            return None, COOKIE_BLDCMPROD, COOKIE_MPROD
        
        if "set-cookie" in resp.headers:
            match = re.search(r'(Edge-Cache-Cookie=[^;]+)', resp.headers["set-cookie"])
            if match:
                cookie = match.group(1)
                if "bldcmprod" in stream_url:
                    COOKIE_BLDCMPROD = cookie
                elif "mprod" in stream_url:
                    COOKIE_MPROD = cookie
        
        return stream_url, COOKIE_BLDCMPROD, COOKIE_MPROD
    except Exception as e:
        return None, COOKIE_BLDCMPROD, COOKIE_MPROD

def get_stream_url_from_slug(title: str, slug: str) -> str:
    if is_sports_channel(title, slug):
        return f"https://mprod-cdn.toffeelive.com/live/{slug}/index.m3u8"
    return f"https://bldcmprod-cdn.toffeelive.com/cdn/live/{slug}/playlist.m3u8"

def fetch_all_channels(access_token: str) -> List[Dict]:
    channels = []
    headers = get_headers(access_token)
    for page in range(1, 9):
        try:
            resp = requests.get(ALL_LIVE_TV_URL.format(page=page), headers=headers, timeout=15)
            if resp.status_code != 200:
                break
            items = resp.json().get('list', [])
            if not items:
                break
            for item in items:
                if item.get('v_type') == 'channels' and item.get('subType') == 'Live_TV' and item.get('id'):
                    channels.append(item)
            time.sleep(0.3)
        except:
            break
    return channels

# ========== প্লেলিস্ট জেনারেটর ==========
def generate_playlists(channels: List[Dict], access_token: str):
    global COOKIE_BLDCMPROD, COOKIE_MPROD
    
    ott_lines = ["#EXTM3U"]
    ns_list = []
    toffee_channels = []
    
    api_success = 0
    fallback_success = 0
    sports_count = 0
    
    # প্রথমে কুকি ক্যাপচার
    print("\n🍪 কুকি সংগ্রহ করা হচ্ছে...")
    for ch in channels:
        ch_id = ch.get('id')
        if ch_id:
            get_playback_data(ch_id, access_token)
            if COOKIE_BLDCMPROD and COOKIE_MPROD:
                break
    
    print(f"   🍪 bldcmprod কুকি: {'প্রাপ্ত' if COOKIE_BLDCMPROD else 'প্রাপ্ত নয়'}")
    print(f"   🍪 mprod কুকি: {'প্রাপ্ত' if COOKIE_MPROD else 'প্রাপ্ত নয়'}")
    
    # প্লেলিস্ট তৈরি
    print("\n📝 প্লেলিস্ট তৈরি করা হচ্ছে...")
    for idx, ch in enumerate(channels, 1):
        title = ch.get('title')
        ch_id = ch.get('id')
        if not title or not ch_id:
            continue
        
        logo = get_logo(ch)
        stream_url, cookie_bld, cookie_mprod = get_playback_data(ch_id, access_token)
        
        is_sports = False
        if not stream_url and title in slug_mapping:
            slug = slug_mapping[title]
            stream_url = get_stream_url_from_slug(title, slug)
            is_sports = is_sports_channel(title, slug)
            fallback_success += 1
        elif stream_url:
            api_success += 1
            is_sports = "mprod" in stream_url
        else:
            continue
        
        if is_sports:
            sports_count += 1
            final_cookie = COOKIE_MPROD
            user_agent = SPORTS_USER_AGENT
        else:
            final_cookie = COOKIE_BLDCMPROD
            user_agent = NORMAL_USER_AGENT
        
        # OTT নেভিগেটর M3U
        ott_lines.append(f'#EXTINF:-1 group-title="লাইভ টিভি" tvg-logo="{logo}" tvg-name="{title}", {title}')
        ott_lines.append(f'#EXTVLCOPT:http-user-agent={user_agent}')
        if final_cookie:
            ott_lines.append(f'#EXTHTTP:{{"cookie":"{final_cookie}"}}')
        ott_lines.append(stream_url)
        ott_lines.append('')
        
        # এনএস প্লেয়ার JSON
        ns_list.append({
            "category": "লাইভ টিভি",
            "name": title,
            "link": stream_url,
            "logo": logo,
            "cookie": final_cookie or "",
            "user_agent": user_agent
        })
        
        # টফি JSON
        toffee_channels.append({
            "category_name": "লাইভ টিভি",
            "name": title,
            "link": stream_url,
            "headers": {"cookie": final_cookie or ""},
            "logo": logo
        })
        
        if idx % 30 == 0:
            print(f"      {idx}/{len(channels)} প্রক্রিয়াকৃত...")
    
    # OTT নেভিগেটর M3U ফাইলের শুরুতে ক্রেডিট যোগ
    current_time = datetime.now().strftime("%d-%m-%Y %I:%M:%S %p")
    ott_header = f"""#EXTM3U
# Playlist created by @kgkaku
# Generated on: {current_time}
# Total Channels: {len(toffee_channels)} | Active: {api_success + fallback_success}

"""
    with open("ottnavigator.m3u", "w", encoding='utf-8') as f:
        f.write(ott_header + '\n'.join(ott_lines[1:]))  # প্রথম #EXTM3U বাদ দিয়ে
    
    # NS প্লেয়ার JSON (ক্রেডিট ছাড়া)
    with open("nsplayer.m3u", "w", encoding='utf-8') as f:
        json.dump(ns_list, f, indent=2, ensure_ascii=False)
    
    # টফি JSON (ক্রেডিট সহ)
    toffee_json = {
        "name": "Toffee লাইভ টিভি প্লেলিস্ট",
        "creator": "@kgkaku",
        "generated_on": current_time,
        "total_channels": len(toffee_channels),
        "active_channels": api_success + fallback_success,
        "channels": toffee_channels
    }
    with open("toffee.json", "w", encoding='utf-8') as f:
        json.dump(toffee_json, f, indent=2, ensure_ascii=False)
    
    return len(toffee_channels), api_success, fallback_success, sports_count

# ========== মেইন ফাংশন ==========
def main():
    print("=" * 50)
    print("টফি লাইভ টিভি প্লেলিস্ট জেনারেটর")
    print("সমস্ত চ্যানেলের জন্য কুকি সহ")
    print("=" * 50)
    
    global slug_mapping
    slug_mapping = load_slug_mapping()
    print(f"✓ {len(slug_mapping)}টি স্লাগ ম্যাপিং লোড হয়েছে")
    
    print("\n🔐 ডিভাইস রেজিস্ট্রেশন হচ্ছে...")
    access_token = register_device()
    if not access_token:
        print("❌ রেজিস্ট্রেশন ব্যর্থ!")
        return
    print("✓ ডিভাইস রেজিস্ট্রেশন সফল")
    
    print("\n📺 চ্যানেল সংগ্রহ করা হচ্ছে...")
    channels = fetch_all_channels(access_token)
    print(f"✓ {len(channels)}টি চ্যানেল পাওয়া গেছে")
    
    print("\n📝 প্লেলিস্ট তৈরি করা হচ্ছে...")
    total, api, fallback, sports = generate_playlists(channels, access_token)
    
    # নতুন স্লাগ ম্যাপিং সংরক্ষণ
    new_mappings = {}
    for ch in channels:
        title = ch.get('title')
        if title and title not in slug_mapping:
            ch_id = ch.get('id')
            if ch_id:
                stream_url, _, _ = get_playback_data(ch_id, access_token)
                if stream_url:
                    match = re.search(r'/(?:live|cdn/live)/([^/]+)/', stream_url)
                    if match:
                        slug = match.group(1)
                        new_mappings[title] = slug
    
    if new_mappings:
        slug_mapping.update(new_mappings)
        save_slug_mapping(slug_mapping)
        print(f"\n✓ {len(new_mappings)}টি নতুন স্লাগ ম্যাপিং যোগ করা হয়েছে")
    
    print("\n" + "=" * 50)
    print(f"✓ সম্পূর্ণ! {total}/{len(channels)}টি চ্যানেল")
    print(f"  • এপিআই সফল: {api}")
    print(f"  • ব্যাকআপ: {fallback}")
    print(f"  • স্পোর্টস চ্যানেল: {sports}")
    print("=" * 50)
    
    for f in OUTPUT_FILES:
        if os.path.exists(f):
            print(f"✓ {f}")

if __name__ == "__main__":
    main()
