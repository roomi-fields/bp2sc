"""Structure inference module for BP3 polymetric grouping.

This module provides heuristics for inferring polymetric structure from
flat musical sequences (MIDI/MusicXML) using GTTM-inspired rules.

The main entry point is `infer_structure()` which takes a sequence of notes
and returns a BP3-style polymetric expression.

Example:
    >>> from bp2sc.structure_inference import load_file, infer_structure
    >>> notes = load_file("example.mid")  # or .xml, .musicxml
    >>> structure = infer_structure(notes)
    >>> print(structure.to_bp3())
    {3, C4 D4 E4} {2, F4 G4}
"""

from .grouping import (
    NoteEvent,
    GroupBoundary,
    detect_groupings,
)
from .polymetric import (
    PolymetricGroup,
    PolymetricStructure,
    build_polymetric_structure,
    infer_structure,
)
from .gttm_rules import (
    GTTMConfig,
    compute_gap_strength,
    compute_register_change,
    compute_ioi_change,
    compute_articulation_change,
)
from .io import (
    load_file,
    load_midi,
    load_musicxml,
)

__all__ = [
    # Core types
    "NoteEvent",
    "GroupBoundary",
    "PolymetricGroup",
    "PolymetricStructure",
    # Main functions
    "infer_structure",
    "detect_groupings",
    "build_polymetric_structure",
    # I/O
    "load_file",
    "load_midi",
    "load_musicxml",
    # GTTM utilities
    "GTTMConfig",
    "compute_gap_strength",
    "compute_register_change",
    "compute_ioi_change",
    "compute_articulation_change",
]
