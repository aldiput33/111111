#!/usr/bin/env python3
"""
Bot monitor hidden link tiket The Weeknd Jakarta 2026
Target: https://promo.bca.co.id/id/the-weeknd

Mencari link yang mengarah ke penjualan di tiket.com
Kontrol via Telegram: /start, /stop, /status

Deploy: Railway / Render / VPS
    pip install requests beautifulsoup4
    python weeknd_bca_bot.py

Telegram Setup:
    1. Chat @BotFather di Telegram, buat bot baru (/newbot)
    2. Copy token bot
    3. Chat bot kamu, kirim /start
    4. Set TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID
"""

import os
import sys
import time
import json
import re
import argparse
import threading
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup, Comment

# ============================================================
#  KONFIGURASI
# ============================================================

URL = "https://promo.bca.co.id/id/the-weeknd"
BASE = "https://promo.bca.co.id"
WIB = timezone(timedelta(hours=7))

DEFAULT_INTERVAL = 0.1

LOG_FILE = "weeknd_bca_bot.log"
FOUND_LINKS_FILE = "found_links.json"

# ── TELEGRAM CONFIG ──
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# URL pattern yang dicari (regex)
TIKET_PATTERNS = [
    r'https?://(?:www\.|m\.)?tiket\.com[^\s"\'<>\)]*',
    r'https?://[^\s"\'<>\)]*tiket\.com[^\s"\'<>\)]*',
]

# Pattern spesifik link presale The Weeknd Jakarta
WEEKND_TIKET_PATTERNS = [
    r'https?://(?:www\.|m\.)?tiket\.com/(?:id-id|en-id)/to-do/theweekndinjakarta[^\s"\'<>\)]*',
    r'https?://(?:www\.|m\.)?tiket\.com/(?:id-id|en-id)/to-do/[^\s"\'<>\)]*weeknd[^\s"\'<>\)]*',
    r'https?://(?:www\.|m\.)?tiket\.com/to-do/theweekndinjakarta[^\s"\'<>\)]*',
    r'https?://(?:www\.|m\.)?tiket\.com/to-do/[^\s"\'<>\)]*weeknd[^\s"\'<>\)]*',
]

# ============================================================
#  WARNA TERMINAL (ANSI)
# ============================================================

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    BG_RED  = "\033[41m"
    BG_GRN  = "\033[42m"

# ============================================================
#  BOT STATE (kontrol start/stop dari Telegram)
# ============================================================

class BotState:
    def __init__(self):
        self.monitoring = True  # default: langsung jalan
        self.cycle = 0
        self.last_scan = None
        self.total_found = 0
        self.found_urls = set()

bot_state = BotState()

# ============================================================
#  HELPER
# ============================================================

def now_wib():
    return datetime.now(WIB)

def log_to_file(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{now_wib().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

def is_tiket_url(url):
    return bool(re.search(r'tiket\.com', url, re.IGNORECASE))

def is_relevant_tiket_url(url):
    url_lower = url.lower()
    excludes = [
        "tiket.com/flights", "tiket.com/hotel", "tiket.com/kereta",
        "tiket.com/bus", "tiket.com/car-rental", "tiket.com/airport",
        "tiket.com/xperience", "tiket.com/mobile-apps",
        "tiket.com/en-id/flights", "tiket.com/en-id/hotel",
        "tiket.com/en-my/flights", "tiket.com/en-us/flights",
        "tiket.com/en-sg/flights", "tiket.com/en-th/flights",
        "tiket.com/destination",
    ]
    for ex in excludes:
        if ex in url_lower:
            return False
    if re.match(r'https?://(?:www\.|m\.)?tiket\.com/?(\?.*)?$', url):
        return False
    if re.match(r'https?://(?:www\.|m\.)?tiket\.com/(?:id-id|en-id|en-my|en-sg|en-th|en-us)/?(\?.*)?$', url):
        return False
    high_priority = ["theweekndinjakarta", "weeknd", "the-weeknd", "artistpresale", "presale", "queueittoken"]
    if any(kw in url_lower for kw in high_priority):
        return True
    if "/to-do/" in url_lower:
        return True
    return True

def is_weeknd_presale_url(url):
    url_lower = url.lower()
    if "theweekndinjakarta" in url_lower:
        return True
    if "weeknd" in url_lower and ("presale" in url_lower or "to-do" in url_lower):
        return True
    if "weeknd" in url_lower and "tiket.com" in url_lower:
        return True
    if "queueittoken" in url_lower and "tiket.com" in url_lower:
        return True
    return False

# ============================================================
#  TELEGRAM
# ============================================================

def send_telegram(message, chat_id=None):
    """Kirim pesan ke Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": cid,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        log_to_file(f"Telegram error: {e}")
        return False

def send_telegram_alert(links):
    """Kirim alert link ditemukan."""
    current = now_wib().strftime('%d %b %Y %H:%M:%S WIB')
    presale = [l for l in links if l.get("priority") or "PRESALE" in l.get("type", "")]
    others = [l for l in links if l not in presale]

    msg = "🚨🚨🚨 <b>LINK TIKET.COM DITEMUKAN!</b> 🚨🚨🚨\n\n"
    msg += f"⏰ {current}\n"
    msg += f"🎯 Target: promo.bca.co.id/id/the-weeknd\n\n"

    if presale:
        msg += "🎫 <b>=== PRESALE WEEKND ===</b>\n\n"
        for link in presale:
            text = link.get("text", "")
            msg += f"🔥 <b>[{link['type']}]</b>\n"
            if text:
                msg += f"   {text}\n"
            msg += f"👉 <a href=\"{link['url']}\">{link['url'][:80]}</a>\n\n"

    if others:
        msg += "📎 <b>Link Lainnya:</b>\n\n"
        for link in others:
            msg += f"• <a href=\"{link['url']}\">{link['url'][:60]}</a>\n"

    msg += "\n⚡ <b>BUKA SEKARANG!</b>"
    return send_telegram(msg)

def get_telegram_updates(offset=None):
    """Poll Telegram updates (commands dari user)."""
    if not TELEGRAM_BOT_TOKEN:
        return []
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"timeout": 5, "allowed_updates": ["message"]}
        if offset:
            params["offset"] = offset
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("result", [])
    except Exception:
        pass
    return []

def handle_telegram_command(text, chat_id):
    """Handle command dari Telegram."""
    global TELEGRAM_CHAT_ID
    cmd = text.strip().lower()

    if cmd == "/start":
        TELEGRAM_CHAT_ID = str(chat_id)
        bot_state.monitoring = True
        msg = "✅ <b>Bot AKTIF!</b>\n\n"
        msg += f"🎯 Monitoring: {URL}\n"
        msg += f"⚡ Interval: {DEFAULT_INTERVAL}s\n"
        msg += f"📊 Scan ke-: {bot_state.cycle}\n\n"
        msg += "<b>Commands:</b>\n"
        msg += "/start - Mulai monitoring\n"
        msg += "/stop - Stop monitoring\n"
        msg += "/status - Cek status bot\n"
        msg += "/scan - Force scan sekarang\n"
        send_telegram(msg, chat_id)
        log_to_file(f"Telegram: /start dari {chat_id}")
        return

    if cmd == "/stop":
        bot_state.monitoring = False
        msg = "⛔ <b>Bot STOPPED</b>\n\n"
        msg += f"Total scan: {bot_state.cycle}\n"
        msg += f"Link ditemukan: {bot_state.total_found}\n\n"
        msg += "Kirim /start untuk mulai lagi."
        send_telegram(msg, chat_id)
        log_to_file(f"Telegram: /stop dari {chat_id}")
        return

    if cmd == "/status":
        status = "🟢 AKTIF" if bot_state.monitoring else "🔴 STOPPED"
        last = bot_state.last_scan or "belum pernah"
        msg = f"📊 <b>Status Bot</b>\n\n"
        msg += f"Status: {status}\n"
        msg += f"Scan ke-: {bot_state.cycle}\n"
        msg += f"Last scan: {last}\n"
        msg += f"Link ditemukan: {bot_state.total_found}\n"
        msg += f"Interval: {DEFAULT_INTERVAL}s\n"
        msg += f"Target: {URL}\n"
        send_telegram(msg, chat_id)
        return

    if cmd == "/scan":
        if not bot_state.monitoring:
            bot_state.monitoring = True
        send_telegram("🔍 Force scan... akan diproses di cycle berikutnya.", chat_id)
        return

    # Unknown command
    msg = "🤖 <b>Bot Monitor The Weeknd</b>\n\n"
    msg += "<b>Commands:</b>\n"
    msg += "/start - Mulai monitoring\n"
    msg += "/stop - Stop monitoring\n"
    msg += "/status - Cek status\n"
    msg += "/scan - Force scan\n"
    send_telegram(msg, chat_id)

def telegram_listener():
    """Background thread: listen for Telegram commands."""
    offset = None
    while True:
        try:
            updates = get_telegram_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")
                if text.startswith("/") and chat_id:
                    handle_telegram_command(text, chat_id)
        except Exception as e:
            log_to_file(f"Telegram listener error: {e}")
        time.sleep(2)

# ============================================================
#  FETCH & PARSE
# ============================================================

def fetch_page(session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://promo.bca.co.id/",
    }
    resp = session.get(URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser"), resp.text

def extract_visible_links(soup):
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if is_tiket_url(href) and is_relevant_tiket_url(href):
            text = a.get_text(strip=True) or "[no text]"
            priority = is_weeknd_presale_url(href)
            links.append({
                "type": "*** PRESALE WEEKND ***" if priority else "VISIBLE LINK",
                "text": text, "url": href,
                "relevant": True, "priority": priority,
            })
    return links

def find_hidden_links(soup, raw_html):
    found = []

    # CSS hidden
    for el in soup.find_all(style=re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0')):
        for u in re.findall(r'https?://[^\s"\'<>\)]+', str(el)):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                found.append({"type": "HIDDEN CSS", "text": "", "url": u})

    # HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        for u in re.findall(r'https?://[^\s"\'<>\)]+', comment):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                found.append({"type": "HTML COMMENT", "text": "", "url": u})

    # Data attributes
    for el in soup.find_all(True):
        for attr, val in el.attrs.items():
            if isinstance(val, str) and is_tiket_url(val):
                for u in re.findall(r'https?://[^\s"\'<>\)]+', val):
                    if is_tiket_url(u) and is_relevant_tiket_url(u):
                        found.append({"type": f"DATA-ATTR", "text": "", "url": u})

    # JavaScript
    for script in soup.find_all("script"):
        content = script.string or ""
        for u in re.findall(r'https?://[^\s"\'<>\)\\]+', content):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                lt = "*** PRESALE WEEKND (JS) ***" if is_weeknd_presale_url(u) else "JAVASCRIPT"
                found.append({"type": lt, "text": "", "url": u})
        for u in re.findall(r'https?:\\/\\/[^\s"\'<>\)]+', content):
            unescaped = u.replace("\\/", "/")
            if is_tiket_url(unescaped) and is_relevant_tiket_url(unescaped):
                lt = "*** PRESALE WEEKND (JS) ***" if is_weeknd_presale_url(unescaped) else "JS (escaped)"
                found.append({"type": lt, "text": "", "url": unescaped})

    # Raw HTML URLs not in visible <a>
    visible_hrefs = set(a["href"].strip() for a in soup.find_all("a", href=True))
    for pattern in TIKET_PATTERNS + WEEKND_TIKET_PATTERNS:
        for u in set(re.findall(pattern, raw_html)):
            clean = u.rstrip(".,;:\"')")
            if clean not in visible_hrefs and is_relevant_tiket_url(clean):
                if not any(f["url"] == clean for f in found):
                    lt = "*** PRESALE WEEKND ***" if is_weeknd_presale_url(clean) else "URL BARU"
                    found.append({"type": lt, "text": "", "url": clean})

    # iframe
    for iframe in soup.find_all("iframe", src=True):
        if is_tiket_url(iframe["src"]):
            found.append({"type": "IFRAME", "text": "", "url": iframe["src"]})

    # Meta refresh
    for meta in soup.find_all("meta", attrs={"http-equiv": "refresh"}):
        for u in re.findall(r'url=([^\s"\']+)', meta.get("content", ""), re.IGNORECASE):
            if is_tiket_url(u):
                found.append({"type": "META REFRESH", "text": "", "url": u})

    # Deduplicate
    seen = set()
    unique = []
    for f in found:
        if f["url"] not in seen:
            seen.add(f["url"])
            unique.append(f)
    return unique

def find_all_tiket_links(soup, raw_html):
    all_links = []
    all_links.extend(extract_visible_links(soup))
    all_links.extend(find_hidden_links(soup, raw_html))
    return all_links

# ============================================================
#  TERMINAL DISPLAY
# ============================================================

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def ln(text=""):
    print(f"  {text}")

def print_display(all_links, hidden_links, cycle, elapsed_ms):
    current = now_wib()
    clear_screen()
    print()
    ln(f"{C.CYAN}{C.BOLD}+======================================================+{C.RESET}")
    ln(f"{C.CYAN}{C.BOLD}|   THE WEEKND - BCA x TIKET.COM MONITOR BOT           |{C.RESET}")
    ln(f"{C.CYAN}{C.BOLD}+======================================================+{C.RESET}")
    print()
    status = f"{C.GREEN}MONITORING" if bot_state.monitoring else f"{C.RED}STOPPED"
    ln(f"{C.WHITE}  Waktu  : {C.BOLD}{current.strftime('%d %b %Y  %H:%M:%S WIB')}{C.RESET}")
    ln(f"{C.WHITE}  Status : {status}{C.RESET}")
    ln(f"{C.DIM}  Scan # : {cycle}    Response: {elapsed_ms}ms{C.RESET}")
    tg = f"{C.GREEN}ON" if TELEGRAM_BOT_TOKEN else f"{C.RED}OFF"
    ln(f"{C.DIM}  Telegram: {tg}{C.RESET}")
    print()

    priority = [l for l in all_links if l.get("priority") or "PRESALE" in l["type"]]
    if priority:
        ln(f"{C.BG_GRN}{C.BOLD}{C.WHITE}  !!! PRESALE LINK DITEMUKAN !!!  {C.RESET}")
        for link in priority:
            ln(f"{C.GREEN}{C.BOLD}    >>> {link['url'][:75]}{C.RESET}")
        print()
    else:
        ln(f"{C.DIM}  Menunggu link tiket.com muncul...{C.RESET}")
        print()

    ln(f"{C.DIM}  Links: {len(all_links)}  |  Hidden: {len(hidden_links)}  |  Found total: {bot_state.total_found}{C.RESET}")
    ln(f"{C.DIM}  Ctrl+C stop  |  Telegram: /start /stop /status{C.RESET}")
    print()

# ============================================================
#  NOTIFY
# ============================================================

def notify_user(links):
    ln(f"{C.BG_RED}{C.BOLD}{C.WHITE}{'!!! LINK DITEMUKAN !!!':^54}{C.RESET}")
    for link in links:
        ln(f"{C.GREEN}{C.BOLD}  >> {link['url']}{C.RESET}")
    print("\a" * 3)

    # Save
    with open(FOUND_LINKS_FILE, "w") as f:
        json.dump({"found_at": now_wib().isoformat(), "links": links}, f, indent=2)
    log_to_file(f"LINK DITEMUKAN: {json.dumps(links)}")

    # Telegram
    send_telegram_alert(links)

# ============================================================
#  MAIN LOOP
# ============================================================

def run_monitor():
    session = requests.Session()

    print()
    ln(f"{C.CYAN}{C.BOLD}  THE WEEKND - BCA x TIKET.COM MONITOR BOT{C.RESET}")
    ln(f"{C.DIM}  Target: {URL}{C.RESET}")

    if TELEGRAM_BOT_TOKEN:
        ln(f"{C.GREEN}  Telegram: AKTIF - kirim /start ke bot{C.RESET}")
        # Start Telegram listener thread
        t = threading.Thread(target=telegram_listener, daemon=True)
        t.start()
        send_telegram(
            "🤖 <b>Bot Started!</b>\n\n"
            f"🎯 {URL}\n"
            "⚡ Kirim /start untuk mulai monitoring\n"
            "📊 Kirim /status untuk cek status\n"
            "⛔ Kirim /stop untuk stop"
        )
    else:
        ln(f"{C.YELLOW}  Telegram: OFF (set TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID){C.RESET}")

    print()
    time.sleep(1)
    log_to_file("Bot dimulai")

    try:
        while True:
            if not bot_state.monitoring:
                # Idle mode - tunggu /start dari Telegram
                time.sleep(2)
                continue

            bot_state.cycle += 1
            try:
                t0 = time.time()
                soup, raw_html = fetch_page(session)
                elapsed_ms = int((time.time() - t0) * 1000)

                all_links = find_all_tiket_links(soup, raw_html)
                hidden_links = find_hidden_links(soup, raw_html)
                bot_state.last_scan = now_wib().strftime('%H:%M:%S')

                print_display(all_links, hidden_links, bot_state.cycle, elapsed_ms)

                # Check new links
                new_relevant = []
                for link in all_links:
                    if link.get("relevant") and link["url"] not in bot_state.found_urls:
                        new_relevant.append(link)

                if new_relevant:
                    bot_state.total_found += len(new_relevant)
                    notify_user(new_relevant)
                    for l in new_relevant:
                        bot_state.found_urls.add(l["url"])
                    time.sleep(30)

                time.sleep(DEFAULT_INTERVAL)

            except KeyboardInterrupt:
                raise
            except requests.RequestException as e:
                ln(f"{C.RED}  Network error: {e}{C.RESET}")
                log_to_file(f"Network error: {e}")
                time.sleep(5)
            except Exception as e:
                ln(f"{C.RED}  Error: {e}{C.RESET}")
                log_to_file(f"Error: {e}")
                time.sleep(5)

    except KeyboardInterrupt:
        print(f"\n  {C.YELLOW}Bot dihentikan. Total scan: {bot_state.cycle}{C.RESET}\n")
        log_to_file(f"Bot dihentikan setelah {bot_state.cycle} scan")
        send_telegram(f"⛔ Bot dihentikan. Total scan: {bot_state.cycle}")

def main():
    parser = argparse.ArgumentParser(description="Bot monitor tiket.com - The Weeknd Jakarta 2026")
    parser.add_argument("--interval", "-i", type=float, default=None)
    parser.add_argument("--no-auto-open", action="store_true")
    parser.add_argument("--telegram-token", type=str, default=None)
    parser.add_argument("--telegram-chat", type=str, default=None)
    args = parser.parse_args()

    global DEFAULT_INTERVAL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    if args.interval:
        DEFAULT_INTERVAL = args.interval
    if args.telegram_token:
        TELEGRAM_BOT_TOKEN = args.telegram_token
    if args.telegram_chat:
        TELEGRAM_CHAT_ID = args.telegram_chat

    run_monitor()

if __name__ == "__main__":
    main()
