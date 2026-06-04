# -*- coding: utf-8 -*-
"""Run the requested JD crawl for 健康零食低脂."""

from __future__ import annotations

import asyncio

from jd_listing_crawler import crawl_jd_listing


async def main() -> None:
    await crawl_jd_listing(
        keyword="健康零食低脂",
        max_pages=20,
        save_interval=1,
        output="raw_listing_健康零食低脂.csv",
        user_data_dir=".jd_playwright_profile",
    )


if __name__ == "__main__":
    asyncio.run(main())
