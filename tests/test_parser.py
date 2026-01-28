"""Tests for the BP3 parser."""

import pytest
from bp2sc.grammar.parser import parse_text, parse_file
from bp2sc.ast_nodes import (
    BPFile, GrammarBlock, Rule, Weight, Flag,
    Note, Rest, NonTerminal, Variable, Wildcard,
    Polymetric, SpecialFn, Lambda, HomoApply, HomoApplyKind, TimeSig,
    Comment, FileRef, InitDirective, Annotation,
)


class TestParseHeaders:
    def test_comment(self):
        ast = parse_text("// Hello world\nORD\ngram#1[1] S --> A\n")
        assert len(ast.headers) == 1
        assert isinstance(ast.headers[0], Comment)
        assert ast.headers[0].text == "Hello world"

    def test_file_ref(self):
        ast = parse_text("-se.EkDoTin\n-al.EkDoTin\nORD\ngram#1[1] S --> A\n")
        assert len(ast.headers) == 2
        assert isinstance(ast.headers[0], FileRef)
        assert ast.headers[0].prefix == "se"
        assert ast.headers[0].name == "EkDoTin"

    def test_init_directive(self):
        ast = parse_text("INIT: MIDI program 110\nORD\ngram#1[1] S --> A\n")
        inits = [h for h in ast.headers if isinstance(h, InitDirective)]
        assert len(inits) == 1
        assert "MIDI program 110" in inits[0].text


class TestParseGrammarBlocks:
    def test_single_ord_block(self):
        ast = parse_text("ORD\ngram#1[1] S --> A B\n")
        assert len(ast.grammars) == 1
        assert ast.grammars[0].mode == "ORD"

    def test_multiple_blocks(self):
        text = "RND\ngram#1[1] S --> A\n---\nORD\ngram#2[1] A --> B\n"
        ast = parse_text(text)
        assert len(ast.grammars) == 2
        assert ast.grammars[0].mode == "RND"
        assert ast.grammars[1].mode == "ORD"

    def test_block_with_index(self):
        ast = parse_text("LIN [3]\ngram#3[1] S --> A\n")
        assert ast.grammars[0].mode == "LIN"
        assert ast.grammars[0].index == 3

    def test_block_with_label(self):
        ast = parse_text("RND [Effects]\ngram#9[1] S --> A\n")
        assert ast.grammars[0].label == "Effects"


class TestParseRules:
    def test_simple_rule(self):
        ast = parse_text("ORD\ngram#1[1] S --> A B C\n")
        rule = ast.grammars[0].rules[0]
        assert rule.grammar_num == 1
        assert rule.rule_num == 1
        assert len(rule.lhs) == 1
        assert isinstance(rule.lhs[0], NonTerminal)
        assert rule.lhs[0].name == "S"
        assert len(rule.rhs) == 3

    def test_weight_fixed(self):
        ast = parse_text("RND\ngram#1[1] <4> S --> A\n")
        rule = ast.grammars[0].rules[0]
        assert rule.weight is not None
        assert rule.weight.value == 4
        assert rule.weight.decrement is None

    def test_weight_decrement(self):
        ast = parse_text("RND\ngram#1[1] <50-12> A --> B\n")
        rule = ast.grammars[0].rules[0]
        assert rule.weight.value == 50
        assert rule.weight.decrement == 12

    def test_flags_assign(self):
        ast = parse_text("RND\ngram#1[1] S --> A /Ideas=20/\n")
        rule = ast.grammars[0].rules[0]
        flag = next(f for f in rule.flags if f.name == "Ideas")
        assert flag.op == "="
        assert flag.value == "20"

    def test_flags_condition(self):
        ast = parse_text("RND\ngram#1[1] /Ideas/ S --> A\n")
        rule = ast.grammars[0].rules[0]
        flag = rule.flags[0]
        assert flag.name == "Ideas"
        assert flag.op == ""

    def test_lambda(self):
        ast = parse_text("SUB1\ngram#1[1] I --> lambda\n")
        rule = ast.grammars[0].rules[0]
        assert len(rule.rhs) == 1
        assert isinstance(rule.rhs[0], Lambda)


class TestParseNotes:
    def test_french_solfege(self):
        ast = parse_text("ORD\ngram#1[1] S --> fa4 sol4 la4 sib4 do5\n")
        notes = [e for e in ast.grammars[0].rules[0].rhs if isinstance(e, Note)]
        assert len(notes) == 5
        assert notes[0].name == "fa"
        assert notes[0].octave == 4
        assert notes[3].name == "sib"
        assert notes[4].name == "do"
        assert notes[4].octave == 5

    def test_indian_sargam(self):
        ast = parse_text("ORD\ngram#1[1] S --> sa6 re6 ga6 pa6 dha6\n")
        notes = [e for e in ast.grammars[0].rules[0].rhs if isinstance(e, Note)]
        assert len(notes) == 5
        assert notes[0].name == "sa"
        assert notes[0].octave == 6
        assert notes[4].name == "dha"


class TestParseVariables:
    def test_variable(self):
        ast = parse_text("LIN\ngram#1[1] |x| --> |y| |z|\n")
        rule = ast.grammars[0].rules[0]
        assert isinstance(rule.lhs[0], Variable)
        assert rule.lhs[0].name == "x"
        assert isinstance(rule.rhs[0], Variable)


class TestParsePolymetric:
    def test_poly_with_ratio(self):
        ast = parse_text("ORD\ngram#1[1] S --> {2, A B C}\n")
        rule = ast.grammars[0].rules[0]
        assert len(rule.rhs) == 1
        poly = rule.rhs[0]
        assert isinstance(poly, Polymetric)
        assert poly.tempo_ratio == 2
        assert len(poly.voices) == 1
        assert len(poly.voices[0]) == 3

    def test_poly_multi_voice(self):
        ast = parse_text("ORD\ngram#1[1] S --> {A B, C D}\n")
        rule = ast.grammars[0].rules[0]
        poly = rule.rhs[0]
        assert isinstance(poly, Polymetric)
        assert poly.tempo_ratio is None
        assert len(poly.voices) == 2


class TestParseWildcards:
    def test_wildcards(self):
        ast = parse_text("RND\ngram#1[1] R1 ?1 R2 --> ?1 ?1\n")
        rule = ast.grammars[0].rules[0]
        # LHS: R1, ?1, R2
        assert isinstance(rule.lhs[1], Wildcard)
        assert rule.lhs[1].index == 1
        # RHS: ?1, ?1
        assert isinstance(rule.rhs[0], Wildcard)
        assert isinstance(rule.rhs[1], Wildcard)


class TestParseSpecialFn:
    def test_fn_with_args(self):
        ast = parse_text("RND\ngram#1[1] S --> _vel(110) A _vel(64)\n")
        rhs = ast.grammars[0].rules[0].rhs
        assert isinstance(rhs[0], SpecialFn)
        assert rhs[0].name == "vel"
        assert rhs[0].args == ["110"]

    def test_fn_no_args(self):
        ast = parse_text("ORD\ngram#1[1] S --> _pitchcont A\n")
        rhs = ast.grammars[0].rules[0].rhs
        assert isinstance(rhs[0], SpecialFn)
        assert rhs[0].name == "pitchcont"
        assert rhs[0].args == []

    def test_goto(self):
        ast = parse_text("RND\ngram#1[1] S --> A _goto(2,1)\n")
        rhs = ast.grammars[0].rules[0].rhs
        fns = [e for e in rhs if isinstance(e, SpecialFn)]
        goto = next(f for f in fns if f.name == "goto")
        assert goto.args == ["2", "1"]


class TestParseHomoApply:
    def test_master_slave(self):
        ast = parse_text("ORD\ngram#1[1] S --> (= Tihai) (: Tihai)\n")
        rhs = ast.grammars[0].rules[0].rhs
        assert isinstance(rhs[0], HomoApply)
        assert rhs[0].kind == HomoApplyKind.MASTER
        assert isinstance(rhs[1], HomoApply)
        assert rhs[1].kind == HomoApplyKind.SLAVE


class TestParseRealFiles:
    def test_12345678(self):
        ast = parse_file("bp3-ctests/-gr.12345678")
        assert len(ast.grammars) == 1
        assert ast.grammars[0].mode == "ORD"
        assert len(ast.grammars[0].rules) == 6

    def test_ruwet(self):
        ast = parse_file("bp3-ctests/-gr.Ruwet")
        assert len(ast.grammars) == 5
        total = sum(len(g.rules) for g in ast.grammars)
        assert total == 110  # verified manually

    def test_mohanam(self):
        ast = parse_file("bp3-ctests/-gr.trial.mohanam")
        assert len(ast.grammars) == 9
        # Check first rule has flags
        rule0 = ast.grammars[0].rules[0]
        flag_names = {f.name for f in rule0.flags}
        assert "Ideas" in flag_names
        assert "Notes" in flag_names


class TestParseUppercaseGram:
    """Phase 0: GRAM# case-insensitivity."""

    def test_parse_uppercase_gram(self):
        """Parser should handle GRAM#1[1] (uppercase) the same as gram#1[1]."""
        ast = parse_text("ORD\nGRAM#1[1] S --> A B\n")
        assert len(ast.grammars) == 1
        rule = ast.grammars[0].rules[0]
        assert rule.grammar_num == 1
        assert rule.rule_num == 1
        assert rule.lhs[0].name == "S"

    def test_parse_765432(self):
        """Parse -gr.765432 which uses GRAM# (uppercase). Must find >150 rules."""
        ast = parse_file("bp3-ctests/-gr.765432")
        total = sum(len(g.rules) for g in ast.grammars)
        assert total > 150, f"Expected >150 rules, got {total}"


class TestParseBpgrFiles:
    """Phase 0: .bpgr file parsing."""

    def test_parse_produce_all(self):
        ast = parse_file("bp3-ctests/produce-all.bpgr")
        total = sum(len(g.rules) for g in ast.grammars)
        assert total == 5

    def test_parse_symbols(self):
        ast = parse_file("bp3-ctests/symbols.bpgr")
        total = sum(len(g.rules) for g in ast.grammars)
        assert total == 6

    def test_parse_unknown_terminal(self):
        """Parse unknown-terminal.bpgr with bare rule 'B --> x a'."""
        ast = parse_file("bp3-ctests/unknown-terminal.bpgr")
        total = sum(len(g.rules) for g in ast.grammars)
        assert total == 3  # gram#1[1], gram#1[2], bare B --> x a


class TestParseBareRule:
    """Phase 0: Rules without gram#N[M] prefix."""

    def test_bare_rule(self):
        """B --> x a should be parsed as a rule."""
        ast = parse_text("ORD\ngram#1[1] S --> A B\nB --> x a\n")
        assert len(ast.grammars[0].rules) == 2
        bare_rule = ast.grammars[0].rules[1]
        assert bare_rule.lhs[0].name == "B"
        assert len(bare_rule.rhs) == 2
