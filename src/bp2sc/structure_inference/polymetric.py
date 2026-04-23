"""Polymetric structure generation for BP3.

This module provides functions to generate BP3-style polymetric expressions
{n, ...} from detected groupings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .grouping import (
    NoteEvent,
    GroupBoundary,
    detect_groupings,
    split_into_groups,
)
from .gttm_rules import GTTMConfig


@dataclass
class PolymetricGroup:
    """A single polymetric group with tempo ratio.

    Attributes:
        notes: List of notes in this group
        tempo_ratio: Number of time slots (beats) this group occupies
                    If None, duration is determined by sum of note durations
        is_nested: True if this group contains nested polymetric structures
    """
    notes: list[NoteEvent]
    tempo_ratio: int | None = None
    is_nested: bool = False

    @property
    def size(self) -> int:
        """Number of notes in this group."""
        return len(self.notes)

    def to_bp3(self, use_note_names: bool = True) -> str:
        """Convert group to BP3 polymetric expression.

        Args:
            use_note_names: If True, use note names (C4, do4); else MIDI numbers

        Returns:
            BP3 expression like "{3, C4 D4 E4}"
        """
        if not self.notes:
            return ""

        note_strs = []
        for note in self.notes:
            if use_note_names and note.name:
                note_strs.append(note.name)
            else:
                note_strs.append(_midi_to_name(note.pitch))

        notes_expr = " ".join(note_strs)

        if self.tempo_ratio is not None:
            return f"{{{self.tempo_ratio}, {notes_expr}}}"
        else:
            # No tempo ratio - return just the notes (flat)
            return notes_expr


@dataclass
class PolymetricStructure:
    """A complete polymetric structure with multiple groups.

    Attributes:
        groups: List of polymetric groups
        boundaries: The detected boundaries used to create this structure
        total_duration: Total duration of the original sequence
    """
    groups: list[PolymetricGroup] = field(default_factory=list)
    boundaries: list[GroupBoundary] = field(default_factory=list)
    total_duration: float = 0.0

    @property
    def num_groups(self) -> int:
        """Number of groups in the structure."""
        return len(self.groups)

    def to_bp3(self, use_note_names: bool = True) -> str:
        """Convert entire structure to BP3 expression.

        Args:
            use_note_names: If True, use note names

        Returns:
            BP3 expression like "{3, C4 D4 E4} {2, F4 G4}"
        """
        return " ".join(g.to_bp3(use_note_names) for g in self.groups)

    def to_bp3_nested(self, use_note_names: bool = True) -> str:
        """Convert to nested BP3 expression with outer grouping.

        Returns:
            BP3 expression like "{{3, C4 D4 E4} {2, F4 G4}}"
        """
        inner = self.to_bp3(use_note_names)
        return f"{{{inner}}}"


def _midi_to_name(pitch: int) -> str:
    """Convert MIDI pitch number to note name.

    Uses French solfege convention (do4 = 60) for consistency with BP3.

    Args:
        pitch: MIDI pitch number (0-127)

    Returns:
        Note name like "do4", "re#5", "sib3"
    """
    note_names = ["do", "do#", "re", "re#", "mi", "fa",
                  "fa#", "sol", "sol#", "la", "la#", "si"]

    # BP3 convention: octave = pitch // 12 - 1
    # So MIDI 60 = do4 (middle C)
    octave = pitch // 12 - 1
    note_idx = pitch % 12

    return f"{note_names[note_idx]}{octave}"


def compute_tempo_ratio(
    group_notes: list[NoteEvent],
    reference_duration: float,
) -> int | None:
    """Compute tempo ratio for a group of notes.

    The tempo ratio is the number of time slots (beats) that the group
    occupies, based on its duration relative to a reference.

    Args:
        group_notes: Notes in the group
        reference_duration: Reference duration (e.g., beat or measure)

    Returns:
        Tempo ratio as integer, or None if not meaningful
    """
    if not group_notes or reference_duration <= 0:
        return None

    # Group duration is from first onset to last note end
    first_onset = group_notes[0].onset
    last_end = max(n.onset + n.duration for n in group_notes)
    group_duration = last_end - first_onset

    if group_duration <= 0:
        return len(group_notes)  # Fall back to note count

    # Round to nearest integer
    ratio = round(group_duration / reference_duration)

    # Ensure at least 1
    return max(1, ratio)


def build_polymetric_structure(
    notes: Sequence[NoteEvent],
    boundaries: list[GroupBoundary],
    use_note_count_ratio: bool = True,
) -> PolymetricStructure:
    """Build a polymetric structure from notes and boundaries.

    Args:
        notes: Sequence of notes
        boundaries: Detected group boundaries
        use_note_count_ratio: If True, use note count as tempo ratio;
                             else compute from durations

    Returns:
        PolymetricStructure with groups
    """
    groups_notes = split_into_groups(notes, boundaries)

    if not groups_notes:
        return PolymetricStructure()

    # Compute total duration
    total_duration = 0.0
    if notes:
        first_onset = notes[0].onset
        last_end = max(n.onset + n.duration for n in notes)
        total_duration = last_end - first_onset

    # Compute reference duration (average note duration or median IOI)
    ref_duration = 1.0
    if len(notes) >= 2:
        from .grouping import compute_median_ioi
        ref_duration = compute_median_ioi(notes)

    groups: list[PolymetricGroup] = []
    for group_notes in groups_notes:
        if not group_notes:
            continue

        if use_note_count_ratio:
            # Simple: tempo ratio = number of notes
            tempo_ratio = len(group_notes)
        else:
            # Duration-based ratio
            tempo_ratio = compute_tempo_ratio(group_notes, ref_duration)

        groups.append(PolymetricGroup(
            notes=list(group_notes),
            tempo_ratio=tempo_ratio,
        ))

    return PolymetricStructure(
        groups=groups,
        boundaries=boundaries,
        total_duration=total_duration,
    )


def infer_structure(
    notes: Sequence[NoteEvent],
    config: GTTMConfig | None = None,
    use_note_count_ratio: bool = True,
) -> PolymetricStructure:
    """Infer polymetric structure from a sequence of notes.

    This is the main entry point for structure inference. It:
    1. Detects group boundaries using GTTM rules
    2. Splits notes into groups at boundaries
    3. Computes tempo ratios for each group
    4. Returns a BP3-compatible polymetric structure

    Args:
        notes: Sequence of NoteEvent objects
        config: GTTM configuration (uses defaults if None)
        use_note_count_ratio: If True, use note count as tempo ratio

    Returns:
        PolymetricStructure that can be converted to BP3 expression
    """
    if not notes:
        return PolymetricStructure()

    if config is None:
        config = GTTMConfig()

    # Detect boundaries
    boundaries = detect_groupings(notes, config)

    # Build structure
    return build_polymetric_structure(
        notes, boundaries, use_note_count_ratio
    )


def optimize_structure(
    structure: PolymetricStructure,
    config: GTTMConfig | None = None,
) -> PolymetricStructure:
    """Optimize a polymetric structure for musical coherence.

    This performs post-processing optimizations:
    - Merge very small groups
    - Split very large groups
    - Normalize tempo ratios to common denominators

    Args:
        structure: Input structure
        config: GTTM configuration

    Returns:
        Optimized structure
    """
    if config is None:
        config = GTTMConfig()

    if not structure.groups:
        return structure

    optimized_groups: list[PolymetricGroup] = []
    pending_merge: PolymetricGroup | None = None

    for group in structure.groups:
        # Check for very small groups to merge
        if group.size < config.min_group_size and pending_merge is not None:
            # Merge with pending
            merged_notes = pending_merge.notes + group.notes
            pending_merge = PolymetricGroup(
                notes=merged_notes,
                tempo_ratio=len(merged_notes),
            )
        elif group.size < config.min_group_size:
            # Start a new pending merge
            pending_merge = group
        else:
            # Add pending if any
            if pending_merge is not None:
                # Merge pending with current if still small
                if pending_merge.size < config.min_group_size:
                    merged_notes = pending_merge.notes + group.notes
                    optimized_groups.append(PolymetricGroup(
                        notes=merged_notes,
                        tempo_ratio=len(merged_notes),
                    ))
                    pending_merge = None
                    continue
                else:
                    optimized_groups.append(pending_merge)
                    pending_merge = None

            # Check for very large groups to split
            if group.size > config.max_group_size:
                # Split into roughly equal parts
                split_groups = _split_large_group(group, config.max_group_size)
                optimized_groups.extend(split_groups)
            else:
                optimized_groups.append(group)

    # Handle any remaining pending
    if pending_merge is not None:
        optimized_groups.append(pending_merge)

    return PolymetricStructure(
        groups=optimized_groups,
        boundaries=structure.boundaries,
        total_duration=structure.total_duration,
    )


def _split_large_group(
    group: PolymetricGroup,
    max_size: int,
) -> list[PolymetricGroup]:
    """Split a large group into smaller groups.

    Args:
        group: Group to split
        max_size: Maximum size per group

    Returns:
        List of smaller groups
    """
    notes = group.notes
    result: list[PolymetricGroup] = []

    # Calculate number of splits needed
    num_splits = (len(notes) + max_size - 1) // max_size
    ideal_size = len(notes) // num_splits

    start = 0
    for i in range(num_splits):
        # Last group gets remaining notes
        if i == num_splits - 1:
            end = len(notes)
        else:
            end = start + ideal_size

        split_notes = notes[start:end]
        if split_notes:
            result.append(PolymetricGroup(
                notes=split_notes,
                tempo_ratio=len(split_notes),
            ))
        start = end

    return result
