import csv
import difflib
import io
import math
import os
import statistics
import sys
import zipfile
from collections import Counter, defaultdict

from falkordb import FalkorDB

ZIP_PATH = sys.argv[1] if len(sys.argv) > 1 else "dmrc_gtfs.zip"

# Approximate coordinates of Jantar Mantar. VERIFY on a map (right-click -> copy coordinates).
PLACE_NAME = "Jantar Mantar"
PLACE_LAT, PLACE_LON = 28.6271, 77.2166
NEAR_LIMIT_KM = 8.0     # stations farther than this (straight line) are not linked
NEAR_COUNT = 40         # link at most this many nearest stations
WALK_KMH = 4.5
STREET_FACTOR = 1.3     # walking routes are longer than straight lines

# A reported closure event. Entry and exit were closed at these stations. Names are as
# DMRC and the press wrote them. Check the sources before quoting details in your README.
# Wording rule for this project: attribute every statement to DMRC or Delhi Police and
# take no position on the event itself.
EVENT = {
    "id": "2026-10-10-jantar-mantar",
    "date": "9 to 10 October 2026",
    "description": "DMRC closed entry and exit at 45 Delhi metro stations ahead of a "
                   "planned demonstration near Jantar Mantar",
    "reason": (
        "DMRC said entry and exit would be closed at these stations for security reasons, "
        "from 9 pm on 9 October, with 6 pm on 10 October given as the end time. Its update "
        "said security agencies would review the situation. Delhi Police had proposed "
        "closures at 57 stations; DMRC's revised update covered 45. DMRC said the "
        "restrictions applied to entry and exit, and that passengers could still change "
        "trains at the affected stations except New Delhi."
    ),
    "sources": [
        "https://www.businesstoday.in/india/story/dmrc-issues-revised-metro-closure-update-ahead-of-oct-10-check-affected-stations-560777-2026-10-09",
        "https://newsonair.gov.in/delhi-police-proposes-closure-of-entry-and-exit-gates-at-57-metro-stations-from-9-pm/",
    ],
    "stations": [
        "Janpath", "Patel Chowk", "Central Secretariat", "Lok Kalyan Marg", "Rajiv Chowk",
        "New Delhi", "Seva Teerth", "Mandi House", "Barakhamba Road", "ITO", "Delhi Gate",
        "Khan Market", "Ramakrishna Ashram Marg", "Jhandewalan", "Supreme Court",
        "Indraprastha", "Shivaji Stadium", "Dilli Haat-INA", "Hauz Khas", "Jor Bagh",
        "Lajpat Nagar", "Jangpura", "Ashram", "Jamia Millia Islamia", "Chawri Bazar",
        "Jama Masjid", "Karol Bagh", "Rajendra Place", "Vishwavidyalaya", "Kashmere Gate",
        "Inderlok", "Guru Teg Bahadur Nagar", "Netaji Subhash Place", "Azadpur",
        "Jahangirpuri", "Haiderpur Badli Mor", "Majlis Park", "Seelampur",
        "Maujpur-Babarpur", "Jaffrabad", "Welcome", "Yamuna Vihar", "Khajuri Khas",
        "Shahdara", "Rithala",
    ],
    # Entry and exit were closed everywhere above. Passengers could still change trains
    # at all of them except these.
    "no_interchange": ["New Delhi"],
}

z = zipfile.ZipFile(ZIP_PATH)


def read(filename):
    path = next(n for n in z.namelist()
                if n.endswith(filename) and "__MACOSX" not in n)
    with z.open(path) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def to_seconds(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def km_between(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# ---- read the feed ----
stops = {r["stop_id"]: r for r in read("stops.txt")}
line_of_route = {r["route_id"]: r["route_long_name"].split("_")[0].title()
                 for r in read("routes.txt")}
line_of_trip = {r["trip_id"]: line_of_route.get(r["route_id"], "Unknown")
                for r in read("trips.txt")}

trip_stops = defaultdict(list)
for r in read("stop_times.txt"):
    try:
        trip_stops[r["trip_id"]].append(
            (int(r["stop_sequence"]), r["stop_id"], to_seconds(r["arrival_time"])))
    except ValueError:
        continue  # skip rows with missing times

# Ride time between neighbouring stops = median over all trips
segments = defaultdict(list)
for trip_id, rows in trip_stops.items():
    rows.sort()
    line = line_of_trip.get(trip_id, "Unknown")
    for (_, a, ta), (_, b, tb) in zip(rows, rows[1:]):
        if a != b and tb >= ta:
            segments[(a, b, line)].append(tb - ta)

edges = [{"a": a, "b": b, "line": line,
          "minutes": max(0.5, round(statistics.median(secs) / 60, 1))}
         for (a, b, line), secs in segments.items()]

used = {e["a"] for e in edges} | {e["b"] for e in edges}
nodes = [{"id": sid, "name": stops[sid]["stop_name"].strip(),
          "lat": float(stops[sid]["stop_lat"]), "lon": float(stops[sid]["stop_lon"])}
         for sid in used if sid in stops]

dupes = [n for n, c in Counter(n["name"] for n in nodes).items() if c > 1]
if dupes:
    print("WARNING: station names used by more than one stop:", dupes)

# ---- build the graph ----
def connect():
    """Connect to FalkorDB. Defaults to localhost; set FALKORDB_* variables to use another instance."""
    kwargs = {"host": os.environ.get("FALKORDB_HOST", "localhost"),
              "port": int(os.environ.get("FALKORDB_PORT", "6379"))}
    if os.environ.get("FALKORDB_USERNAME"):
        kwargs["username"] = os.environ["FALKORDB_USERNAME"]
    if os.environ.get("FALKORDB_PASSWORD"):
        kwargs["password"] = os.environ["FALKORDB_PASSWORD"]
    if os.environ.get("FALKORDB_SSL") == "1":
        kwargs["ssl"] = True
    return FalkorDB(**kwargs)


db = connect()
g = db.select_graph("transport")
g.query("MATCH (n) DETACH DELETE n")
for stmt in ("CREATE INDEX FOR (s:Station) ON (s.stop_id)",
             "CREATE INDEX FOR (s:Station) ON (s.name)"):
    try:
        g.query(stmt)
    except Exception as e:
        print("(index skipped:", e, ")")

g.query("UNWIND $rows AS r "
        "CREATE (:Station {stop_id: r.id, name: r.name, lat: r.lat, lon: r.lon})",
        {"rows": nodes})

# Other names people use for the same station (so "Seva Teerth" finds Udyog Bhawan)
OTHER_NAMES = [
    {"name": "Udyog Bhawan", "alias": "Seva Teerth"},
    {"name": "Barakhamba", "alias": "Barakhamba Road"},
    {"name": "RK Ashram Marg", "alias": "Ramakrishna Ashram Marg"},
    {"name": "Jorbagh", "alias": "Jor Bagh"},
]
g.query("UNWIND $rows AS r MATCH (s:Station {name: r.name}) SET s.alias = r.alias",
        {"rows": OTHER_NAMES})

for i in range(0, len(edges), 300):
    g.query(
        """
        UNWIND $rows AS r
        MATCH (a:Station {stop_id: r.a}), (b:Station {stop_id: r.b})
        CREATE (a)-[:NEXT {line: r.line, minutes: r.minutes}]->(b)
        """,
        {"rows": edges[i:i + 300]},
    )

# ---- the place and the stations near it ----
g.query("CREATE (:Place {name: $n, lat: $lat, lon: $lon})",
        {"n": PLACE_NAME, "lat": PLACE_LAT, "lon": PLACE_LON})

near = []
for n in nodes:
    km = km_between(PLACE_LAT, PLACE_LON, n["lat"], n["lon"])
    if km <= NEAR_LIMIT_KM:
        near.append({"id": n["id"], "name": n["name"], "m": round(km * 1000),
                     "walk": max(1, round(km * STREET_FACTOR / WALK_KMH * 60))})
near.sort(key=lambda x: x["m"])
near = near[:NEAR_COUNT]

g.query(
    """
    UNWIND $rows AS r
    MATCH (p:Place {name: $place}), (s:Station {stop_id: r.id})
    CREATE (p)-[:NEAR {walk_min: r.walk, meters: r.m}]->(s)
    """,
    {"rows": near, "place": PLACE_NAME},
)

# ---- a real, reported closure event ----
# The reports and the data sometimes spell station names differently
ALIASES = {
    "barakhamba road": "barakhamba",
    "ramakrishna ashram marg": "rk ashram marg",
    "jor bagh": "jorbagh",
    "seva teerth": "udyog bhawan",   # renamed on 14 Feb 2026; the 2023 data uses the old name
    "dilli haat-ina": "ina",
    "guru teg bahadur nagar": "gtb nagar",
}


def norm(text):
    return " ".join(text.lower().replace("-", " ").replace(".", " ").split())


by_norm = {norm(n["name"]): n["name"] for n in nodes}


def match_station(reported):
    keys = [norm(ALIASES.get(reported.lower(), reported)), norm(reported)]
    for key in keys:
        if key in by_norm:
            return by_norm[key]
    for key in keys:
        hits = [v for k, v in by_norm.items() if key in k or k in key]
        if len(hits) == 1:
            return hits[0]
    close = difflib.get_close_matches(keys[-1], list(by_norm), n=1, cutoff=0.85)
    if close:
        print(f"  note: matched {reported!r} to {by_norm[close[0]]!r}")
        return by_norm[close[0]]
    return None


g.query(
    "CREATE (:Closure {id: $id, date: $date, description: $d, reason: $r, sources: $s})",
    {"id": EVENT["id"], "date": EVENT["date"], "d": EVENT["description"],
     "r": EVENT["reason"], "s": " | ".join(EVENT["sources"])},
)

closed_names = set()
for reported in EVENT["stations"]:
    name = match_station(reported)
    if name is None:
        close = difflib.get_close_matches(reported, list(by_norm.values()),
                                          n=3, cutoff=0.4)
        print(f"WARNING: no station in the data matches {reported!r}. "
              f"Closest names: {close}")
        continue
    g.query(
        """
        MATCH (c:Closure {id: $id}), (s:Station {name: $n})
        CREATE (c)-[:CLOSES {interchange_open: $ic}]->(s)
        """,
        {"id": EVENT["id"], "n": name, "ic": reported not in EVENT["no_interchange"]},
    )
    closed_names.add(name)

g.query(
    "MATCH (c:Closure {id: $id}) SET c.reported_count = $r, c.matched_count = $m",
    {"id": EVENT["id"], "r": len(EVENT["stations"]), "m": len(closed_names)},
)

# ---- report ----
print(f"\nStations: {len(nodes)}   NEXT edges: {len(edges)}")
print(f"\nStations nearest to {PLACE_NAME} (straight-line, walking time estimated):")
for x in near[:12]:
    status = "CLOSED" if x["name"] in closed_names else "open"
    print(f"  {x['name']}: {x['m']} m, about {x['walk']} min walk ({status})")

open_near = [x for x in near if x["name"] not in closed_names]
print(f"\nNearest OPEN stations during the event (of {len(near)} within {NEAR_LIMIT_KM} km):")
for x in open_near[:5]:
    print(f"  {x['name']}: {x['m']} m, about {x['walk']} min walk")
if not open_near:
    print("  none within the search radius")
print(f"Closed stations matched in the data: {len(closed_names)} of "
      f"{len(EVENT['stations'])}")

print("\nRajiv Chowk neighbours (check these against a map):")
rows = g.ro_query(
    "MATCH (:Station {name: 'Rajiv Chowk'})-[r:NEXT]->(b:Station) "
    "RETURN b.name, r.line, r.minutes ORDER BY r.line"
).result_set
for name, line, minutes in rows:
    print(f"  -> {name} ({line}, {minutes} min)")
