from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
REPORT_TXT = BASE_DIR / "crawler_quality_status.txt"
REPORT_JSON = BASE_DIR / "crawler_quality_status.json"


def read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def find_latest_file(name: str) -> Path | None:
    matches: list[Path] = []
    for root, _, files in os.walk(BASE_DIR):
        if name in files:
            matches.append(Path(root) / name)
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def nonempty_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return 0
    values = df[column].fillna("").astype(str).str.strip()
    return int((values != "").sum())


def unique_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return 0
    values = df[column].fillna("").astype(str).str.strip()
    values = values[values != ""]
    return int(values.nunique())


def status_counts(df: pd.DataFrame) -> dict[str, int]:
    if "status" not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df["status"].value_counts(dropna=False).to_dict().items()}


def file_summary(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"exists": False}
    if not path.exists():
        return {"exists": False, "path": str(path)}
    df = read_csv(path)
    if df is None:
        return {"exists": True, "path": str(path), "readable": False}
    return {
        "exists": True,
        "readable": True,
        "path": str(path),
        "rows": int(len(df)),
        "cols": int(len(df.columns)),
        "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "status_counts": status_counts(df),
    }


def process_status() -> list[dict[str, str]]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -match 'jd_cdp_review_scraper.py|mmb_price_history_crawler.py|mmb_cdp_price_history_crawler.py' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Depth 3"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            cwd=BASE_DIR,
            text=True,
            capture_output=True,
            timeout=10,
        )
        text = proc.stdout.strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        result = []
        for item in data:
            cmd = str(item.get("CommandLine", ""))
            if "crawler_quality_monitor.py" in cmd or "Get-CimInstance Win32_Process" in cmd:
                continue
            result.append({"pid": str(item.get("ProcessId", "")), "command": cmd})
        return result
    except Exception as exc:
        return [{"pid": "", "command": f"process_check_error: {exc}"}]


def jd_quality() -> dict[str, Any]:
    details_path = find_latest_file("product_details.csv")
    reviews_path = find_latest_file("product_reviews.csv")
    negative_path = find_latest_file("negative_reviews.csv")
    checkpoint_path = find_latest_file("crawled_items.csv")

    details = file_summary(details_path)
    reviews = file_summary(reviews_path)
    negatives = file_summary(negative_path)
    checkpoint = file_summary(checkpoint_path)

    details_df = read_csv(details_path) if details_path else None
    reviews_df = read_csv(reviews_path) if reviews_path else None
    negatives_df = read_csv(negative_path) if negative_path else None

    checks: dict[str, Any] = {}
    if details_df is not None:
        for column in ["好评率", "评价标签", "产地", "保质期", "配料表", "规格"]:
            if column in details_df.columns:
                checks[f"{column}_nonempty"] = nonempty_count(details_df, column)
        if "好评率" in details_df.columns and len(details_df) > 0:
            rate_values = details_df["好评率"].fillna("").astype(str).str.strip()
            checks["good_rate_100_ratio"] = round(float((rate_values == "100%").sum() / len(details_df)), 4)

    if reviews_df is not None:
        content_col = "content" if "content" in reviews_df.columns else "review_text" if "review_text" in reviews_df.columns else ""
        if content_col:
            nonempty = nonempty_count(reviews_df, content_col)
            unique = unique_count(reviews_df, content_col)
            checks["reviews_nonempty"] = nonempty
            checks["reviews_unique"] = unique
            checks["reviews_duplicate_ratio"] = round(1 - unique / nonempty, 4) if nonempty else None

    if negatives_df is not None:
        content_col = "content" if "content" in negatives_df.columns else "review_text" if "review_text" in negatives_df.columns else ""
        if content_col:
            nonempty = nonempty_count(negatives_df, content_col)
            unique = unique_count(negatives_df, content_col)
            checks["negative_nonempty"] = nonempty
            checks["negative_unique"] = unique
            checks["negative_duplicate_ratio"] = round(1 - unique / nonempty, 4) if nonempty else None

    alerts: list[str] = []
    counts = checkpoint.get("status_counts", {})
    total_status = sum(counts.values())
    if total_status:
        blocked = counts.get("access_blocked", 0)
        if blocked / total_status > 0.2:
            alerts.append("京东访问受阻比例超过20%，建议暂停或降低频率")
    if checks.get("good_rate_100_ratio", 0) > 0.8 and details.get("rows", 0) >= 20:
        alerts.append("好评率100%占比异常偏高，需要复核详情页解析")
    if checks.get("negative_nonempty", 0) == 0 and negatives.get("rows", 0) == 0:
        alerts.append("差评文件为空，需要复核评论筛选入口")

    return {
        "details": details,
        "reviews": reviews,
        "negative_reviews": negatives,
        "checkpoint": checkpoint,
        "checks": checks,
        "alerts": alerts,
    }


def price_quality() -> dict[str, Any]:
    price_path = BASE_DIR / "price_history.csv"
    checkpoint_path = BASE_DIR / "crawled_price_items.csv"
    price = file_summary(price_path)
    checkpoint = file_summary(checkpoint_path)
    df = read_csv(price_path)

    checks: dict[str, Any] = {}
    alerts: list[str] = []
    if df is not None and len(df) > 0:
        counts = status_counts(df)
        success = counts.get("success", 0)
        error = counts.get("error", 0)
        no_result = counts.get("no_result", 0)
        checks["success_rate"] = round(success / len(df), 4)
        checks["error_rate"] = round(error / len(df), 4)
        checks["no_result_rate"] = round(no_result / len(df), 4)
        checks["current_price_nonempty"] = nonempty_count(df, "current_price")
        checks["lowest_price_nonempty"] = nonempty_count(df, "lowest_price")
        checks["lowest_price_25m_nonempty"] = nonempty_count(df, "lowest_price_25m")
        checks["lowest_date_25m_nonempty"] = nonempty_count(df, "lowest_date_25m")
        checks["avg_price_60d_nonempty"] = nonempty_count(df, "avg_price_60d")
        if "price_detail" in df.columns:
            detail_series = df["price_detail"].fillna("").astype(str).str.strip()
            checks["price_detail_nonempty"] = int(((detail_series != "") & (detail_series != "[]")).sum())
        else:
            checks["price_detail_nonempty"] = 0
        checks["trend_nonempty"] = int((df.get("price_trend", pd.Series(dtype=str)).fillna("").astype(str).str.strip() != "[]").sum()) if "price_trend" in df.columns else 0
        if success and "lowest_price_25m" in df.columns and checks["lowest_price_25m_nonempty"] / success < 0.8:
            alerts.append("慢慢买成功记录中25个月历史最低价缺失偏高，需要复核页面解析")
        if error / len(df) > 0.2:
            alerts.append("慢慢买错误率超过20%，不要扩大批量")
        if len(df) >= 3 and success == 0:
            alerts.append("慢慢买成功数为0，当前接口可能需要验证或签名/风控已变化")
        if success and max(checks.get("price_detail_nonempty", 0), checks.get("trend_nonempty", 0)) < success:
            alerts.append("慢慢买存在success但price_detail为空的记录，需要剔除断点后重跑")

    return {"price_history": price, "checkpoint": checkpoint, "checks": checks, "alerts": alerts}


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "爬虫数据质量巡检",
        f"生成时间: {report['generated_at']}",
        "",
        "进程状态:",
    ]
    processes = report["processes"]
    if processes:
        for proc in processes:
            lines.append(f"- PID {proc['pid']}: {proc['command'][:180]}")
    else:
        lines.append("- 未发现京东评论或慢慢买价格爬取进程")

    lines.extend(["", "京东评论/详情:"])
    for key in ["checkpoint", "details", "reviews", "negative_reviews"]:
        item = report["jd"][key]
        state = "exists" if item.get("exists") else "missing"
        lines.append(f"- {key}: {state}, rows={item.get('rows', 0)} path={item.get('path', 'missing')}")
        if item.get("status_counts"):
            lines.append(f"  status={item['status_counts']}")
    lines.append(f"- checks: {report['jd']['checks']}")
    for alert in report["jd"]["alerts"]:
        lines.append(f"! {alert}")

    lines.extend(["", "慢慢买历史价:"])
    for key in ["price_history", "checkpoint"]:
        item = report["price"][key]
        state = "exists" if item.get("exists") else "missing"
        lines.append(f"- {key}: {state}, rows={item.get('rows', 0)} path={item.get('path', 'missing')}")
        if item.get("status_counts"):
            lines.append(f"  status={item['status_counts']}")
    lines.append(f"- checks: {report['price']['checks']}")
    for alert in report["price"]["alerts"]:
        lines.append(f"! {alert}")

    return "\n".join(lines) + "\n"


def main() -> None:
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "processes": process_status(),
        "jd": jd_quality(),
        "price": price_quality(),
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_TXT.write_text(render_text(report), encoding="utf-8")
    print(REPORT_TXT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
