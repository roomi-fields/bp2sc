"""Tests using sclang event tracing to validate generated .scd output.

These tests require sclang to be installed. They are skipped automatically
if sclang is not available.
"""

import pytest
from pathlib import Path
from bp2sc.grammar.parser import parse_file
from bp2sc.sc_emitter import emit_scd

try:
    from tests.sclang_trace import trace_scd_content, sclang_available, TraceEvent
except ImportError:
    from sclang_trace import trace_scd_content, sclang_available, TraceEvent

GOLDEN_DIR = Path(__file__).parent / "golden"

pytestmark = pytest.mark.skipif(
    not sclang_available(),
    reason="sclang not available"
)


class TestSclangSyntax:
    """Verify that generated .scd files compile without errors in sclang."""

    @pytest.mark.parametrize("bp_name", ["12345678", "ruwet"])
    def test_compiles(self, bp_name):
        bp_path = GOLDEN_DIR / f"{bp_name}.bp"
        ast = parse_file(bp_path)
        scd = emit_scd(ast, bp_path.name)
        # If trace_scd_content doesn't raise, the code compiled
        events = trace_scd_content(scd, max_events=10, timeout=60)
        assert len(events) > 0, f"{bp_name}.scd produced no events"


class TestTihai12345678:
    """Validate the Kathak tihai produces the correct note sequence."""

    @pytest.fixture
    def events(self):
        bp_path = GOLDEN_DIR / "12345678.bp"
        ast = parse_file(bp_path)
        scd = emit_scd(ast, bp_path.name)
        return trace_scd_content(scd, max_events=200, timeout=30)

    def test_stream_finite(self, events):
        """The pattern should produce a finite number of events."""
        assert len(events) > 0
        # 3 tihais × (8+6+5+4 notes + 1 rest + 12 elements in accelerando) = ~108
        assert len(events) < 150, f"Too many events: {len(events)}"

    def test_total_events(self, events):
        """Each tihai has: Huit(8) + Six(6) + Cinq(5) + Quatre(4) + rest(1) + accel(12) = 36.
        Three tihais = 108 events."""
        assert len(events) == 108

    def test_first_tihai_notes(self, events):
        """First tihai: Huit = notes 60,61,62,63,64,65,66,67."""
        note_events = [e for e in events[:8] if e.type == "note"]
        assert len(note_events) == 8
        midis = [e.midinote for e in note_events]
        assert midis == [60, 61, 62, 63, 64, 65, 66, 67]

    def test_first_tihai_six(self, events):
        """After Huit, Six = notes 60,61,62,63,64,65."""
        note_events = [e for e in events[8:14] if e.type == "note"]
        midis = [e.midinote for e in note_events]
        assert midis == [60, 61, 62, 63, 64, 65]

    def test_first_tihai_cinq(self, events):
        """After Six, Cinq = notes 60,61,62,63,64."""
        note_events = [e for e in events[14:19] if e.type == "note"]
        midis = [e.midinote for e in note_events]
        assert midis == [60, 61, 62, 63, 64]

    def test_first_tihai_quatre(self, events):
        """After Cinq, Quatre = notes 60,61,62,63."""
        note_events = [e for e in events[19:23] if e.type == "note"]
        midis = [e.midinote for e in note_events]
        assert midis == [60, 61, 62, 63]

    def test_stretch_huit(self, events):
        """Huit events should have stretch=2.0 (from {2, Huit})."""
        for e in events[:8]:
            if e.type == "note":
                assert e.stretch == 2.0

    def test_second_tihai_transpose(self, events):
        """Second tihai should have ctranspose=-2."""
        # Second tihai starts at event 36
        second_tihai_notes = [e for e in events[36:72] if e.type == "note"]
        for e in second_tihai_notes:
            assert e.ctranspose == -2.0

    def test_third_tihai_detune(self, events):
        """Third tihai should have ctranspose=-2 and detune=-200."""
        third_tihai_notes = [e for e in events[72:] if e.type == "note"]
        for e in third_tihai_notes:
            assert e.ctranspose == -2.0
            assert e.detune == -200.0

    def test_accelerando_stretch(self, events):
        """Accelerando section should have stretch=0.25 (3/12)."""
        # Events 24-35 are the accelerando in first tihai
        accel_events = events[24:36]
        for e in accel_events:
            assert e.stretch == 0.25, f"Event {e.index}: stretch={e.stretch}"
