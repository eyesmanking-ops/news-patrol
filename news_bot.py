# -*- coding: utf-8 -*-
import time, random, os, sys, requests, feedparser, urllib3, json
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HISTORY_FILE = "last_run_time.txt"

def get_last_run_time():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try: return datetime.strptime(f.read().strip(), "%Y-%m-%d %H:%M:%S")
            except: pass
    return datetime.now() - timedelta(hours=2)

def save_current_run_time(latest_time):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write(latest_time.strftime("%Y-%m-%d %H:%M:%S"))

from concurrent.futures import ThreadPoolExecutor

def fetch_single_channel(name, base_url, max_pages, start_time, driver_path):
    res = []; seen = set()
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    driver = webdriver.Chrome(service=Service(driver_path), options=options)
    
    buffer_pages = 3 
    stop_count = 0
    
    try:
        sep = "&" if "?" in base_url else "?"
        for page in range(1, max_pages + 1):
            driver.get(f"{base_url}{sep}page={page}")
            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            items = soup.select('ul.vertical-list > li, .article-list .col, .list-group li')
            if not items: break

            found_new_in_this_page = False
            for art in items:
                t_tag = art.select_one('.title a, h3.title a, h4.title a')
                d_tag = art.select_one('time, .date')
                if not t_tag or not d_tag: continue
                
                url = t_tag.get('href', '')
                if not url.startswith('http'): url = "https://www.chinatimes.com" + url
                
                raw_time = d_tag.get('datetime') or d_tag.text.strip()
                try:
                    clean_time = raw_time.replace('T', ' ').replace('/', '-').strip()[:16]
                    if clean_time[2] == ':' and '-' in clean_time:
                        parts = clean_time.split(' ')
                        clean_time = f"{parts[1]} {parts[0]}"
                    dt = datetime.strptime(clean_time, "%Y-%m-%d %H:%M")
                    if dt >= start_time:
                        if url not in seen:
                            res.append((dt, t_tag.text.strip(), url))
                            seen.add(url)
                            found_new_in_this_page = True
                except: continue
            
            if not found_new_in_this_page:
                stop_count += 1
                if stop_count >= buffer_pages: break
            else:
                stop_count = 0
    finally:
        driver.quit()
    return res

def fetch_chinatimes_paged(start_time):
    all_res = []; seen = set()
    targets = [("即時", "https://www.chinatimes.com/realtimenews/?chdtv", 10)]
    driver_path = ChromeDriverManager().install() 
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = [executor.submit(fetch_single_channel, t[0], t[1], t[2], start_time, driver_path) for t in targets]
        for future in futures:
            for item in future.result():
                if item[2] not in seen:
                    all_res.append(item); seen.add(item[2])
    all_res.sort(key=lambda x: x[0], reverse=True)
    return all_res

def fetch_cna(start_time):
    res = []
    for p in range(1, 3):
        try:
            resp = requests.get(f"https://www.cna.com.tw/list/aall.aspx?page={p}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')
            for art in soup.select('#jsMainList li'):
                link_tag = art.select_one('a'); t_tag = art.select_one('.date'); title_tag = art.select_one('h2')
                if t_tag and title_tag:
                    dt = datetime.strptime(t_tag.text.strip().replace('/', '-'), "%Y-%m-%d %H:%M")
                    if dt >= start_time:
                        url = "https://www.cna.com.tw" + link_tag['href']
                        res.append((dt, title_tag.text.strip(), url))
        except: break
    return res

def fetch_ltn(start_time):
    res = []; seen = set()
    for ch in ["all"]:
        try:
            feed = feedparser.parse(f"https://news.ltn.com.tw/rss/{ch}.xml")
            for e in feed.entries:
                dt = datetime(*(e.published_parsed[0:6])) + timedelta(hours=8)
                if dt >= start_time and e.link not in seen:
                    seen.add(e.link); res.append((dt, e.title, e.link))
                elif dt < start_time: break
        except: continue
    return res

def fetch_udn(start_time):
    res = []
    for p in range(1, 5):
        try:
            resp = requests.get(f"https://udn.com/news/breaknews/1/0/{p}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')
            for art in soup.select('.story-list__text'):
                title_tag = art.find('a'); time_tag = art.find('time')
                if title_tag and time_tag:
                    t_str = time_tag.text.strip()
                    if len(t_str) <= 11: t_str = f"{datetime.now().year}-{t_str}"
                    dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M")
                    if dt >= start_time:
                        url = title_tag['href'] if title_tag['href'].startswith('http') else "https://udn.com"+title_tag['href']
                        res.append((dt, title_tag.text.strip(), url))
                    else: return res
        except: break
    return res

def main():
    last_run_ts = get_last_run_time()
    buffer_start_ts = last_run_ts - timedelta(minutes=10)
    
    all_data = {
        "中時新聞網": fetch_chinatimes_paged(buffer_start_ts),
        "中央通訊社": fetch_cna(buffer_start_ts),
        "自由時報": fetch_ltn(buffer_start_ts),
        "聯合新聞網": fetch_udn(buffer_start_ts)
    }
    
    total = sum(len(v) for v in all_data.values())
    if total > 0:
        now_str = datetime.now().strftime('%Y%m%d_%H%M')
        html_content = f"<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'></head><body><h1>新聞摘要 {now_str}</h1>"
        
        new_latest_ts = last_run_ts
        for media, items in all_data.items():
            html_content += f"<h2>{media} ({len(items)})</h2><ul>"
            if items:
                items.sort(key=lambda x: x[0], reverse=True)
                if items[0][0] > new_latest_ts: new_latest_ts = items[0][0]
                for dt, title, url in items:
                    html_content += f"<li>[{dt.strftime('%H:%M')}] <a href='{url}'>{title}</a></li>"
            html_content += "</ul>"
        
        file_name = f"index.html" # 固定檔名方便預覽
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(html_content)
        save_current_run_time(new_latest_ts)
        print(f"✅ 完成！產出 {file_name}")
    else:
        print("目前無新內容。")

if __name__ == "__main__":
    main()
