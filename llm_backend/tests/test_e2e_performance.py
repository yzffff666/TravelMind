"""API-level E2E performance test.

Run against a live server to measure real latencies.
This is NOT a CI test — run manually:

    py -X utf8 tests/test_e2e_performance.py

Requires the backend server running on http://127.0.0.1:8000.
"""

import json
import statistics
import sys
import time

import requests

BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/api/travel/query"

TEST_CASES = [
    {"label": "Complete query", "query": "上海 4天 预算6000 文化 美食"},
    {"label": "Missing P0 (early exit)", "query": "想去海边玩几天"},
    {"label": "Beijing 3-day", "query": "北京 3天 预算5000 亲子"},
]


def measure_sse_events(query: str, user_id: int = 1) -> dict:
    """POST to the travel/query endpoint and measure SSE event timings."""
    session = requests.Session()
    session.trust_env = False

    form = {"query": query, "user_id": str(user_id)}

    t_start = time.perf_counter()
    resp = session.post(ENDPOINT, data=form, stream=True, timeout=120)
    t_first_byte = time.perf_counter()

    events = []
    buffer = ""
    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        if chunk:
            buffer += chunk
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                t_event = time.perf_counter()
                event_type = None
                data_obj = None
                for line in frame.strip().split("\n"):
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        try:
                            data_obj = json.loads(line[6:])
                        except (json.JSONDecodeError, ValueError):
                            pass
                events.append({
                    "type": event_type,
                    "elapsed_ms": (t_event - t_start) * 1000,
                    "data": data_obj,
                })

    t_end = time.perf_counter()

    result = {
        "ttfb_ms": (t_first_byte - t_start) * 1000,
        "total_ms": (t_end - t_start) * 1000,
        "events": events,
    }

    for ev in events:
        if ev["type"] == "pipeline_complete":
            result["pipeline_complete_ms"] = ev["elapsed_ms"]
        elif ev["type"] == "day_ready" and "first_day_ready_ms" not in result:
            result["first_day_ready_ms"] = ev["elapsed_ms"]
        elif ev["type"] == "final_itinerary":
            result["final_itinerary_ms"] = ev["elapsed_ms"]
        elif ev["type"] == "final_text":
            result["final_text_ms"] = ev["elapsed_ms"]

    return result


def run_tests():
    print("=" * 70)
    print("TravelMind E2E Performance Test")
    print("=" * 70)

    try:
        health = requests.get(f"{BASE_URL}/docs", timeout=5)
        if health.status_code != 200:
            print(f"Server not reachable at {BASE_URL}")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"Cannot connect to {BASE_URL}. Is the server running?")
        sys.exit(1)

    for tc in TEST_CASES:
        print(f"\n--- {tc['label']} ---")
        print(f"Query: {tc['query']}")

        result = measure_sse_events(tc["query"])

        print(f"  TTFB:               {result['ttfb_ms']:>8.1f} ms")
        if "pipeline_complete_ms" in result:
            print(f"  Pipeline Complete:   {result['pipeline_complete_ms']:>8.1f} ms")
        if "first_day_ready_ms" in result:
            print(f"  First Day Ready:    {result['first_day_ready_ms']:>8.1f} ms")
        if "final_itinerary_ms" in result:
            print(f"  Final Itinerary:    {result['final_itinerary_ms']:>8.1f} ms")
        if "final_text_ms" in result:
            print(f"  Final Text:         {result['final_text_ms']:>8.1f} ms")
        print(f"  Total:              {result['total_ms']:>8.1f} ms")

        event_types = [e["type"] for e in result["events"] if e["type"]]
        print(f"  Events: {' -> '.join(event_types)}")

        # Print perf dict if available from final_itinerary
        for ev in result["events"]:
            if ev["type"] == "final_itinerary" and ev.get("data"):
                perf = ev["data"].get("payload", {}).get("perf")
                if perf:
                    print(f"  Node timings:")
                    for k, v in perf.items():
                        if v is not None:
                            print(f"    {k}: {v:.1f} ms")

    print("\n" + "=" * 70)
    print("Done.")


if __name__ == "__main__":
    run_tests()
