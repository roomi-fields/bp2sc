"""Golden tests: compare generated .scd output against expected files."""

import pytest
from pathlib import Path
from bp2sc.grammar.parser import parse_file
from bp2sc.sc_emitter import emit_scd

GOLDEN_DIR = Path(__file__).parent / "golden"


def _run_golden(bp_name: str):
    """Run a golden test for a given BP file."""
    bp_path = GOLDEN_DIR / f"{bp_name}.bp"
    expected_path = GOLDEN_DIR / f"{bp_name}.expected.scd"

    assert bp_path.exists(), f"Missing input: {bp_path}"
    assert expected_path.exists(), f"Missing expected: {expected_path}"

    ast = parse_file(bp_path)
    actual = emit_scd(ast, bp_path.name)
    expected = expected_path.read_text(encoding="utf-8")

    assert actual == expected, (
        f"Golden test failed for {bp_name}.\n"
        f"Expected length: {len(expected)}, actual: {len(actual)}.\n"
        f"First difference at char {_first_diff(expected, actual)}."
    )


def _first_diff(a: str, b: str) -> int:
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            return i
    return min(len(a), len(b))


class TestGolden:
    def test_12345678(self):
        _run_golden("12345678")

    def test_ruwet(self):
        _run_golden("ruwet")


class TestGoldenStructural:
    """Structural validation of golden outputs."""

    @pytest.mark.parametrize("bp_name", ["12345678", "ruwet"])
    def test_contains_pdef(self, bp_name):
        bp_path = GOLDEN_DIR / f"{bp_name}.bp"
        ast = parse_file(bp_path)
        scd = emit_scd(ast, bp_path.name)
        assert "Pdef" in scd

    @pytest.mark.parametrize("bp_name", ["12345678", "ruwet"])
    def test_contains_pattern(self, bp_name):
        bp_path = GOLDEN_DIR / f"{bp_name}.bp"
        ast = parse_file(bp_path)
        scd = emit_scd(ast, bp_path.name)
        assert any(tok in scd for tok in ["Pseq", "Prand", "Pwrand", "Ppar"])

    @pytest.mark.parametrize("bp_name", ["12345678", "ruwet"])
    def test_non_empty(self, bp_name):
        bp_path = GOLDEN_DIR / f"{bp_name}.bp"
        ast = parse_file(bp_path)
        scd = emit_scd(ast, bp_path.name)
        assert len(scd) > 100
