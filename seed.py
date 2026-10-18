from falkordb import FalkorDB

db = FalkorDB(host="localhost", port=6379)
g = db.select_graph("transport")

# Start clean so you can re-run this script safely
g.query("MATCH (n) DETACH DELETE n")

# Station order along each line (central Delhi segment only).
# Double-check the order against the official DMRC map before the final demo.
LINES = {
    "Yellow": ["Chawri Bazar", "New Delhi", "Rajiv Chowk", "Patel Chowk",
               "Central Secretariat", "Udyog Bhawan"],
    "Blue":   ["Jhandewalan", "RK Ashram Marg", "Rajiv Chowk",
               "Barakhamba Road", "Mandi House"],
    "Violet": ["ITO", "Mandi House", "Janpath", "Central Secretariat",
               "Khan Market", "JLN Stadium"],
}

# Adjacent stations get a NEXT edge in both directions.
# minutes=2 is a rough placeholder, not real timetable data.
for line, stations in LINES.items():
    for a, b in zip(stations, stations[1:]):
        g.query(
            """
            MERGE (x:Station {name: $a})
            MERGE (y:Station {name: $b})
            CREATE (x)-[:NEXT {line: $line, minutes: 2}]->(y)
            CREATE (y)-[:NEXT {line: $line, minutes: 2}]->(x)
            """,
            {"a": a, "b": b, "line": line},
        )

# A place and the stations near it. Walk times are rough guesses to refine later.
g.query("CREATE (:Place {name: 'Jantar Mantar'})")
for station, walk in [("Patel Chowk", 8), ("Rajiv Chowk", 15), ("Janpath", 12)]:
    g.query(
        """
        MATCH (p:Place {name: 'Jantar Mantar'}), (s:Station {name: $s})
        CREATE (p)-[:NEAR {walk_min: $w}]->(s)
        """,
        {"s": station, "w": walk},
    )

# A simulated closure event, stored in the graph. Replace with real data later.
g.query(
    """
    MATCH (s:Station {name: 'Patel Chowk'})
    CREATE (c:Closure {id: 'demo-1',
                       reason: 'Simulated crowd-event closure',
                       simulated: true})
    CREATE (c)-[:CLOSES]->(s)
    """
)

# Quick checks
stations = g.ro_query("MATCH (s:Station) RETURN count(s)").result_set[0][0]
edges = g.ro_query("MATCH ()-[r:NEXT]->() RETURN count(r)").result_set[0][0]
print(f"Stations: {stations}, NEXT edges: {edges}")

# Everything within 2 hops of Patel Chowk, with the route taken
rows = g.ro_query(
    """
    MATCH path = (s:Station)-[:NEXT*1..2]->(:Station {name: 'Patel Chowk'})
    RETURN DISTINCT s.name AS station,
           length(path) AS hops,
           [n IN nodes(path) | n.name] AS via
    ORDER BY hops, station
    """
).result_set
for station, hops, via in rows:
    print(f"{hops} hop(s): {station}  via {' -> '.join(via)}")