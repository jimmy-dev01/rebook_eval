"""`python -m rebook`: check the client's files and show the baseline the new grader has to beat."""
import json

from rebook.baseline import load_naive_grader
from rebook.paths import CLIENT


def load(name):
    return json.loads((CLIENT / name).read_text(encoding="utf-8"))


def main():
    fixture, task = load("fixture.json"), load("task.json")
    runs = [load(f"runs/{p.name}") for p in sorted((CLIENT / "runs").glob("*.json"))]
    print(f"Task {task['task_id']}: {len(fixture['flights'])} itineraries, "
          f"snapshot {fixture['meta']['snapshot_id']}, {len(runs)} recorded runs")

    naive = load_naive_grader()
    print("\nBaseline: the client's grader (naive_grader.py), run without a judge")
    for run in runs:
        grade = naive.grade(run, task, fixture)
        b = run["final_state"]["booking"]
        booked = f"{b['itinerary_id']} {b['fare_class']}, ${b['total_charged']:.2f}, lands {b['arr_local']}" if b else "no booking"
        print(f"  {run['run_id']}  {booked:<38} {grade['result']} {grade['score']:.2f}")
    print("\nThe old grader also counts the missing judge (V7) as a pass.")
    print(
        "Implemented: eight-tool environment, deterministic replay, private/public "
        "boundary, and the V1–V7 reward path."
    )
    print("Run `make replay`, `make grade`, or `make regrade` for the new pipeline.")


if __name__ == "__main__":
    main()
