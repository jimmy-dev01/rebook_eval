"""Step 6: persist new grades and an old-vs-new comparison."""
from __future__ import annotations

from pathlib import Path

import pytest

from rebook.grader.regrade import model_label, regrade_shipped


def test_regrade_writes_grades_and_comparison(tmp_path: Path):
    comparison = regrade_shipped(out_dir=tmp_path)
    assert comparison["old"]["pass_count"] == 6
    assert comparison["new"]["pass_count"] == 2

    by_id = {row["run_id"]: row for row in comparison["runs"]}
    assert by_id["R01"]["new_result"] == "PASS"
    assert by_id["R05"]["new_result"] == "PASS"
    assert by_id["R02"]["new_failed"] == ["V2"]
    assert by_id["R03"]["new_failed"] == ["V2", "V9"]
    assert by_id["R04"]["new_failed"] == ["V6", "V9"]
    assert by_id["R06"]["new_failed"] == ["V2"]
    assert "13:45" in by_id["R02"]["why"]
    assert "$112.10" in by_id["R04"]["why"]

    for run_id in ("R01", "R02", "R03", "R04", "R05", "R06"):
        assert (tmp_path / "grades" / f"{run_id}.json").is_file()
    assert (tmp_path / "comparison.md").is_file()
    assert (tmp_path / "comparison.json").is_file()
    assert (tmp_path / "passk.json").is_file()


def test_label_writes_separate_files_and_does_not_touch_unlabeled_ones(tmp_path: Path):
    regrade_shipped(out_dir=tmp_path)  # unlabeled first, as if run earlier
    regrade_shipped(out_dir=tmp_path, label="some-model")

    # Labeled outputs exist alongside, not instead of, the unlabeled ones.
    assert (tmp_path / "comparison.md").is_file()
    assert (tmp_path / "comparison-some-model.md").is_file()
    assert (tmp_path / "comparison-some-model.json").is_file()
    assert (tmp_path / "passk-some-model.json").is_file()
    for run_id in ("R01", "R02", "R03", "R04", "R05", "R06"):
        assert (tmp_path / "grades-some-model" / f"{run_id}.json").is_file()

    text = (tmp_path / "comparison-some-model.md").read_text(encoding="utf-8")
    assert "some-model" not in text  # label is a filename tag, not a model name claim
    assert "# Old vs new grader" in text


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("anthropic/claude-sonnet-5", "claude-sonnet-5"),
        ("anthropic/claude-opus-5.5", "claude-opus-5.5"),
        ("openai/gpt-5-nano", "gpt-5-nano"),
        ("openai/gpt-4o-mini", "gpt-4o-mini"),
        ("bare-model-name", "bare-model-name"),
        ("vendor/model:with weird chars", "model-with-weird-chars"),
    ],
)
def test_model_label_is_a_safe_filename_tag(model, expected):
    """Judge model -> the filename suffix, so two models never collide."""
    assert model_label(model) == expected
