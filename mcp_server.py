"""MCP server for MetroMarg.

Exposes the same fixed, human-written graph tools to any MCP client. The client's model
chooses a tool and fills in the arguments. It never writes a query: every query lives
in tools.py and routing.py, and every station name is checked against the graph first.

Run it from an MCP client (see README), or test it with the MCP Inspector:
    npx @modelcontextprotocol/inspector python mcp_server.py
"""
from mcp.server.fastmcp import FastMCP

from routing import route, trip_to_place
from tools import critical_stations, impact, place_access

mcp = FastMCP("metromarg")


@mcp.tool()
def station_impact(station: str, depth: int = 2) -> dict:
    """Stations within `depth` hops (max 4) of a station, with the route to each,
    and which stations are closed in the current closure event."""
    return impact(station, depth)


@mcp.tool()
def access_to_place(place: str) -> dict:
    """Stations near a place such as 'Jantar Mantar', nearest first, and whether each is closed."""
    return place_access(place)


@mcp.tool()
def find_route(from_station: str, to_station: str) -> dict:
    """Normal route between two stations and the route while the closure applies."""
    return route(from_station, to_station)


@mcp.tool()
def plan_trip_to_place(from_station: str, place: str) -> dict:
    """Best way to reach a place from a station: metro ride plus walking, normally and
    during the closure, with extra minutes."""
    return trip_to_place(from_station, place)


@mcp.tool()
def most_connected_stations(limit: int = 10) -> dict:
    """Rank stations by how connected they are (FalkorDB PageRank), and say which were closed."""
    return critical_stations(limit)


if __name__ == "__main__":
    mcp.run()  # talks to the client over stdio, so nothing else may print to stdout
