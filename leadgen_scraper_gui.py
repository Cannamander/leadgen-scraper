import csv
import json
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import random
from datetime import datetime

# --------------------------
# CONFIG
# --------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"
]

BLOCKLIST = [
    "google.com", "facebook.com", "instagram.com", "linkedin.com",
    "youtube.com", "tiktok.com", "apple.com", "spotify.com",
    "tripadvisor.com", "bing.com", "yelp.com", "pinterest.com",
    "wordpress", "themeforest", "wix.com", "template"
]

AGGREGATOR_DOMAINS = [
    "restaurantguru", "catchdesmoines", "tripadvisor", "yelp", "opentable",
    "zomato", "foursquare", "yellowpages", "superpages", "whitepages",
    "manta", "bbb.org", "angieslist", "homeadvisor", "thumbtack",
    "nextdoor", "facebook.com", "google.com/maps", "maps.google",
    "grubhub", "ubereats", "doordash", "seamless", "allmenus",
    "menupages", "urbanspoon", "zagat", "opentable.com"
]
EMAIL_BLACKLIST = ["font", "template", "theme", "demo", "sample"]
JUNK_NAME_WORDS = ["Menu", "Reservation", "Homepage", "Home", "Order Online"]

abort_flag = False
max_threads = 10

# --------------------------
# VALIDATION FUNCTIONS
# --------------------------
def normalize_phone(phone):
    digits = re.sub(r'\D', '', str(phone))
    return f"+1{digits}" if len(digits) == 10 else ""

def validate_email(email):
    email = email.lower().strip()
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        return None
    if any(x in email for x in EMAIL_BLACKLIST):
        return None
    return email

def clean_name(name):
    for word in JUNK_NAME_WORDS:
        name = name.replace(word, "")
    return name.strip()

def domain_from_url(url):
    return url.split("//")[-1].split("/")[0]

def unique_key(url):
    return url.split("//")[-1]

def is_junk_domain(url):
    return any(blocked in url for blocked in BLOCKLIST)

def is_aggregator_domain(url):
    """Check if URL is from an aggregator domain - should be filtered out completely"""
    domain = domain_from_url(url).lower()
    return any(agg_domain in domain for agg_domain in AGGREGATOR_DOMAINS)

def is_aggregator_page(url, title):
    """Check if a page is an aggregator listing page (for extracting sub-links)"""
    if any(domain in url for domain in AGGREGATOR_DOMAINS):
        return True
    if title and any(word in title.lower() for word in ["top", "best", "guide", "restaurants near", "list", "directory"]):
        return True
    return False

# --------------------------
# DATA EXTRACTION
# --------------------------
def extract_company_name(soup, url):
    try:
        if soup.title and soup.title.string:
            name = soup.title.string.strip()
            for sep in ["|", "-", "–"]:
                if sep in name:
                    name = name.split(sep)[0].strip()
            return clean_name(name)
        og_title = soup.find("meta", property="og:site_name")
        if og_title and og_title.get("content"):
            return clean_name(og_title["content"].strip())
    except:
        pass
    return domain_from_url(url)

def extract_emails_phones_name(url):
    emails, phones = set(), set()
    company_name = domain_from_url(url)
    page_title = ""
    external_links = 0
    try:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code == 200:
            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            page_title = soup.title.string if soup.title else ""
            company_name = extract_company_name(soup, url)

            raw_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html)
            for email in raw_emails:
                v = validate_email(email)
                if v:
                    emails.add(v)
            for a in soup.find_all('a', href=True):
                if a['href'].startswith("mailto:"):
                    v = validate_email(a['href'].replace("mailto:", ""))
                    if v:
                        emails.add(v)
                if a['href'].startswith("http"):
                    external_links += 1

            for phone in re.findall(r"\+?1?\s*\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", html):
                norm = normalize_phone(phone)
                if norm:
                    phones.add(norm)
            for a in soup.find_all('a', href=True):
                if "tel:" in a['href']:
                    norm = normalize_phone(a['href'])
                    if norm:
                        phones.add(norm)

    except:
        pass

    # Drop aggregator index page with high outbound links and no contacts
    if external_links > 10 and not emails and not phones:
        return None, set(), set(), page_title, True
    return company_name, emails, phones, page_title, False

def extract_links_from_aggregator(url):
    links = set()
    try:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith("http") and not is_junk_domain(href):
                    links.add(href)
    except:
        pass
    return links

# --------------------------
# SEARCH ENGINES
# --------------------------
def search_bing(query, max_results):
    results = []
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    page = 0
    while len(results) < max_results and page < 5:
        url = f"https://www.bing.com/search?q={query.replace(' ', '+')}&first={page * 10 + 1}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                links = [a['href'] for a in soup.select('li.b_algo h2 a') if a.get('href')]
                results += [link for link in links if link not in results]
        except:
            pass
        page += 1
        time.sleep(random.uniform(1, 2))
    return results[:max_results]

def search_duck(query, max_results):
    results = []
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    page = 0
    while len(results) < max_results and page < 5:
        url = f"https://duckduckgo.com/html/?q={query}&s={page * 50}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                links = [a['href'] for a in soup.select('a.result__a') if a.get('href')]
                results += [link for link in links if link not in results]
        except:
            pass
        page += 1
        time.sleep(random.uniform(1, 2))
    return results[:max_results]

# --------------------------
# SCRAPER CORE
# --------------------------
def crawl_url(url, keyword, raw_results, strict_mode):
    if abort_flag:
        return
    
    # Skip aggregator domains entirely - don't even crawl them
    if is_aggregator_domain(url):
        return
    
    name, emails, phones, title, drop_flag = extract_emails_phones_name(url)
    if drop_flag:
        return

    # If aggregator page detected (by title/content), fetch sub-links and crawl them
    if is_aggregator_page(url, title):
        sub_links = extract_links_from_aggregator(url)
        for sub in sub_links:
            s_name, s_emails, s_phones, _, s_drop = extract_emails_phones_name(sub)
            if s_drop:
                continue
            valid_emails = [e for e in s_emails if validate_email(e)]
            if strict_mode and (len(valid_emails) == 0 or len(s_phones) == 0):
                continue
            if valid_emails or s_phones:
                raw_results.append({
                    "Company Name": s_name,
                    "Website": sub,
                    "Email": valid_emails[0] if valid_emails else "",
                    "Additional Emails": ", ".join(valid_emails[1:]),
                    "Phone": next(iter(s_phones), ""),
                    "Source": "From Aggregator",
                    "Tags": keyword
                })
        return

    # Normal page
    valid_emails = [e for e in emails if validate_email(e)]
    if strict_mode and (len(valid_emails) == 0 or len(phones) == 0):
        return
    if valid_emails or phones:
        raw_results.append({
            "Company Name": name,
            "Website": url,
            "Email": valid_emails[0] if valid_emails else "",
            "Additional Emails": ", ".join(valid_emails[1:]),
            "Phone": next(iter(phones), ""),
            "Source": "Direct",
            "Tags": keyword
        })

# --------------------------
# MAIN SCRAPER FUNCTION
# --------------------------
def run_scraper(keyword, max_results, use_bing, use_duck, strict_mode, export_csv, export_xlsx, export_json, progress_var, log_box, output_label):
    global abort_flag
    abort_flag = False
    raw_results = []

    log_box.insert(tk.END, f"[INFO] Searching for: {keyword}\n", "info")
    urls = []
    if use_bing:
        urls += search_bing(keyword, max_results)
    if use_duck:
        urls += search_duck(keyword, max_results)

    # Filter out aggregator domains and junk domains from search results
    filtered_urls = []
    for url in urls:
        if is_aggregator_domain(url) or is_junk_domain(url):
            continue
        filtered_urls.append(url)
    
    urls = list(set(filtered_urls))
    log_box.insert(tk.END, f"[INFO] Found {len(urls)} URLs after filtering aggregators. Crawling...\n", "info")

    start_time = time.time()
    processed = 0

    def update_progress():
        progress_var.set(int((processed / len(urls)) * 100))
        log_box.yview(tk.END)

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = []
        for url in urls:
            futures.append(executor.submit(crawl_url, url, keyword, raw_results, strict_mode))
        for f in futures:
            f.result()
            processed += 1
            update_progress()

    # CLEAN + EXPORT
    cleaned = []
    seen_keys = set()
    seen_domains = set()  # Track domains to ensure one entry per domain
    for r in raw_results:
        key = unique_key(r["Website"])
        domain = domain_from_url(r["Website"]).lower()
        
        # Skip junk/aggregator domains
        if is_junk_domain(key) or is_aggregator_domain(key):
            continue
        
        # Skip if we've already seen this exact URL
        if key in seen_keys:
            continue
        
        # Skip if we've already seen this domain (one entry per domain)
        if domain in seen_domains:
            continue
        
        seen_keys.add(key)
        seen_domains.add(domain)
        cleaned.append(r)

    duration = round(time.time() - start_time, 2)

    if cleaned:
        base_name = keyword.replace(" ", "_") + "_" + datetime.now().strftime('%Y%m%d_%H%M%S')
        if export_csv:
            csv_file = f"{base_name}.csv"
            pd.DataFrame(cleaned).to_csv(csv_file, index=False, quoting=csv.QUOTE_ALL)
            log_box.insert(tk.END, f"[EXPORT] CSV saved as {csv_file}\n", "success")
        if export_xlsx:
            xlsx_file = f"{base_name}.xlsx"
            pd.DataFrame(cleaned).to_excel(xlsx_file, index=False)
            log_box.insert(tk.END, f"[EXPORT] XLSX saved as {xlsx_file}\n", "success")
        if export_json:
            json_file = f"{base_name}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=4)
            log_box.insert(tk.END, f"[EXPORT] JSON saved as {json_file}\n", "success")

        output_label.config(text=f"Export Complete: {len(cleaned)} leads in {duration}s")
    else:
        messagebox.showwarning("No Data", "No valid contacts found.")

# --------------------------
# CINEMATIC INTRO
# --------------------------
ASCII_LOGO = [
    "██╗     ███████╗ █████╗ ██████╗      ██████╗ ███████╗███╗   ██╗",
    "██║     ██╔════╝██╔══██╗██╔══██╗    ██╔════╝ ██╔════╝████╗  ██║",
    "██║     █████╗  ███████║██║  ██║    ██║  ███╗█████╗  ██╔██╗ ██║",
    "██║     ██╔══╝  ██╔══██║██║  ██║    ██║   ██║██╔══╝  ██║╚██╗██║",
    "███████╗███████╗██║  ██║██████╔╝    ╚██████╔╝███████╗██║ ╚████║",
    "╚══════╝╚══════╝╚═╝  ╚═╝╚═════╝      ╚═════╝ ╚══════╝╚═╝  ╚═══╝"
]

BOOT_LINES = [
    "[BOOT] Initializing Scraper Core... [OK]",
    "[BOOT] Engaging Multi-Thread Engine... [OK]",
    "[BOOT] Neural Network Pre-Filters Loaded... [OK]",
    "[SYSTEM ONLINE] Awaiting Orders..."
]

def animate_intro(log_box):
    def show_logo(index=0):
        if index < len(ASCII_LOGO):
            log_box.insert(tk.END, ASCII_LOGO[index] + "\n", "logo")
            log_box.yview(tk.END)
            log_box.after(80, show_logo, index + 1)
        else:
            log_box.after(150, show_boot)

    def show_boot(index=0):
        if index < len(BOOT_LINES):
            log_box.insert(tk.END, BOOT_LINES[index] + "\n", "boot")
            log_box.yview(tk.END)
            log_box.after(400, show_boot, index + 1)

    show_logo()

# --------------------------
# GUI
# --------------------------
root = tk.Tk()
root.title("CreativeDash.ai Lead Extractor v9")
root.geometry("1000x750")
root.configure(bg="#000")
root.resizable(False, False)

tk.Label(root, text="CreativeDash.ai Lead Extractor v9", fg="#00FFF7", bg="#000", font=("Courier", 24)).pack(pady=10)

# Keyword input
tk.Label(root, text="Keyword:", fg="white", bg="#000", font=("Courier", 12)).pack()
keyword_entry = tk.Entry(root, width=60, insertbackground="white", font=("Courier", 12), 
                         bg="#111", fg="gray", selectbackground="#007ACC", selectforeground="white")
placeholder_text = "Enter keyword (e.g., Restaurants in Miami)"
keyword_entry.insert(0, placeholder_text)

def on_entry_focus_in(event):
    current_text = keyword_entry.get()
    if current_text == placeholder_text:
        keyword_entry.delete(0, tk.END)
        keyword_entry.config(fg="white")
        # Select all so typing replaces it, or position cursor at start
        keyword_entry.icursor(0)
    else:
        # Ensure text is visible even if not placeholder
        keyword_entry.config(fg="white")

def on_entry_focus_out(event):
    current_text = keyword_entry.get()
    if current_text.strip() == "":
        keyword_entry.delete(0, tk.END)
        keyword_entry.insert(0, placeholder_text)
        keyword_entry.config(fg="gray")

def on_entry_key(event):
    # If placeholder is still there when user types, clear it first
    current_text = keyword_entry.get()
    if current_text == placeholder_text:
        keyword_entry.delete(0, tk.END)
    # Always ensure text color is white when typing
    keyword_entry.config(fg="white")
    # Don't prevent the key from being processed
    return None

keyword_entry.bind("<FocusIn>", on_entry_focus_in)
keyword_entry.bind("<FocusOut>", on_entry_focus_out)
keyword_entry.bind("<Key>", on_entry_key)
keyword_entry.pack(pady=5)

# Max results
tk.Label(root, text="Max Results per Engine:", fg="white", bg="#000").pack()
results_spinbox = tk.Spinbox(root, from_=10, to=100, width=6)
results_spinbox.pack(pady=5)

# Options
bing_var = tk.BooleanVar(value=True)
duck_var = tk.BooleanVar(value=True)
strict_var = tk.BooleanVar(value=False)
csv_var = tk.BooleanVar(value=True)
xlsx_var = tk.BooleanVar(value=False)
json_var = tk.BooleanVar(value=False)

tk.Checkbutton(root, text="Use Bing", variable=bing_var, fg="white", bg="#000", selectcolor="#111").pack()
tk.Checkbutton(root, text="Use DuckDuckGo", variable=duck_var, fg="white", bg="#000", selectcolor="#111").pack()
tk.Checkbutton(root, text="Strict Mode (Email AND Phone)", variable=strict_var, fg="white", bg="#000", selectcolor="#111").pack()

tk.Label(root, text="Export Formats:", fg="white", bg="#000", font=("Courier", 12)).pack(pady=5)
tk.Checkbutton(root, text="CSV", variable=csv_var, fg="white", bg="#000", selectcolor="#111").pack()
tk.Checkbutton(root, text="XLSX", variable=xlsx_var, fg="white", bg="#000", selectcolor="#111").pack()
tk.Checkbutton(root, text="JSON", variable=json_var, fg="white", bg="#000", selectcolor="#111").pack()

# Buttons
def start_scraper():
    keyword = keyword_entry.get().strip()
    # Ignore placeholder text
    if keyword == placeholder_text or keyword == "":
        messagebox.showwarning("Invalid Input", "Please enter a search keyword.")
        return
    threading.Thread(target=run_scraper, args=(
        keyword, int(results_spinbox.get()), bing_var.get(), duck_var.get(),
        strict_var.get(), csv_var.get(), xlsx_var.get(), json_var.get(),
        progress_var, log_box, output_label)).start()

button_frame = tk.Frame(root, bg="#000")
button_frame.pack(pady=15)
start_btn = tk.Button(button_frame, text="START SCRAPER", command=start_scraper,
    bg="#007ACC", fg="white", width=20, font=("Courier", 12))
start_btn.grid(row=0, column=0, padx=10)

progress_var = tk.IntVar()
progress_bar = ttk.Progressbar(root, orient="horizontal", length=600, mode="determinate", variable=progress_var)
progress_bar.pack(pady=10)

log_box = tk.Text(root, width=120, height=20, bg="#111", fg="white", insertbackground="white", font=("Courier", 10))
log_box.tag_config("logo", foreground="#00FFF7")
log_box.tag_config("boot", foreground="#FFD700")
log_box.tag_config("info", foreground="#00FFF7")
log_box.tag_config("success", foreground="#00FF00")
log_box.pack(pady=10)

output_label = tk.Label(root, text="", fg="white", bg="#000", font=("Courier", 10))
output_label.pack(pady=5)

footer = tk.Label(root, text="© CreativeDash.ai | Proprietary Tool", fg="#666", bg="#000", font=("Courier", 10))
footer.pack(side="bottom", pady=10)

animate_intro(log_box)
root.mainloop()

