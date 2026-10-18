from falkordb import FalkorDB

db = FalkorDB(host="localhost", port=6379)
g = db.select_graph("transport")
g.query("CREATE (:Station {name: 'Patel Chowk'})")
print(g.ro_query("MATCH (s:Station) RETURN s.name").result_set)