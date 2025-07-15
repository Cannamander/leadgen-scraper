import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import requests
from bs4 import BeautifulSoup
import re
import csv
import threading
from urllib.parse import urlparse, parse_qs, unquote, urljoin
import logging

# Configure logging
logging.basicConfig(
    filename="scraper.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

HEADERS = {"User-Agent": "Mozilla/5.0"}
MAX_SUBPAGES = 5

AGGREGATORS = [
    "yelp.com", "tripadvisor.com", "opentable.com", "zomato.com",
    "restaurantobserver.com", "la.eater.com", "visitlongbeach.com", "tastingtable.com"
]

EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
PHONE_REGEX = r"(\+?\d[\d\s\-\(\)]{7,}\d)"
SOCIAL_REGEX = {
    "facebook": r"https?://(www\.)?facebook\.com/[a-zA-Z0-9._-]+",
    "instagram": r"https?://(www\.)?instagram\.com/[a-zA-Z0-9._-]+"
}

# Utility: Normalize emails like info [at] site.com
def normalize_email(email):
    return email.replace("[at]", "@").replace("(at)", "@").replace(" at ", "@")

def extract_info_from_url(url, extra_paths=None):
    """Scrape a single page and optional subpages for emails, phones, socials."""
    visited = set()
    data = {"URL": url, "Business Name": "", "Emails": "", "Phone": "", "Facebook": "", "Instagram": ""}
    queue = [url] + [urljoin(url, path) for path in (extra_paths or [])]

    while queue and len(visited) < MAX_SUBPAGES:
        target = queue.pop(0)
        if target in visited:
            continue
        visited.add(target)
        try:
            html = requests.get(target, headers=HEADERS, timeout=8).text
        except:
            continue

        soup = BeautifulSoup(html, "html.parser")
        if not data["Business Name"] and soup.title:
            data["Business Name"] = soup.title.get_text(strip=True)

        emails = [normalize_email(e) for e in re.findall(EMAIL_REGEX, html)]
        phones = re.findall(PHONE_REGEX, html)
        if emails: data["Emails"] += ", " + ", ".join(set(emails))
        if phones: data["Phone"] += ", " + ", ".join(set(phones))

        for key, pattern in SOCIAL_REGEX.items():
            links = re.findall(pattern, html)
            if links:
                data[key.capitalize()] += ", " + ", ".join(set(links))

    # Deduplicate fields
    for key in ["Emails", "Phone", "Facebook", "Instagram"]:
        data[key] = ", ".join(set(filter(None, [x.strip() for x in data[key].split(",")])))

    return data

def scrape_duckduckgo(query, pages=5):
    """Scrape DuckDuckGo and decode uddg links."""
    links = []
    for page in range(pages):
        search_url = f"https://duckduckgo.com/html/?q={query}&s={page*50}"
        r = requests.get(search_url, headers=HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")

        raw_links = soup.select("a.result__a")
        for a in raw_links:
            href = a.get("href")
            if href.startswith("/l/?uddg="):
                parsed = parse_qs(urlparse(href).query)
                if "uddg" in parsed:
                    real_url = unquote(parsed["uddg"][0])
                    links.append(real_url)
            elif href.startswith("http"):
                links.append(href)

    return list(set(links))

def scrape_bing(query, pages=5):
    """Scrape Bing with count=50 for more results."""
    links = []
    for page in range(pages):
        offset = page * 50 + 1
        search_url = f"https://www.bing.com/search?q={query}&first={offset}&count=50"
        r = requests.get(search_url, headers=HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("li.b_algo h2 a"):
            href = a.get("href")
            if href and href.startswith("http"):
                links.append(href)

    return list(set(links))

def is_aggregator(url):
    return any(domain in urlparse(url).netloc for domain in AGGREGATORS)

def extract_external_links(html, base_domain):
    """Find external links inside aggregator pages."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and base_domain not in href:
            if not is_aggregator(href):
                found.append(href)
    return list(set(found))

def handle_aggregator(url):
    """Crawl aggregator and extract external business links."""
    try:
        html = requests.get(url, headers=HEADERS, timeout=10).text
    except:
        return []
    base_domain = urlparse(url).netloc
    return extract_external_links(html, base_domain)

def scrape_pages(query, results_box, progress_bar):
    results = []
    all_links = []

    # DuckDuckGo Phase
    results_box.insert(tk.END, "[DuckDuckGo] Searching...\n")
    logging.info(f"Searching DuckDuckGo for {query}")
    duck_links = scrape_duckduckgo(query)
    results_box.insert(tk.END, f"[DuckDuckGo] Found {len(duck_links)} links\n")
    logging.info(f"[Duck] Found {len(duck_links)} links")

    # Bing fallback if Duck is empty
    if len(duck_links) == 0:
        results_box.insert(tk.END, "[Duck] 0 links → Using Bing fallback...\n")
    bing_links = scrape_bing(query)
    results_box.insert(tk.END, f"[Bing] Found {len(bing_links)} links\n")
    logging.info(f"[Bing] Found {len(bing_links)} links")

    all_links = list(set(duck_links + bing_links))

    results_box.insert(tk.END, f"[Combined] Total unique links: {len(all_links)}\n")
    progress_bar["maximum"] = len(all_links)
    progress_bar["value"] = 0

    for idx, link in enumerate(all_links):
        source = "Aggregator" if is_aggregator(link) else "Direct"
        if is_aggregator(link):
            results_box.insert(tk.END, f"[Aggregator] {link} → Extracting external URLs...\n")
            logging.info(f"Aggregator detected: {link}")
            extra_links = handle_aggregator(link)
            all_links.extend(extra_links)

        else:
            data = extract_info_from_url(link, extra_paths=["/contact", "/about", "/menu", "/info"])
            data["Source"] = source
            results.append(data)

        results_box.insert(tk.END, f"Scraped: {link}\n")
        results_box.see(tk.END)
        progress_bar["value"] = idx + 1

    # Save results
    file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
    if file_path:
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["Business Name", "URL", "Emails", "Phone", "Facebook", "Instagram", "Source"])
            writer.writeheader()
            for row in results:
                writer.writerow(row)

    results_box.insert(tk.END, f"\nScraping Complete. {len(results)} businesses saved.\n")

def start_scrape(query_entry, results_box, progress_bar):
    query = query_entry.get().strip()
    if not query:
        messagebox.showwarning("Input Error", "Enter a search query.")
        return
    results_box.insert(tk.END, f"Starting scrape for: {query}\n")
    threading.Thread(target=scrape_pages, args=(query, results_box, progress_bar), daemon=True).start()

# Dark UI
def apply_dark_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    dark_bg = "#1e1e1e"
    light_fg = "#d4d4d4"
    accent = "#007acc"
    root.configure(bg=dark_bg)
    style.configure(".", background=dark_bg, foreground=light_fg, fieldbackground=dark_bg)
    style.configure("TLabel", background=dark_bg, foreground=light_fg)
    style.configure("TButton", background=accent, foreground="white", relief="flat", padding=6)
    style.map("TButton", background=[("active", "#005f99")])
    style.configure("TEntry", fieldbackground="#252526", foreground=light_fg)
    style.configure("Horizontal.TProgressbar", troughcolor="#252526", background=accent)

def launch_gui():
    root = tk.Tk()
    root.title("LeadGen Scraper Pro")
    root.geometry("850x600")
    apply_dark_theme(root)

    main = ttk.Frame(root, padding="10")
    main.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    ttk.Label(main, text="Search Query:", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky=tk.W, pady=5)
    query_entry = ttk.Entry(main, width=60)
    query_entry.grid(row=0, column=1, padx=5, pady=5)
    query_entry.insert(0, "restaurants in Long Beach site:.com")

    results_box = tk.Text(main, height=20, width=90, bg="#1e1e1e", fg="#d4d4d4", insertbackground="white")
    results_box.grid(row=2, column=0, columnspan=2, pady=10)

    progress_bar = ttk.Progressbar(main, orient="horizontal", length=500, mode="determinate")
    progress_bar.grid(row=3, column=0, columnspan=2, pady=5)

    ttk.Button(main, text="Start Scraping", command=lambda: start_scrape(query_entry, results_box, progress_bar)).grid(row=1, column=0, columnspan=2, pady=10)

    root.mainloop()

if __name__ == "__main__":
    launch_gui()
