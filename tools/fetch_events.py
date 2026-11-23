#!/usr/bin/env python3
"""Read every listing from Now That's Cincinnati for the next 8 days.

The site's home page carries its events as structured records inside the page
source, so one plain request is enough (no browser). Writes build/ntc.json.

Usage: python3 tools/fetch_events.py [--html saved_page.html] [--days 8]
Exit codes: 0 ok, 2 could not fetch, 3 page layout changed (too few events).
"""
import argparse, datetime as dt, json, os, re, sys, urllib.request
from zoneinfo import ZoneInfo

URL = "https://www.nowthatscincinnati.com/"
UA = "cincy-wall-frame/1.0 (household events display; two reads a day)"
TZ = ZoneInfo("America/New_York")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")

def records(html):
    """Event dicts from the page's embedded data."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)
    text = "".join(json.loads(c) for c in chunks)
    dec, out = json.JSONDecoder(), []
    for m in re.finditer(r'\{"_id":"', text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and "venue" in obj and "title" in obj and obj.get("fullDate"):
            out.append(obj)
    return out

def start_minutes(t):
    """Minutes after midnight for the first clock time in a string like '6-9PM', '7:30PM', '2PM & 7:30PM'."""
    t = (t or "").upper().replace("NOON", "12PM").replace("MIDNIGHT", "12AM")
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\s*(?:[-–—]|TO)\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", t)
    if m:  # a range: the first time may borrow AM/PM from the second
        h, mi, ap, h2, ap2 = int(m[1]), int(m[2] or 0), m[3], int(m[4]), m[6]
        if not ap:
            ap = ap2
            if ap2 == "PM" and h < 12 and h > h2 % 12 and h2 != 12:
                ap = "AM"          # e.g. 11-1PM
    else:
        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", t)
        if not m:
            return None
        h, mi, ap = int(m[1]), int(m[2] or 0), m[3]
    if not 1 <= h <= 12 or mi > 59:
        return None
    return (h % 12 + (12 if ap == "PM" else 0)) * 60 + mi

def nice_time(mins):
    if mins is None:
        return ""
    h, m = divmod(mins, 60)
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html"); ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--today"); ap.add_argument("--out", default=os.path.join(ROOT, "build", "ntc.json"))
    a = ap.parse_args()
    try:
        html = open(a.html, encoding="utf-8").read() if a.html else fetch(URL)
    except Exception as e:
        print(f"could not fetch {URL}: {e}", file=sys.stderr); return 2
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(TZ).date()
    last = today + dt.timedelta(days=a.days - 1)
    seen, events = set(), []
    for r in records(html):
        try:
            day = dt.datetime.fromisoformat(r["fullDate"].replace("Z", "+00:00")).astimezone(TZ).date()
        except ValueError:
            continue
        if not today <= day <= last:
            continue
        venue = re.sub(r"\s+", " ", r.get("venue") or "").strip()
        title = re.sub(r"\s+", " ", r.get("title") or "").strip()
        raw = re.sub(r"\s+", " ", r.get("time") or "").strip()
        key = (day.isoformat(), venue.lower(), title.lower())
        if not title or key in seen:
            continue
        seen.add(key)
        mins = start_minutes(raw)
        events.append({"date": day.isoformat(), "venue": venue, "title": title, "time_raw": raw,
                       "time": nice_time(mins), "sort": mins if mins is not None else 24 * 60,
                       "link": (r.get("link") or r.get("eventLink") or "").strip()})
    events.sort(key=lambda e: (e["date"], e["sort"], e["venue"], e["title"]))
    days = sorted({e["date"] for e in events})
    if len(events) < 40 or len(days) < 4:
        print(f"only {len(events)} events on {len(days)} days: the page layout may have changed", file=sys.stderr); return 3
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"read_at": dt.datetime.now(TZ).isoformat(timespec="seconds"), "source": URL, "from": today.isoformat(),
               "to": last.isoformat(), "events": events}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(events)} events on {len(days)} days ({days[0]} to {days[-1]}) -> {os.path.relpath(a.out, ROOT)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
