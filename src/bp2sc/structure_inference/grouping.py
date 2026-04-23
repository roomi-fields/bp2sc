"""Grouping detection using GTTM heuristics.

This module provides functions to detect group boundaries in a sequence
of notes using GTTM-inspired rules and pattern analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from statistics import median
from typing import Sequence

from .gttm_rules import (
    GTTMConfig,
    compute_combined_boundary_strength,
    compute_gap_strength,
    compute_register_change,
)


@dataclass
class NoteEvent:
    """A single note event with timing and pitch information.

    Attributes:
        pitch: MIDI pitch number (0-127)
        onset: Start time in beats (or seconds)
        duration: Duration in beats (or seconds)
        velocity: MIDI velocity (0-127), optional
        channel: MIDI channel, optional
        name: Note name (e.g., "C4", "do4"), optional
    """
    pitch: int
    onset: float
    duration: float
    velocity: int | None = None
    channel: int | None = None
    name: str | None = None

    def __repr__(self) -> str:
        name_str = self.name or f"MIDI {self.pitch}"
        return f"NoteEvent({name_str}, onset={self.onset:.2f}, dur={self.duration:.2f})"


class BoundaryType(Enum):
    """Type of group boundary."""
    GAP = "gap"              # GPR 2a: silence/rest
    IOI_CHANGE = "ioi"       # GPR 2b: rhythmic discontinuity
    REGISTER = "register"    # GPR 3a: pitch jump
    DYNAMICS = "dynamics"    # GPR 3c: velocity change
    ARTICULATION = "articulation"  # GPR 3d: articulation change
    PATTERN = "pattern"      # Pattern repetition boundary
    COMBINED = "combined"    # Multiple factors


@dataclass
class GroupBoundary:
    """A detected boundary between groups.

    Attributes:
        position: Index of the note AFTER which the boundary occurs
                 (boundary is between notes[position] and notes[position+1])
        strength: Boundary strength in [0, 1]
        type: Primary type of boundary
        details: Dictionary with per-rule strengths
    """
    position: int
    strength: float
    type: BoundaryType
    details: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"GroupBoundary(pos={self.position}, strength={self.strength:.2f}, type={self.type.value})"


def compute_median_ioi(notes: Sequence[NoteEvent]) -> float:
    """Compute median inter-onset interval from a note sequence.

    Args:
        notes: Sequence of NoteEvent objects

    Returns:
        Median IOI, or 1.0 if not enough notes
    """
    if len(notes) < 2:
        return 1.0

    iois = [notes[i+1].onset - notes[i].onset for i in range(len(notes) - 1)]
    positive_iois = [ioi for ioi in iois if ioi > 0]

    if not positive_iois:
        return 1.0

    return median(positive_iois)


def detect_boundaries_gttm(
    notes: Sequence[NoteEvent],
    config: GTTMConfig | None = None,
) -> list[GroupBoundary]:
    """Detect group boundaries using GTTM rules.

    Args:
        notes: Sequence of NoteEvent objects
        config: GTTM configuration (uses defaults if None)

    Returns:
        List of GroupBoundary objects, sorted by position
    """
    if len(notes) < 2:
        return []

    if config is None:
        config = GTTMConfig()

    median_ioi = compute_median_ioi(notes)
    boundaries: list[GroupBoundary] = []

    for i in range(len(notes) - 1):
        note1 = notes[i]
        note2 = notes[i + 1]
        note3 = notes[i + 2] if i + 2 < len(notes) else None

        strength = compute_combined_boundary_strength(
            note1, note2, note3, median_ioi, config
        )

        if strength >= config.boundary_threshold:
            # Determine primary boundary type
            gap_s = compute_gap_strength(note1, note2, median_ioi, config)
            register_s = compute_register_change(note1, note2, config)

            if gap_s >= register_s:
                btype = BoundaryType.GAP
            else:
                btype = BoundaryType.REGISTER

            boundaries.append(GroupBoundary(
                position=i,
                strength=strength,
                type=btype,
                details={"gap": gap_s, "register": register_s}
            ))

    return boundaries


def detect_pattern_boundaries(
    notes: Sequence[NoteEvent],
    config: GTTMConfig | None = None,
) -> list[GroupBoundary]:
    """Detect boundaries based on pattern repetition.

    Looks for repeated melodic patterns and places boundaries at pattern
    edges. Uses pitch contour (intervals) rather than absolute pitches.

    Args:
        notes: Sequence of NoteEvent objects
        config: GTTM configuration

    Returns:
        List of GroupBoundary objects at pattern boundaries
    """
    if len(notes) < 4:
        return []

    if config is None:
        config = GTTMConfig()

    if not config.enable_pattern_detection:
        return []

    # Compute pitch contour (intervals between consecutive notes)
    intervals = [notes[i+1].pitch - notes[i].pitch for i in range(len(notes) - 1)]

    boundaries: list[GroupBoundary] = []

    # Try pattern lengths from 2 to len/2
    max_pattern_len = len(intervals) // 2

    for pattern_len in range(2, min(max_pattern_len + 1, 8)):
        # Look for repeated patterns
        i = 0
        while i <= len(intervals) - 2 * pattern_len:
            pattern1 = intervals[i:i + pattern_len]
            pattern2 = intervals[i + pattern_len:i + 2 * pattern_len]

            if _patterns_similar(pattern1, pattern2, config.pattern_similarity_threshold):
                # Found a pattern repetition
                # Boundary at the end of the first pattern
                boundary_pos = i + pattern_len - 1  # Note index

                # Check if boundary already exists nearby
                if not any(abs(b.position - boundary_pos) <= 1 for b in boundaries):
                    boundaries.append(GroupBoundary(
                        position=boundary_pos,
                        strength=0.6,  # Pattern boundaries have moderate strength
                        type=BoundaryType.PATTERN,
                        details={"pattern_len": pattern_len}
                    ))

                i += pattern_len
            else:
                i += 1

    return boundaries


def _patterns_similar(p1: list[int], p2: list[int], threshold: float) -> bool:
    """Check if two interval patterns are similar.

    Args:
        p1: First pattern (list of intervals)
        p2: Second pattern (list of intervals)
        threshold: Similarity threshold in [0, 1]

    Returns:
        True if patterns are similar above threshold
    """
    if len(p1) != len(p2):
        return False

    if not p1:
        return False

    # Count matching intervals
    matches = sum(1 for a, b in zip(p1, p2) if a == b)
    similarity = matches / len(p1)

    return similarity >= threshold


def detect_groupings(
    notes: Sequence[NoteEvent],
    config: GTTMConfig | None = None,
) -> list[GroupBoundary]:
    """Detect all group boundaries using combined heuristics.

    This is the main entry point for grouping detection. It combines
    GTTM rules with pattern detection to identify probable boundaries.

    Args:
        notes: Sequence of NoteEvent objects
        config: GTTM configuration (uses defaults if None)

    Returns:
        List of GroupBoundary objects, sorted by position and merged
    """
    if len(notes) < 2:
        return []

    if config is None:
        config = GTTMConfig()

    # Get boundaries from both sources
    gttm_boundaries = detect_boundaries_gttm(notes, config)
    pattern_boundaries = detect_pattern_boundaries(notes, config)

    # Merge boundaries (combine nearby ones)
    all_boundaries = _merge_boundaries(gttm_boundaries + pattern_boundaries)

    # Filter by minimum group size
    all_boundaries = _filter_by_group_size(all_boundaries, len(notes), config)

    return sorted(all_boundaries, key=lambda b: b.position)


def _merge_boundaries(boundaries: list[GroupBoundary]) -> list[GroupBoundary]:
    """Merge boundaries that are at the same or adjacent positions.

    Args:
        boundaries: List of boundaries to merge

    Returns:
        Merged list of boundaries
    """
    if not boundaries:
        return []

    # Sort by position
    sorted_bounds = sorted(boundaries, key=lambda b: b.position)

    merged: list[GroupBoundary] = []
    current = sorted_bounds[0]

    for b in sorted_bounds[1:]:
        if b.position <= current.position + 1:
            # Merge: keep the stronger one, combine details
            if b.strength > current.strength:
                new_details = {**current.details, **b.details}
                current = GroupBoundary(
                    position=b.position,
                    strength=b.strength,
                    type=b.type,
                    details=new_details,
                )
            else:
                current.details.update(b.details)
        else:
            merged.append(current)
            current = b

    merged.append(current)
    return merged


def _filter_by_group_size(
    boundaries: list[GroupBoundary],
    total_notes: int,
    config: GTTMConfig,
) -> list[GroupBoundary]:
    """Filter boundaries that would create groups smaller than min_group_size.

    Args:
        boundaries: List of boundaries
        total_notes: Total number of notes
        config: GTTM configuration

    Returns:
        Filtered list of boundaries
    """
    if not boundaries:
        return []

    # Sort by position
    sorted_bounds = sorted(boundaries, key=lambda b: b.position)

    # Add virtual boundaries at start (-1) and end
    positions = [-1] + [b.position for b in sorted_bounds] + [total_notes - 1]

    # Check each group size
    valid_positions = set()
    for i in range(len(positions) - 1):
        group_size = positions[i + 1] - positions[i]
        if group_size >= config.min_group_size:
            if positions[i + 1] < total_notes - 1:  # Not the end boundary
                valid_positions.add(positions[i + 1])

    # Filter boundaries
    return [b for b in sorted_bounds if b.position in valid_positions]


def split_into_groups(
    notes: Sequence[NoteEvent],
    boundaries: list[GroupBoundary],
) -> list[list[NoteEvent]]:
    """Split notes into groups based on detected boundaries.

    Args:
        notes: Sequence of notes
        boundaries: Detected boundaries

    Returns:
        List of note groups
    """
    if not notes:
        return []

    if not boundaries:
        return [list(notes)]

    groups: list[list[NoteEvent]] = []
    positions = sorted([b.position for b in boundaries])

    start = 0
    for pos in positions:
        # Boundary is AFTER position, so group includes notes[start:pos+1]
        groups.append(list(notes[start:pos + 1]))
        start = pos + 1

    # Add remaining notes
    if start < len(notes):
        groups.append(list(notes[start:]))

    return groups
