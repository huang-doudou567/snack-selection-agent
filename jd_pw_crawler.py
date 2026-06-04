# -*- coding: utf-8 -*-
"""京东评论爬虫 — Playwright + stealth，绕 CDP 检测"""
import sys, time, random, re, json, os
from datetime import datetime
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
INPUT_CSV = BASE / "merged_products.csv"
PROFILE = BASE / ".jd_pw_profile"
OUTPUT_DIR = BASE / "数据" / "京东评论爬取"
REVIEWS_FILE = OUTPUT_DIR / "product_reviews.csv"
CHECKPOINT_FILE = OUTPUT_DIR / "crawled_items.csv"

MAX_PRODUCTS = 100
MIN_DELAY, MAX_DELAY = 60, 120  # 秒

def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def load_checkpoint():
    cp = set()
    if CHECKPOINT_FILE.exists():
        try:
            for _, row in pd.read_csv(CHECKPOINT_FILE, dtype=str).fillna("").iterrows():
                cp.add(str(row.get("item_id", "")))
        except: pass
    return cp

def _stealth(page):
    """注入反检测脚本"""
    page.add_init_script("""
    delete navigator.__proto__.webdriver;
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
    window.chrome = {runtime:{}, loadTimes:function(){}, csi:function(){}, app:{}};
    """)

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)

    # 加载待爬列表
    df = pd.read_csv(INPUT_CSV, dtype=str).fillna("")
    crawled = load_checkpoint()
    todo = []
    for _, row in df.iterrows():
        url = str(row.get("detail_url", ""))
        m = re.search(r"item\.jd\.com/(\d+)", url)
        pid = m.group(1) if m else ""
        if not pid or pid in crawled: continue
        title = str(row.get("product_title", ""))[:50]
        todo.append((pid, title))
        if len(todo) >= MAX_PRODUCTS: break

    print(f"[TODO] {len(todo)} 个商品, {len(crawled)} 已爬")

    with sync_playwright() as p:
        # 持久化 profile，跟普通 Chrome 一样
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1200,800",
            ],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1200, "height": 800},
            locale="zh-CN",
        )

        page = context.pages[0] if context.pages else context.new_page()
        _stealth(page)

        print("[LOGIN] 检查登录态...", flush=True)
        # 加载 cookie
        ck_json = BASE / ".jd_cookies_pw.json"
        if ck_json.exists():
            try:
                with open(ck_json) as f:
                    jd_cks = json.load(f)
                if jd_cks:
                    context.add_cookies(jd_cks)
                    print(f"[LOGIN] 已添加 {len(jd_cks)} 个 cookie", flush=True)
            except Exception as e:
                print(f"[LOGIN] cookie 添加失败: {e}", flush=True)

        # 跳过登录检测 — 直接试爬第一个商品验证 cookie 是否有效
        print("[INFO] Cookie 已加载，直接开始爬取", flush=True)

        # 导出 cookie
        try:
            cookies = context.cookies()
            jd_cks = [c for c in cookies if "jd.com" in str(c.get("domain",""))]
            with open(".jd_cookies.json", "w") as f:
                json.dump(jd_cks, f, ensure_ascii=False)
        except: pass

        reviews_buf = []
        success, failed, blocked = 0, 0, 0
        consecutive_blocks = 0

        for idx, (pid, title) in enumerate(todo, 1):
            if idx > 1:
                delay = random.uniform(MIN_DELAY, MAX_DELAY)
                print(f"  等待 {delay:.0f}s...", flush=True)
                time.sleep(delay)

            print(f"\n[{idx}/{len(todo)}] {pid} {title[:40]}", flush=True)

            url = f"https://item.jd.com/{pid}.html"
            try:
                resp = page.goto(url, timeout=15000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"  [FAIL] page.goto: {type(e).__name__}", flush=True)
                failed += 1
                continue

            page.wait_for_timeout(random.randint(5000, 10000))

            # 检查风控
            current_url = page.url
            if "risk_handler" in current_url or "passport" in current_url:
                print(f"  [BLOCK] 风控/重定向", flush=True)
                blocked += 1; consecutive_blocks += 1
                if consecutive_blocks >= 3:
                    print("[STOP] 连续风控3次，冷却5分钟")
                    time.sleep(300)
                    consecutive_blocks = 0
                continue
            consecutive_blocks = 0

            # 等待页面渲染 + 滚动到评论区
            page.wait_for_timeout(random.randint(3000, 6000))
            try:
                page.evaluate("window.scrollTo(0, Math.floor(document.documentElement.scrollHeight * 0.35))")
            except: pass
            page.wait_for_timeout(random.randint(2000, 4000))

            # 提取
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            items = soup.select("#comment-root ul.list > li.item")

            for item in items:
                nick_el = item.select_one(".nickname")
                info_el = item.select_one(".info.text-ellipsis-2")
                if info_el:
                    reviews_buf.append({
                        "item_id": pid, "title": title,
                        "nickname": nick_el.text.strip() if nick_el else "",
                        "content": info_el.text.strip()[:500],
                        "crawl_time": now_str(),
                    })

            n = len(items)
            print(f"  [OK] {n} 条评论", flush=True)
            if n: success += 1

            # 断点
            with open(CHECKPOINT_FILE, "a", encoding="utf-8-sig") as f:
                f.write(f"{pid},{title},{n},{now_str()}\n")

            # 落盘
            if len(reviews_buf) >= 60:
                new = pd.DataFrame(reviews_buf)
                if REVIEWS_FILE.exists():
                    old = pd.read_csv(REVIEWS_FILE, dtype=str).fillna("")
                    new = pd.concat([old, new], ignore_index=True)
                new = new.drop_duplicates(subset=["item_id", "content"], keep="last")
                new.to_csv(REVIEWS_FILE, index=False, encoding="utf-8-sig")
                print(f"  [SAVE] {len(reviews_buf)} 条已写入", flush=True)
                reviews_buf.clear()

        # 最终写入
        if reviews_buf:
            new = pd.DataFrame(reviews_buf)
            if REVIEWS_FILE.exists():
                old = pd.read_csv(REVIEWS_FILE, dtype=str).fillna("")
                new = pd.concat([old, new], ignore_index=True)
            new = new.drop_duplicates(subset=["item_id", "content"], keep="last")
            new.to_csv(REVIEWS_FILE, index=False, encoding="utf-8-sig")

        context.close()

    print(f"\n[DONE] 成功={success}, 风控={blocked}, 失败={failed}")

if __name__ == "__main__":
    main()
