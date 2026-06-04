# -*- coding: utf-8 -*-
"""Run the requested JD listing crawl from the user-provided entry URL."""

from __future__ import annotations

import asyncio

from jd_listing_crawler import crawl_jd_listing


START_URL = (
    "https://search.jd.com/Search?"
    "keyword=%E4%BC%91%E9%97%B2%E9%A3%9F%E5%93%81"
    "&enc=utf-8"
    "&pvid=8f84ef257c264303995dfb7bcd3d5727"
    "&spmTag=YTAyMTkuYjAwMjM1Ni5jMDAwMDYzOTQuOF8xJTQwMTc3OTAxNDEzMzMyOCUyMzE3NzkwMTM5MjU4NTE5MDY2MDQ0MjklMjMxNDk2NDc2Mzkz"
)


async def main() -> None:
    await crawl_jd_listing(
        keyword="休闲食品",
        max_pages=20,
        save_interval=1,
        output="raw_listing_休闲食品.csv",
        user_data_dir=".jd_playwright_profile",
        start_url=START_URL,
    )


if __name__ == "__main__":
    asyncio.run(main())
