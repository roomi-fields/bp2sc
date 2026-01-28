"""Parser for BP3 alphabet (-al.*) and homomorphism files.

BP3 -al.* files contain two types of data:
1. Terminal alphabets: simple lists of terminal symbol names
2. Homomorphism definitions: mappings from symbol to symbol

File format:
- Lines starting with // are comments
- Lines starting with - are file references (-mi.name, etc.)
- Lines with --> define homomorphism rules: source --> target
- Lines with only --- are section separators
- Other non-empty lines are either:
  - Section names (start of homomorphism block)
  - Terminal names (in alphabet-only files)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HomoRule:
    """A single homomorphism rule: source --> target."""
    source: str
    target: str


@dataclass
class HomoSection:
    """A named homomorphism section containing rules."""
    name: str
    rules: list[HomoRule] = field(default_factory=list)


@dataclass
class AlphabetFile:
    """Parsed content of a -al.* file."""
    name: str
    # Terminal symbols (for simple alphabet files)
    terminals: list[str] = field(default_factory=list)
    # Homomorphism sections (for mapping files)
    homomorphisms: dict[str, HomoSection] = field(default_factory=dict)
    # File references found (-mi.name, etc.)
    file_refs: list[str] = field(default_factory=list)


# Regex for homomorphism rule: source --> target
_RE_HOMO_RULE = re.compile(r'^(.+?)\s*-->\s*(.+)$')
# Regex for file reference: -XX.name
_RE_FILE_REF = re.compile(r'^-([a-z]{2})\.(.+)$')
# Regex for section separator: three or more dashes
_RE_SEPARATOR = re.compile(r'^-{3,}$')


def parse_alphabet_file(path: str | Path) -> AlphabetFile:
    """Parse a BP3 alphabet file.

    Args:
        path: Path to the -al.* file

    Returns:
        AlphabetFile with terminals and/or homomorphism sections
    """
    path = Path(path)
    name = path.name
    if name.startswith("-al."):
        name = name[4:]  # Remove -al. prefix

    result = AlphabetFile(name=name)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    current_section: HomoSection | None = None
    pending_name: str | None = None

    for line in lines:
        line = line.strip()

        # Skip empty lines
        if not line:
            continue

        # Skip comments
        if line.startswith("//"):
            continue

        # Check for file reference
        m = _RE_FILE_REF.match(line)
        if m:
            result.file_refs.append(f"-{m.group(1)}.{m.group(2)}")
            continue

        # Check for section separator
        if _RE_SEPARATOR.match(line):
            # End current section if any
            if current_section and current_section.rules:
                result.homomorphisms[current_section.name] = current_section
            current_section = None
            pending_name = None
            continue

        # Check for homomorphism rule
        m = _RE_HOMO_RULE.match(line)
        if m:
            source, target = m.group(1).strip(), m.group(2).strip()
            if current_section is None:
                # Need to create a section from pending name
                if pending_name:
                    current_section = HomoSection(name=pending_name)
                else:
                    # Anonymous section - use "*"
                    current_section = HomoSection(name="*")
            current_section.rules.append(HomoRule(source=source, target=target))
            pending_name = None
            continue

        # Check for special keywords
        if line.lower() in ("sync", "*"):
            # These are directives, not section names
            continue

        # This is either a section name or a terminal
        # If we're in a homomorphism context (have rules), it's a section name
        # Otherwise, it could be a terminal
        if current_section and current_section.rules:
            # Save current section and start new one
            result.homomorphisms[current_section.name] = current_section
            current_section = None

        # Store as pending name (might be section name or terminal)
        if pending_name:
            # Previous pending was a terminal (no --> followed)
            result.terminals.append(pending_name)
        pending_name = line

    # Handle remaining pending name
    if pending_name:
        if current_section and not current_section.rules:
            # Was a section name with no rules
            pass
        else:
            result.terminals.append(pending_name)

    # Save last section
    if current_section and current_section.rules:
        result.homomorphisms[current_section.name] = current_section

    return result


def parse_alphabet_dir(dir_path: str | Path) -> dict[str, AlphabetFile]:
    """Parse all -al.* files in a directory.

    Args:
        dir_path: Directory containing BP3 files

    Returns:
        Dict mapping file names (without -al. prefix) to AlphabetFile
    """
    dir_path = Path(dir_path)
    results = {}

    for path in dir_path.glob("-al.*"):
        try:
            af = parse_alphabet_file(path)
            results[af.name] = af
        except Exception:
            pass

    return results


def get_homomorphism_mapping(
    alphabet_files: dict[str, AlphabetFile],
    homo_name: str
) -> dict[str, str] | None:
    """Get a homomorphism mapping by name.

    Searches all alphabet files for a homomorphism section with the given name.

    Args:
        alphabet_files: Dict of parsed alphabet files
        homo_name: Name of the homomorphism (e.g., "mineur", "m1")

    Returns:
        Dict mapping source symbols to target symbols, or None if not found
    """
    for af in alphabet_files.values():
        if homo_name in af.homomorphisms:
            section = af.homomorphisms[homo_name]
            return {r.source: r.target for r in section.rules}
    return None
