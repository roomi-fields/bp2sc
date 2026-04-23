"""GTTM-inspired grouping rules for structure inference.

This module implements heuristics based on the Generative Theory of Tonal Music
(Lerdahl & Jackendoff, 1983) Grouping Preference Rules (GPRs).

Key GPRs implemented:
- GPR 2a (Proximity): Slur/rest creates boundary
- GPR 2b (Change): Attack-point distance change creates boundary
- GPR 3a (Register): Large pitch interval creates boundary
- GPR 3c (Dynamics): Intensity change creates boundary
- GPR 3d (Articulation): Articulation change creates boundary

The rules are applied locally to detect potential group boundaries between
consecutive notes. The strength of each boundary is computed as a weighted
sum of the individual rule activations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .grouping import NoteEvent


@dataclass
class GTTMConfig:
    """Configuration for GTTM rule weights and thresholds.

    Attributes:
        gap_weight: Weight for GPR 2a/2b (temporal proximity)
        register_weight: Weight for GPR 3a (pitch interval)
        ioi_weight: Weight for GPR 2b (IOI change)
        articulation_weight: Weight for GPR 3d (articulation change)
        dynamics_weight: Weight for GPR 3c (velocity change)

        gap_threshold: Minimum gap ratio to consider as boundary (vs median IOI)
        register_threshold: Minimum semitones for significant register change
        ioi_ratio_threshold: Minimum IOI ratio change to consider significant
        dynamics_threshold: Minimum velocity change (0-127) for boundary

        min_group_size: Minimum notes in a group
        max_group_size: Maximum notes in a group (soft limit)
        boundary_threshold: Minimum combined strength to create boundary
    """
    # Rule weights (sum to 1.0 for interpretability)
    gap_weight: float = 0.35
    register_weight: float = 0.25
    ioi_weight: float = 0.20
    articulation_weight: float = 0.10
    dynamics_weight: float = 0.10

    # Thresholds
    gap_threshold: float = 1.5  # Gap > 1.5x median IOI is significant
    register_threshold: int = 7  # Perfect fifth (7 semitones) is significant
    ioi_ratio_threshold: float = 1.8  # 80% change in IOI is significant
    dynamics_threshold: int = 30  # ~24% of velocity range (0-127)

    # Structural constraints
    min_group_size: int = 2
    max_group_size: int = 12
    boundary_threshold: float = 0.25  # Combined strength threshold (lowered from 0.4)

    # Pattern detection
    enable_pattern_detection: bool = True
    pattern_similarity_threshold: float = 0.85


def compute_gap_strength(
    note1: NoteEvent,
    note2: NoteEvent,
    median_ioi: float,
    config: GTTMConfig,
) -> float:
    """Compute GPR 2a/2b: proximity/gap boundary strength.

    A large gap (silence) between notes suggests a group boundary.
    The strength is normalized based on the ratio to median IOI.

    Args:
        note1: First note (ends before gap)
        note2: Second note (starts after gap)
        median_ioi: Median inter-onset interval in the sequence
        config: GTTM configuration

    Returns:
        Boundary strength in [0, 1] based on gap size
    """
    if median_ioi <= 0:
        return 0.0

    # Gap is the time from end of note1 to start of note2
    gap = note2.onset - (note1.onset + note1.duration)

    if gap <= 0:
        # No gap (overlapping or adjacent notes)
        return 0.0

    # Normalize gap by median IOI
    gap_ratio = gap / median_ioi

    if gap_ratio < config.gap_threshold:
        # Gap is too small to be significant
        return 0.0

    # Sigmoid-like scaling: maps gap_ratio to [0, 1]
    # At threshold, strength is ~0; at 3x threshold, strength is ~1
    normalized = (gap_ratio - config.gap_threshold) / config.gap_threshold
    strength = min(1.0, normalized / 2.0)

    return strength


def compute_register_change(
    note1: NoteEvent,
    note2: NoteEvent,
    config: GTTMConfig,
) -> float:
    """Compute GPR 3a: register change boundary strength.

    A large pitch interval between consecutive notes suggests a group boundary.
    This reflects the gestalt principle that distant elements are perceived
    as separate.

    Args:
        note1: First note
        note2: Second note
        config: GTTM configuration

    Returns:
        Boundary strength in [0, 1] based on pitch interval
    """
    interval = abs(note2.pitch - note1.pitch)

    if interval < config.register_threshold:
        return 0.0

    # Linear scaling from threshold to octave+fifth (19 semitones)
    max_interval = 19
    normalized = (interval - config.register_threshold) / (max_interval - config.register_threshold)
    strength = min(1.0, normalized)

    return strength


def compute_ioi_change(
    note1: NoteEvent,
    note2: NoteEvent,
    note3: NoteEvent | None,
    config: GTTMConfig,
) -> float:
    """Compute GPR 2b: IOI change boundary strength.

    A significant change in inter-onset interval suggests a boundary.
    This detects rhythmic discontinuities (e.g., switching from 8th notes
    to quarter notes).

    Args:
        note1: First note
        note2: Second note (potential boundary point)
        note3: Third note (None if note2 is last)
        config: GTTM configuration

    Returns:
        Boundary strength in [0, 1] based on IOI ratio change
    """
    if note3 is None:
        return 0.0

    ioi_before = note2.onset - note1.onset
    ioi_after = note3.onset - note2.onset

    if ioi_before <= 0 or ioi_after <= 0:
        return 0.0

    # Compute ratio (always >= 1)
    ratio = max(ioi_before / ioi_after, ioi_after / ioi_before)

    if ratio < config.ioi_ratio_threshold:
        return 0.0

    # Normalize: at threshold, strength is 0; at 3x, strength is 1
    normalized = (ratio - config.ioi_ratio_threshold) / config.ioi_ratio_threshold
    strength = min(1.0, normalized)

    return strength


def compute_articulation_change(
    note1: NoteEvent,
    note2: NoteEvent,
    config: GTTMConfig,
) -> float:
    """Compute GPR 3d: articulation change boundary strength.

    A change in articulation (staccato vs legato) suggests a boundary.
    We approximate articulation by the ratio of note duration to IOI.

    Args:
        note1: First note
        note2: Second note
        config: GTTM configuration

    Returns:
        Boundary strength in [0, 1] based on articulation difference
    """
    # Compute articulation as duration/IOI ratio (legato ~1, staccato <0.5)
    ioi = note2.onset - note1.onset

    if ioi <= 0:
        return 0.0

    # Clamp articulation to [0, 1.5] (can be >1 for overlapping notes)
    art1 = min(1.5, note1.duration / ioi if ioi > 0 else 1.0)
    art2 = min(1.5, note2.duration / ioi if ioi > 0 else 1.0)

    # Articulation change
    change = abs(art2 - art1)

    # Threshold at 0.3 (30% change in articulation)
    if change < 0.3:
        return 0.0

    # Normalize to [0, 1]
    strength = min(1.0, (change - 0.3) / 0.7)

    return strength


def compute_dynamics_change(
    note1: NoteEvent,
    note2: NoteEvent,
    config: GTTMConfig,
) -> float:
    """Compute GPR 3c: dynamics change boundary strength.

    A significant change in velocity (dynamics) suggests a boundary,
    especially when combined with other factors.

    Args:
        note1: First note
        note2: Second note
        config: GTTM configuration

    Returns:
        Boundary strength in [0, 1] based on velocity difference
    """
    if note1.velocity is None or note2.velocity is None:
        return 0.0

    diff = abs(note2.velocity - note1.velocity)

    if diff < config.dynamics_threshold:
        return 0.0

    # Normalize to [0, 1]
    max_diff = 127 - config.dynamics_threshold
    strength = min(1.0, (diff - config.dynamics_threshold) / max_diff)

    return strength


def compute_combined_boundary_strength(
    note1: NoteEvent,
    note2: NoteEvent,
    note3: NoteEvent | None,
    median_ioi: float,
    config: GTTMConfig,
) -> float:
    """Compute combined boundary strength from all GPRs.

    The final strength is a weighted sum of individual rule activations.

    Args:
        note1: First note
        note2: Second note (potential boundary point)
        note3: Third note (for IOI change, None if note2 is last)
        median_ioi: Median inter-onset interval
        config: GTTM configuration

    Returns:
        Combined boundary strength in [0, 1]
    """
    gap_s = compute_gap_strength(note1, note2, median_ioi, config)
    register_s = compute_register_change(note1, note2, config)
    ioi_s = compute_ioi_change(note1, note2, note3, config)
    articulation_s = compute_articulation_change(note1, note2, config)
    dynamics_s = compute_dynamics_change(note1, note2, config)

    combined = (
        config.gap_weight * gap_s
        + config.register_weight * register_s
        + config.ioi_weight * ioi_s
        + config.articulation_weight * articulation_s
        + config.dynamics_weight * dynamics_s
    )

    return combined
