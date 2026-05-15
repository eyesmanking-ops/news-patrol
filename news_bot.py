# -*- coding: utf-8 -*-
import time, os, sys, requests, feedparser, urllib3
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

def fetch_chinatimes_paged(start_time):
    res = []; seen = set()
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    driver_path = ChromeDriverManager().install()
    driver = webdriver.Chrome(service=Service(driver_path), options=options)
    
    try:
        # 爬取中時即時新聞前 5 頁
        for page in range(1, 6):
            driver.get(f"https://www.chinatimes.com/realtimenews/?chdtv&page={page}")
            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            items = soup.select('ul.vertical-list > li')
            
            found_new = False
            for art in items:
                t_tag = art.select_one('.title a')
                d_tag = art.select_one('time')
                if not t_tag or not d_tag: continue
                
                url = "https://www.chinatimes.com" + t_tag.get('href', '')
                try:
                    dt = datetime.strptime(d_tag.get('datetime'), "%Y-%m-%d %H:%M")
                    if dt >= start_time:
                        if url not in seen:
                            res.append((dt, t_tag.text.strip(), url))
                            seen.add(url)
                            found_new = True
                except: continue
            if not found_new: break
    finally:
        driver.quit()
    return res

def fetch_cna(start_time):
    res = []
    try:
        resp = requests.get("https://www.cna.com.tw/list/aall.aspx", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        for art in soup.select('#jsMainList li'):
            t_tag = art.select_one('.date'); title_tag = art.select_one('h2')
            if t_tag and title_tag:
                dt = datetime.strptime(t_tag.text.strip().replace('/', '-'), "%Y-%m-%d %H:%M")
                if dt >= start_time:
                    url = "https://www.cna.com.tw" + art.select_one('a')['href']
                    res.append((dt, title_tag.text.strip(), url))
    except: pass
    return res

def fetch_ltn(start_time):
    res = []
    feed = feedparser.parse("https://news.ltn.com.tw/rss/all.xml")
    for e in feed.entries:
        dt = datetime(*(e.published_parsed[0:6])) + timedelta(hours=8)
        if dt >= start_time:
            res.append((dt, e.title, e.link))
    return res

def fetch_udn(start_time):
    res = []
    try:
        resp = requests.get("https://udn.com/news/breaknews/1/0", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        for art in soup.select('.story-list__text'):
            title_tag = art.find('a'); time_tag = art.find('time')
            if title_tag and time_tag:
                t_str = time_tag.text.strip()
                if len(t_str) <= 11: t_str = f"{datetime.now().year}-{t_str}"
                dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M")
                if dt >= start_time:
                    url = "https://udn.com" + title_tag['href'] if not title_tag['href'].startswith('http') else title_tag['href']
                    res.append((dt, title_tag.text.strip(), url))
    except: pass
    return res

def main():
    manual_time = None
    # 解析民國格式: 11505152100 (11位數字)
    if len(sys.argv) > 1 and len(sys.argv[1].strip()) == 11:
        raw = sys.argv[1].strip()
        try:
            ad_year = int(raw[:3]) + 1911
            manual_time = datetime(ad_year, int(raw[3:5]), int(raw[5:7]), int(raw[7:9]), int(raw[9:11]))
            print(f"🎯 使用手動時間: {manual_time}")
        except:
            print("⚠️ 時間格式錯誤，將使用紀錄時間")

    last_run_ts = manual_time if manual_time else get_last_run_time()
    buffer_start_ts = last_run_ts - timedelta(minutes=10)
    
    print(f"🕒 抓取基準點: {buffer_start_ts}")
    
    all_data = {
        "中時新聞網": fetch_chinatimes_paged(buffer_start_ts),
        "中央通訊社": fetch_cna(buffer_start_ts),
        "自由時報": fetch_ltn(buffer_start_ts),
        "聯合新聞網": fetch_udn(buffer_start_ts)
    }
    
    total = sum(len(v) for v in all_data.values())
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    html_content = f"<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body{{font-family:sans-serif;padding:20px;line-height:1.6;}}a{{text-decoration:none;color:#004a99;font-weight:bold;}}li{{margin-bottom:10px;border-bottom:1px solid #eee;padding-bottom:5px;}}.time{{color:#e74c3c;margin-right:10px;}}</style></head><body>"
    html_content += f"<h1>新聞摘要 ({now_str})</h1><p>起始時間：{buffer_start_ts}</p>"
    
    new_latest_ts = last_run_ts
    for media, items in all_data.items():
        html_content += f"<h2>{media} ({len(items)})</h2><ul>"
        items.sort(key=lambda x: x[0], reverse=True)
        for dt, title, url in items:
            if dt > new_latest_ts: new_latest_ts = dt
            html_content += f"<li><span class='time'>{dt.strftime('%H:%M')}</span><a href='{url}'>{title}</a></li>"
        if not items: html_content += "<li>無新新聞</li>"
        html_content += "</ul>"
    
    html_content += "</body></html>"
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    
    save_current_run_time(new_latest_ts)
    print(f"✅ 任務完成，最新紀錄點: {new_latest_ts}")

if __name__ == "__main__":
    main()
