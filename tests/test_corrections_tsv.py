"""Regression checks for every rule in the built-in Turkish correction table."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from app.medical.postprocess import (
    MedicalPostProcessor,
    read_corrections,
    tr_capitalize,
    tr_lower,
    tr_upper,
)


ROOT = Path(__file__).resolve().parent.parent
CORRECTIONS = ROOT / "app" / "medical" / "corrections_tr.tsv"


def _rules() -> list[tuple[str, str]]:
    return read_corrections(CORRECTIONS)


@pytest.mark.parametrize("wrong,right", _rules())
def test_each_builtin_correction_matches_its_own_input(wrong: str, right: str) -> None:
    """A newly added or accidentally malformed TSV row must fail visibly."""
    processor = MedicalPostProcessor(corrections=[(wrong, right)], use_itn=False)
    source = wrong.removesuffix("*")
    assert processor.apply_corrections(source) == right


@pytest.mark.parametrize("wrong,right", [r for r in _rules() if r[0].endswith("*")])
def test_root_corrections_preserve_suffixes(wrong: str, right: str) -> None:
    processor = MedicalPostProcessor(corrections=[(wrong, right)], use_itn=False)
    root = wrong[:-1]
    # Appending a suffix exercises the root match without tying the test to a specific case ending.
    assert processor.apply_corrections(root + "lar") == right + "lar"


def test_correction_sources_do_not_conflict() -> None:
    by_source: dict[str, set[str]] = defaultdict(set)
    for wrong, right in _rules():
        by_source[tr_lower(wrong)].add(right)
    conflicts = {source: sorted(targets) for source, targets in by_source.items() if len(targets) > 1}
    assert not conflicts, f"Correction sources map to multiple targets: {conflicts}"


@pytest.mark.parametrize("wrong,right", _rules())
def test_exact_corrections_are_case_insensitive_and_respect_word_boundaries(
    wrong: str, right: str
) -> None:
    processor = MedicalPostProcessor(corrections=[(wrong, right)], use_itn=False)
    source = wrong.removesuffix("*")
    # Mixed case still matches. A surrounding word character must prevent partial replacement.
    mixed = tr_upper(source[:1]) + source[1:]
    expected = tr_capitalize(right) if right[:1].islower() else right
    assert processor.apply_corrections(mixed) == expected
    if wrong.endswith("*"):
        assert processor.apply_corrections("x" + source) == "x" + source
    else:
        assert processor.apply_corrections("x" + source + "x") == "x" + source + "x"
