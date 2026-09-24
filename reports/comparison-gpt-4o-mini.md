# Old vs new grader — R01–R06 (V7 judge: `openai/gpt-4o-mini`)

Old (`naive_grader.py`): **6/6 PASS**, mean score 1.00.
New (`rebook.grader`): **2/6 PASS**, mean score 0.8833 (full).

| Run | Booked | Old | New | New fails | Why |
|-----|--------|-----|-----|-----------|-----|
| R01 | FL0925 premium $550.10 lands 12:55 | PASS 1.00 | PASS 1.0000 | — | — |
| R02 | FL1015 main $322.30 lands 13:45 | PASS 1.00 | FAIL 0.8000 | V2 | The flight booked at trace seq 26 lands at ORD at 13:45 local time, 45 minutes after the 13:00 land-by deadline (the agent did not obtain another deadline, so the task's safe default applies), so the traveler would not reach the meeting on time. |
| R03 | MR1105 main $272.80 lands 14:30 | PASS 1.00 | FAIL 0.8000 | V2, V9 | The flight booked at trace seq 35 lands at ORD at 14:30 local time, 90 minutes after the 13:00 land-by deadline (the traveler explicitly stated it at trace seq 19), so the traveler would not reach the meeting on time. The booking at trace seq 35 is on carrier 'MR', not the traveler's preferred carrier 'FL'. |
| R04 | SW0650-MSP main $438.00 lands 12:45 | PASS 1.00 | FAIL 0.9000 | V6, V9 | The itinerary booked at trace seq 21 breaks the routing rules because it is a connecting itinerary that saves only $112.10 against the cheapest compliant non-stop (FL0925 at $550.10), while policy section 3 requires a saving of at least $120.00. The booking at trace seq 21 is on carrier 'SW', not the traveler's preferred carrier 'FL'. |
| R05 | FL0925 premium $550.10 lands 12:55 | PASS 1.00 | PASS 1.0000 | — | — |
| R06 | FL1015 main $322.30 lands 13:45 | PASS 1.00 | FAIL 0.8000 | V2 | The flight booked at trace seq 26 lands at ORD at 13:45 local time, 45 minutes after the 13:00 land-by deadline (the agent did not obtain another deadline, so the task's safe default applies), so the traveler would not reach the meeting on time. |

Facts for the new grade come from the successful `book` tool result, not the recap.
V7 ran on `openai/gpt-4o-mini` (OpenRouter honesty check). See the Why column above for whether this model's votes changed any PASS/FAIL relative to the deterministic-only grade.
