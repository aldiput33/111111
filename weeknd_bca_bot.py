#!/usr/bin/env python3
"""
Bot monitor hidden link tiket The Weeknd Jakarta 2026
Target: https://promo.bca.co.id/id/the-weeknd + direct URL probing

Kontrol via Telegram: /start, /stop, /status
Semua orang bisa akses bot Telegram ini.

Deploy: Render / Railway / VPS
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
WIB = timezone(timedelta(hours=7))
DEFAULT_INTERVAL = 0.1

LOG_FILE = "weeknd_bca_bot.log"
FOUND_LINKS_FILE = "found_links.json"

# ── TELEGRAM CONFIG ──
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8757063005:AAHYTOK5SCUC3LSTWwpNhsID97wdEyGh-_I")
TELEGRAM_CHAT_IDS = set()  # semua user yang /start akan masuk sini

# ── DIRECT URL PROBING ──
# Semua kemungkinan URL BCA presale yang akan di-probe langsung
PROBE_URLS = [
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bcapresaleday1",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bcapresaleday2",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bcapresale1",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bcapresale2",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bca-presale-day1",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bca-presale-day2",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bca-presale1",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bca-presale2",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-mybcapresaleday1",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-mybcapresaleday2",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-mybcapresale1",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-mybcapresale2",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bcapresale",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-bca-presale",
    "https://www.tiket.com/id-id/to-do/theweekndinjakarta-mybcapresale",
    "https://www.tiket.com/id-id/to-do/the-weeknd-in-jakarta-bcapresaleday1",
    "https://www.tiket.com/id-id/to-do/the-weeknd-in-jakarta-bcapresaleday2",
    "https://www.tiket.com/to-do/theweekndinjakarta-bcapresaleday1",
    "https://www.tiket.com/to-do/theweekndinjakarta-bcapresaleday2",
]

# URL patterns for HTML scanning
TIKET_PATTERNS = [
    r'https?://(?:www\.|m\.)?tiket\.com[^\s"\'<>\)]*',
]
WEEKND_TIKET_PATTERNS = [
    r'https?://(?:www\.|m\.)?tiket\.com/(?:id-id|en-id)/to-do/theweekndinjakarta[^\s"\'<>\)]*',
    r'https?://(?:www\.|m\.)?tiket\.com/to-do/theweekndinjakarta[^\s"\'<>\)]*',
]

# ============================================================
#  BOT STATE
# ============================================================

class BotState:
    def __init__(self):
        self.monitoring = True
        self.cycle = 0
        self.last_scan = None
        self.total_found = 0
        self.found_urls = set()
        self.live_urls = set()  # URLs yang sudah confirmed live

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
    excludes = ["tiket.com/flights", "tiket.com/hotel", "tiket.com/kereta", "tiket.com/bus",
                "tiket.com/car-rental", "tiket.com/airport", "tiket.com/xperience",
                "tiket.com/mobile-apps", "tiket.com/destination"]
    for ex in excludes:
        if ex in url_lower:
            return False
    if re.match(r'https?://(?:www\.|m\.)?tiket\.com/?(\?.*)?$', url):
        return False
    if re.match(r'https?://(?:www\.|m\.)?tiket\.com/(?:id-id|en-id|en-my|en-sg|en-th|en-us)/?(\?.*)?$', url):
        return False
    return True

def is_weeknd_presale_url(url):
    url_lower = url.lower()
    if "theweekndinjakarta" in url_lower:
        return True
    if "weeknd" in url_lower and "tiket.com" in url_lower:
        return True
    if "queueittoken" in url_lower and "tiket.com" in url_lower:
        return True
    return False

# ============================================================
#  TELEGRAM (multi-user, semua orang bisa akses)
# ============================================================

def send_telegram(message, chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return False
    targets = [chat_id] if chat_id else list(TELEGRAM_CHAT_IDS)
    if not targets:
        return False
    success = False
    for cid in targets:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": cid, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                success = True
        except Exception:
            pass
    return success

def send_telegram_all(message):
    """Kirim ke SEMUA user yang sudah /start."""
    for cid in list(TELEGRAM_CHAT_IDS):
        send_telegram(message, cid)

def send_alert_all(links):
    """Kirim alert link ditemukan ke semua user."""
    current = now_wib().strftime('%d %b %Y %H:%M:%S WIB')
    msg = "🚨🚨🚨 <b>LINK TIKET.COM DITEMUKAN!</b> 🚨🚨🚨\n\n"
    msg += f"⏰ {current}\n\n"

    for link in links:
        if link.get("live"):
            msg += f"🟢 <b>LIVE!</b> "
        else:
            msg += f"🔥 "
        msg += f"<a href=\"{link['url']}\">{link['url']}</a>\n\n"

    msg += "⚡ <b>BUKA SEKARANG!</b>"
    send_telegram_all(msg)

def send_live_alert(url, status_code):
    """Kirim alert khusus URL yang LIVE."""
    current = now_wib().strftime('%d %b %Y %H:%M:%S WIB')
    msg = "🟢🟢🟢 <b>URL PRESALE LIVE!</b> 🟢🟢🟢\n\n"
    msg += f"⏰ {current}\n"
    msg += f"📊 HTTP Status: {status_code}\n\n"
    msg += f"👉 <a href=\"{url}\">{url}</a>\n\n"
    msg += "⚡⚡⚡ <b>BUKA SEKARANG! LINK AKTIF!</b> ⚡⚡⚡"
    send_telegram_all(msg)

def get_telegram_updates(offset=None):
    if not TELEGRAM_BOT_TOKEN:
        return []
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"timeout": 5, "allowed_updates": ["message"]}
        if offset:
            params["offset"] = offset
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("result", [])
    except Exception:
        pass
    return []

def handle_telegram_command(text, chat_id):
    cmd = text.strip().lower().split()[0] if text.strip() else ""

    if cmd == "/start":
        TELEGRAM_CHAT_IDS.add(str(chat_id))
        bot_state.monitoring = True
        msg = "✅ <b>Kamu terdaftar! Bot AKTIF!</b>\n\n"
        msg += f"🎯 Monitoring: promo.bca.co.id + {len(PROBE_URLS)} URL presale\n"
        msg += f"⚡ Interval: {DEFAULT_INTERVAL}s\n\n"
        msg += "<b>Commands:</b>\n"
        msg += "/start - Mulai & daftar notifikasi\n"
        msg += "/stop - Stop monitoring\n"
        msg += "/status - Cek status bot\n"
        msg += "/probe - Force cek semua URL presale\n"
        msg += "/urls - Lihat daftar URL yang dipantau\n"
        send_telegram(msg, chat_id)
        log_to_file(f"Telegram: /start dari {chat_id}")
        return

    if cmd == "/stop":
        bot_state.monitoring = False
        msg = "⛔ <b>Monitoring STOPPED</b>\n\n"
        msg += f"Total scan: {bot_state.cycle}\n"
        msg += f"Link ditemukan: {bot_state.total_found}\n"
        msg += f"URL live: {len(bot_state.live_urls)}\n\n"
        msg += "Kirim /start untuk mulai lagi."
        send_telegram(msg, chat_id)
        log_to_file(f"Telegram: /stop dari {chat_id}")
        return

    if cmd == "/status":
        status = "🟢 AKTIF" if bot_state.monitoring else "🔴 STOPPED"
        msg = f"📊 <b>Status Bot</b>\n\n"
        msg += f"Status: {status}\n"
        msg += f"Scan ke-: {bot_state.cycle}\n"
        msg += f"Last scan: {bot_state.last_scan or '-'}\n"
        msg += f"Link ditemukan: {bot_state.total_found}\n"
        msg += f"URL live: {len(bot_state.live_urls)}\n"
        msg += f"Users terdaftar: {len(TELEGRAM_CHAT_IDS)}\n"
        msg += f"URL dipantau: {len(PROBE_URLS)}\n"
        if bot_state.live_urls:
            msg += "\n🟢 <b>URL LIVE:</b>\n"
            for u in bot_state.live_urls:
                msg += f"• {u}\n"
        send_telegram(msg, chat_id)
        return

    if cmd == "/probe":
        send_telegram("🔍 Memulai probe semua URL presale...", chat_id)
        # trigger probe di next cycle
        bot_state.monitoring = True
        return

    if cmd == "/urls":
        msg = "📋 <b>Daftar URL yang dipantau:</b>\n\n"
        for i, u in enumerate(PROBE_URLS, 1):
            live = "🟢" if u in bot_state.live_urls else "⚪"
            msg += f"{live} {i}. {u.split('/')[-1]}\n"
        send_telegram(msg, chat_id)
        return

    # Unknown
    msg = "🤖 <b>Bot Monitor The Weeknd BCA Presale</b>\n\n"
    msg += "/start - Daftar & mulai\n"
    msg += "/stop - Stop\n"
    msg += "/status - Status bot\n"
    msg += "/probe - Force cek URL\n"
    msg += "/urls - Lihat URL dipantau\n"
    send_telegram(msg, chat_id)

def telegram_listener():
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
            log_to_file(f"TG listener error: {e}")
        time.sleep(2)

# ============================================================
#  DIRECT URL PROBING
# ============================================================

def probe_urls(session):
    """Cek semua kemungkinan URL presale - apakah sudah live (HTTP 200)."""
    newly_live = []
    for url in PROBE_URLS:
        if url in bot_state.live_urls:
            continue  # sudah dinotif sebelumnya
        try:
            resp = session.head(url, timeout=10, allow_redirects=True)
            # HTTP 200 = LIVE! / 302 redirect ke queue = juga LIVE
            if resp.status_code in [200, 301, 302]:
                bot_state.live_urls.add(url)
                newly_live.append({"url": url, "status": resp.status_code, "live": True})
                log_to_file(f"LIVE! {url} -> HTTP {resp.status_code}")
                send_live_alert(url, resp.status_code)
            # 404 = belum ada, skip
        except requests.RequestException:
            pass
        except Exception:
            pass
        time.sleep(0.05)  # jangan terlalu agresif
    return newly_live

# ============================================================
#  FETCH & PARSE (halaman BCA promo)
# ============================================================

def fetch_page(session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://promo.bca.co.id/",
    }
    resp = session.get(URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser"), resp.text

def find_all_tiket_links(soup, raw_html):
    found = []

    # Visible <a> links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if is_tiket_url(href) and is_relevant_tiket_url(href):
            found.append({"type": "VISIBLE", "text": a.get_text(strip=True)[:40], "url": href,
                          "relevant": True, "priority": is_weeknd_presale_url(href)})

    # Hidden CSS
    for el in soup.find_all(style=re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0')):
        for u in re.findall(r'https?://[^\s"\'<>\)]+', str(el)):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                found.append({"type": "HIDDEN", "text": "", "url": u, "relevant": True, "priority": is_weeknd_presale_url(u)})

    # HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        for u in re.findall(r'https?://[^\s"\'<>\)]+', comment):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                found.append({"type": "COMMENT", "text": "", "url": u, "relevant": True, "priority": is_weeknd_presale_url(u)})

    # JavaScript
    for script in soup.find_all("script"):
        content = script.string or ""
        for u in re.findall(r'https?://[^\s"\'<>\)\\]+', content):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                found.append({"type": "JS", "text": "", "url": u, "relevant": True, "priority": is_weeknd_presale_url(u)})
        for u in re.findall(r'https?:\\/\\/[^\s"\'<>\)]+', content):
            unesc = u.replace("\\/", "/")
            if is_tiket_url(unesc) and is_relevant_tiket_url(unesc):
                found.append({"type": "JS", "text": "", "url": unesc, "relevant": True, "priority": is_weeknd_presale_url(unesc)})

    # Data attributes
    for el in soup.find_all(True):
        for attr, val in el.attrs.items():
            if isinstance(val, str) and is_tiket_url(val):
                for u in re.findall(r'https?://[^\s"\'<>\)]+', val):
                    if is_relevant_tiket_url(u):
                        found.append({"type": "DATA", "text": "", "url": u, "relevant": True, "priority": is_weeknd_presale_url(u)})

    # Raw HTML patterns
    visible_hrefs = set(a["href"].strip() for a in soup.find_all("a", href=True))
    for pattern in TIKET_PATTERNS + WEEKND_TIKET_PATTERNS:
        for u in set(re.findall(pattern, raw_html)):
            clean = u.rstrip(".,;:\"')")
            if clean not in visible_hrefs and is_relevant_tiket_url(clean):
                if not any(f["url"] == clean for f in found):
                    found.append({"type": "RAW", "text": "", "url": clean, "relevant": True, "priority": is_weeknd_presale_url(clean)})

    # Deduplicate
    seen = set()
    unique = []
    for f in found:
        if f["url"] not in seen:
            seen.add(f["url"])
            unique.append(f)
    return unique

# ============================================================
#  TERMINAL DISPLAY
# ============================================================

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_display(all_links, probe_live, cycle, elapsed_ms):
    current = now_wib()
    clear_screen()
    print()
    print(f"  ╔══════════════════════════════════════════════════════╗")
    print(f"  ║  THE WEEKND - BCA PRESALE MONITOR BOT               ║")
    print(f"  ╚══════════════════════════════════════════════════════╝")
    print()
    status = "🟢 MONITORING" if bot_state.monitoring else "🔴 STOPPED"
    print(f"  Waktu  : {current.strftime('%d %b %Y  %H:%M:%S WIB')}")
    print(f"  Status : {status}")
    print(f"  Scan # : {cycle}    Response: {elapsed_ms}ms")
    print(f"  Users  : {len(TELEGRAM_CHAT_IDS)}    URLs probe: {len(PROBE_URLS)}")
    print()

    if bot_state.live_urls:
        print(f"  🟢 URL LIVE ({len(bot_state.live_urls)}):")
        for u in bot_state.live_urls:
            print(f"     >>> {u}")
        print()

    priority = [l for l in all_links if l.get("priority")]
    if priority:
        print(f"  🔥 PRESALE LINKS FOUND ({len(priority)}):")
        for link in priority:
            print(f"     >>> {link['url'][:75]}")
        print()
    else:
        print(f"  ⏳ Menunggu link muncul...")
        print()

    print(f"  Total links: {len(all_links)}  |  Live URLs: {len(bot_state.live_urls)}  |  Found: {bot_state.total_found}")
    print(f"  Telegram: /start /stop /status /probe /urls")
    print()

# ============================================================
#  MAIN LOOP
# ============================================================

def run_monitor():
    session = requests.Session()

    print()
    print(f"  THE WEEKND - BCA PRESALE MONITOR BOT")
    print(f"  Target: {URL}")
    print(f"  Probe URLs: {len(PROBE_URLS)}")

    if TELEGRAM_BOT_TOKEN:
        print(f"  Telegram: AKTIF")
        t = threading.Thread(target=telegram_listener, daemon=True)
        t.start()
    else:
        print(f"  Telegram: OFF")

    print()
    time.sleep(1)
    log_to_file("Bot dimulai")

    probe_counter = 0

    try:
        while True:
            if not bot_state.monitoring:
                time.sleep(2)
                continue

            bot_state.cycle += 1
            probe_counter += 1

            try:
                t0 = time.time()
                soup, raw_html = fetch_page(session)
                elapsed_ms = int((time.time() - t0) * 1000)

                all_links = find_all_tiket_links(soup, raw_html)
                bot_state.last_scan = now_wib().strftime('%H:%M:%S')

                # Probe URLs setiap 10 cycle (supaya gak terlalu sering)
                probe_live = []
                if probe_counter >= 10:
                    probe_counter = 0
                    probe_live = probe_urls(session)

                print_display(all_links, probe_live, bot_state.cycle, elapsed_ms)

                # Check new links from BCA page
                new_relevant = []
                for link in all_links:
                    if link.get("relevant") and link["url"] not in bot_state.found_urls:
                        new_relevant.append(link)

                if new_relevant:
                    bot_state.total_found += len(new_relevant)
                    for l in new_relevant:
                        bot_state.found_urls.add(l["url"])
                    send_alert_all(new_relevant)
                    log_to_file(f"FOUND: {[l['url'] for l in new_relevant]}")
                    time.sleep(30)

                time.sleep(DEFAULT_INTERVAL)

            except KeyboardInterrupt:
                raise
            except requests.RequestException as e:
                print(f"  ❌ Network error: {e}")
                log_to_file(f"Network error: {e}")
                time.sleep(5)
            except Exception as e:
                print(f"  ❌ Error: {e}")
                log_to_file(f"Error: {e}")
                time.sleep(5)

    except KeyboardInterrupt:
        print(f"\n  Bot dihentikan. Total scan: {bot_state.cycle}\n")
        log_to_file(f"Bot stop setelah {bot_state.cycle} scan")
        send_telegram_all(f"⛔ Bot dihentikan. Scan: {bot_state.cycle}")

def main():
    parser = argparse.ArgumentParser(description="Bot monitor tiket.com - The Weeknd Jakarta 2026")
    parser.add_argument("--interval", "-i", type=float, default=None)
    parser.add_argument("--telegram-token", type=str, default=None)
    args = parser.parse_args()

    global DEFAULT_INTERVAL, TELEGRAM_BOT_TOKEN
    if args.interval:
        DEFAULT_INTERVAL = args.interval
    if args.telegram_token:
        TELEGRAM_BOT_TOKEN = args.telegram_token

    run_monitor()

if __name__ == "__main__":
    main()
