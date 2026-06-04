# -*- coding: utf-8 -*-
"""
手动登录脚本：打开慢慢买页面，等你手动登录。
登录成功后关闭浏览器，cookie 会保存在 .mmb_playwright_profile 中。
之后运行爬虫就能直接用这个登录态。
"""
from __future__ import annotations
import sys
from DrissionPage import ChromiumPage, ChromiumOptions
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
PROFILE = BASE_DIR / ".mmb_playwright_profile"
LOGIN_URL = "https://www.manmanbuy.com"
HISTORY_URL = "http://tool.manmanbuy.com/HistoryLowest.aspx"

print("=" * 60)
print("慢慢买手动登录")
print("=" * 60)
print()
print(f"Profile: {PROFILE}")
print()
print("请在弹出的 Chrome 窗口中：")
print("  1. 点击右上角「请登录」或「免费注册」")
print("  2. 完成登录（手机号/微信扫码均可）")
print("  3. 确认登录成功后，回到这里按 Enter")
print()

print("[1] 启动 Chrome...")
PROFILE.mkdir(parents=True, exist_ok=True)
co = ChromiumOptions()
co.set_user_data_path(str(PROFILE.resolve()))
co.set_argument("--no-sandbox")
co.set_argument("--disable-gpu")
co.auto_port()
page = ChromiumPage(co)
print(f"     Chrome 已启动")

print(f"\n[2] 打开慢慢买首页: {LOGIN_URL}")
page.get(LOGIN_URL)
print(f"     当前页面: {page.title}")

print(f"\n[3] 同时打开历史价页面（备用）...")
page.new_tab(HISTORY_URL)
print(f"     当前页面: {page.title}")

print(f"\n{'=' * 60}")
print("请在浏览器中完成登录，然后回到这里按 Enter 继续...")
print("=" * 60)
try:
    input()
except EOFError:
    pass

# 验证登录状态
print("\n[4] 验证登录状态...")
page.get(HISTORY_URL)

try:
    text = page.run_js("return document.body ? document.body.innerText : ''")
    has_welcome = "请登录" in text or "免费注册" in text
    has_logged_in = "我的慢慢买" in text or "退出" in text

    print(f"     bodyText 长度: {len(text) if text else 0}")
    print(f"     是否仍有 '请登录': {has_welcome}")
    print(f"     是否有登录态: {has_logged_in}")

    if has_logged_in:
        print("\n[OK] 登录成功！Session 已保存到 profile。")
        print("     现在可以运行爬虫: python mmb_cdp_price_history_crawler.py")
    else:
        print("\n[WARN] 未检测到登录态，可能是登录未完成或需要其他操作。")
        print("       请重新运行本脚本再试。")
except Exception as e:
    print(f"     检测失败: {e}")

print("\n按 Enter 关闭浏览器...")
try:
    input()
except EOFError:
    pass
page.quit()
print("完成。")
