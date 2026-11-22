"""A evidência da camada 2 versionada em eval/layer2 sustenta os números do README."""

import hashlib
import json
from pathlib import Path

import pytest

LAYER2 = Path(__file__).resolve().parents[1] / "eval" / "layer2"

EXPECTED = {
    "2026-11-08_939d2ba": (10, {"C": 32, "P": 48, "I": 6}),
    "2026-11-15_df1ddbb": (10, {"C": 47, "P": 27, "I": 12}),
    "2026-11-17_877163b_S06": (1, {"C": 5, "P": 2, "I": 3}),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def official_totals(report: dict) -> tuple[int, dict]:
    totals = {"C": 0, "P": 0, "I": 0}
    rows = [row for row in report["rows"] if row["scenario"] != "S05-V"]
    for row in rows:
        for label in totals:
            totals[label] += row["quality"][label]
    return len(rows), totals


@pytest.mark.parametrize("round_name", sorted(EXPECTED))
def test_report_totals_match_the_numbers_in_the_readme(round_name):
    report = json.loads((LAYER2 / round_name / "report.json").read_text(encoding="utf-8"))

    assert official_totals(report) == EXPECTED[round_name]


@pytest.mark.parametrize("round_name", sorted(EXPECTED))
def test_labels_are_the_ones_frozen_and_used_by_the_report(round_name):
    folder = LAYER2 / round_name
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    frozen = json.loads((folder / "labels_frozen.json").read_text(encoding="utf-8"))

    for name in ("labels.json", "labels_fallback.json"):
        assert report["labels_sha256"][name] == sha256(folder / name)
        assert frozen[name] == sha256(folder / name)


@pytest.mark.parametrize("round_name", sorted(EXPECTED))
def test_index_hashes_match_the_files(round_name):
    index = {entry["round"]: entry for entry in json.loads((LAYER2 / "index.json").read_text(encoding="utf-8"))}

    for name, info in index[round_name]["files"].items():
        assert info["sha256"] == sha256(LAYER2 / round_name / name), name


@pytest.mark.parametrize("round_name", sorted(EXPECTED))
def test_each_report_row_comes_from_the_commit_in_the_manifest(round_name):
    folder = LAYER2 / round_name
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    commit = json.dumps(manifest.get("code"))

    assert {row["commit"][:7] for row in report["rows"]} == {round_name.split("_")[1][:7]}
    assert round_name.split("_")[1][:7] in commit


def test_evidence_has_no_local_paths():
    for path in LAYER2.rglob("*"):
        if path.is_file():
            assert "/home/" not in path.read_text(encoding="utf-8"), path.name
