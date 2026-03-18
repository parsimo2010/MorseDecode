"""Tests for the Morse code lookup table and trie."""

import pytest
from morse_decode.decoder.morse_table import (
    decode_elements,
    encode_char,
    is_valid_prefix,
    MORSE_TREE,
    DECODE_TABLE,
    PROSIGN_CODES,
    MAX_CODE_LEN,
)


class TestDecodeTable:
    def test_letters(self):
        assert decode_elements(".-") == "A"
        assert decode_elements("-...") == "B"
        assert decode_elements(".") == "E"
        assert decode_elements("-") == "T"
        assert decode_elements("--..") == "Z"

    def test_digits(self):
        assert decode_elements(".----") == "1"
        assert decode_elements("-----") == "0"
        assert decode_elements("...--") == "3"

    def test_punctuation(self):
        assert decode_elements(".-.-.-") == "."
        assert decode_elements("--..--") == ","
        assert decode_elements("..--..") == "?"

    def test_prosigns_override_punctuation(self):
        # <AR> == '+', prosign wins in DECODE_TABLE
        assert decode_elements(".-.-.") == "<AR>"
        assert decode_elements("-...-") == "<BT>"
        assert decode_elements("-.--.") == "<KN>"
        assert decode_elements("...-.-") == "<SK>"

    def test_unknown_sequence(self):
        assert decode_elements("......") is None
        assert decode_elements("") is None

    def test_all_entries_non_empty(self):
        for code, char in DECODE_TABLE.items():
            assert code, "empty code in table"
            assert char, "empty char in table"
            assert all(c in ".−-" for c in code), f"invalid element in code {code!r}"

    def test_max_code_len(self):
        assert MAX_CODE_LEN >= 5   # standard ITU max
        assert MAX_CODE_LEN <= 12  # prosigns extend to ~9


class TestEncodeTable:
    def test_letters(self):
        assert encode_char("A") == ".-"
        assert encode_char("E") == "."
        assert encode_char("T") == "-"

    def test_case_insensitive(self):
        assert encode_char("a") == ".-"
        assert encode_char("z") == "--.."

    def test_digits(self):
        assert encode_char("0") == "-----"
        assert encode_char("5") == "....."

    def test_prosigns(self):
        assert encode_char("<AR>") == ".-.-."
        assert encode_char("<SK>") == "...-.-"
        assert encode_char("<BT>") == "-...-"

    def test_unknown_char(self):
        assert encode_char("~") is None


class TestMorseTrie:
    def test_navigate_to_A(self):
        node = MORSE_TREE
        node = node.get(".")
        assert node is not None
        node = node.get("-")
        assert node is not None
        assert node.char == "A"

    def test_navigate_to_E(self):
        node = MORSE_TREE
        node = node.get(".")
        assert node is not None
        assert node.char == "E"

    def test_navigate_to_SK(self):
        # <SK> = ...-.-  (end of contact — one of the longest kept prosigns)
        node = MORSE_TREE
        for ch in "...-.-":
            node = node.get(ch)
            assert node is not None, f"tree path broke at {ch}"
        assert node.char == "<SK>"

    def test_invalid_prefix(self):
        # <HH> and <SOS> are removed; long dit-runs are no longer valid prefixes
        assert is_valid_prefix(".......") is False  # <HH> removed
        assert is_valid_prefix(".-.-.-.-") is False  # too long / invalid

    def test_root_has_no_char(self):
        assert MORSE_TREE.char is None


class TestProsignCodes:
    def test_all_prosigns_in_table(self):
        for code in PROSIGN_CODES:
            assert code in DECODE_TABLE
            char = DECODE_TABLE[code]
            assert char.startswith("<") and char.endswith(">"), \
                f"prosign code {code!r} maps to non-prosign char {char!r}"
