import pytest
from bs4 import BeautifulSoup
from hypothesis import given
from hypothesis.extra.pydantic import from_type

from scripts.process_new_format import Ruling, RulingType, process_ruling_html


@given(from_type(Ruling))
def test_ruling_model_properties(ruling: Ruling) -> None:
    # Verify that the ruling instance adheres to the properties defined in the Ruling model
    assert isinstance(ruling.ruling_type, RulingType)
    assert isinstance(ruling.content, list)
    for item in ruling.content:
        assert isinstance(item, bs4.Tag | str)


# Existing tests...
def test_process_ruling_html_empty_input() -> None:
    empty_soup = BeautifulSoup("", "html.parser")
    result = process_ruling_html(empty_soup)
    assert result == []


def test_process_ruling_html_with_valid_input() -> None:
    html_content = """
    <strong>Errata:</strong> Corrected text.
    <strong>Q:</strong> Question text?
    <strong>A:</strong> Answer text.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    result = process_ruling_html(soup)
    assert len(result) == 2
    assert result[0].ruling_type == RulingType.ERRATA
    assert result[1].ruling_type == RulingType.QUESTION
    assert isinstance(result[0].content[0], str)
    assert isinstance(result[1].content[0], str)
    assert "Corrected text." in result[0].content[0]
    assert "Question text?" in result[1].content[0]
    assert "Answer text." in result[1].content[1]


def test_process_ruling_html_combines_q_and_a() -> None:
    html_content = """
    <strong>Q:</strong> Question text?
    <strong>A:</strong> Answer text.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    result = process_ruling_html(soup)
    assert len(result) == 1
    assert result[0].ruling_type == RulingType.QUESTION
    assert len(result[0].content) == 2
    assert "Question text?" in result[0].content[0]
    assert "Answer text." in result[0].content[1]


@pytest.mark.parametrize(
    "input_html,expected_ruling_types",
    [
        ("<strong>Errata:</strong> Some text.", [RulingType.ERRATA]),
        ("<strong>Q:</strong> Question? <strong>A:</strong> Answer.",
         [RulingType.QUESTION]),
        ("<strong>Clarification:</strong> Clarification text.",
         [RulingType.CLARIFICATION]),
    ],
)
def test_process_ruling_html_various_types(input_html, expected_ruling_types) -> None:
    soup = BeautifulSoup(input_html, "html.parser")
    result = process_ruling_html(soup)
    assert len(result) == len(expected_ruling_types)
    for ruling, expected_type in zip(result, expected_ruling_types, strict=False):
        assert ruling.ruling_type == expected_type
