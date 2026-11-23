#!/usr/bin/env python3
"""Build data.json for the wall frame from the events site listings and the gig list.

Inputs
  build/ntc.json        every listing for the next 8 days (tools/fetch_events.py)
  build/gigs.csv        the Cincy gig list (date, artist, event, venue, city, genre, tier, ...)
  tools/curation.json   hand decisions that override the rules below
  tools/art.json        the paintings to rotate

Usage
  python3 tools/build_data.py            write data.json
  python3 tools/build_data.py --report   also print what is shown and what was left out
"""
import argparse, csv, datetime as dt, json, os, re, sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo("America/New_York")
GIG_DAYS = 10          # how far ahead gig list rows are used
MIN_PER_DAY = 10       # quiet days are filled up to this many events
MAX_TITLE = 92

# Listings that are never worth a card on the wall.
HIDE = [r"open mic", r"karaoke", r"\btrivia\b", r"\bbingo\b", r"\b(jazz|open|blues|drum|bluegrass)\s+jam\b", r"open jamb",
        r"\bsession$", r"sign ?up", r"book club", r"workshop", r"fitness class", r"\b(coat|clothing) drive\b", r"potluck",
        r"pop-?up", r"photo walk", r"day camp", r"drum circle", r"^dj\b", r"\bdj set\b", r"^reception$", r"industry night",
        r"pro-am", r"poetry", r"drag", r"boxing|fight series", r"nightclub", r"weed", r"small business saturday"]
# Never shown, whatever the source says.
BLOCKED = ["clit", "fuck", "shit", "cunt"]

# Venue name (lower case, contains) -> category. A listing at one of these is shown by default.
FEATURED = [
    ("playhouse in the park", "theater"), ("cincinnati shakespeare", "theater"), ("aronoff center", "theater"),
    ("ensemble theatre", "theater"), ("know theatre", "theater"), ("mariemont players", "theater"), ("falcon theatre", "theater"),
    ("the carnegie", "theater"), ("go bananas", "comedy"), ("commonwealth comedy", "comedy"), ("funny bone", "comedy"),
    ("contemporary arts center", "art"), ("cincinnati art museum", "art"), ("taft museum", "art"),
    ("american sign museum", "family"), ("behringer-crawford", "family"), ("museum center", "family"), ("cincinnati zoo", "family"),
    ("joseph-beth", "family"), ("mercantile library", "family"), ("krohn conservatory", "family"),
    ("esquire theatre", "film"),
    ("music hall", "music"), ("taft theatre", "music"), ("memorial hall", "music"), ("hard rock cincinnati", "music"),
    ("andrew j brady", "music"), ("megacorp pavilion", "music"), ("bogart's", "music"), ("ludlow garage", "music"),
    ("woodward theater", "music"), ("southgate house revival", "music"), ("madison theater", "music"), ("madison live", "music"),
    ("heritage bank center", "music"), ("riverbend", "music"), ("annie's music center", "music"), ("the redmoor", "music"),
    ("blue note harrison", "music"), ("liberty theater", "music"), ("lori's roadhouse", "music"), ("20th century theat", "music"),
    ("fountain square", "music"), ("washington park", "music"), ("ccm", "music"), ("xavier", "music"),
    ("caffe vivace", "music"), ("schwartz's point", "music"), ("christ church cathedral", "music"),
    ("newport car barn", "music"), ("good shepherd lutheran", "music"), ("liberty exhibition hall", "music"),
]
# Title patterns -> category. A match is shown by default.
KEYWORDS = [
    (r"^film\b|\bfilm:|movie night|movie screening|film collective|\(19\d\d\)|\(20\d\d\)", "film"),
    (r"holiday market|christmas market|christkindl|winter market|\bmarket\b|city flea|light up|tree lighting|santa\b|muppet christmas|plaid friday", "holiday"),
    (r"art opening|art on vine|exhibit|artist in residence|record store day", "art"),
    (r"comedy at|stand-?up|improv\b|comedysportz", "comedy"),
    (r"book signing|discussing & signing|story ?time|sign crafting|cardboard architects", "family"),
    (r"album release|single release|sing-?along|tribute|big band|in concert", "music"),
]
# Shorter, friendlier venue names.
VENUE_NAMES = [(r"^the southgate house revival.*$", "Southgate House Revival"), (r"^the woodward theater$", "Woodward Theater"),
               (r"^the andrew j brady music center$", "Andrew J Brady Music Center"), (r"^motr$", "MOTR Pub"),
               (r"^the lounge at liberty exhibition hall$", "Liberty Exhibition Hall"), (r"^xavier gallagher student center theater$", "Xavier University"),
               (r"^the lytle park hotel.*$", "Lytle Park Hotel"), (r"^the aquifer at new riff.*$", "New Riff Distilling"),
               (r"^cincinnati shakespeare company$", "Cincinnati Shakespeare Company")]

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
def vnorm(s): return re.sub(r"^the", "", norm(re.sub(r"\(.*?\)", "", s or "")))

def tidy_venue(v):
    for pat, rep in VENUE_NAMES:
        if re.match(pat, v, re.I): return rep
    return v

def tidy_title(t):
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^Cameo Cincy Film Collective Presents (.+?) Featuring.*$", r"Film: \1", t)
    if len(t) > MAX_TITLE:
        t = t[:MAX_TITLE].rsplit(" ", 1)[0].rstrip(",;:–- ") + "…"
    return t

def classify(e, counts):
    """(show, cat, why) from the rules alone."""
    title, venue = e["title"].lower(), e["venue"].lower()
    if any(b in norm(e["title"]) for b in BLOCKED): return False, "music", "blocked word"
    for pat in HIDE:
        if re.search(pat, title): return False, "music", "hide rule"
    if e["sort"] >= 23 * 60 and e["sort"] < 24 * 60: return False, "music", "starts 11 PM or later"
    cat, show, why = "music", False, "not a featured venue"
    for name, c in FEATURED:
        if name in venue: cat, show, why = c, True, "featured venue"; break
    for pat, c in KEYWORDS:
        if re.search(pat, title):
            if c != "music" or cat == "music": cat = c
            if not show: show, why = True, "keyword"
            break
    if counts[(venue, title)] >= 4 and show is False: why = "nightly residency"
    return show, cat, why

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--report", action="store_true"); ap.add_argument("--today")
    a = ap.parse_args()
    now = dt.datetime.now(TZ)
    today = dt.date.fromisoformat(a.today) if a.today else now.date()
    ntc = json.load(open(os.path.join(ROOT, "build", "ntc.json"), encoding="utf-8"))
    cur = json.load(open(os.path.join(ROOT, "tools", "curation.json"), encoding="utf-8"))
    items = {k.lower(): v for k, v in cur.get("items", {}).items()}
    extra_hide = cur.get("hide", [])
    art = json.load(open(os.path.join(ROOT, "tools", "art.json"), encoding="utf-8"))

    counts = {}
    for e in ntc["events"]:
        k = (e["venue"].lower(), e["title"].lower()); counts[k] = counts.get(k, 0) + 1
    rows = []
    for e in ntc["events"]:
        if e["date"] < today.isoformat(): continue
        show, cat, why = classify(e, counts)
        if any(re.search(p, e["title"], re.I) for p in extra_hide): show, why = False, "curation hide"
        ov = items.get(f'{e["venue"].lower()}|{e["title"].lower()}')
        r = dict(date=e["date"], time=e["time"], sort=e["sort"], title=tidy_title(e["title"]), venue=tidy_venue(e["venue"]),
                 cat=cat, src="ntc", show=show, why=why, raw_venue=e["venue"], raw_title=e["title"], filler=False,
                 nightly=counts[(e["venue"].lower(), e["title"].lower())] >= 4)
        if ov:
            if "show" in ov: r["show"], r["why"] = bool(ov["show"]), "curation"
            for f in ("cat", "title", "venue"):
                if ov.get(f): r[f] = ov[f]
        rows.append(r)

    # gig list: the household's own concert picks always show; borrow the start time when the events site has the same show
    gig_path, gigs_used, gigs_merged = os.path.join(ROOT, "build", "gigs.csv"), 0, 0
    if os.path.exists(gig_path):
        last = (today + dt.timedelta(days=GIG_DAYS - 1)).isoformat()
        for g in csv.DictReader(open(gig_path, encoding="utf-8")):
            d = (g.get("date") or "").strip()
            if not today.isoformat() <= d <= last: continue
            artist, event = (g.get("artist") or "").strip(), (g.get("event") or "").strip()
            if not artist or any(b in norm(artist + event) for b in BLOCKED): continue
            gigs_used += 1
            tier = (g.get("tier") or "").strip().upper()
            genre = (g.get("genre") or "").strip()
            if re.search(r"unknown|not stated", genre, re.I): genre = ""
            first = norm(re.split(r"[,/&;]| w/ | with ", artist)[0])
            gv = vnorm(g.get("venue"))
            def same_show(r):
                rv, rt = vnorm(r["raw_venue"]), norm(r["raw_title"])
                venue_ok = bool(gv and rv) and (gv[:7] in rv or rv[:7] in gv)
                act_ok = len(first) >= 4 and first[:6] in rt
                event_ok = len(norm(event)) >= 8 and norm(event)[:12] in rt
                return (venue_ok and (act_ok or event_ok)) or (len(first) >= 8 and first[:9] in rt)
            hit = [r for r in rows if r["date"] == d and r["src"] != "gig" and same_show(r)]
            if hit:
                for r in hit:
                    if r["why"] == "blocked word": continue
                    r.update(show=True, why="gig list", src="both", tier=tier, cat="music")
                    if genre: r["genre"] = genre
                gigs_merged += 1
                continue
            title = event if artist.lower() in event.lower() else artist + (f": {event}" if event else "")
            city = (g.get("city") or "").replace(", OH", "").replace(", KY", " KY").strip()
            venue = re.sub(r"\s*\(.*?\)", "", g.get("venue") or "").strip() + ("" if city in ("", "Cincinnati") else f", {city}")
            r = dict(date=d, time="", sort=24 * 60 + 1, title=tidy_title(title), venue=venue, cat="music", src="gig", tier=tier,
                     show=True, why="gig list", raw_venue=g.get("venue") or "", raw_title=title, filler=False, nightly=False)
            if genre: r["genre"] = genre
            rows.append(r)

    # quiet days: fill up with the remaining listings in time order (residencies last)
    days = sorted({r["date"] for r in rows})
    for d in days:
        shown = [r for r in rows if r["date"] == d and r["show"]]
        spare = [r for r in rows if r["date"] == d and not r["show"] and r["why"] in ("not a featured venue", "nightly residency")]
        spare.sort(key=lambda r: (r["nightly"], r["sort"]))
        for r in spare[:max(0, MIN_PER_DAY - len(shown))]:
            r["show"], r["filler"], r["why"] = True, True, "fills a quiet day"

    rows.sort(key=lambda r: (r["date"], r["sort"], r["title"].lower()))
    seen, events = set(), []
    for r in rows:
        if not r["show"]: continue
        k = (r["date"], r["time"], norm(r["title"]), norm(r["venue"]))
        if k in seen: continue
        seen.add(k)
        ev = {f: r[f] for f in ("date", "time", "sort", "title", "venue", "cat", "src")}
        for f in ("tier", "genre"):
            if r.get(f): ev[f] = r[f]
        events.append(ev)

    read = dt.datetime.fromisoformat(ntc["read_at"])
    data = dict(version=now.isoformat(timespec="seconds"),
                events_read=read.strftime("%a %b ") + str(read.day) + read.strftime(", %-I:%M %p"),
                events=events, weather=None, art=art)
    json.dump(data, open(os.path.join(ROOT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    per = {d: sum(e["date"] == d for e in events) for d in sorted({e["date"] for e in events})}
    print(f"data.json: {len(events)} events; gig list rows used {gigs_used} ({gigs_merged} matched to a listing); per day {per}")

    if a.report:
        for d in days[:8]:
            print(f"\n## {d}  shown")
            for r in rows:
                if r["date"] == d and r["show"]:
                    print(f'  + {r["time"] or "-":>8} [{r["cat"]:7}] {r["title"][:60]} @ {r["venue"][:30]}  ({r["why"]}{", " + r["tier"] if r.get("tier") else ""})')
            print(f"## {d}  left out")
            for r in rows:
                if r["date"] == d and not r["show"]:
                    print(f'  - {r["time"] or "-":>8} {r["raw_title"][:60]} @ {r["raw_venue"][:30]}  ({r["why"]})  key: {r["raw_venue"].lower()}|{r["raw_title"].lower()}'[:230])
    if len(events) < 30:
        print("too few events: not safe to publish", file=sys.stderr); return 3
    return 0

if __name__ == "__main__":
    sys.exit(main())
