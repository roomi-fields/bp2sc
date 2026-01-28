"""CLI entry point for bp2sc: BP3 → SuperCollider transpiler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bp2sc.grammar.parser import parse_file
from bp2sc.sc_emitter import emit_scd


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="bp2sc",
        description="Transpile Bol Processor BP3 grammar files to SuperCollider Pattern code (.scd)",
    )
    parser.add_argument(
        "input",
        help="Path to BP3 grammar file (e.g., -gr.12345678)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output .scd file path (default: stdout)",
    )
    parser.add_argument(
        "--start-symbol",
        default="S",
        help="Start symbol for the grammar (default: S)",
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="List all parsed rules and exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output (include extra comments in .scd)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for deterministic RND grammar output (e.g., 42)",
    )
    parser.add_argument(
        "--alphabet-dir",
        default=None,
        help="Directory containing -al.* alphabet/homomorphism files",
    )
    parser.add_argument(
        "--max-dur",
        type=float,
        default=None,
        help="Maximum duration in beats (wraps in Pfindur to prevent infinite loops)",
    )

    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Parse
    try:
        bp_ast = parse_file(input_path)
    except Exception as e:
        print(f"Error parsing {input_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # List rules mode
    if args.list_rules:
        _print_rules(bp_ast)
        return

    # Emit SC code
    source_name = input_path.name
    scd_code = emit_scd(bp_ast, source_name, args.start_symbol, args.verbose,
                        seed=args.seed, alphabet_dir=args.alphabet_dir,
                        max_dur=args.max_dur)

    # Output
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(scd_code, encoding="utf-8")
        print(f"Written: {output_path}", file=sys.stderr)
    else:
        print(scd_code)


def _print_rules(bp_ast) -> None:
    """Print all parsed rules in a readable format."""
    from bp2sc.ast_nodes import (
        Note, Rest, NonTerminal, Variable, Wildcard,
        Polymetric, SpecialFn, Lambda, HomoApply, TimeSig,
    )

    for block in bp_ast.grammars:
        print(f"\n{'='*60}")
        print(f"Subgrammar {block.index} — Mode: {block.mode}", end="")
        if block.label:
            print(f" [{block.label}]", end="")
        print()
        if block.preamble:
            print(f"  Preamble: {block.preamble}")
        print(f"  Rules: {len(block.rules)}")
        print(f"{'='*60}")

        for rule in block.rules:
            weight_str = f"<{rule.weight.value}" + (f"-{rule.weight.decrement}" if rule.weight.decrement else "") + ">" if rule.weight else ""
            flag_str = " ".join(f"/{_format_flag(f)}/" for f in rule.flags) if rule.flags else ""
            lhs_str = " ".join(_elem_str(e) for e in rule.lhs)
            rhs_str = " ".join(_elem_str(e) for e in rule.rhs)
            print(f"  gram#{rule.grammar_num}[{rule.rule_num}] {weight_str} {flag_str} {lhs_str} --> {rhs_str}")
            if rule.comment:
                print(f"    // {rule.comment}")


def _format_flag(f) -> str:
    if f.op and f.value is not None:
        return f"{f.name}{f.op}{f.value}"
    return f.name


def _elem_str(e) -> str:
    from bp2sc.ast_nodes import (
        Note, Rest, NonTerminal, Variable, Wildcard,
        Polymetric, SpecialFn, Lambda, HomoApply, TimeSig, BracketComment,
    )
    if isinstance(e, Note):
        return f"{e.name}{e.octave}"
    if isinstance(e, Rest):
        return "-" if e.determined else "_"
    if isinstance(e, NonTerminal):
        return e.name
    if isinstance(e, Variable):
        return f"|{e.name}|"
    if isinstance(e, Wildcard):
        return f"?{e.index}"
    if isinstance(e, Polymetric):
        voices = ", ".join(" ".join(_elem_str(x) for x in v) for v in e.voices)
        if e.tempo_ratio:
            return f"{{{e.tempo_ratio}, {voices}}}"
        return f"{{{voices}}}"
    if isinstance(e, SpecialFn):
        if e.args:
            return f"_{e.name}({','.join(e.args)})"
        return f"_{e.name}"
    if isinstance(e, Lambda):
        return "lambda"
    if isinstance(e, HomoApply):
        inner = " ".join(_elem_str(x) for x in e.elements)
        if e.kind == "master":
            return f"(= {inner})"
        if e.kind == "slave":
            return f"(: {inner})"
        return f"homo:{inner}"
    if isinstance(e, TimeSig):
        return e.text
    if isinstance(e, BracketComment):
        return f"[{e.text}]"
    return repr(e)


if __name__ == "__main__":
    main()
