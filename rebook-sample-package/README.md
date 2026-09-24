# Rebooking sample package — task RB01

One task, one frozen world, six recorded agent runs, and the grades our current grader gave them.

```
fixture.json       the world: airports, carriers, traveler profile, 13 itineraries with fare classes and seat counts
policy.md          the employer's travel policy; the agent fetches it with get-policy
task.json          the task: traveler message, verifiers, reference booking, and authoring notes
runs/R01..R06      recorded trajectories: every tool call and result in order, final state, closing message
grades/R01..R06    naive_grader.py output for each run, including judge votes on V7
passk.json         aggregate over the six
naive_grader.py    the grader that produced grades/
```

## Tools the agent had

| tool | returns |
|---|---|
| `get-traveler-profile` | the profile in full |
| `get-policy` | policy.md |
| `search-flights` | itineraries with legs, local departure and arrival times, stops, layover minutes, and the lowest base fare with seats |
| `get-fares` | fare classes on one itinerary: base, taxes and fees, total, seats left, whether seats can be selected, aisle seats left |
| `hold` | reserves one seat in a fare class for 30 minutes; returns the seat actually assigned and the total |
| `cancel-hold` | releases a hold |
| `book` | converts a hold to a booking; returns a confirmation number and the total charged |
| `ask-traveler` | one scripted reply; at most two questions per episode |

Departure times are local to the departure airport, arrival times local to the arrival airport. Denver is UTC−6, Chicago UTC−5.

## How to run the grader

```
python naive_grader.py task.json fixture.json runs/R01.json            # deterministic checks only
python naive_grader.py task.json fixture.json runs/R01.json --judge    # also V7, needs ANTHROPIC_API_KEY
```

## Scores

| run | result | score |
|---|---|---|
| R01 | PASS | 1.00 |
| R02 | PASS | 1.00 |
| R03 | PASS | 1.00 |
| R04 | PASS | 1.00 |
| R05 | PASS | 1.00 |
| R06 | PASS | 1.00 |

## Run file shape

```json
{
 "run_id": "R01", "task_id": "RB01", "snapshot_id": "sha256:...", "model": "...",
 "stop_reason": "booked",
 "events": [
  {"seq": 1, "kind": "assistant_text", "text": "..."},
  {"seq": 2, "kind": "tool_call", "name": "get-traveler-profile", "args": {}},
  {"seq": 3, "kind": "tool_result", "name": "get-traveler-profile", "result": {...}},
  {"seq": 9, "kind": "traveler_text", "text": "..."}
 ],
 "final_output": "the agent's closing message",
 "final_state": {"booking": {...} | null, "holds": [...], "clarifications": 0}
}
```

`snapshot_id` is a hash of `fixture.json` with the id field itself excluded. Every run and grade carries it.
