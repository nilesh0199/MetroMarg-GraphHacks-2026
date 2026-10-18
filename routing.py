from tools import g, resolve_station, place_access

MAX_HOPS = 8

NOT_ALLOWED_BOARDING = ("Entry and exit are closed at this station, so you cannot "
                        "board or leave a train there.")


def closure_info():
    """Closed stations (entry and exit shut), and those where you also cannot change trains."""
    rows = g.ro_query(
        """
        MATCH (:Closure)-[x:CLOSES]->(s:Station)
        RETURN DISTINCT s.name, x.interchange_open
        """
    ).result_set
    closed = [name for name, _ in rows]
    no_transfer = [name for name, interchange_open in rows if not interchange_open]
    return closed, no_transfer


WALK_KMH, STREET_FACTOR = 4.5, 1.3


def nearest_open_stations(name: str, closed: list, limit: int = 3) -> list:
    """Open stations closest to a station, with an estimated walking time."""
    try:
        rows = g.ro_query(
            """
            MATCH (o:Station {name: $name}), (s:Station)
            WHERE NOT (s.name IN $closed)
            RETURN s.name AS station,
                   distance(point({latitude: o.lat, longitude: o.lon}),
                            point({latitude: s.lat, longitude: s.lon})) AS meters
            ORDER BY meters
            LIMIT """ + str(int(limit)),
            {"name": name, "closed": closed},
        ).result_set
    except Exception:
        return []
    return [{"station": s, "meters": round(m),
             "walk_min": max(1, round(m / 1000 * STREET_FACTOR / WALK_KMH * 60))}
            for s, m in rows]


def _best_route(a: str, b: str, no_transfer: list):
    """Fastest ride from a to b. Trains run through closed stations, but you cannot
    change lines at a station listed in no_transfer."""
    transfer_rule = ""
    if no_transfer:
        transfer_rule = """
            WHERE all(i IN range(0, size(relationships(path)) - 2)
                      WHERE NOT (nodes(path)[i + 1].name IN $no_transfer)
                         OR relationships(path)[i].line = relationships(path)[i + 1].line)
        """
    # Try short searches first: long searches get expensive on a big network
    for max_hops in (3, 5, MAX_HOPS):
        rows = g.ro_query(
            f"""
            MATCH path = (x:Station {{name: $a}})-[:NEXT*1..{max_hops}]->(y:Station {{name: $b}})
            {transfer_rule}
            RETURN [n IN nodes(path) | n.name] AS via,
                   reduce(t = 0, r IN relationships(path) | t + r.minutes) AS minutes
            ORDER BY minutes
            LIMIT 1
            """,
            {"a": a, "b": b, "no_transfer": no_transfer},
        ).result_set
        if rows:
            return {"via": rows[0][0], "minutes": round(rows[0][1], 1)}
    return None


def route(frm: str, to: str) -> dict:
    a, b = resolve_station(frm), resolve_station(to)
    if a is None or b is None:
        unknown = [n for n, r in ((frm, a), (to, b)) if r is None]
        return {"outcome": "unknown_station", "asked": unknown}

    closed, no_transfer = closure_info()
    if a in closed or b in closed:
        return {"outcome": "endpoint_closed", "note": NOT_ALLOWED_BOARDING,
                "closed": [s for s in (a, b) if s in closed],
                "nearest_open": {s: nearest_open_stations(s, closed)
                                 for s in (a, b) if s in closed}}

    normal = _best_route(a, b, [])
    detour = _best_route(a, b, no_transfer)

    if normal is None:
        return {"outcome": "not_in_graph", "from": a, "to": b,
                "note": "No route found. The link may not be modelled."}
    if detour is None:
        return {"outcome": "no_route_while_closed", "from": a, "to": b,
                "normal": normal, "closed": closed}
    return {
        "outcome": "answered_with_path",
        "from": a, "to": b,
        "closed": closed,
        "normal": normal,
        "detour": detour,
        "extra_minutes": round(detour["minutes"] - normal["minutes"], 1),
    }


def _option(frm: str, station: str, walk: int, no_transfer: list):
    """Ride from `frm` to `station`, then walk to the place."""
    if frm == station:
        ride = {"via": [frm], "minutes": 0}
    else:
        ride = _best_route(frm, station, no_transfer)
    if ride is None:
        return None
    return {"station": station, "via": ride["via"], "ride": ride["minutes"],
            "walk": walk, "minutes": round(ride["minutes"] + walk, 1)}


def trip_to_place(frm: str, place: str) -> dict:
    """Best way from a station to a place: ride + walk, normally vs during the closure."""
    a = resolve_station(frm)
    if a is None:
        return {"outcome": "unknown_station", "asked": [frm]}

    access = place_access(place)
    if access["outcome"] != "answered_with_path":
        return {"outcome": "not_in_graph", "place": place,
                "note": "That place is not in the graph."}

    closed, no_transfer = closure_info()
    if a in closed:
        return {"outcome": "endpoint_closed", "note": NOT_ALLOWED_BOARDING,
                "closed": [a],
                "nearest_open": {a: nearest_open_stations(a, closed)}}

    near = access["stations"]
    # Normally you can get off at any nearby station.
    # Walking time dominates, so only the nearest few candidates can win.
    normal = [o for s in near[:6]
              for o in [_option(a, s["station"], s["walk_min"], [])] if o]
    # During the closure you can only get off at a station that is open.
    open_near = [s for s in near if s["station"] not in closed][:8]
    detour = [o for s in open_near
              for o in [_option(a, s["station"], s["walk_min"], no_transfer)] if o]

    if not normal:
        return {"outcome": "not_in_graph", "place": place,
                "note": "No route found. The link may not be modelled."}

    best_normal = min(normal, key=lambda o: o["minutes"])
    if not detour:
        return {"outcome": "no_route_while_closed", "from": a, "place": place,
                "normal": best_normal, "closed": closed}

    best_detour = min(detour, key=lambda o: o["minutes"])
    return {
        "outcome": "answered_with_path",
        "from": a, "place": place, "closed": closed,
        "normal": best_normal, "detour": best_detour,
        "extra_minutes": round(best_detour["minutes"] - best_normal["minutes"], 1),
    }


if __name__ == "__main__":
    for frm, to in [("Chawri Bazar", "Jhandewalan"),
                    ("Rajiv Chowk", "Central Secretariat"),
                    ("Atlantis Central", "Jhandewalan")]:
        r = route(frm, to)
        print(f"\n{frm} -> {to}: {r['outcome']}")
        if r["outcome"] == "answered_with_path":
            print("  normal:", " -> ".join(r["normal"]["via"]), f"({r['normal']['minutes']} min)")
            print("  closed:", " -> ".join(r["detour"]["via"]), f"({r['detour']['minutes']} min)")
        else:
            print(" ", r)

    for frm in ("Chawri Bazar", "Jhandewalan", "Mandi House"):
        r = trip_to_place(frm, "Jantar Mantar")
        print(f"\n{frm} -> Jantar Mantar: {r['outcome']}")
        if r["outcome"] == "answered_with_path":
            for label in ("normal", "detour"):
                o = r[label]
                print(f"  {label}: get off at {o['station']}: {o['ride']} ride + "
                      f"{o['walk']} walk = {o['minutes']} min")
            print("  extra:", r["extra_minutes"], "min")
        else:
            print(" ", r)
