# -*- coding: utf-8 -*-
"""Run the JD rank page crawl requested by the user."""

from __future__ import annotations

import asyncio

from jd_rank_page_crawler import crawl_rank_tabs


START_URL = (
    "https://pro.jd.com/mall/active/4JRfHorUDXgL77E9YdNxSCNMKwkJ/index.html"
    "?pageNum=1&rankId=3989075&queryType=1&fromName=searchtuodiPC"
    "&preSrc=main_channel&bbtf=1&rankType=22&currSku=100103883068"
)


async def main() -> None:
    await crawl_rank_tabs(
        start_url=START_URL,
        output="raw_listing_京东排行榜_休闲食品_tabs.csv",
        user_data_dir=".jd_playwright_profile",
    )


if __name__ == "__main__":
    asyncio.run(main())
