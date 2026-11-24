#!/usr/bin/env python3
"""Build restaurants.json for the wall frame from tools/restaurants.json.

tools/restaurants.json is the hand-kept list of approved places (see its _about line).
The page reads restaurants.json by itself, so the twice-daily events refresh never touches it.

The frame is a kiosk and cannot open links, so each place gets a QR code for its Google Maps
listing, worked out here and stored as rows of 0 and 1. Link format (the documented search
action): https://developers.google.com/maps/documentation/urls/get-started

Distances are straight-line miles from the frame. The frame's position is never stored here:
pass it with --home when a place is added or moved, and the result is saved as "mi" per place.

Usage
  pip install segno
  python3 tools/build_restaurants.py                      rebuild with the saved distances
  python3 tools/build_restaurants.py --home LAT,LON       also recompute every distance
"""
import argparse, datetime as dt, json, math, os, sys
from urllib.parse import urlencode
import segno

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tools", "restaurants.json")

def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))

def maps_url(r):
    q = {"api": "1", "query": f'{r["name"]}, {r["address"]}, Cincinnati, OH'}
    if r.get("place_id"): q["query_place_id"] = r["place_id"]
    return "https://www.google.com/maps/search/?" + urlencode(q)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--home")
    a = ap.parse_args()
    src = json.load(open(SRC, encoding="utf-8"))
    if a.home:
        home = tuple(float(x) for x in a.home.split(","))
        for r in src["places"]:
            if "lat" in r and "lon" in r: r["mi"] = round(miles(home, (r["lat"], r["lon"])), 1)
        json.dump(src, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out, skipped = [], []
    for r in src["places"]:
        if r.get("show") is False: continue
        if not (r.get("address") or "").strip(): skipped.append(r["name"]); continue
        url = maps_url(r)
        rows = ["".join("1" if c else "0" for c in row) for row in segno.make(url, error="m", micro=False).matrix]
        p = dict(name=r["name"], type=r.get("type", ""), desc=r.get("desc", ""), addr=r["address"], url=url, qr=rows)
        if "mi" in r: p["mi"] = r["mi"]
        out.append(p)
    out.sort(key=lambda p: (p.get("mi", 99), p["name"].lower()))
    data = dict(version=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), source=src.get("source", ""), places=out)
    json.dump(data, open(os.path.join(ROOT, "restaurants.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"restaurants.json: {len(out)} places" + (f"; left out, no address yet: {', '.join(skipped)}" if skipped else ""))
    return 0

if __name__ == "__main__":
    sys.exit(main())
