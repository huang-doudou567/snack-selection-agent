# -*- coding: utf-8 -*-
"""Run JD rank page crawl for the latest user-provided URL."""

from __future__ import annotations

import asyncio

from jd_rank_page_crawler import crawl_rank_tabs


START_URL = (
    "https://pro.jd.com/mall/active/4JRfHorUDXgL77E9YdNxSCNMKwkJ/index.html"
    "?pageNum=1&bbtf=1&queryType=1&rankId=3165631&rankType=10"
    "&fromName=ProductdetailPC&preSrc=null&currSku=100256729280"
    "&currSpu=100110393619&animate=1"
)


async def main() -> None:
    await crawl_rank_tabs(
        start_url=START_URL,
        output="raw_listing_京东排行榜_新入口_tabs.csv",
        user_data_dir=".jd_playwright_profile",
    )


if __name__ == "__main__":
    asyncio.run(main())
