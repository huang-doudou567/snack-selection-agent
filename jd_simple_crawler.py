# -*- coding: utf-8 -*-
"""京东评论极简爬虫 — DrissionPage 零额外参数，最小化CDP指纹暴露"""
import sys, time, random, re, json
from datetime import datetime
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
from bs4 import BeautifulSoup
from DrissionPage import ChromiumPage, ChromiumOptions

BASE = Path(__file__).resolve().parent
INPUT_CSV = BASE / "merged_products.csv"
PROFILE = BASE / ".jd_playwright_profile"
OUTPUT_DIR = BASE / "数据" / "京东评论爬取"
REVIEWS_FILE = OUTPUT_DIR / "product_reviews.csv"
CHECKPOINT_FILE = OUTPUT_DIR / "crawled_items.csv"

MAX_PRODUCTS = 100
MIN_DELAY, MAX_DELAY = 90, 150  # 商品间隔 90-150 秒

def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def load_checkpoint():
    cp = set()
    if CHECKPOINT_FILE.exists():
        try:
            df = pd.read_csv(CHECKPOINT_FILE, dtype=str).fillna("")
            for pid in df.get("item_id", []):
                cp.add(str(pid))
        except: pass
    return cp

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 浏览器
    co = ChromiumOptions()
    co.set_user_data_path(str(PROFILE))
    co.set_argument("--no-sandbox")
    co.set_local_port(9515)
    pg = ChromiumPage(co)
    pg.set.timeouts(page_load=15, script=10)
    print(f"[BROWSER] Chrome 已启动")

    # 验证登录
    pg.get("https://www.jd.com/", timeout=10)
    time.sleep(2)
    body = pg.run_js("return document.body.innerText")
    if "请登录" in body:
        print("[FATAL] 未登录，请先运行登录流程")
        pg.quit(); return
    print("[OK] 已登录")

    # 导出 cookie 备份
    try:
        cks = pg.cookies()
        with open(".jd_cookies.json", "w", encoding="utf-8") as f:
            json.dump(cks, f, ensure_ascii=False)
    except: pass

    # 加载待爬列表
    df = pd.read_csv(INPUT_CSV, dtype=str).fillna("")
    crawled = load_checkpoint()
    print(f"[INPUT] {len(df)} 商品, {len(crawled)} 已爬")

    todo = []
    for _, row in df.iterrows():
        url = str(row.get("detail_url", ""))
        m = re.search(r"item\.jd\.com/(\d+)", url)
        pid = m.group(1) if m else ""
        if not pid or pid in crawled: continue
        title = str(row.get("product_title", ""))[:50]
        todo.append((pid, title))
        if len(todo) >= MAX_PRODUCTS: break

    print(f"[TODO] {len(todo)} 个待爬")

    reviews_buf, success, fail, block = [], 0, 0, 0
    consecutive_blocks = 0

    for idx, (pid, title) in enumerate(todo, 1):
        print(f"\n[{idx}/{len(todo)}] {pid} {title[:40]}")

        # 极简操作：只 get + get html + 提取
        try:
            pg.get(f"https://item.jd.com/{pid}.html", timeout=15)
        except Exception as e:
            print(f"  [FAIL] get: {type(e).__name__}")
            fail += 1
            continue

        time.sleep(random.uniform(5, 10))

        # 检查是否被拦
        url = pg.url or ""
        if "passport" in url or "risk_handler" in url or "reason=403" in url:
            print(f"  [BLOCK] {url[:80]}")
            block += 1; consecutive_blocks += 1
            if consecutive_blocks >= 5:
                print("[STOP] 连续风控5次，暂停10分钟后重试")
                time.sleep(600)
                consecutive_blocks = 0
            else:
                time.sleep(random.uniform(60, 120))
            continue

        consecutive_blocks = 0

        # 提取评论
        html = pg.html
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
        print(f"  [OK] {n} 条评论")

        # 写入断点
        with open(CHECKPOINT_FILE, "a", encoding="utf-8-sig") as f:
            f.write(f"{pid},{title},{n},{now_str()}\n")

        if n > 0: success += 1

        # 每 20 条落盘一次
        if len(reviews_buf) >= 60:
            new = pd.DataFrame(reviews_buf)
            if REVIEWS_FILE.exists():
                old = pd.read_csv(REVIEWS_FILE, dtype=str).fillna("")
                new = pd.concat([old, new], ignore_index=True)
                new = new.drop_duplicates(subset=["item_id", "content"], keep="last")
            new.to_csv(REVIEWS_FILE, index=False, encoding="utf-8-sig")
            print(f"  [SAVE] {len(reviews_buf)} 条已写入")
            reviews_buf.clear()

        # 长间隔
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        print(f"  等待 {delay:.0f}s...")
        time.sleep(delay)

    # 最终写入
    if reviews_buf:
        new = pd.DataFrame(reviews_buf)
        if REVIEWS_FILE.exists():
            old = pd.read_csv(REVIEWS_FILE, dtype=str).fillna("")
            new = pd.concat([old, new], ignore_index=True)
            new = new.drop_duplicates(subset=["item_id", "content"], keep="last")
        new.to_csv(REVIEWS_FILE, index=False, encoding="utf-8-sig")

    pg.quit()
    print(f"\n[DONE] 成功={success}, 风控={block}, 失败={fail}")

if __name__ == "__main__":
    main()
