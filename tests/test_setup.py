"""Checks on the starting point: the client's files are all here, unchanged, and consistent with each other."""
import hashlib
import json

from rebook.baseline import load_naive_grader
from rebook.paths import CLIENT, ROOT

RUN_IDS = ["R01", "R02", "R03", "R04", "R05", "R06"]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_client_files_are_unchanged():
    """Every client file matches the checksum taken when it was copied, with none missing and none added."""
    expected = {}
    for line in (ROOT / "client-files.sha256").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        expected[name] = digest
    actual = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in CLIENT.rglob("*") if p.is_file() and not p.name.startswith(".")}
    assert actual == expected


def test_snapshot_ids_agree():
    """The fixture, the task, and every run and grade name the same frozen world."""
    sid = load(CLIENT / "fixture.json")["meta"]["snapshot_id"]
    assert load(CLIENT / "task.json")["snapshot_id"] == sid
    for rid in RUN_IDS:
        assert load(CLIENT / "runs" / f"{rid}.json")["snapshot_id"] == sid, rid
        assert load(CLIENT / "grades" / f"{rid}.json")["snapshot_id"] == sid, rid


def test_old_grader_reproduces_shipped_grades():
    """Rerun here, the client's grader gives the shipped verdicts, so our baseline matches theirs."""
    naive = load_naive_grader()
    task, fixture = load(CLIENT / "task.json"), load(CLIENT / "fixture.json")
    for rid in RUN_IDS:
        regraded = naive.grade(load(CLIENT / "runs" / f"{rid}.json"), task, fixture)
        shipped = load(CLIENT / "grades" / f"{rid}.json")
        for new, old in zip(regraded["verifiers"], shipped["verifiers"]):
            if new["type"] == "judged":
                continue  # V7 needs a live judge; the shipped votes came from one
            assert (new["id"], new["pass"], new["evidence"]) == (old["id"], old["pass"], old["evidence"]), rid
        assert regraded["result"] == shipped["result"], rid
