# -*- coding: utf-8 -*-
"""
京东评论 HTTP 爬虫 — 零浏览器指纹，纯 HTTP 请求
原理: 读取 DrissionPage profile 中未加密的 cookie，通过 requests 直接调 JD 评论 API
"""
import sys
import time
import random
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = Path(__file__).resolve().parent
COOKIE_JSON = BASE / ".jd_cookies.json"
INPUT_CSV = BASE / "merged_products.csv"
OUTPUT_DIR = BASE / "数据" / "京东评论爬取"
REVIEWS_FILE = OUTPUT_DIR / "product_reviews_http.csv"
CHECKPOINT_FILE = OUTPUT_DIR / "crawled_items_http.csv"

MAX_PER_RUN = 200
MIN_DELAY = 5
MAX_DELAY = 15
SESSION = requests.Session()

def load_cookies():
    """从 DrissionPage 导出的 JSON 加载明文 cookie"""
    if not COOKIE_JSON.exists():
        raise RuntimeError(f"Cookie JSON 不存在: {COOKIE_JSON}，请先运行登录")
    with open(COOKIE_JSON, encoding='utf-8') as f:
        cookies = json.load(f)
    for c in cookies:
        name = c.get('name',''); value = c.get('value','')
        domain = c.get('domain','.jd.com')
        if name and value:
            SESSION.cookies.set(name, value, domain=domain)
    return len(cookies)

def fetch_comments(product_id: str, page: int = 0):
    """请求京东评论 API"""
    url = "https://club.jd.com/comment/productPageComments.action"
    params = {
        "productId": product_id,
        "score": 0,
        "sortType": 5,
        "page": page,
        "pageSize": 10,
        "isShadowSku": 0,
        "fold": 1,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://item.jd.com/{product_id}.html",
    }
    try:
        r = SESSION.get(url, params=params, headers=headers, timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

def parse_review(comment: dict, item_id: str, title: str) -> dict:
    return {
        "item_id": str(item_id),
        "title": title,
        "nickname": comment.get("nickname", ""),
        "score": comment.get("score", ""),
        "date": comment.get("creationTime", ""),
        "sku": comment.get("referenceName", ""),
        "content": comment.get("content", ""),
        "like_count": comment.get("usefulVoteCount", 0),
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def load_checkpoint():
    if not CHECKPOINT_FILE.exists():
        return set()
    try:
        df = pd.read_csv(CHECKPOINT_FILE, dtype=str).fillna("")
        return set(df["item_id"].astype(str))
    except Exception:
        return set()

def save_checkpoint(item_id: str, title: str, review_count: int, status: str):
    row = pd.DataFrame([{
        "item_id": str(item_id), "title": title, "review_count": review_count,
        "status": status, "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }])
    if CHECKPOINT_FILE.exists():
        row.to_csv(CHECKPOINT_FILE, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        row.to_csv(CHECKPOINT_FILE, index=False, encoding="utf-8-sig")

def save_reviews(reviews: list[dict]):
    if not reviews:
        return
    df = pd.DataFrame(reviews)
    if REVIEWS_FILE.exists():
        existing = pd.read_csv(REVIEWS_FILE, dtype=str).fillna("")
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=["item_id", "content"], keep="last")
    df.to_csv(REVIEWS_FILE, index=False, encoding="utf-8-sig")

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[COOKIE] 加载 cookie...")
    n = load_cookies()
    if n == 0:
        print("[FATAL] 未找到有效 cookie，请先在 DrissionPage 浏览器中登录京东")
        sys.exit(1)
    print(f"[COOKIE] 加载了 {n} 个 cookie")

    print(f"[INPUT] 读取 {INPUT_CSV}...")
    df = pd.read_csv(INPUT_CSV, dtype=str).fillna("")
    crawled = load_checkpoint()
    print(f"[INPUT] 总数: {len(df)}，已爬: {len(crawled)}")

    todo = []
    for _, row in df.iterrows():
        pid = str(row.get("product_id", ""))
        url = str(row.get("detail_url", ""))
        m = re.search(r"item\.jd\.com/(\d+)", url)
        if m:
            pid = m.group(1)
        if not pid or pid == "nan" or pid in crawled:
            continue
        todo.append((pid, str(row.get("product_title", ""))[:60]))
        if len(todo) >= MAX_PER_RUN:
            break

    print(f"[TODO] 本轮: {len(todo)} 个商品")

    reviews_buffer = []
    success, failed, empty = 0, 0, 0

    for idx, (pid, title) in enumerate(todo, 1):
        print(f"\n[{idx}/{len(todo)}] {pid[:12]} {title[:40]}")

        data = fetch_comments(pid)
        if data is None:
            print(f"  [FAIL] API 请求失败")
            save_checkpoint(pid, title, 0, "failed")
            failed += 1
            time.sleep(random.uniform(10, 20))
            continue

        comments_list = data.get("comments", [])
        total_count = data.get("productCommentSummary", {}).get("commentCount", 0)
        print(f"  [OK] 总评论={total_count}, 本页={len(comments_list)}")

        for c in comments_list:
            reviews_buffer.append(parse_review(c, pid, title))

        save_checkpoint(pid, title, total_count, "success" if comments_list else "empty")
        if comments_list:
            success += 1
        else:
            empty += 1

        if len(reviews_buffer) >= 50:
            save_reviews(reviews_buffer)
            print(f"  [SAVE] {len(reviews_buffer)} 条已写入")
            reviews_buffer.clear()

        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    save_reviews(reviews_buffer)
    print(f"\n[DONE] 成功={success}, 无评论={empty}, 失败={failed}")
    print(f"[DONE] 评论文件: {REVIEWS_FILE}")
    print(f"[DONE] 断点文件: {CHECKPOINT_FILE}")

if __name__ == "__main__":
    main()
