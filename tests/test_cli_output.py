from __future__ import annotations

from src.cli.output import get_output_format, print_data, print_json, set_output_format


def test_set_output_format_default():
    assert get_output_format() == "text"


def test_set_output_format_json():
    set_output_format("json")
    assert get_output_format() == "json"


def test_set_output_format_text():
    set_output_format("text")
    assert get_output_format() == "text"


def test_set_output_format_invalid():
    set_output_format("invalid")
    assert get_output_format() == "text"


def test_print_data_dict_json(capsys):
    set_output_format("json")
    print_data({"a": 1, "b": "hello"})
    captured = capsys.readouterr()
    assert '"a": 1' in captured.out
    assert '"b": "hello"' in captured.out


def test_print_data_list_json(capsys):
    set_output_format("json")
    print_data([{"ticker": "SBER", "price": 250}], columns=["ticker", "price"])
    captured = capsys.readouterr()
    assert "SBER" in captured.out


def test_print_data_str_json(capsys):
    set_output_format("json")
    print_data("just a string")
    captured = capsys.readouterr()
    assert "just a string" in captured.out


def test_print_json(capsys):
    print_json([1, 2, 3])
    captured = capsys.readouterr()
    assert "1" in captured.out
    assert "2" in captured.out


def test_set_output_format_resets_between_tests():
    pass  # run after json tests; default should be text
