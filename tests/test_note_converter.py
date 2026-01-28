"""Tests for note_converter.py."""

import pytest
from bp2sc.note_converter import note_to_midi, detect_convention


class TestFrenchSolfege:
    # BP3 French convention: MIDI = (octave + 1) * 12 + semitone
    # Same as English: do4 = C4 = 60
    def test_do4_is_60(self):
        assert note_to_midi("do", 4) == 60

    def test_la4_is_69(self):
        assert note_to_midi("la", 4) == 69

    def test_sib4(self):
        assert note_to_midi("sib", 4) == 70

    def test_fa4(self):
        assert note_to_midi("fa", 4) == 65

    def test_sol4(self):
        assert note_to_midi("sol", 4) == 67

    def test_do5(self):
        assert note_to_midi("do", 5) == 72

    def test_mi4(self):
        assert note_to_midi("mi", 4) == 64


class TestIndianSargam:
    def test_sa4_is_60(self):
        assert note_to_midi("sa", 4) == 60

    def test_pa6(self):
        assert note_to_midi("pa", 6) == 91

    def test_ga6(self):
        assert note_to_midi("ga", 6) == 88

    def test_dha6(self):
        assert note_to_midi("dha", 6) == 93


class TestAnglo:
    def test_c4_is_60(self):
        assert note_to_midi("C", 4) == 60

    def test_a4_is_69(self):
        assert note_to_midi("A", 4) == 69

    def test_fsharp3(self):
        assert note_to_midi("F#", 3) == 54

    def test_bb5(self):
        assert note_to_midi("Bb", 5) == 82


class TestDetectConvention:
    def test_french(self):
        assert detect_convention(["do", "re", "fa", "sol"]) == "french"

    def test_indian(self):
        assert detect_convention(["sa", "re", "ga", "pa"]) == "indian"

    def test_unknown(self):
        assert detect_convention(["ek", "do", "tin"]) == "french"  # "do" triggers french
