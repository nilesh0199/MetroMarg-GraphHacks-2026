import os

from falkordb import FalkorDB

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

MAX_DEPTH = 4


def resolve_station(name: str):
    """Return the exact station name if it exists in the graph, else None."""
    rows = g.ro_query(
        "MATCH (s:Station {name: $name}) RETURN s.name",
        {"name": name},
    ).result_set
    if rows:
        return rows[0][0]

    # Same name ignoring capitals, or a partial match (e.g. "Barakhamba Road"
    # vs "Barakhamba"), accepted only when exactly one station matches.
    rows = g.ro_query(
        """
        MATCH (s:Station)
        WHERE toLower(s.name) = toLower($name)
           OR toLower(s.alias) = toLower($name)
           OR toLower(s.name) CONTAINS toLower($name)
           OR toLower($name) CONTAINS toLower(s.name)
        RETURN DISTINCT s.name
        """,
        {"name": name.strip()},
    ).result_set
    return rows[0][0] if len(rows) == 1 else None


def impact(station: str, depth: int = 2) -> dict:
    """Which stations are within `depth` hops of this station, and by what route."""
    exact = resolve_station(station)
    if exact is None:
        return {"outcome": "unknown_station", "asked": station}

    depth = max(1, min(int(depth), MAX_DEPTH))  # int() makes this safe to format in

    rows = g.ro_query(
        f"""
        MATCH path = (s:Station)-[:NEXT*1..{depth}]->(t:Station {{name: $name}})
        WHERE s.name <> $name
        RETURN s.name AS station,
               length(path) AS hops,
               [n IN nodes(path) | n.name] AS via
        ORDER BY hops, station
        """,
        {"name": exact},
    ).result_set

    # Keep only the shortest route per station
    seen = {}
    for station_name, hops, via in rows:
        if station_name not in seen:
            seen[station_name] = {"station": station_name, "hops": hops, "via": via}

    results = list(seen.values())
    if not results:
        return {"outcome": "not_in_graph", "station": exact,
                "note": "No connections found. The network may not be fully modelled."}
    closed = [r[0] for r in g.ro_query(
        "MATCH (:Closure)-[:CLOSES]->(s:Station) RETURN DISTINCT s.name").result_set]
    return {"outcome": "answered_with_path", "station": exact,
            "depth": depth, "affected": results, "closed": closed}


def place_access(place: str) -> dict:
    """Stations near a place, nearest first, and whether each one is closed."""
    rows = g.ro_query(
        """
        MATCH (p:Place {name: $place})-[n:NEAR]->(s:Station)
        OPTIONAL MATCH (c:Closure)-[:CLOSES]->(s)
        RETURN s.name AS station, n.walk_min AS walk_min,
               c.id IS NOT NULL AS closed
        ORDER BY n.walk_min
        """,
        {"place": place},
    ).result_set

    if not rows:
        return {"outcome": "not_in_graph", "place": place}
    return {
        "outcome": "answered_with_path",
        "place": place,
        "stations": [{"station": s, "walk_min": w, "closed": bool(c)}
                     for s, w, c in rows],
    }


def critical_stations(limit: int = 10) -> dict:
    """Stations ranked by FalkorDB's PageRank over the NEXT links, with closure status."""
    limit = max(1, min(int(limit), 20))
    rows = g.ro_query(
        """
        CALL algo.pageRank('Station', 'NEXT')
        YIELD node, score
        RETURN node.name AS station, score
        ORDER BY score DESC
        LIMIT """ + str(limit)
    ).result_set
    if not rows:
        return {"outcome": "not_in_graph",
                "note": "The ranking returned nothing. The network may not be loaded."}

    closed = {r[0] for r in g.ro_query(
        "MATCH (:Closure)-[:CLOSES]->(s:Station) RETURN DISTINCT s.name").result_set}
    ranking = [{"rank": i + 1, "station": name, "score": round(score, 4),
                "closed": name in closed}
               for i, (name, score) in enumerate(rows)]
    return {"outcome": "answered_by_algorithm", "algorithm": "PageRank",
            "ranking": ranking,
            "closed_in_top": sum(1 for x in ranking if x["closed"])}


if __name__ == "__main__":
    for d in (1, 4):
        print(f"\n--- impact of Patel Chowk, depth {d} ---")
        r = impact("Patel Chowk", d)
        for a in r.get("affected", []):
            print(f"{a['hops']} hop(s): {a['station']}  via {' -> '.join(a['via'])}")

    print("\n--- access to Jantar Mantar ---")
    for s in place_access("Jantar Mantar")["stations"]:
        status = "CLOSED" if s["closed"] else "open"
        print(f"{s['station']}: {s['walk_min']} min walk ({status})")

    print("\n--- unknown station ---")
    print(impact("Hauz Khas Fake"))
