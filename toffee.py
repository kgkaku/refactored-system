# ===================================================
# Toffee Live TV Playlist Generator - FINAL
# English Version with Live Events Priority
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

# ========== CONFIGURATION ==========
SECRET_KEY = "06e63248b1b56d5789ba0b047f548eba"
SECRET_KEY_BYTES = SECRET_KEY.encode('utf-8')

DEVICE_REGISTER_URL = "https://prod-services.toffeelive.com/sms/v1/device/register"
CONTENT_BASE = "https://content-prod.services.toffeelive.com/toffee/BD/DK/android-mobile"
PLAYBACK_BASE = "https://entitlement-prod.services.toffeelive.com/toffee/BD/DK/android-mobile/playback"
ALL_LIVE_TV_URL = f"{CONTENT_BASE}/rail/generic/editorial-dynamic?filters=v_type:channels;subType:Live_TV&page={{page}}"

SLUG_FILE = "slug.txt"
OUTPUT_FILES = ["ottnavigator.m3u", "nsplayer.m3u", "toffee.json"]

# Patterns to identify LIVE EVENTS (match-*, bdvsnz, epl, bfl, etc.)
LIVE_EVENT_PATTERNS = ["match-", "bdvsnz", "epl", "bfl"]
SPORTS_CHANNEL_PATTERNS = ["sports", "cricket", "ten", "eurosport", "icc"]

# User agents
LIVE_EVENT_USER_AGENT = "Toffee/8.8.0 (Linux;Android 7.1.2) ExoPlayerLib/2.18.6"
NORMAL_USER_AGENT = "okhttp/5.1.0"

# ========== GLOBAL VARIABLES ==========
slug_mapping = {}
COOKIE_BLDCMPROD = None
COOKIE_MPROD = None

# ========== UTILITY FUNCTIONS ==========
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

def is_live_event(slug: str) -> bool:
    """Check if channel is a LIVE EVENT (uses mprod-cdn)"""
    slug_lower = slug.lower()
    return any(pattern in slug_lower for pattern in LIVE_EVENT_PATTERNS)

def is_sports_channel(title: str, slug: str) -> bool:
    """Check if channel is a regular sports channel (uses bldcmprod-cdn)"""
    text = (title + " " + slug).lower()
    return any(pattern in text for pattern in SPORTS_CHANNEL_PATTERNS) and not is_live_event(slug)

def get_channel_type(slug: str) -> str:
    """Return channel type: 'live_event', 'sports', or 'normal'"""
    if is_live_event(slug):
        return "live_event"
    elif is_sports_channel("", slug):
        return "sports"
    else:
        return "normal"

def get_user_agent(channel_type: str) -> str:
    """Return appropriate user agent based on channel type"""
    if channel_type == "live_event":
        return LIVE_EVENT_USER_AGENT
    return NORMAL_USER_AGENT

def get_cookie(channel_type: str) -> Optional[str]:
    """Return appropriate cookie based on channel type"""
    if channel_type == "live_event":
        return COOKIE_MPROD
    return COOKIE_BLDCMPROD

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

# ========== SLUG FILE MANAGEMENT ==========
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
        f.write("# Toffee Channel Slug Mapping\n")
        f.write("# Format: Channel Name = slug\n\n")
        for channel, slug in sorted(mapping.items()):
            f.write(f"{channel} = {slug}\n")

# ========== DEVICE REGISTRATION ==========
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
        print(f"Registration error: {e}")
    return None

def get_headers(access_token: str) -> Dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "okhttp/5.1.0",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

def get_playback_data(content_id: str, access_token: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (stream_url, cookie_bldcmprod, cookie_mprod)"""
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
    """Generate stream URL from slug based on channel type"""
    if is_live_event(slug):
        return f"https://mprod-cdn.toffeelive.com/live/{slug}/index.m3u8"
    else:
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

# ========== PLAYLIST GENERATOR ==========
def generate_playlists(channels: List[Dict], access_token: str):
    global COOKIE_BLDCMPROD, COOKIE_MPROD
    
    # First, capture cookies
    print("\n🍪 Capturing cookies...")
    for ch in channels:
        ch_id = ch.get('id')
        if ch_id:
            get_playback_data(ch_id, access_token)
            if COOKIE_BLDCMPROD and COOKIE_MPROD:
                break
    
    print(f"   🍪 bldcmprod Cookie: {'Captured' if COOKIE_BLDCMPROD else 'Not captured'}")
    print(f"   🍪 mprod Cookie: {'Captured' if COOKIE_MPROD else 'Not captured'}")
    
    # Process all channels and add metadata
    channel_data = []
    api_success = 0
    fallback_success = 0
    
    print("\n📝 Processing channels...")
    for ch in channels:
        title = ch.get('title')
        ch_id = ch.get('id')
        if not title or not ch_id:
            continue
        
        logo = get_logo(ch)
        stream_url, _, _ = get_playback_data(ch_id, access_token)
        
        # If API fails, use slug mapping
        if not stream_url and title in slug_mapping:
            slug = slug_mapping[title]
            stream_url = get_stream_url_from_slug(title, slug)
            fallback_success += 1
        elif stream_url:
            api_success += 1
        else:
            continue
        
        # Determine channel type from slug
        slug = slug_mapping.get(title, "")
        channel_type = get_channel_type(slug)
        
        channel_data.append({
            "title": title,
            "logo": logo,
            "stream_url": stream_url,
            "channel_type": channel_type,
            "slug": slug
        })
    
    # Sort: Live events first, then sports, then normal channels
    live_events = [c for c in channel_data if c["channel_type"] == "live_event"]
    sports = [c for c in channel_data if c["channel_type"] == "sports"]
    normal = [c for c in channel_data if c["channel_type"] == "normal"]
    
    sorted_channels = live_events + sports + normal
    
    print(f"\n   📊 Channel breakdown:")
    print(f"      Live Events: {len(live_events)}")
    print(f"      Sports: {len(sports)}")
    print(f"      Normal: {len(normal)}")
    
    # Generate OTT Navigator M3U
    ott_lines = ["#EXTM3U"]
    current_time = datetime.now().strftime("%d-%m-%Y at %I:%M:%S %p")
    ott_lines.append(f"# Playlist created by @kgkaku")
    ott_lines.append(f"# Generated on: {current_time}")
    ott_lines.append(f"# Total Channels: {len(sorted_channels)} | Active: {api_success + fallback_success}")
    ott_lines.append("")
    
    ns_list = []
    toffee_channels = []
    
    for ch in sorted_channels:
        channel_type = ch["channel_type"]
        user_agent = get_user_agent(channel_type)
        cookie = get_cookie(channel_type)
        
        # OTT Navigator M3U
        ott_lines.append(f'#EXTINF:-1 group-title="Live TV" tvg-logo="{ch["logo"]}" tvg-name="{ch["title"]}", {ch["title"]}')
        ott_lines.append(f'#EXTVLCOPT:http-user-agent={user_agent}')
        if cookie:
            ott_lines.append(f'#EXTHTTP:{{"cookie":"{cookie}"}}')
        ott_lines.append(ch["stream_url"])
        ott_lines.append('')
        
        # NS Player JSON
        ns_list.append({
            "category": "Live TV",
            "name": ch["title"],
            "link": ch["stream_url"],
            "logo": ch["logo"],
            "cookie": cookie or "",
            "user_agent": user_agent
        })
        
        # Toffee JSON
        toffee_channels.append({
            "category_name": "Live TV",
            "name": ch["title"],
            "link": ch["stream_url"],
            "headers": {"cookie": cookie or ""},
            "logo": ch["logo"]
        })
    
    # Write OTT Navigator M3U
    with open("ottnavigator.m3u", "w", encoding='utf-8') as f:
        f.write('\n'.join(ott_lines))
    
    # Write NS Player M3U
    with open("nsplayer.m3u", "w", encoding='utf-8') as f:
        json.dump(ns_list, f, indent=2, ensure_ascii=False)
    
    # Write Toffee JSON
    toffee_json = {
        "name": "Toffee Live TV Playlist",
        "creator": "@kgkaku",
        "generated_on": current_time,
        "total_channels": len(toffee_channels),
        "active_channels": api_success + fallback_success,
        "live_events": len(live_events),
        "sports_channels": len(sports),
        "normal_channels": len(normal),
        "channels": toffee_channels
    }
    with open("toffee.json", "w", encoding='utf-8') as f:
        json.dump(toffee_json, f, indent=2, ensure_ascii=False)
    
    return len(toffee_channels), api_success, fallback_success, len(live_events), len(sports), len(normal)

# ========== MAIN FUNCTION ==========
def main():
    print("=" * 50)
    print("Toffee Live TV Playlist Generator")
    print("Live Events Priority | Cookie Support")
    print("=" * 50)
    
    global slug_mapping
    slug_mapping = load_slug_mapping()
    print(f"✓ Loaded {len(slug_mapping)} slug mappings")
    
    print("\n🔐 Registering device...")
    access_token = register_device()
    if not access_token:
        print("❌ Registration failed!")
        return
    print("✓ Device registered")
    
    print("\n📺 Fetching channels...")
    channels = fetch_all_channels(access_token)
    print(f"✓ Found {len(channels)} channels")
    
    print("\n📝 Generating playlists...")
    total, api, fallback, live_events, sports, normal = generate_playlists(channels, access_token)
    
    # Auto-discover and save new slug mappings
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
        print(f"\n✓ Added {len(new_mappings)} new slug mappings")
    
    print("\n" + "=" * 50)
    print(f"✓ Complete! {total}/{len(channels)} channels")
    print(f"  • API success: {api}")
    print(f"  • Fallback: {fallback}")
    print(f"  • Live Events: {live_events}")
    print(f"  • Sports: {sports}")
    print(f"  • Normal: {normal}")
    print("=" * 50)
    
    for f in OUTPUT_FILES:
        if os.path.exists(f):
            print(f"✓ {f}")

if __name__ == "__main__":
    main()
