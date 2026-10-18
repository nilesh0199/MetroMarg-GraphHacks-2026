import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from textwrap import dedent

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import agent  # sets up the graph connection and the Gemini client

api = FastAPI(title="MetroMarg")
app = api  # some hosts, such as Vercel, look for an object named app
lock = threading.Lock()  # the agent keeps its trace in shared lists, so one question at a time


# Saved answers. The file next to this script ships with the repository. On hosts with a
# read-only disk (such as Vercel) new answers go to a temporary folder instead.
CACHE_FILE = Path(__file__).with_name("answer_cache.json")
TEMP_CACHE_FILE = Path(tempfile.gettempdir()) / "metromarg_answer_cache.json"


def load_cache() -> dict:
    cache = {}
    for path in (CACHE_FILE, TEMP_CACHE_FILE):
        try:
            cache.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cache


def save_cache(cache: dict) -> None:
    for path in (CACHE_FILE, TEMP_CACHE_FILE):
        try:
            path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
            return
        except OSError:
            continue  # read-only disk: try the next location


def current_event():
    """The closure event stored in the graph, or None."""
    rows = agent.g.ro_query(
        "MATCH (c:Closure) RETURN c.id, c.date, c.description, c.reason, c.sources, "
        "c.reported_count, c.matched_count LIMIT 1"
    ).result_set
    if not rows:
        return None
    event_id, date, description, reason, sources, reported, matched = rows[0]
    count = agent.g.ro_query(
        "MATCH (:Closure)-[:CLOSES]->(s:Station) RETURN count(DISTINCT s)"
    ).result_set[0][0]
    return {"id": event_id, "date": date, "description": description, "reason": reason,
            "sources": (sources or "").split(" | "), "closed_count": count,
            "reported_count": reported, "matched_count": matched}


def cache_key(question: str, event_id: str) -> str:
    # saved answers belong to one closure event, so an old event never shows up here
    return event_id + "|" + " ".join(question.lower().split())


class Question(BaseModel):
    question: str


@api.get("/")
def index():
    return FileResponse(Path(__file__).with_name("index.html"))


@api.get("/api/event")
def event():
    with lock:
        return current_event() or {"error": "No closure event in the graph."}


@api.post("/api/ask")
def ask(q: Question):
    text = q.question.strip()
    if not text:
        return {"error": "Type a question first."}
    with lock:
        try:
            answer = agent.ask(text)
        except Exception as e:  # show real problems (bad key, bad model name) on the page
            return {"error": f"{type(e).__name__}: {e}"}

        seen, queries = set(), []
        for q_text, params in agent.QUERIES:
            clean = "\n".join(line for line in dedent(q_text).strip().splitlines()
                              if line.strip())
            # the route search is tried at several depths; show that query once
            shape = re.sub(r"\*1\.\.\d+", "*1..N", clean)
            if shape not in seen:
                seen.add(shape)
                queries.append({"text": clean, "params": params})

        payload = {
            "answer": answer,
            "results": list(agent.RESULTS),
            "trace": [{"tool": t["tool"], "args": str(t["args"]),
                       "ms": t["ms"], "outcome": t["outcome"]} for t in agent.TRACE],
            "queries": queries,
        }

        cache = load_cache()
        event = current_event()
        key = cache_key(text, event["id"] if event else "")
        if answer.startswith(agent.BUSY_PREFIX):
            # The language model was unavailable. Reuse an earlier answer if we have one,
            # and say so on the page.
            if key in cache:
                return {**cache[key], "cached": True}
            return payload
        if not answer.startswith("[answer rejected"):
            cache[key] = payload
            save_cache(cache)
        return payload


def ensure_graph():
    """If the database restarted empty, rebuild the graph from the DMRC timetable."""
    try:
        count = agent.g.ro_query("MATCH (s:Station) RETURN count(s)").result_set[0][0]
    except Exception:
        count = 0
    if count > 0:
        print(f"Graph ready: {count} stations.")
        return

    here = Path(__file__).parent
    zip_path, importer = here / "dmrc_gtfs.zip", here / "import_gtfs.py"
    if not (zip_path.exists() and importer.exists()):
        print("The graph is empty, and dmrc_gtfs.zip or import_gtfs.py is missing "
              "from this folder. Run: python import_gtfs.py dmrc_gtfs.zip")
        return

    print("The graph is empty. Rebuilding it from dmrc_gtfs.zip ...")
    subprocess.run([sys.executable, str(importer), str(zip_path)], check=False)
    # the agent's list of valid station names was read before the rebuild
    agent.ALL_STATIONS[:] = [r[0] for r in
                             agent.g.ro_query("MATCH (s:Station) RETURN s.name").result_set]


if __name__ == "__main__":
    ensure_graph()
    host = os.environ.get("HOST", "127.0.0.1")  # set HOST=0.0.0.0 when hosting
    port = int(os.environ.get("PORT", "8000"))
    print(f"Open http://localhost:{port} in your browser")
    uvicorn.run(api, host=host, port=port)
