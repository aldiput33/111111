#!/usr/bin/env python3
"""
Bot monitor hidden link tiket The Weeknd Jakarta 2026
Target: https://promo.bca.co.id/id/the-weeknd

Mencari link yang mengarah ke penjualan di tiket.com

Cara pakai:
    pip install requests beautifulsoup4
    python weeknd_bca_bot.py
    python weeknd_bca_bot.py --no-auto-open
"""

import os
import sys
import time
import json
import re
import argparse
import webbrowser
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

# Keyword untuk mendeteksi link tiket.com
TIKET_KEYWORDS = [
    "tiket.com",
    "m.tiket.com",
    "www.tiket.com",
    "tiket.com/to-do",
    "tiket.com/id-id/to-do",
    "tiket.com/en-id/to-do",
    "tiket.com/event",
    "theweekndinjakarta",
]

# URL pattern yang dicari (regex)
TIKET_PATTERNS = [
    r'https?://(?:www\.|m\.)?tiket\.com[^\s"\'<>\)]*',
    r'https?://[^\s"\'<>\)]*tiket\.com[^\s"\'<>\)]*',
]

# Pattern spesifik link presale The Weeknd Jakarta (berdasarkan link hari ini)
# Format: tiket.com/id-id/to-do/theweekndinjakarta-{type}
WEEKND_TIKET_PATTERNS = [
    r'https?://(?:www\.|m\.)?tiket\.com/(?:id-id|en-id)/to-do/theweekndinjakarta[^\s"\'<>\)]*',
    r'https?://(?:www\.|m\.)?tiket\.com/(?:id-id|en-id)/to-do/[^\s"\'<>\)]*weeknd[^\s"\'<>\)]*',
    r'https?://(?:www\.|m\.)?tiket\.com/to-do/theweekndinjakarta[^\s"\'<>\)]*',
    r'https?://(?:www\.|m\.)?tiket\.com/to-do/[^\s"\'<>\)]*weeknd[^\s"\'<>\)]*',
]

# Contoh link presale hari ini (18 May 2026):
# https://www.tiket.com/id-id/to-do/theweekndinjakarta-artistpresaleday1?utm_page=toDoSearchResult&queueittoken=...

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
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    BG_RED  = "\033[41m"
    BG_GRN  = "\033[42m"

# ============================================================
#  HELPER
# ============================================================

def now_wib():
    return datetime.now(WIB)

def fmt_countdown(seconds):
    if seconds <= 0:
        return "LIVE!"
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if d > 0:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"

def log_to_file(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{now_wib().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

def is_tiket_url(url):
    """Cek apakah URL mengarah ke tiket.com"""
    return bool(re.search(r'tiket\.com', url, re.IGNORECASE))

def is_relevant_tiket_url(url):
    """Filter URL tiket.com yang relevan (bukan generic homepage / flight / hotel)"""
    url_lower = url.lower()
    # Exclude generic pages
    excludes = [
        "tiket.com/flights",
        "tiket.com/hotel",
        "tiket.com/kereta",
        "tiket.com/bus",
        "tiket.com/car-rental",
        "tiket.com/airport",
        "tiket.com/xperience",
        "tiket.com/mobile-apps",
        "tiket.com/en-id/flights",
        "tiket.com/en-id/hotel",
        "tiket.com/en-my/flights",
        "tiket.com/en-us/flights",
        "tiket.com/en-sg/flights",
        "tiket.com/en-th/flights",
        "tiket.com/destination",
    ]
    for ex in excludes:
        if ex in url_lower:
            return False

    # Plain homepage, skip
    if re.match(r'https?://(?:www\.|m\.)?tiket\.com/?(\?.*)?$', url):
        return False
    if re.match(r'https?://(?:www\.|m\.)?tiket\.com/(?:id-id|en-id|en-my|en-sg|en-th|en-us)/?(\?.*)?$', url):
        return False

    # HIGH PRIORITY: link spesifik The Weeknd Jakarta
    high_priority = [
        "theweekndinjakarta",
        "weeknd",
        "the-weeknd",
        "artistpresale",
        "presale",
        "queueittoken",
    ]
    if any(kw in url_lower for kw in high_priority):
        return True

    # Include if it has event-related patterns
    includes = [
        "to-do",
        "/event/",
        "concert",
        "after-hours",
    ]
    if any(inc in url_lower for inc in includes):
        return True

    # Also include any tiket.com/to-do/* or /id-id/to-do/* link (event tickets)
    if "/to-do/" in url_lower:
        return True

    # Any other tiket.com link on a concert promo page is suspicious/relevant
    return True

def is_weeknd_presale_url(url):
    """Cek apakah URL adalah link presale The Weeknd Jakarta (high priority)"""
    url_lower = url.lower()
    # Check specific patterns based on actual link format:
    # tiket.com/id-id/to-do/theweekndinjakarta-artistpresaleday1
    # tiket.com/id-id/to-do/theweekndinjakarta-bcapresaleday1
    # tiket.com/id-id/to-do/theweekndinjakarta-generalsaleday1
    if "theweekndinjakarta" in url_lower:
        return True
    if "weeknd" in url_lower and ("presale" in url_lower or "to-do" in url_lower):
        return True
    if "weeknd" in url_lower and "tiket.com" in url_lower:
        return True
    # Queue-it token on tiket.com likely means active sale page
    if "queueittoken" in url_lower and "tiket.com" in url_lower:
        return True
    return False

# ============================================================
#  FETCH & PARSE
# ============================================================

def fetch_page(session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://promo.bca.co.id/",
        "sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
    }
    resp = session.get(URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser"), resp.text

def extract_page_info(soup):
    """Extract info dasar dari halaman BCA promo."""
    info = {
        "title": "",
        "description": "",
        "promo_period": "",
    }

    # Title
    title_el = soup.find("h1") or soup.find("title")
    if title_el:
        info["title"] = title_el.get_text(strip=True)

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        info["description"] = meta_desc.get("content", "")[:100]

    # Promo period - look for date patterns
    for el in soup.find_all(["p", "span", "div"]):
        text = el.get_text(strip=True)
        if re.search(r'\d{1,2}\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', text, re.IGNORECASE):
            if "periode" in text.lower() or "valid" in text.lower() or "berlaku" in text.lower():
                info["promo_period"] = text[:80]
                break

    return info

def extract_visible_links(soup):
    """Extract semua visible links yang mengarah ke tiket.com."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if is_tiket_url(href):
            text = a.get_text(strip=True) or "[no text]"
            relevant = is_relevant_tiket_url(href)
            priority = is_weeknd_presale_url(href)
            links.append({
                "type": "*** PRESALE WEEKND ***" if priority else "VISIBLE LINK",
                "text": text,
                "url": href,
                "relevant": relevant,
                "priority": priority,
            })
    return links

def extract_buttons(soup):
    """Extract buttons/CTA yang mungkin mengarah ke tiket.com."""
    buttons = []
    # Button elements with onclick or data attributes
    for btn in soup.find_all(["button", "a"], class_=re.compile(r'btn|button|cta', re.IGNORECASE)):
        href = btn.get("href", "")
        onclick = btn.get("onclick", "")
        data_href = btn.get("data-href", "") or btn.get("data-url", "") or btn.get("data-link", "")
        text = btn.get_text(strip=True)

        target_url = ""
        if href and is_tiket_url(href):
            target_url = href
        elif onclick and is_tiket_url(onclick):
            urls = re.findall(r'https?://[^\s"\'<>\)]+', onclick)
            for u in urls:
                if is_tiket_url(u):
                    target_url = u
                    break
        elif data_href and is_tiket_url(data_href):
            target_url = data_href

        if target_url:
            buttons.append({
                "type": "BUTTON/CTA",
                "text": text or "[button]",
                "url": target_url,
                "relevant": is_relevant_tiket_url(target_url),
            })

    return buttons

def find_hidden_links(soup, raw_html):
    """Cari hidden links / URL baru yang mengarah ke tiket.com."""
    found = []

    # 1. CSS hidden elements (display:none, visibility:hidden, opacity:0)
    for el in soup.find_all(style=re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0')):
        for u in re.findall(r'https?://[^\s"\'<>\)]+', str(el)):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                found.append({"type": "HIDDEN CSS", "text": el.get_text(strip=True)[:50], "url": u})

    # 2. HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        for u in re.findall(r'https?://[^\s"\'<>\)]+', comment):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                found.append({"type": "HTML COMMENT", "text": "", "url": u})

    # 3. Data attributes with tiket.com URLs
    for el in soup.find_all(True):
        for attr, val in el.attrs.items():
            if isinstance(val, str) and is_tiket_url(val):
                urls = re.findall(r'https?://[^\s"\'<>\)]+', val)
                for u in urls:
                    if is_tiket_url(u) and is_relevant_tiket_url(u):
                        found.append({"type": f"DATA-ATTR ({attr})", "text": el.get_text(strip=True)[:30], "url": u})

    # 4. Inline/embedded JavaScript
    for script in soup.find_all("script"):
        content = script.string or ""
        # Normal URLs
        for u in re.findall(r'https?://[^\s"\'<>\)\\]+', content):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                link_type = "JAVASCRIPT"
                if is_weeknd_presale_url(u):
                    link_type = "*** PRESALE WEEKND (JS) ***"
                found.append({"type": link_type, "text": "", "url": u})
        # Escaped URLs in JS (e.g., https:\/\/www.tiket.com\/...)
        for u in re.findall(r'https?:\\/\\/[^\s"\'<>\)]+', content):
            unescaped = u.replace("\\/", "/")
            if is_tiket_url(unescaped) and is_relevant_tiket_url(unescaped):
                link_type = "JAVASCRIPT (escaped)"
                if is_weeknd_presale_url(unescaped):
                    link_type = "*** PRESALE WEEKND (JS) ***"
                found.append({"type": link_type, "text": "", "url": unescaped})

    # 5. JSON-LD / structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            json_str = json.dumps(data)
            for u in re.findall(r'https?://[^\s"\'<>\)\\]+', json_str):
                if is_tiket_url(u) and is_relevant_tiket_url(u):
                    found.append({"type": "JSON-LD", "text": "", "url": u})
        except Exception:
            pass

    # 6. Next.js / React hydration data (__NEXT_DATA__, __NUXT__, etc.)
    for script in soup.find_all("script", id=re.compile(r'__NEXT|__NUXT|__APP')):
        content = script.string or ""
        for u in re.findall(r'https?://[^\s"\'<>\)\\]+', content):
            if is_tiket_url(u) and is_relevant_tiket_url(u):
                found.append({"type": "HYDRATION DATA", "text": "", "url": u})

    # 7. All raw URLs in HTML source not already in visible <a> tags
    visible_hrefs = set()
    for a in soup.find_all("a", href=True):
        visible_hrefs.add(a["href"].strip())

    # Search with general tiket patterns
    for pattern in TIKET_PATTERNS:
        for u in set(re.findall(pattern, raw_html)):
            clean = u.rstrip(".,;:\"')")
            if clean not in visible_hrefs and is_relevant_tiket_url(clean):
                if not any(f["url"] == clean for f in found):
                    link_type = "URL BARU (raw HTML)"
                    if is_weeknd_presale_url(clean):
                        link_type = "*** PRESALE WEEKND ***"
                    found.append({"type": link_type, "text": "", "url": clean})

    # Search with weeknd-specific patterns (high priority)
    for pattern in WEEKND_TIKET_PATTERNS:
        for u in set(re.findall(pattern, raw_html)):
            clean = u.rstrip(".,;:\"')")
            if not any(f["url"] == clean for f in found):
                found.append({"type": "*** PRESALE WEEKND ***", "text": "", "url": clean})

    # 8. iframe src
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if is_tiket_url(src):
            found.append({"type": "IFRAME", "text": "", "url": src})

    # 9. Meta refresh / redirect
    for meta in soup.find_all("meta", attrs={"http-equiv": "refresh"}):
        content = meta.get("content", "")
        urls = re.findall(r'url=([^\s"\']+)', content, re.IGNORECASE)
        for u in urls:
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
    """Gabungkan semua metode pencarian link tiket.com."""
    all_links = []

    # Visible links
    visible = extract_visible_links(soup)
    all_links.extend(visible)

    # Buttons/CTA
    buttons = extract_buttons(soup)
    all_links.extend(buttons)

    # Hidden links
    hidden = find_hidden_links(soup, raw_html)
    all_links.extend(hidden)

    return all_links

# ============================================================
#  TAMPILAN TERMINAL
# ============================================================

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def ln(text=""):
    print(f"  {text}")

def print_display(page_info, all_links, hidden_links, cycle, interval, elapsed_ms, status_code):
    current = now_wib()
    clear_screen()

    print()
    ln(f"{C.CYAN}{C.BOLD}+======================================================+{C.RESET}")
    ln(f"{C.CYAN}{C.BOLD}|   THE WEEKND - BCA PROMO TIKET.COM LINK MONITOR      |{C.RESET}")
    ln(f"{C.CYAN}{C.BOLD}|   Target: promo.bca.co.id/id/the-weeknd              |{C.RESET}")
    ln(f"{C.CYAN}{C.BOLD}+======================================================+{C.RESET}")
    print()

    # Info
    ln(f"{C.WHITE}  Waktu    : {C.BOLD}{current.strftime('%d %b %Y  %H:%M:%S WIB')}{C.RESET}")
    ln(f"{C.DIM}  Scan #   : {cycle}    Interval: {interval}s    Response: {elapsed_ms}ms    HTTP: {status_code}{C.RESET}")
    print()

    # Page Info
    if page_info["title"]:
        ln(f"{C.WHITE}{C.BOLD}  {page_info['title'][:60]}{C.RESET}")
    if page_info["description"]:
        ln(f"{C.DIM}  {page_info['description'][:70]}{C.RESET}")
    if page_info["promo_period"]:
        ln(f"{C.YELLOW}  {page_info['promo_period']}{C.RESET}")
    print()

    # ── Visible tiket.com Links ──
    visible = [l for l in all_links if "VISIBLE" in l["type"] or "PRESALE" in l["type"]]
    priority = [l for l in all_links if l.get("priority") or "PRESALE" in l["type"]]
    ln(f"{C.WHITE}{C.BOLD}  VISIBLE TIKET.COM LINKS ({len(visible)}){C.RESET}")
    ln(f"{C.DIM}  {'─' * 52}{C.RESET}")

    # Show priority links first
    if priority:
        for link in priority:
            ln(f"{C.BG_GRN}{C.BOLD}{C.WHITE}    >>> PRESALE LINK! {link['text'][:30]}{C.RESET}")
            ln(f"{C.GREEN}{C.BOLD}       {link['url'][:80]}{C.RESET}")
            print()

    # Then other visible links
    other_visible = [l for l in visible if not l.get("priority") and "PRESALE" not in l["type"]]
    if other_visible:
        for link in other_visible:
            relevance = f"{C.GREEN}[RELEVANT]" if link.get("relevant") else f"{C.DIM}[generic]"
            ln(f"{C.GREEN}    >> {link['text'][:40]}{C.RESET}")
            ln(f"{C.GREEN}       {link['url'][:70]}{C.RESET}")
            ln(f"       {relevance}{C.RESET}")
            print()
    elif not priority:
        ln(f"{C.DIM}    Belum ada visible link ke tiket.com...{C.RESET}")
        print()

    # ── Buttons/CTA ──
    buttons = [l for l in all_links if l["type"] == "BUTTON/CTA"]
    if buttons:
        ln(f"{C.YELLOW}{C.BOLD}  BUTTONS / CTA ({len(buttons)}){C.RESET}")
        ln(f"{C.DIM}  {'─' * 52}{C.RESET}")
        for link in buttons:
            ln(f"{C.YELLOW}    >> [{link['text'][:30]}]{C.RESET}")
            ln(f"{C.YELLOW}       {link['url'][:70]}{C.RESET}")
            print()

    # ── Hidden Links ──
    if hidden_links:
        ln(f"{C.BG_GRN}{C.BOLD}{C.WHITE}  !!! HIDDEN TIKET.COM LINK DITEMUKAN !!!  {C.RESET}")
        ln(f"{C.DIM}  {'─' * 52}{C.RESET}")
        for h in hidden_links:
            ln(f"{C.GREEN}{C.BOLD}    >> [{h['type']}] {h.get('text','')}{C.RESET}")
            ln(f"{C.GREEN}{C.BOLD}       {h['url']}{C.RESET}")
            print()
    else:
        ln(f"{C.WHITE}{C.BOLD}  HIDDEN LINKS{C.RESET}")
        ln(f"{C.DIM}  {'─' * 52}{C.RESET}")
        ln(f"{C.DIM}    Belum ada hidden link terdeteksi...{C.RESET}")
        print()

    # Summary
    total = len(all_links)
    relevant = len([l for l in all_links if l.get("relevant")])
    ln(f"{C.DIM}  Total links: {total}  |  Relevant: {relevant}  |  Hidden: {len(hidden_links)}{C.RESET}")
    ln(f"{C.DIM}  Log: {LOG_FILE}  |  Tekan Ctrl+C untuk stop{C.RESET}")
    print()

# ============================================================
#  NOTIFY
# ============================================================

def notify_user(links, auto_open):
    print()
    for _ in range(2):
        ln(f"{C.BG_RED}{C.BOLD}{C.WHITE}{'':^54}{C.RESET}")
    ln(f"{C.BG_RED}{C.BOLD}{C.WHITE}{'!!! LINK TIKET.COM DITEMUKAN !!!':^54}{C.RESET}")
    for _ in range(2):
        ln(f"{C.BG_RED}{C.BOLD}{C.WHITE}{'':^54}{C.RESET}")
    print()

    # Sort: presale links first
    presale = [l for l in links if l.get("priority") or "PRESALE" in l.get("type", "")]
    others = [l for l in links if l not in presale]

    if presale:
        ln(f"{C.BG_GRN}{C.BOLD}{C.WHITE}  === PRESALE WEEKND LINK === {C.RESET}")
        for link in presale:
            t = link.get("text", "")
            ln(f"{C.GREEN}{C.BOLD}  >> [{link['type']}] {t}{C.RESET}")
            ln(f"{C.GREEN}{C.BOLD}     {link['url']}{C.RESET}")
        print()

    for link in others:
        t = link.get("text", "")
        ln(f"{C.GREEN}{C.BOLD}  >> [{link['type']}] {t}{C.RESET}")
        ln(f"{C.GREEN}{C.BOLD}     {link['url']}{C.RESET}")
    print()
    print("\a" * 5)

    # Save to file
    with open(FOUND_LINKS_FILE, "w") as f:
        json.dump({"found_at": now_wib().isoformat(), "links": links}, f, indent=2)
    log_to_file(f"LINK TIKET.COM DITEMUKAN: {json.dumps(links)}")

    if auto_open:
        # Open presale links first
        for link in (presale + others):
            url = link["url"]
            if url.startswith("http"):
                try:
                    webbrowser.open(url)
                except Exception:
                    pass

# ============================================================
#  MAIN LOOP
# ============================================================

def run_monitor(auto_open=True):
    session = requests.Session()
    previously_found = set()
    cycle = 0

    clear_screen()
    print()
    ln(f"{C.CYAN}{C.BOLD}+======================================================+{C.RESET}")
    ln(f"{C.CYAN}{C.BOLD}|   THE WEEKND - BCA x TIKET.COM LINK MONITOR BOT      |{C.RESET}")
    ln(f"{C.CYAN}{C.BOLD}+======================================================+{C.RESET}")
    print()
    ln(f"{C.CYAN}  Memulai monitoring...{C.RESET}")
    ln(f"{C.DIM}  Target : {URL}{C.RESET}")
    ln(f"{C.DIM}  Mencari: Link ke tiket.com (presale / pembelian tiket){C.RESET}")
    ln(f"{C.DIM}  Log    : {LOG_FILE}{C.RESET}")
    print()
    time.sleep(1)
    log_to_file(f"Bot dimulai - monitoring {URL} untuk link tiket.com")

    try:
        while True:
            cycle += 1
            interval = DEFAULT_INTERVAL
            try:
                t0 = time.time()
                soup, raw_html = fetch_page(session)
                elapsed_ms = int((time.time() - t0) * 1000)

                page_info = extract_page_info(soup)
                all_links = find_all_tiket_links(soup, raw_html)
                hidden_links = find_hidden_links(soup, raw_html)

                # Get HTTP status (already raised for errors, so it's 200)
                status_code = 200

                print_display(page_info, all_links, hidden_links, cycle, interval, elapsed_ms, status_code)

                # Log summary
                visible_count = len([l for l in all_links if l["type"] == "VISIBLE LINK"])
                log_to_file(f"#{cycle} | Visible: {visible_count} | Hidden: {len(hidden_links)} | Total: {len(all_links)}")

                # Check for new relevant links
                new_relevant = []
                for link in all_links:
                    if link.get("relevant") and link["url"] not in previously_found:
                        new_relevant.append(link)

                if new_relevant:
                    notify_user(new_relevant, auto_open)
                    for l in new_relevant:
                        previously_found.add(l["url"])
                    time.sleep(30)

                time.sleep(interval)

            except KeyboardInterrupt:
                raise
            except requests.RequestException as e:
                clear_screen()
                ln(f"\n{C.RED}  Network error: {e}{C.RESET}")
                ln(f"{C.DIM}  Retry dalam 5 detik...{C.RESET}\n")
                log_to_file(f"Network error: {e}")
                time.sleep(5)
            except Exception as e:
                clear_screen()
                ln(f"\n{C.RED}  Error: {e}{C.RESET}")
                ln(f"{C.DIM}  Retry dalam 5 detik...{C.RESET}\n")
                log_to_file(f"Error: {e}")
                time.sleep(5)

    except KeyboardInterrupt:
        print(f"\n\n  {C.YELLOW}{C.BOLD}Bot dihentikan.{C.RESET}")
        print(f"  {C.DIM}Total scan  : {cycle}{C.RESET}")
        print(f"  {C.DIM}Log tersimpan: {LOG_FILE}{C.RESET}\n")
        log_to_file(f"Bot dihentikan setelah {cycle} scan")

def main():
    parser = argparse.ArgumentParser(description="Bot monitor link tiket.com di halaman BCA promo The Weeknd Jakarta 2026")
    parser.add_argument("--interval", "-i", type=float, default=None, help="Override interval polling (detik)")
    parser.add_argument("--no-auto-open", action="store_true", help="Jangan auto-buka browser saat link ditemukan")
    args = parser.parse_args()

    if args.interval:
        global DEFAULT_INTERVAL
        DEFAULT_INTERVAL = args.interval

    run_monitor(auto_open=not args.no_auto_open)

if __name__ == "__main__":
    main()
