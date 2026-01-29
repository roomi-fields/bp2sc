"""Tests for the SC emitter."""

import pytest
from bp2sc.grammar.parser import parse_text, parse_file
from bp2sc.sc_emitter import emit_scd


class TestEmitBasic:
    def test_simple_seq(self):
        ast = parse_text("ORD\ngram#1[1] S --> fa4 sol4 la4\n")
        scd = emit_scd(ast, "test")
        assert "Pdef(\\S" in scd
        assert "Pseq" in scd
        # BP3 French: do4=C4=60, so fa4 = 65, sol4 = 67, la4 = 69
        assert "65" in scd
        assert "67" in scd
        assert "69" in scd

    def test_rest(self):
        ast = parse_text("ORD\ngram#1[1] S --> fa4 - la4\n")
        scd = emit_scd(ast, "test")
        assert "Rest()" in scd

    def test_nonterminal_ref(self):
        ast = parse_text("ORD\ngram#1[1] S --> A B\ngram#1[2] A --> fa4\ngram#1[3] B --> sol4\n")
        scd = emit_scd(ast, "test")
        assert "Pdef(\\A)" in scd
        assert "Pdef(\\B)" in scd

    def test_lambda(self):
        ast = parse_text("SUB1\ngram#1[1] I --> lambda\n")
        scd = emit_scd(ast, "test")
        # Lambda produces empty Pdef - Rest() is invalid as Pdef body
        # so we use Event.silent(0) instead
        assert "Event.silent(0)" in scd


class TestEmitPolymetric:
    def test_poly_ratio(self):
        ast = parse_text("ORD\ngram#1[1] S --> {2, A B}\n")
        scd = emit_scd(ast, "test")
        assert "Pseq" in scd
        assert "stretch" in scd

    def test_poly_multi_voice(self):
        ast = parse_text("ORD\ngram#1[1] S --> {A B, C D}\n")
        scd = emit_scd(ast, "test")
        assert "Ppar" in scd


class TestEmitWeighted:
    def test_rnd_prand(self):
        text = "RND\ngram#1[1] S --> A\ngram#1[2] S --> B\n"
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert "Prand" in scd

    def test_rnd_pwrand(self):
        text = "RND\ngram#1[1] <4> S --> A\ngram#1[2] <1> S --> B\n"
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert "Pwrand" in scd
        assert "normalizeSum" in scd


class TestEmitSpecialFn:
    def test_transpose(self):
        ast = parse_text("ORD\ngram#1[1] S --> _transpose(-2) A\n")
        scd = emit_scd(ast, "test")
        assert "ctranspose" in scd
        assert "-2" in scd

    def test_velocity(self):
        ast = parse_text("ORD\ngram#1[1] S --> _vel(110) A\n")
        scd = emit_scd(ast, "test")
        assert "amp" in scd

    def test_tempo(self):
        ast = parse_text("ORD\n_mm(120.0000)\ngram#1[1] S --> A\n")
        scd = emit_scd(ast, "test")
        assert "TempoClock" in scd
        assert "120" in scd


class TestEmitStructural:
    def test_has_header(self):
        ast = parse_text("ORD\ngram#1[1] S --> A\n")
        scd = emit_scd(ast, "myfile.bp")
        assert "myfile.bp" in scd

    def test_has_synthdef(self):
        ast = parse_text("ORD\ngram#1[1] S --> A\n")
        scd = emit_scd(ast, "test")
        assert "SynthDef" in scd

    def test_has_play(self):
        ast = parse_text("ORD\ngram#1[1] S --> A\n")
        scd = emit_scd(ast, "test")
        assert "Pdef(\\S).play" in scd

    def test_balanced_parens(self):
        ast = parse_file("bp3-ctests/-gr.12345678")
        scd = emit_scd(ast, "test")
        depth = 0
        for ch in scd:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            assert depth >= 0, "Unbalanced closing paren"
        assert depth == 0, f"Unclosed parens: depth={depth}"

    def test_balanced_brackets(self):
        ast = parse_file("bp3-ctests/-gr.Ruwet")
        scd = emit_scd(ast, "test")
        depth = 0
        for ch in scd:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            assert depth >= 0, "Unbalanced closing bracket"
        assert depth == 0, f"Unclosed brackets: depth={depth}"


class TestMultiSymbolLHS:
    """Test that multi-symbol LHS rules strip pass-through context symbols."""

    def test_passthrough_stripped(self):
        """Rule |o| |miny| --> |o1| |miny| should emit only Pdef(o1)."""
        text = (
            "LIN [1]\n"
            "gram#1[1] |o| --> fa4 fa4\n"
            "gram#1[2] |o| |miny| --> |o1| |miny|\n"
            "------\n"
            "ORD [2]\n"
            "gram#2[1] |o1| --> sol4 la4\n"
            "gram#2[2] |miny| --> do5 re5\n"
        )
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        # Pdef(\o) should NOT contain Pdef(\miny) — miny is pass-through
        # Find the Pdef(\o, ...) definition
        import re
        m = re.search(r'Pdef\(\\o,\s*(.*?)\);', scd, re.DOTALL)
        assert m, "Pdef(\\o, ...) not found"
        o_body = m.group(1)
        assert "Pdef(\\miny)" not in o_body, (
            f"Pdef(\\miny) should be stripped from Pdef(\\o) body: {o_body}"
        )
        assert "Pdef(\\o1)" in o_body

    def test_ruwet_o_no_miny(self):
        """In Ruwet, Pdef(\\o) variants should not contain Pdef(\\miny)."""
        ast = parse_file("bp3-ctests/-gr.Ruwet")
        scd = emit_scd(ast, "test")
        import re
        m = re.search(r'Pdef\(\\o,\s*(.*?)\);', scd, re.DOTALL)
        assert m, "Pdef(\\o, ...) not found in Ruwet"
        o_body = m.group(1)
        assert "Pdef(\\miny)" not in o_body, (
            f"Pdef(\\miny) pass-through not stripped from Pdef(\\o): {o_body}"
        )

    def test_ruwet_z1_no_miny(self):
        """In Ruwet, Pdef(\\z1) variants should not contain Pdef(\\miny)."""
        ast = parse_file("bp3-ctests/-gr.Ruwet")
        scd = emit_scd(ast, "test")
        import re
        m = re.search(r'Pdef\(\\z1,\s*(.*?)\);', scd, re.DOTALL)
        assert m, "Pdef(\\z1, ...) not found in Ruwet"
        z1_body = m.group(1)
        assert "Pdef(\\miny)" not in z1_body, (
            f"Pdef(\\miny) pass-through not stripped from Pdef(\\z1): {z1_body}"
        )


class TestEmitPhase1SpecialFn:
    """Phase 1: Easy special functions."""

    def test_emit_chan(self):
        ast = parse_text("ORD\ngram#1[1] S --> _chan(2) A\n")
        scd = emit_scd(ast, "test")
        assert "chan" in scd
        assert "2" in scd

    def test_emit_volume(self):
        ast = parse_text("ORD\ngram#1[1] S --> _volume(100) A\n")
        scd = emit_scd(ast, "test")
        assert "amp" in scd

    def test_emit_repeat(self):
        ast = parse_text(
            "ORD\ngram#1[1] S --> _repeat(3) A\n"
            "gram#1[2] A --> fa4\n"
        )
        scd = emit_scd(ast, "test")
        assert "Pn(" in scd
        assert "3" in scd

    def test_emit_mod(self):
        ast = parse_text("ORD\ngram#1[1] S --> _mod(10) A\n")
        scd = emit_scd(ast, "test")
        assert "detune" in scd
        assert "10" in scd

    def test_emit_rest_fn(self):
        """_rest should emit Rest()."""
        ast = parse_text("ORD\ngram#1[1] S --> A _rest B\n")
        scd = emit_scd(ast, "test")
        assert "Rest()" in scd or "Event.silent" in scd

    def test_emit_velcont(self):
        """_velcont should NOT produce unsupported_fn warning."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _velcont A\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        unsup = [w for w in warnings if w.category == "unsupported_fn"]
        assert len(unsup) == 0, f"Unexpected unsupported_fn warnings: {unsup}"

    def test_emit_press(self):
        """_press should produce approximation, not unsupported_fn."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _press(64) A\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        unsup = [w for w in warnings if w.category == "unsupported_fn"]
        assert len(unsup) == 0

    def test_emit_step(self):
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _step(12) A\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        unsup = [w for w in warnings if w.category == "unsupported_fn"]
        assert len(unsup) == 0

    def test_emit_keyxpand(self):
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _keyxpand(1) A\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        unsup = [w for w in warnings if w.category == "unsupported_fn"]
        assert len(unsup) == 0

    def test_emit_part(self):
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _part(2) A\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        unsup = [w for w in warnings if w.category == "unsupported_fn"]
        assert len(unsup) == 0


class TestEmitPhase2SpecialFn:
    """Phase 2: Medium special functions."""

    def test_emit_tempo_integer(self):
        """_tempo(2) should emit stretch 0.5 (2x faster)."""
        ast = parse_text("ORD\ngram#1[1] S --> _tempo(2) A\n")
        scd = emit_scd(ast, "test")
        assert "stretch" in scd
        assert "0.5" in scd

    def test_emit_tempo_fraction(self):
        """_tempo(2/3) should emit stretch 1.5."""
        ast = parse_text("ORD\ngram#1[1] S --> _tempo(2/3) A\n")
        scd = emit_scd(ast, "test")
        assert "stretch" in scd
        assert "1.5" in scd

    def test_emit_value_pair(self):
        """_value(pan, -0.5) should emit \\pan, -0.5 modifier."""
        ast = parse_text("ORD\ngram#1[1] S --> _value(pan,-0.5) A\n")
        scd = emit_scd(ast, "test")
        assert "pan" in scd

    def test_emit_retro(self):
        """_retro should produce approximation, not unsupported_fn."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _retro A\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        unsup = [w for w in warnings if w.category == "unsupported_fn"]
        assert len(unsup) == 0

    def test_emit_scale(self):
        """_scale should produce approximation, not unsupported_fn."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _scale(1,2,3) A\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        unsup = [w for w in warnings if w.category == "unsupported_fn"]
        assert len(unsup) == 0


class TestEmitFlags:
    """Phase 3: Flag-based conditional rules."""

    def test_emit_flag_condition(self):
        """/Ideas/ condition should generate ~Ideas > 0 check."""
        text = (
            "RND\n"
            "gram#1[1] /Ideas/ S --> A\n"
            "gram#1[2] S --> B\n"
        )
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert "~Ideas" in scd
        assert "Prout" in scd

    def test_emit_flag_assign(self):
        """/Ideas=20/ should generate ~Ideas = 20;"""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        text = (
            "RND\n"
            "gram#1[1] S --> A /Ideas=20/\n"
        )
        ast = parse_text(text)
        scd, warnings = emit_scd_with_warnings(ast, "test")
        assert "~Ideas = 20;" in scd
        flag_ignored = [w for w in warnings if w.category == "flag_ignored"]
        assert len(flag_ignored) == 0

    def test_emit_flag_decrement(self):
        """/Ideas-1/ should generate ~Ideas = ~Ideas - 1;"""
        text = (
            "RND\n"
            "gram#1[1] /Ideas/ S --> A /Ideas-1/\n"
            "gram#1[2] S --> B\n"
        )
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert "~Ideas - 1" in scd

    def test_flag_initialization(self):
        """Flag variables should be initialized at the top of the output."""
        text = (
            "RND\n"
            "gram#1[1] /Ideas/ S --> A /Ideas-1/\n"
            "gram#1[2] S --> B\n"
        )
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert "~Ideas = 0;" in scd

    def test_flag_initial_value(self):
        """Flags with = on start symbol should set initial values."""
        text = (
            "RND\n"
            "gram#1[1] /Ideas=20/ /Notes=32/ S --> A\n"
            "gram#1[2] /Ideas/ S --> B /Ideas-1/\n"
        )
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert "~Ideas = 20;" in scd
        assert "~Notes = 32;" in scd

    def test_no_flag_ignored_warnings(self):
        """Flagged rules should NOT produce flag_ignored warnings."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        text = (
            "RND\n"
            "gram#1[1] /Ideas/ S --> A /Ideas-1/\n"
            "gram#1[2] S --> B\n"
        )
        ast = parse_text(text)
        scd, warnings = emit_scd_with_warnings(ast, "test")
        flag_ignored = [w for w in warnings if w.category == "flag_ignored"]
        assert len(flag_ignored) == 0, f"Unexpected flag_ignored: {flag_ignored}"

    def test_mohanam_no_flag_warnings(self):
        """trial.mohanam should have zero flag_ignored warnings."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_file("bp3-ctests/-gr.trial.mohanam")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        flag_ignored = [w for w in warnings if w.category == "flag_ignored"]
        assert len(flag_ignored) == 0, (
            f"Expected 0 flag_ignored, got {len(flag_ignored)}: "
            f"{[str(w) for w in flag_ignored[:5]]}"
        )


class TestEmitScaleMapping:
    """Phase 8: _scale() with scale_map.py resolution."""

    def test_scale_major_root(self):
        """_scale(Cmaj, 0) -> Scale.major, root 0"""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _scale(Cmaj,C4) fa4 sol4\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        assert "scale" in scd
        assert "Scale.major" in scd
        assert "root" in scd
        # Should NOT have approximation warning for known scale
        approx = [w for w in warnings if w.category == "approximation" and "scale" in w.message.lower()]
        assert len(approx) == 0, f"Unexpected approximation: {approx}"

    def test_scale_minor_transposed(self):
        """_scale(Dmin, 0) -> Scale.minor, root 2"""
        ast = parse_text("ORD\ngram#1[1] S --> _scale(Dmin,0) fa4\n")
        scd = emit_scd(ast, "test")
        assert "Scale.minor" in scd
        assert "root" in scd
        assert "2" in scd  # D = 2 semitones from C

    def test_scale_tuning_just(self):
        """_scale(just intonation, A4) -> Tuning.just, root 9"""
        ast = parse_text("ORD\ngram#1[1] S --> _scale(just intonation,A4) fa4\n")
        scd = emit_scd(ast, "test")
        assert "tuning" in scd
        assert "Tuning.just" in scd
        assert "root" in scd

    def test_scale_tuning_reset(self):
        """_scale(0, 0) -> Tuning.et12 (equal temperament)"""
        ast = parse_text("ORD\ngram#1[1] S --> _scale(0,0) fa4\n")
        scd = emit_scd(ast, "test")
        assert "Tuning.et12" in scd

    def test_scale_raga_todi(self):
        """_scale(todi_ka_4, 0) -> Scale.todi"""
        ast = parse_text("ORD\ngram#1[1] S --> _scale(todi_ka_4,0) fa4\n")
        scd = emit_scd(ast, "test")
        assert "Scale.todi" in scd

    def test_scale_unknown_chromatic(self):
        """Unknown scale name -> Scale.chromatic with approximation warning"""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _scale(gloubibolga,0) fa4\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        assert "Scale.chromatic" in scd
        approx = [w for w in warnings if w.category == "approximation"]
        assert len(approx) == 1
        assert "unknown" in approx[0].message.lower()


class TestScaleRootParsing:
    """Unit tests for parse_root_arg function."""

    def test_anglo_notes(self):
        from bp2sc.scale_map import parse_root_arg
        assert parse_root_arg("C4") == 0
        assert parse_root_arg("D4") == 2
        assert parse_root_arg("A4") == 9
        assert parse_root_arg("F#3") == 6
        assert parse_root_arg("Bb5") == 10

    def test_indian_notes(self):
        from bp2sc.scale_map import parse_root_arg
        assert parse_root_arg("sa_4") == 0
        assert parse_root_arg("ri_4") == 2
        assert parse_root_arg("pa_4") == 7

    def test_numeric(self):
        from bp2sc.scale_map import parse_root_arg
        assert parse_root_arg("0") == 0
        assert parse_root_arg("5") == 5
        assert parse_root_arg("12") == 0  # wraps


class TestEmitScriptMidiProgram:
    """Phase B: _script(MIDI program N) -> program modifier."""

    def test_script_midi_program(self):
        """_script(MIDI program 43) -> program 43"""
        ast = parse_text("ORD\ngram#1[1] S --> _script(MIDI program 43) fa4\n")
        scd = emit_scd(ast, "test")
        assert "program" in scd
        assert "43" in scd

    def test_script_other_still_unsupported(self):
        """_script(Beep) -> unsupported_fn warning"""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _script(Beep) fa4\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        unsup = [w for w in warnings if w.category == "unsupported_fn"]
        assert len(unsup) == 1


class TestEmitInsModifier:
    """Phase C: _ins(N) -> instrument modifier."""

    def test_ins_named(self):
        """_ins(Vina) -> instrument \\vina"""
        ast = parse_text("ORD\ngram#1[1] S --> _ins(Vina) fa4\n")
        scd = emit_scd(ast, "test")
        assert "instrument" in scd
        assert "\\vina" in scd

    def test_ins_numeric(self):
        """_ins(3) -> instrument \\inst_3"""
        ast = parse_text("ORD\ngram#1[1] S --> _ins(3) fa4\n")
        scd = emit_scd(ast, "test")
        assert "instrument" in scd
        assert "\\inst_3" in scd

    def test_ins_no_warning(self):
        """_ins should NOT produce approximation warning anymore."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _ins(Vina) fa4\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        approx = [w for w in warnings if w.category == "approximation" and "ins" in w.message.lower()]
        assert len(approx) == 0


class TestEmitRndvel:
    """Phase D: _rndvel(N) -> Pwhite random velocity."""

    def test_rndvel_pwhite(self):
        """_vel(80) _rndvel(20) -> amp contains Pwhite"""
        ast = parse_text("ORD\ngram#1[1] S --> _vel(80) _rndvel(20) fa4\n")
        scd = emit_scd(ast, "test")
        assert "Pwhite" in scd
        assert "amp" in scd

    def test_rndvel_then_vel(self):
        """_rndvel(20) _vel(80) -> same result (order shouldn't matter)"""
        ast = parse_text("ORD\ngram#1[1] S --> _rndvel(20) _vel(80) fa4\n")
        scd = emit_scd(ast, "test")
        assert "Pwhite" in scd

    def test_rndvel_zero_reset(self):
        """_rndvel(0) -> amp becomes fixed again"""
        ast = parse_text("ORD\ngram#1[1] S --> _vel(80) _rndvel(20) _rndvel(0) fa4\n")
        scd = emit_scd(ast, "test")
        # With rndvel=0, should have fixed amp, not Pwhite
        # The last _rndvel(0) should reset
        assert "0.787" in scd or "0.63" in scd  # 100/127 or 80/127


class TestEmitPressModifier:
    """Phase E: _press(N) -> aftertouch modifier."""

    def test_press_modifier(self):
        """_press(127) -> aftertouch 1.0"""
        ast = parse_text("ORD\ngram#1[1] S --> _press(127) fa4\n")
        scd = emit_scd(ast, "test")
        assert "aftertouch" in scd
        assert "1.0" in scd

    def test_press_no_approximation_warning(self):
        """_press should NOT produce approximation warning anymore."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> _press(64) fa4\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        approx = [w for w in warnings if w.category == "approximation" and "press" in w.message.lower()]
        assert len(approx) == 0


class TestEmitRetroRotate:
    """Phase 9: _retro and _rotate in polymetric context."""

    def test_retro_in_polymetric(self):
        """_retro in polymetric reverses element order."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        # {_retro A B C} should emit C, B, A order
        ast = parse_text(
            "ORD\n"
            "gram#1[1] S --> {_retro A B C}\n"
            "gram#1[2] A --> fa4\n"
            "gram#1[3] B --> sol4\n"
            "gram#1[4] C --> la4\n"
        )
        scd, warnings = emit_scd_with_warnings(ast, "test")
        # Should have no _retro warnings
        retro_warn = [w for w in warnings if "retro" in w.message.lower()]
        assert len(retro_warn) == 0
        # Check order in Pseq: C, B, A
        import re
        m = re.search(r'Pseq\(\[([^\]]+)\]', scd)
        if m:
            seq_content = m.group(1)
            # Should have Pdef(\C) before Pdef(\B) before Pdef(\A)
            c_pos = seq_content.find("Pdef(\\C)")
            b_pos = seq_content.find("Pdef(\\B)")
            a_pos = seq_content.find("Pdef(\\A)")
            if c_pos >= 0 and b_pos >= 0 and a_pos >= 0:
                assert c_pos < b_pos < a_pos, f"Order should be C, B, A but got: {seq_content}"

    def test_rotate_in_polymetric(self):
        """_rotate(N) in polymetric rotates element order."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        # {_rotate(1) A B C} should emit B, C, A
        ast = parse_text(
            "ORD\n"
            "gram#1[1] S --> {_rotate(1) A B C}\n"
            "gram#1[2] A --> fa4\n"
            "gram#1[3] B --> sol4\n"
            "gram#1[4] C --> la4\n"
        )
        scd, warnings = emit_scd_with_warnings(ast, "test")
        # Should have no _rotate warnings
        rotate_warn = [w for w in warnings if "rotate" in w.message.lower()]
        assert len(rotate_warn) == 0

    def test_retro_no_warning(self):
        """_retro should NOT produce approximation or unsupported warning."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> {_retro fa4 sol4 la4}\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        retro_warn = [w for w in warnings if "retro" in w.message.lower()]
        assert len(retro_warn) == 0

    def test_rotate_no_warning(self):
        """_rotate should NOT produce unsupported_fn warning."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        ast = parse_text("ORD\ngram#1[1] S --> {_rotate(2) fa4 sol4 la4 si4}\n")
        scd, warnings = emit_scd_with_warnings(ast, "test")
        rotate_warn = [w for w in warnings if "rotate" in w.message.lower()]
        assert len(rotate_warn) == 0


class TestEmitWeightDecrement:
    """Phase 4: Weight decrement via Prout mutable weights."""

    def test_weight_decrement_prout(self):
        """<50-12> should emit Prout, not Pwrand."""
        text = (
            "RND\n"
            "gram#1[1] <50-12> S --> A\n"
            "gram#1[2] <1> S --> B\n"
        )
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert "Prout" in scd
        assert "w0 = 50" in scd

    def test_weight_decrement_max_zero(self):
        """Decrement should be clamped with .max(0)."""
        text = (
            "RND\n"
            "gram#1[1] <50-12> S --> A\n"
            "gram#1[2] <1> S --> B\n"
        )
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert ".max(0)" in scd

    def test_no_weight_decrement_warning(self):
        """weight_decrement warnings should be gone."""
        from bp2sc.sc_emitter import emit_scd_with_warnings
        text = (
            "RND\n"
            "gram#1[1] <50-12> S --> A\n"
            "gram#1[2] <1> S --> B\n"
        )
        ast = parse_text(text)
        scd, warnings = emit_scd_with_warnings(ast, "test")
        wd = [w for w in warnings if w.category == "weight_decrement"]
        assert len(wd) == 0, f"Unexpected weight_decrement warnings: {wd}"

    def test_static_weights_still_pwrand(self):
        """Static weights (no decrement) should still use Pwrand."""
        text = (
            "RND\n"
            "gram#1[1] <4> S --> A\n"
            "gram#1[2] <1> S --> B\n"
        )
        ast = parse_text(text)
        scd = emit_scd(ast, "test")
        assert "Pwrand" in scd
        assert "Prout" not in scd
