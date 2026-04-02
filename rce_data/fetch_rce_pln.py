from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API_URL: str = "https://api.raporty.pse.pl/api/rce-pln"
OUTPUT_PATH: Path = Path(__file__).with_name("rce_pln_current.json")
WARSAW_TZ: ZoneInfo = ZoneInfo("Europe/Warsaw")


def parse_rce_datetime(value: str) -> datetime:
    parsed: datetime = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=WARSAW_TZ)


def read_json(url: str) -> dict[str, Any]:
    request: Request = Request(url, headers={"accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    return payload


def fetch_all_from_now() -> tuple[list[dict[str, Any]], str]:
    now_local: datetime = datetime.now(WARSAW_TZ).replace(second=0, microsecond=0)

    # Determine what data we are looking for based on current time
    # After 20:00 we want next day's data, before 20:00 we want today's data.
    if now_local.hour >= 20:
        search_start: datetime = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        search_start: datetime = now_local

    # target_time is used to check if cache/response has enough coverage
    target_time: datetime = search_start.replace(hour=20, minute=0, second=0, microsecond=0)

    if OUTPUT_PATH.exists():
        try:
            cache: dict[str, Any] = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            cached_items: list[dict[str, Any]] = cache.get("value", [])

            # Check if we have data up to at least target_time
            has_required_data: bool = any(parse_rce_datetime(item["dtime"]) >= target_time for item in cached_items)

            if has_required_data:
                print(f"Data up to {target_time.strftime('%Y-%m-%d %H:%M')} found in cache, skipping API call.")
                filtered_items: list[dict[str, Any]] = [
                    item for item in cached_items if parse_rce_datetime(item["dtime"]) >= search_start
                ]
                if filtered_items:
                    return filtered_items, cache.get("generated_at", now_local.isoformat())
                print("Cache had data but filtering resulted in empty list, falling back to API.")
        except (json.JSONDecodeError, KeyError, Exception) as e:
            print(f"Error reading cache: {e}")

    search_start_str: str = search_start.strftime("%Y-%m-%d %H:%M:%S")

    query: dict[str, str] = {
        "$filter": f"dtime ge '{search_start_str}'",
        "$orderby": "dtime asc",
        "$first": "500",
    }
    first_url: str = f"{API_URL}?{urlencode(query)}"

    all_items: list[dict[str, Any]] = []
    next_url: str | None = first_url

    while next_url:
        page: dict[str, Any] = read_json(next_url)
        page_items_raw: Any = page.get("value", [])
        page_items: list[dict[str, Any]] = [item for item in page_items_raw if isinstance(item, dict)]
        all_items.extend(page_items)

        next_raw: Any = page.get("nextLink")
        next_url = next_raw if isinstance(next_raw, str) and next_raw else None

    filtered_items: list[dict[str, Any]] = []
    for item in all_items:
        dtime_raw: Any = item.get("dtime")
        if not isinstance(dtime_raw, str):
            continue
        dtime_value: datetime = parse_rce_datetime(dtime_raw)
        if dtime_value >= search_start:
            filtered_items.append(item)

    if not filtered_items:
        raise ValueError(f"No RCE data available for {search_start_str} or later.")

    return filtered_items, now_local.isoformat()


def save_rce_data(items: list[dict[str, Any]], generated_at: str) -> None:
    output: dict[str, Any] = {
        "generated_at": generated_at,
        "source": API_URL,
        "count": len(items),
        "value": items,
    }

    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Saved {len(items)} records to {OUTPUT_PATH}")


def main() -> None:
    items: list[dict[str, Any]]
    generated_at: str
    items, generated_at = fetch_all_from_now()

    save_rce_data(items, generated_at)


if __name__ == "__main__":
    main()
