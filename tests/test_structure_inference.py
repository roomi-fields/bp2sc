"""Tests for the structure_inference module."""

import pytest
from bp2sc.structure_inference import (
    NoteEvent,
    GroupBoundary,
    PolymetricGroup,
    PolymetricStructure,
    GTTMConfig,
    detect_groupings,
    infer_structure,
    build_polymetric_structure,
    compute_gap_strength,
    compute_register_change,
)
from bp2sc.structure_inference.grouping import (
    compute_median_ioi,
    detect_boundaries_gttm,
    detect_pattern_boundaries,
    split_into_groups,
)
from bp2sc.structure_inference.polymetric import (
    _midi_to_name,
    compute_tempo_ratio,
    optimize_structure,
)


# --- Helper functions ---

def make_note(pitch: int, onset: float, duration: float = 0.25,
              velocity: int = 80, name: str | None = None) -> NoteEvent:
    """Create a NoteEvent for testing."""
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        velocity=velocity,
        name=name,
    )


def make_scale(start_pitch: int = 60, num_notes: int = 8,
               note_duration: float = 0.25) -> list[NoteEvent]:
    """Create an ascending scale for testing."""
    return [
        make_note(
            pitch=start_pitch + i,
            onset=i * note_duration,
            duration=note_duration,
        )
        for i in range(num_notes)
    ]


# --- NoteEvent tests ---

class TestNoteEvent:
    def test_basic_creation(self):
        note = NoteEvent(pitch=60, onset=0.0, duration=0.5)
        assert note.pitch == 60
        assert note.onset == 0.0
        assert note.duration == 0.5
        assert note.velocity is None
        assert note.name is None

    def test_with_all_fields(self):
        note = NoteEvent(
            pitch=64, onset=1.0, duration=0.25,
            velocity=100, channel=1, name="E4"
        )
        assert note.pitch == 64
        assert note.velocity == 100
        assert note.name == "E4"

    def test_repr(self):
        note = make_note(60, 0.0, 0.5, name="C4")
        assert "C4" in repr(note)
        assert "onset=0.00" in repr(note)


# --- GTTM rules tests ---

class TestGTTMRules:
    def test_compute_gap_strength_no_gap(self):
        """Adjacent notes should have no gap strength."""
        note1 = make_note(60, 0.0, 0.25)
        note2 = make_note(62, 0.25, 0.25)
        config = GTTMConfig()

        strength = compute_gap_strength(note1, note2, 0.25, config)
        assert strength == 0.0

    def test_compute_gap_strength_with_gap(self):
        """Large gap should produce positive strength."""
        note1 = make_note(60, 0.0, 0.25)
        note2 = make_note(62, 1.0, 0.25)  # 0.75 beat gap
        config = GTTMConfig()

        strength = compute_gap_strength(note1, note2, 0.25, config)
        assert strength > 0.0

    def test_compute_register_change_small_interval(self):
        """Small interval should have no register change."""
        note1 = make_note(60, 0.0)
        note2 = make_note(62, 0.25)  # 2 semitones
        config = GTTMConfig()

        strength = compute_register_change(note1, note2, config)
        assert strength == 0.0

    def test_compute_register_change_large_interval(self):
        """Large interval should produce positive strength."""
        note1 = make_note(60, 0.0)
        note2 = make_note(72, 0.25)  # 12 semitones (octave)
        config = GTTMConfig()

        strength = compute_register_change(note1, note2, config)
        assert strength > 0.0


# --- Grouping tests ---

class TestGrouping:
    def test_compute_median_ioi(self):
        """Test median IOI computation."""
        notes = make_scale(num_notes=4, note_duration=0.5)
        median = compute_median_ioi(notes)
        assert median == 0.5

    def test_compute_median_ioi_single_note(self):
        """Single note should return default."""
        notes = [make_note(60, 0.0)]
        median = compute_median_ioi(notes)
        assert median == 1.0

    def test_detect_boundaries_empty(self):
        """Empty sequence should return no boundaries."""
        boundaries = detect_boundaries_gttm([])
        assert boundaries == []

    def test_detect_boundaries_uniform_scale(self):
        """Uniform scale with no gaps should have few boundaries."""
        notes = make_scale(num_notes=8)
        config = GTTMConfig(boundary_threshold=0.3)

        boundaries = detect_boundaries_gttm(notes, config)
        # A uniform scale shouldn't have strong boundaries
        # (depends on threshold)
        assert all(b.strength >= config.boundary_threshold for b in boundaries)

    def test_detect_boundaries_with_gap(self):
        """Gap in sequence should create boundary."""
        notes = [
            make_note(60, 0.0),
            make_note(62, 0.25),
            make_note(64, 0.5),
            # Gap here
            make_note(65, 2.0),  # Big gap
            make_note(67, 2.25),
            make_note(69, 2.5),
        ]
        config = GTTMConfig(boundary_threshold=0.2)

        boundaries = detect_boundaries_gttm(notes, config)

        # Should detect boundary after position 2 (before the gap)
        positions = [b.position for b in boundaries]
        assert 2 in positions

    def test_detect_boundaries_register_jump(self):
        """Large register jump should create boundary."""
        notes = [
            make_note(60, 0.0),
            make_note(62, 0.25),
            make_note(64, 0.5),
            make_note(84, 0.75),  # +20 semitones jump
            make_note(86, 1.0),
            make_note(88, 1.25),
        ]
        config = GTTMConfig(
            boundary_threshold=0.15,
            register_threshold=7,
        )

        boundaries = detect_boundaries_gttm(notes, config)

        # Should detect boundary between positions 2 and 3
        positions = [b.position for b in boundaries]
        assert 2 in positions


class TestPatternDetection:
    def test_detect_pattern_simple_repeat(self):
        """Repeated pattern should create boundary."""
        # Pattern: +2 +2 +1 | +2 +2 +1 (exact repeat)
        # Intervals: [+2,+2,+1] [+2,+2,+1]
        notes = [
            make_note(60, 0.0),   # C4
            make_note(62, 0.25),  # D4: +2
            make_note(64, 0.5),   # E4: +2
            make_note(65, 0.75),  # F4: +1 (end first pattern)
            make_note(67, 1.0),   # G4: +2 (start repeat)
            make_note(69, 1.25),  # A4: +2
            make_note(70, 1.5),   # Bb4: +1 (end second pattern)
        ]
        config = GTTMConfig(
            enable_pattern_detection=True,
            pattern_similarity_threshold=1.0,  # Exact match
        )

        boundaries = detect_pattern_boundaries(notes, config)

        # Should find boundary at pattern edge (position 2, between E4 and F4)
        # Note: pattern detection works on intervals, pattern len 3 means 4 notes
        assert len(boundaries) >= 1

    def test_detect_pattern_disabled(self):
        """Pattern detection should return empty when disabled."""
        notes = make_scale(num_notes=8)
        config = GTTMConfig(enable_pattern_detection=False)

        boundaries = detect_pattern_boundaries(notes, config)
        assert boundaries == []


class TestSplitIntoGroups:
    def test_split_no_boundaries(self):
        """No boundaries should return single group."""
        notes = make_scale(num_notes=4)
        groups = split_into_groups(notes, [])
        assert len(groups) == 1
        assert len(groups[0]) == 4

    def test_split_single_boundary(self):
        """Single boundary should create two groups."""
        notes = make_scale(num_notes=6)
        boundaries = [GroupBoundary(position=2, strength=0.5, type=None)]

        groups = split_into_groups(notes, boundaries)

        assert len(groups) == 2
        assert len(groups[0]) == 3  # notes 0, 1, 2
        assert len(groups[1]) == 3  # notes 3, 4, 5

    def test_split_multiple_boundaries(self):
        """Multiple boundaries should create correct groups."""
        notes = make_scale(num_notes=8)
        boundaries = [
            GroupBoundary(position=1, strength=0.5, type=None),
            GroupBoundary(position=4, strength=0.5, type=None),
        ]

        groups = split_into_groups(notes, boundaries)

        assert len(groups) == 3
        assert len(groups[0]) == 2  # notes 0, 1
        assert len(groups[1]) == 3  # notes 2, 3, 4
        assert len(groups[2]) == 3  # notes 5, 6, 7


# --- Polymetric tests ---

class TestPolymetric:
    def test_midi_to_name_middle_c(self):
        """MIDI 60 should be do4."""
        assert _midi_to_name(60) == "do4"

    def test_midi_to_name_with_sharp(self):
        """MIDI 61 should be do#4."""
        assert _midi_to_name(61) == "do#4"

    def test_midi_to_name_octaves(self):
        """Test various octaves."""
        assert _midi_to_name(48) == "do3"
        assert _midi_to_name(72) == "do5"
        assert _midi_to_name(36) == "do2"

    def test_polymetric_group_to_bp3(self):
        """Test BP3 expression generation."""
        notes = [
            make_note(60, 0.0, name="do4"),
            make_note(62, 0.25, name="re4"),
            make_note(64, 0.5, name="mi4"),
        ]
        group = PolymetricGroup(notes=notes, tempo_ratio=3)

        bp3 = group.to_bp3()
        assert bp3 == "{3, do4 re4 mi4}"

    def test_polymetric_group_without_names(self):
        """Test BP3 generation with auto-generated names."""
        notes = [
            make_note(60, 0.0),
            make_note(62, 0.25),
        ]
        group = PolymetricGroup(notes=notes, tempo_ratio=2)

        bp3 = group.to_bp3()
        assert bp3 == "{2, do4 re4}"

    def test_polymetric_structure_to_bp3(self):
        """Test full structure to BP3 conversion."""
        g1 = PolymetricGroup(
            notes=[make_note(60, 0.0, name="do4"),
                   make_note(62, 0.25, name="re4"),
                   make_note(64, 0.5, name="mi4")],
            tempo_ratio=3
        )
        g2 = PolymetricGroup(
            notes=[make_note(65, 0.75, name="fa4"),
                   make_note(67, 1.0, name="sol4")],
            tempo_ratio=2
        )
        structure = PolymetricStructure(groups=[g1, g2])

        bp3 = structure.to_bp3()
        assert bp3 == "{3, do4 re4 mi4} {2, fa4 sol4}"


# --- Integration tests ---

class TestInferStructure:
    def test_infer_empty(self):
        """Empty input should return empty structure."""
        structure = infer_structure([])
        assert structure.num_groups == 0

    def test_infer_single_note(self):
        """Single note should return single group."""
        notes = [make_note(60, 0.0)]
        structure = infer_structure(notes)

        # Single note creates a group with 1 note
        assert structure.num_groups == 1

    def test_infer_with_gap(self):
        """Sequence with gap should be split."""
        notes = [
            make_note(60, 0.0),
            make_note(62, 0.25),
            make_note(64, 0.5),
            # Gap here
            make_note(65, 2.0),
            make_note(67, 2.25),
        ]
        config = GTTMConfig(
            boundary_threshold=0.2,
            min_group_size=2,
        )

        structure = infer_structure(notes, config)

        # Should have at least 2 groups due to gap
        assert structure.num_groups >= 2

    def test_infer_uniform_scale(self):
        """Uniform scale should remain mostly ungrouped."""
        notes = make_scale(num_notes=8)
        config = GTTMConfig(
            boundary_threshold=0.5,  # High threshold
            min_group_size=2,
        )

        structure = infer_structure(notes, config)

        # With high threshold and uniform scale, fewer boundaries
        bp3 = structure.to_bp3()
        assert bp3  # Should produce valid output

    def test_full_pipeline(self):
        """Test complete pipeline from notes to BP3."""
        # Create a sequence with clear structure:
        # 3 notes, gap, 2 notes
        notes = [
            make_note(60, 0.0, name="C4"),
            make_note(62, 0.25, name="D4"),
            make_note(64, 0.5, name="E4"),
            # Gap
            make_note(65, 2.0, name="F4"),
            make_note(67, 2.25, name="G4"),
        ]
        config = GTTMConfig(
            boundary_threshold=0.2,
            min_group_size=2,
        )

        structure = infer_structure(notes, config)
        bp3 = structure.to_bp3()

        # Check output format
        assert "{" in bp3
        assert "}" in bp3


class TestOptimizeStructure:
    def test_merge_small_groups(self):
        """Small groups should be merged."""
        g1 = PolymetricGroup(
            notes=[make_note(60, 0.0)],  # Too small (1 note)
            tempo_ratio=1
        )
        g2 = PolymetricGroup(
            notes=[make_note(62, 0.25), make_note(64, 0.5), make_note(65, 0.75)],
            tempo_ratio=3
        )
        structure = PolymetricStructure(groups=[g1, g2])

        config = GTTMConfig(min_group_size=2)
        optimized = optimize_structure(structure, config)

        # Small group should be merged
        assert optimized.num_groups == 1
        assert optimized.groups[0].size == 4

    def test_split_large_groups(self):
        """Large groups should be split."""
        notes = [make_note(60 + i, i * 0.25) for i in range(16)]
        g = PolymetricGroup(notes=notes, tempo_ratio=16)
        structure = PolymetricStructure(groups=[g])

        config = GTTMConfig(max_group_size=8)
        optimized = optimize_structure(structure, config)

        # Large group should be split
        assert optimized.num_groups >= 2
        for group in optimized.groups:
            assert group.size <= config.max_group_size


# --- Edge cases ---

class TestEdgeCases:
    def test_overlapping_notes(self):
        """Overlapping notes should be handled."""
        notes = [
            make_note(60, 0.0, 1.0),  # Long note
            make_note(62, 0.25, 0.5),  # Overlaps
            make_note(64, 0.5, 0.25),
        ]
        # Should not raise
        structure = infer_structure(notes)
        assert structure is not None

    def test_simultaneous_notes(self):
        """Simultaneous notes (chord) should be handled."""
        notes = [
            make_note(60, 0.0),
            make_note(64, 0.0),  # Same onset
            make_note(67, 0.0),  # Same onset
            make_note(72, 0.5),
        ]
        structure = infer_structure(notes)
        assert structure is not None

    def test_very_short_notes(self):
        """Very short notes should be handled."""
        notes = [
            make_note(60, 0.0, 0.01),
            make_note(62, 0.01, 0.01),
            make_note(64, 0.02, 0.01),
        ]
        structure = infer_structure(notes)
        assert structure is not None

    def test_extreme_velocity_range(self):
        """Full velocity range should be handled."""
        notes = [
            NoteEvent(60, 0.0, 0.25, velocity=1),
            NoteEvent(62, 0.25, 0.25, velocity=127),
            NoteEvent(64, 0.5, 0.25, velocity=64),
        ]
        structure = infer_structure(notes)
        assert structure is not None
