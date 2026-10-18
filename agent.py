import functools
import json
import os
import sys
import time

from google import genai
from google.genai import errors, types

from tools import g, impact, place_access, critical_stations
from routing import route, trip_to_place

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    sys.exit("Set your key first:  set GEMINI_API_KEY=your_key_here")

client = genai.Client(api_key=API_KEY)
MODEL = "gemini-3.8-flash"  # if this errors, use a current model name from AI Studio
MODELS = [MODEL, "gemini-3.7-flash", "gemini-3.6-flash"]  # tried in order if one is busy
BUSY_PREFIX = "The language model"  # messages that start with this mean the model was unavailable

SYSTEM = """You are a transit disruption assistant for a small Delhi Metro graph.
Rules:
- Answer ONLY from tool results. Never use your own knowledge of Delhi Metro.
- Always call a tool before answering questions about the metro network. Never invent
  station names or times.
- If the question is not about the Delhi Metro network (stations, routes, closures,
  places), call no tool at all.
- If a result says unknown_station, say that station is not in the graph.
- If a result says not_in_graph, say nothing connects it in the graph, which may
  mean the link is not modelled. Do NOT say it is safe or unaffected.
- A closed station means entry and exit are shut: nobody can board or leave a train
  there. Trains still run through it, and passengers can change trains only at
  stations where interchange is open. Never say a train does not run.
- Walking times are estimates. Say "about" when you give them.
- Use the single most relevant tool. Call a second tool only if the first result
  cannot answer the question.
- If a result is endpoint_closed and lists nearest_open stations, say the person
  cannot board or leave there, and name the nearest open stations with the walking
  minutes. Never say the journey is impossible.
- Mention the route (the stations in order) and any extra minutes.
- Keep the answer to 2 or 3 sentences."""

TRACE = []     # what the judges see: tool, arguments, time, outcome
RESULTS = []   # raw results, used to check the final sentence


def traced(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.time()
        out = fn(*args, **kwargs)
        TRACE.append({
            "tool": fn.__name__,
            "args": kwargs or args,
            "ms": round((time.time() - start) * 1000),
            "outcome": out.get("outcome"),
        })
        RESULTS.append(out)
        return out
    return wrapper


# The model sees these names, type hints and docstrings
@traced
def station_impact(station: str, depth: int = 2) -> dict:
    """Stations within `depth` hops (max 4) of a station, with the route to each."""
    return impact(station, depth)


@traced
def access_to_place(place: str) -> dict:
    """Stations near a place such as 'Jantar Mantar', nearest first, and whether each is closed."""
    return place_access(place)


@traced
def find_route(from_station: str, to_station: str) -> dict:
    """Normal route and the detour while closures apply, with extra minutes."""
    return route(from_station, to_station)


@traced
def most_connected_stations(limit: int = 10) -> dict:
    """Rank stations by how connected they are (FalkorDB PageRank), and say which were closed."""
    return critical_stations(limit)


@traced
def plan_trip_to_place(from_station: str, place: str) -> dict:
    """Best way to reach a place such as 'Jantar Mantar' from a station: metro ride
    plus walking, normally and while closures apply, with extra minutes."""
    return trip_to_place(from_station, place)


ALL_STATIONS = [r[0] for r in g.ro_query("MATCH (s:Station) RETURN s.name").result_set]

# Record every query the tools run, so the CLI can show "the queries behind this answer"
QUERIES = []
_original_ro_query = g.ro_query


def _logged_ro_query(q, params=None, *args, **kwargs):
    QUERIES.append((q, params))
    return _original_ro_query(q, params, *args, **kwargs)


g.ro_query = _logged_ro_query


def accepts(sentence: str):
    """Reject answers that name stations the tools never returned."""
    if not TRACE:
        return False, "no tool was called"
    blob = json.dumps(RESULTS).lower()
    text = sentence.lower()
    invented = [s for s in ALL_STATIONS if s.lower() in text and s.lower() not in blob]
    if invented:
        return False, f"named stations not in the results: {invented}"
    return True, "ok"


def ask(question: str) -> str:
    resp, last_code = None, None
    for model in MODELS:
        for attempt in range(4):
            TRACE.clear()
            RESULTS.clear()
            QUERIES.clear()
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=question,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM,
                        tools=[station_impact, access_to_place, find_route, plan_trip_to_place,
                               most_connected_stations],
                        temperature=0,
                    ),
                )
                break
            except errors.APIError as e:
                last_code = getattr(e, "code", None)
                if last_code not in (429, 500, 503):
                    raise  # a real problem (bad key, bad model name), so show it
                if last_code == 429:
                    break  # rate limit: retrying the same model only makes it worse
                time.sleep(2 ** (attempt + 1))  # busy server: wait 2, 4, 8, 16 seconds
        if resp is not None:
            break
    if resp is None:
        if last_code == 429:
            return (f"{BUSY_PREFIX}'s usage limit has been reached (error 429). "
                    "Wait a minute and try again.")
        return (f"{BUSY_PREFIX} is busy right now (error {last_code}). "
                "Please try again in a moment.")
    sentence = resp.text or ""
    ok, why = accepts(sentence)
    if not ok:
        if not TRACE:
            return ("I can only answer from the graph. Try asking about a station "
                    "closure, a route, or access to Jantar Mantar.")
        return f"[answer rejected: {why}]\n" + json.dumps(RESULTS, indent=1)[:1500]
    return sentence


if __name__ == "__main__":
    print("Ask about the network (empty line to quit).")
    while True:
        q = input("\n> ").strip()
        if not q:
            break
        print("\n" + ask(q))
        print("\nTrace:")
        for t in TRACE:
            print(f"  {t['tool']} {t['args']}  {t['ms']} ms  -> {t['outcome']}")
