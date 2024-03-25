import json
import logging
from enum import Enum, auto
from pathlib import Path
from pprint import pp

import bs4
import markdown_it as md_it
import markdownify
from bs4 import BeautifulSoup
from pydantic import BaseModel

from symbol import postProcess, tokenize

logging.basicConfig(level=logging.INFO)

FAQS_PATH = Path(r"../faqs/faqs.json")

TAG_TO_LETTER = {
    "willpower": "p",
    "agility": "a",
    "combat": "c",
    "intellect": "b",
    "skull": "k",
    "cultist": "l",
    "tablet": "q",
    "elderthing": "n",
    "autofail": "m",
    "eldersign": "o",
    "bless": "v",
    "curse": "w",
    "frost": "x",
    "reaction": "!",
    "unique": "s",
    "mystic": "g",
    "guardian": "f",
    "seeker": "h",
    "rogue": "d",
    "survivor": "e",
    "free": "j",
    "action": "i",
}


class RulingType(Enum):
    ERRATA = auto()
    ADDENDUM = auto()
    QUESTION = auto()
    ANSWER = auto()
    CLARIFICATION = auto()
    NOTE = auto()
    FOLLOWUP_Q = auto()
    UPDATE = auto()
    AS_IF = auto()
    AUTOMATIC_SUCCESS_FAILURE = auto()
    AUTOMATIC_SUCCESS_FAILURE_AUTOMATIC_EVASION = auto()


class Ruling(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    ruling_type: RulingType
    question: str | None = None
    answer: str | None = None
    content: list[str] | None = None

    def __init__(self, **data) -> None:
        super().__init__(**data)
        if self.ruling_type in [RulingType.QUESTION, RulingType.ANSWER] and not self.content:
            self.content = [self.question, self.answer]


TEXT_TO_RULING_TYPE = {
    "errata": RulingType.ERRATA,
    "addendum": RulingType.ADDENDUM,
    "q": RulingType.QUESTION,
    "a": RulingType.ANSWER,
    "clarification": RulingType.CLARIFICATION,
    "note": RulingType.NOTE,
    "follow-up q": RulingType.FOLLOWUP_Q,
    "update": RulingType.UPDATE,
    '"as if"': RulingType.AS_IF,
    "automatic success/failure": RulingType.AUTOMATIC_SUCCESS_FAILURE,
    "automatic success/failure &  automatic evasion": RulingType.AUTOMATIC_SUCCESS_FAILURE_AUTOMATIC_EVASION,
}

RULING_REMOVAL_PATTERNS = [
    "FAQ removed - double-checking provenance.",
    "OVERRULED SEE BELOW",
    "SEE BELOW",
    'Matt writes: "This was unintentional and we are looking into fixing this, perhaps in the next edition of the FAQ."',
    "A: [NB see follow-up Q]",
]

RULING_STRIP_PATTERNS = [
    "NB: ArkhamDB now incorporates errata from the Arkham Horror FAQ in its card text, so the ArkhamDB text and the card image above differ, as the ArkhamDB text has been edited to contain this erratum (updated August 2022): ",
    '"As If": This was added to the FAQ (v.1.7, March 2020) and then amended (v.1.8, October 2020). You can read the October ruling on the ArkhamDB rules page here. (I\'m adding a hyperlink rather than retyping the rules in case in future the ruling is changed or amended - at that point, the rules page will be updated and all ArkhamDB FAQ entries will link to the correct ruling.)',
]


def load_faqs(faqs_path: Path) -> dict[str, dict[str, str]]:
    if not faqs_path.exists():
        raise FileNotFoundError(f"File {faqs_path} does not exist.")
    if not faqs_path.is_file():
        raise ValueError(f"Path {faqs_path} is not a file.")
    if faqs_path.suffix != ".json":
        raise ValueError(f"File {faqs_path} is not a JSON file.")
    if not faqs_path.stat().st_size:
        raise ValueError(f"File {faqs_path} is empty.")

    with faqs_path.open() as file:
        return json.load(file)


def convert_html_to_markdown(faq_data: dict[str, dict[str, str]]) -> dict[str, str]:
    return {
        card_code: markdownify.markdownify(card_data["text"])
        for card_code, card_data in faq_data.items()
    }


def convert_json_to_html(faq_data: dict[str, dict[str, str]]) -> dict[str, BeautifulSoup]:
    return {
        card_code: BeautifulSoup(card_data["text"], features="html.parser")
        for card_code, card_data in faq_data.items()
    }


def print_token_stream(tokens: list[md_it.token.Token], nest_level: int = 0) -> None:
    for token in tokens:
        for i in range(nest_level):
            print(f"{' ' * 2 * i}Ã¢ÂÂ¾Ã¢ÂÂ¾Ã¢ÂÂ¾|")
        if not token.children:
            tok = token.as_dict(
                children=True, filter=lambda k, v: k in ("type", "tag", "markup", "content")
            )
            print(
                f"{' ' * 4 * nest_level}{tok['type']=} {tok['tag']=} {tok['markup']=} {tok.get('info')=}\n"
            )
            if tok["content"]:
                print(" " * 4 * nest_level, end="")
                pp(tok["content"])
        else:
            childless = token.as_dict(
                children=True, filter=lambda k, v: k in ("type", "tag", "markup", "content")
            )
            if "children" in childless:
                childless.pop("children")
            print(
                f"Parent Token:\n{' ' * 4 * nest_level}{childless['type']=} {childless['tag']=} {childless['markup']=} {childless.get('info')=}\n"
            )
            if childless["content"]:
                print(" " * 4 * nest_level, end="")
                pp(childless["content"])
            print_token_stream(token.children, nest_level + 1)


def process_markdown_faq_data(markdown_faq_data: dict[str, str]) -> None:
    md = md_it.MarkdownIt("gfm-like", {"typographer": True})
    md.enable(["replacements", "smartquotes"])
    md.inline.ruler.push("symbol", tokenize)
    md.inline.ruler2.push("symbol", postProcess)

    for card_code, rulings_text in markdown_faq_data.items():
        tokens = md.parse(rulings_text)
        print(f"Tokens for {card_code}:\n")
        print_token_stream(tokens)
        print(f"\n{'=' * 80}\n\n")


def process_ruling_html(ruling: BeautifulSoup) -> list[Ruling]:
    rulings = []
    current_question = None
    for strong in ruling.find_all("strong"):
        stripped_strong = strong.get_text(strip=True).strip(":").lower()
        if stripped_strong in TEXT_TO_RULING_TYPE:
            between = []
            for nxt in strong.next_siblings:
                if isinstance(nxt, bs4.Tag | bs4.NavigableString):
                    if isinstance(nxt, bs4.Tag) and nxt.name == "strong":
                        break
                    content_str = str(nxt).strip()
                    if content_str:  # Only add non-empty strings
                        between.append(content_str)
            ruling_type = TEXT_TO_RULING_TYPE[stripped_strong]
            if ruling_type == RulingType.QUESTION:
                current_question = " ".join(between)
            elif ruling_type == RulingType.ANSWER and current_question is not None:
                rulings.append(
                    Ruling(
                        ruling_type=RulingType.QUESTION,
                        question=current_question,
                        answer=" ".join(between),
                    )
                )
                current_question = None
            else:
                rulings.append(
                    Ruling(ruling_type=ruling_type, content=between))
    return rulings


def process_html_faq_data(
    html_faq_data: dict[str, BeautifulSoup],
) -> dict[str, list[BeautifulSoup]]:
    processed_data = {}

    for card_code, rulings_html in html_faq_data.items():
        # Find all list item tags and create a new BeautifulSoup object for each list item's contents
        rulings = (
            BeautifulSoup(
                "".join(str(content) for content in list_item.contents), features="html.parser"
            )
            for list_item in rulings_html.find_all("li")
        )

        processed_rulings = []
        for ruling in rulings:
            processed_rulings.append(process_ruling_html(ruling))
            print(f"Processed rulings for {card_code}:\n")
            print(processed_rulings[-1])

        # Add the generator of BeautifulSoup objects to the processed data
        processed_data[card_code] = list(rulings)

    return processed_data


def main() -> None:
    try:
        faq_data = load_faqs(FAQS_PATH)
    except (FileNotFoundError, ValueError) as e:
        logging.error(f"Error loading faqs: {e}, aborting.")
        return
    else:
        logging.info("Successfully loaded faqs.")

    html_faq_data = convert_json_to_html(faq_data)

    process_html_faq_data(html_faq_data)

    # markdown_faq_data = convert_html_to_markdown(faq_data)

    # process_markdown_faq_data(markdown_faq_data)


if __name__ == "__main__":
    main()
