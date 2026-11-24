#!/usr/bin/env python3
"""Build data.json for the wall frame from the events site listings and the gig list.

Inputs
  build/ntc.json        every listing for the next 8 days (tools/fetch_events.py)
  build/gigs.csv        the Cincy gig list (date, artist, event, venue, city, genre, tier, ...)
  tools/curation.json   hand decisions that override the rules below
  tools/art.json        the paintings to rotate

Usage
  python3 tools/build_data.py            write data.json
  python3 tools/build_data.py --report   also print the main list and the "more" page for each day

data.json holds "events" (the main list, capped per day) and "more" (everything else, shown on the
"im really bored...give me more" page for a day).
"""
import argparse, csv, datetime as dt, json, os, re, sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo("America/New_York")
GIG_DAYS = 10          # how far ahead gig list rows are used
CAP_WEEKDAY = 25       # hard limit on the main list, Sunday to Thursday
CAP_WEEKEND = 35       # hard limit on the main list, Friday and Saturday
MAX_TITLE = 92

# Every listing gets a priority. The main list for a day is filled in priority order up to the cap;
# whatever is left goes to the "more" page for that day.
#   1  highlights: gig list, featured venues, keyword matches, hand picks
#   2  ordinary bar and restaurant gigs
#   3  shows starting at 11 PM or later
#   4  open mics, karaoke and jam sessions
#   5  not family-room suitable
#   9  "more" page only
MORE_ONLY = 9
PRIORITY_NAMES = {1: "highlight", 2: "ordinary gig", 3: "late show", 4: "open mic, karaoke or jam", 5: "not family-room", 9: "more page only"}
# Title patterns -> (priority, category when nothing better is known)
CASUAL = [r"open mic", r"karaoke", r"\b(jazz|open|blues|drum|bluegrass)\s+jam\b", r"open jamb", r"\bsession$"]
ADULT = [(r"drag", "other"), (r"nightclub", "music"), (r"weed", "other")]
MORE_PAGE = [(r"^dj\b|\bdj set\b", "music"),
             (r"\btrivia\b|\bbingo\b|sign ?up|book club|workshop|fitness class|\b(coat|clothing) drive\b|potluck|pop[- ]?up|photo walk|"
              r"day camp|drum circle|^reception$|industry night|pro-am|poetry|boxing|fight series|small business saturday", "other")]
# Swear words in a title: lowest priority on the main list.
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
    """(priority, cat, why) from the rules alone."""
    title, venue = e["title"].lower(), e["venue"].lower()
    cat, pri, why, known = "music", 2, "not a featured venue", False
    for name, c in FEATURED:
        if name in venue: cat, pri, why, known = c, 1, "featured venue", True; break
    for pat, c in KEYWORDS:
        if re.search(pat, title):
            if c != "music" or cat == "music": cat = c
            if pri != 1: pri, why = 1, "keyword"
            known = True
            break
    if pri == 2 and counts[(venue, title)] >= 4: why = "nightly residency"
    def lower(p, w, c=None):
        nonlocal pri, why, cat
        if p > pri: pri, why = p, w
        if c and (not known or (c == "other" and cat == "music")): cat = c
    if 23 * 60 <= e["sort"] < 24 * 60: lower(3, "starts 11 PM or later")
    if any(re.search(p, title) for p in CASUAL): lower(4, "open mic, karaoke or jam", "comedy" if "comedy" in title else "music")
    for pat, c in ADULT:
        if re.search(pat, title): lower(5, "not family-room", c)
    if any(b in norm(e["title"]) for b in BLOCKED): lower(5, "blocked word")
    for pat, c in MORE_PAGE:
        if re.search(pat, title): lower(MORE_ONLY, "more page only", c)
    return pri, cat, why

def cap_for(d):
    return CAP_WEEKEND if dt.date.fromisoformat(d).weekday() in (4, 5) else CAP_WEEKDAY

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
        pri, cat, why = classify(e, counts)
        if any(re.search(p, e["title"], re.I) for p in extra_hide): pri, why = MORE_ONLY, "curation hide"
        ov = items.get(f'{e["venue"].lower()}|{e["title"].lower()}')
        r = dict(date=e["date"], time=e["time"], sort=e["sort"], title=tidy_title(e["title"]), venue=tidy_venue(e["venue"]),
                 cat=cat, src="ntc", pri=pri, why=why, raw_venue=e["venue"], raw_title=e["title"],
                 nightly=counts[(e["venue"].lower(), e["title"].lower())] >= 4)
        if ov:
            if "show" in ov: r["pri"], r["why"] = (1 if ov["show"] else MORE_ONLY), "curation"
            for f in ("cat", "title", "venue"):
                if ov.get(f): r[f] = ov[f]
        rows.append(r)

    # gig list: the household's own concert picks come first; borrow the start time when the events site has the same show
    gig_path, gigs_used, gigs_merged = os.path.join(ROOT, "build", "gigs.csv"), 0, 0
    if os.path.exists(gig_path):
        last = (today + dt.timedelta(days=GIG_DAYS - 1)).isoformat()
        for g in csv.DictReader(open(gig_path, encoding="utf-8")):
            d = (g.get("date") or "").strip()
            if not today.isoformat() <= d <= last: continue
            artist, event = (g.get("artist") or "").strip(), (g.get("event") or "").strip()
            if not artist: continue
            rude = any(b in norm(artist + event) for b in BLOCKED)
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
                    r.update(src="both", tier=tier, cat="music")
                    if r["why"] != "blocked word": r.update(pri=1, why="gig list")
                    if genre: r["genre"] = genre
                gigs_merged += 1
                continue
            title = event if artist.lower() in event.lower() else artist + (f": {event}" if event else "")
            city = (g.get("city") or "").replace(", OH", "").replace(", KY", " KY").strip()
            venue = re.sub(r"\s*\(.*?\)", "", g.get("venue") or "").strip() + ("" if city in ("", "Cincinnati") else f", {city}")
            r = dict(date=d, time="", sort=24 * 60 + 1, title=tidy_title(title), venue=venue, cat="music", src="gig", tier=tier,
                     pri=5 if rude else 1, why="blocked word" if rude else "gig list", raw_venue=g.get("venue") or "", raw_title=title, nightly=False)
            if genre: r["genre"] = genre
            rows.append(r)

    # one row per show: when a listing appears twice, keep the higher-priority copy
    WHY_ORDER = {"gig list": 0, "curation": 1, "featured venue": 2, "keyword": 3}
    rank = lambda r: (r["pri"], WHY_ORDER.get(r["why"], 4), r["nightly"], r["sort"], r["title"].lower())
    seen, uniq = set(), []
    for r in sorted(rows, key=rank):
        k = (r["date"], r["time"], norm(r["title"]), norm(r["venue"]))
        if k in seen: continue
        seen.add(k); uniq.append(r)
    rows = uniq

    # fill each day's main list in priority order up to the cap; the rest is the "more" page
    days = sorted({r["date"] for r in rows})
    for d in days:
        room = cap_for(d)
        for r in sorted((r for r in rows if r["date"] == d), key=rank):
            r["show"] = r["pri"] != MORE_ONLY and room > 0
            if r["show"]: room -= 1
            elif r["pri"] != MORE_ONLY: r["why"] += ", day is full"

    rows.sort(key=lambda r: (r["date"], r["sort"], r["title"].lower()))
    def out(r):
        ev = {f: r[f] for f in ("date", "time", "sort", "title", "venue", "cat", "src")}
        for f in ("tier", "genre"):
            if r.get(f): ev[f] = r[f]
        return ev
    events = [out(r) for r in rows if r["show"]]
    more = [out(r) for r in rows if not r["show"]]

    read = dt.datetime.fromisoformat(ntc["read_at"])
    data = dict(version=now.isoformat(timespec="seconds"),
                events_read=read.strftime("%a %b ") + str(read.day) + read.strftime(", %-I:%M %p"),
                events=events, more=more, weather=None, art=art)
    json.dump(data, open(os.path.join(ROOT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    per = {d: sum(e["date"] == d for e in events) for d in sorted({e["date"] for e in events})}
    per_more = {d: sum(e["date"] == d for e in more) for d in per}
    print(f"data.json: {len(events)} events on the main list, {len(more)} on the more pages {per_more}; gig list rows used {gigs_used} ({gigs_merged} matched to a listing); per day {per}")

    if a.report:
        for d in days[:8]:
            print(f"\n## {d}  shown")
            for r in rows:
                if r["date"] == d and r["show"]:
                    print(f'  + {r["time"] or "-":>8} [{r["cat"]:7}] {r["title"][:60]} @ {r["venue"][:30]}  ({r["pri"]} {r["why"]}{", " + r["tier"] if r.get("tier") else ""})')
            print(f"## {d}  more page only (cap {cap_for(d)})")
            for r in rows:
                if r["date"] == d and not r["show"]:
                    print(f'  - {r["time"] or "-":>8} {r["raw_title"][:60]} @ {r["raw_venue"][:30]}  ({r["pri"]} {r["why"]})  key: {r["raw_venue"].lower()}|{r["raw_title"].lower()}'[:230])
    if len(events) < 30:
        print("too few events: not safe to publish", file=sys.stderr); return 3
    return 0

if __name__ == "__main__":
    sys.exit(main())
