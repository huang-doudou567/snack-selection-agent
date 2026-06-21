# -*- coding: utf-8 -*-
"""Open a persistent Chrome browser profile for manual JD login (DrissionPage)."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from DrissionPage import ChromiumPage, ChromiumOptions


JD_LOGIN_URL = "https://passport.jd.com/new/login.aspx?ReturnUrl=https%3A%2F%2Fwww.jd.com%2F"


def open_login(user_data_dir: str, wait_seconds: int, url: str = JD_LOGIN_URL) -> None:
    profile_dir = Path(user_data_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    co = ChromiumOptions()
    co.set_user_data_path(str(profile_dir.resolve()))

    # 基础
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-software-rasterizer")

    # 反自动化检测
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--disable-features=AutomationControlled")
    co.set_argument("--disable-automation")
    co.set_argument("--disable-features=IsolateOrigins,site-per-process")
    co.set_argument("--disable-site-isolation-trials")
    co.set_argument("--disable-web-security")
    co.set_argument("--disable-sync")
    co.set_argument("--disable-default-apps")
    co.set_argument("--disable-popup-blocking")
    co.set_argument("--disable-notifications")
    co.set_argument("--disable-extensions")
    co.set_argument("--disable-infobars")
    co.set_argument("--disable-background-networking")
    co.set_argument("--disable-component-update")
    co.set_argument("--disable-logging")
    co.set_argument("--no-default-browser-check")
    co.set_argument("--no-first-run")
    co.set_argument("--mute-audio")
    co.set_argument("--password-store=basic")
    co.set_argument("--use-mock-keychain")

    # 伪装
    co.set_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )
    co.set_argument("--window-size=1920,1080")
    co.set_argument("--accept-lang=zh-CN,zh;q=0.9")

    co.set_argument("--headless=new")
    co.set_local_port(9516)

    page = ChromiumPage(co)
    print(f"JD login window opened. Profile directory: {profile_dir.resolve()}", flush=True)
    print(f"Please complete login manually. This helper will keep the window open for {wait_seconds} seconds.", flush=True)
    try:
        page.get(url)
    except Exception as exc:
        print(f"Could not finish loading the target JD page automatically: {exc}", flush=True)
        print(f"Open this URL manually in the browser window: {url}", flush=True)
    try:
        time.sleep(wait_seconds)
    finally:
        page.quit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open JD login page with a reusable Chrome profile.")
    parser.add_argument("--user-data-dir", default=".jd_playwright_profile", help="Persistent profile directory")
    parser.add_argument("--wait-seconds", type=int, default=900, help="How long to keep the browser open")
    parser.add_argument("--url", default=JD_LOGIN_URL, help="JD URL to open")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    open_login(args.user_data_dir, args.wait_seconds, args.url)


if __name__ == "__main__":
    main()
