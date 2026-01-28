"""Transformer from parsed AST representations to formal AST nodes.

This module provides utilities for transforming and validating AST nodes
produced by the parser. It bridges the parser output with the formal AST
specification defined in docs/bp3_ast_spec.md.

The Lark grammar (bp3.lark) serves as the formal reference specification.
The actual parsing is done by the regex-based parser in parser.py, which
produces the same AST node types.
"""

from __future__ import annotations

from bp2sc.ast_nodes import (
    BPFile, GrammarBlock, Rule,
    Note, Rest, NonTerminal, Variable, Wildcard,
    Polymetric, SpecialFn, Lambda, HomoApply, HomoApplyKind,
    TimeSig, Annotation, RHSElement,
)


def validate_ast(bp_file: BPFile) -> list[str]:
    """Validate an AST for structural correctness.

    Returns a list of warning messages (empty if valid).
    """
    warnings: list[str] = []

    if not bp_file.grammars:
        warnings.append("No grammar blocks found")

    for block in bp_file.grammars:
        if block.mode not in ("ORD", "RND", "LIN", "SUB", "SUB1"):
            warnings.append(f"Unknown mode: {block.mode}")

        for rule in block.rules:
            if not rule.lhs:
                warnings.append(
                    f"Rule gram#{rule.grammar_num}[{rule.rule_num}] has empty LHS"
                )
            _validate_elements(rule.rhs, warnings, rule)

    return warnings


def _validate_elements(
    elements: list[RHSElement],
    warnings: list[str],
    rule: Rule,
) -> None:
    """Validate RHS elements recursively."""
    for elem in elements:
        if isinstance(elem, HomoApply):
            if not isinstance(elem.kind, HomoApplyKind):
                warnings.append(
                    f"Rule gram#{rule.grammar_num}[{rule.rule_num}]: "
                    f"HomoApply.kind should be HomoApplyKind enum, got {type(elem.kind)}"
                )
            _validate_elements(elem.elements, warnings, rule)
        elif isinstance(elem, Polymetric):
            for voice in elem.voices:
                _validate_elements(voice, warnings, rule)


def collect_defined_symbols(bp_file: BPFile) -> set[str]:
    """Collect all symbols that appear as LHS in production rules."""
    defined: set[str] = set()
    for block in bp_file.grammars:
        for rule in block.rules:
            for elem in rule.lhs:
                if isinstance(elem, NonTerminal):
                    defined.add(elem.name)
                elif isinstance(elem, Variable):
                    defined.add(elem.name)
    return defined


def collect_terminal_symbols(bp_file: BPFile) -> set[str]:
    """Collect symbols that appear in RHS but have no production rules.

    These are terminal sound-objects (e.g., 'ek', 'do', 'tin').
    """
    defined = collect_defined_symbols(bp_file)
    terminals: set[str] = set()

    for block in bp_file.grammars:
        for rule in block.rules:
            for elem in _walk_rhs(rule.rhs):
                if isinstance(elem, NonTerminal) and elem.name not in defined:
                    terminals.add(elem.name)
    return terminals


def _walk_rhs(elements: list[RHSElement]) -> list[RHSElement]:
    """Recursively walk all RHS elements including nested ones."""
    result: list[RHSElement] = []
    for elem in elements:
        result.append(elem)
        if isinstance(elem, Polymetric):
            for voice in elem.voices:
                result.extend(_walk_rhs(voice))
        elif isinstance(elem, HomoApply):
            result.extend(_walk_rhs(elem.elements))
    return result
