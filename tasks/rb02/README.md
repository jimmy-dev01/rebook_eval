# RB02 — data-only second task (extension)

Same fixture and policy as RB01. Differences are **task.json only** plus one
new registry `check_type`:

- V2 land-by deadline is **14:00** ORD (was 13:00 on RB01)
- **V10** `nonstop_required` — connections are forbidden (`max_stops: 0`)

No environment rewrite. Load with:

```python
from rebook.env import reset
from rebook.paths import ROOT
session = reset(ROOT / "tasks" / "rb02")
```

Grading:

```python
from rebook.grader import grade_run
# task/fixture from tasks/rb02/
```
