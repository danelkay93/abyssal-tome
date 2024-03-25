import contextlib

import pytest
from bs4 import BeautifulSoup
from hypothesis import given
from hypothesis.strategies import lists, sampled_from, text
from pydantic import ValidationError

from scripts.process_new_format import Ruling, RulingType, process_ruling_html


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


@given(question=text(), answer=text())
def test_question_ruling_with_hypothesis(question, answer) -> None:
    with contextlib.suppress(ValidationError):
        ruling = Ruling(ruling_type=RulingType.QUESTION,
                        question=question, answer=answer)
        assert ruling.question == question  # noqa: S101
        assert ruling.answer == answer  # noqa: S101


@given(
    content=lists(text(), min_size=1),
    ruling_type=sampled_from(
        [RulingType.ERRATA, RulingType.CLARIFICATION, RulingType.NOTE]),
)
def test_ruling_content_with_hypothesis(content: list[str], ruling_type: RulingType) -> None:
    ruling = Ruling(ruling_type=ruling_type, content=content)
    assert ruling.ruling_type == ruling_type
    assert ruling.content == content
    assert ruling.question is None  # noqa: S101
    assert ruling.answer is None
