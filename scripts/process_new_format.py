import json
import logging
from pathlib import Path
from pprint import pp

import bs4
import markdown_it as md_it
import markdownify
from bs4 import BeautifulSoup

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

from enum import Enum, auto


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


# def ahlcg_symbol_plugin(md: md_it.MarkdownIt) -> None:
#     def inline_custom_tokenizer(state):
#         tokens = state.tokens
#         i = 0
#         while i < len(tokens) - 2:
#             # Assuming the token type that encloses symbols is 'text'
#             if (tokens[i].type == 'text' and tokens[i].content == '[' and
#                     tokens[i + 1].type == 'text' and
#                     tokens[i + 2].type == 'text' and tokens[i + 2].content == ']'):
#                 symbol = tokens[i + 1].content
#                 if symbol in TAG_TO_LETTER:
#                     # Create a new token for the symbol
#                     symbol_token = state.push("symbol", "", 0)
#                     new_token = state.push('text', '', 0)


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
        card_code: BeautifulSoup(card_data["text"]) for card_code, card_data in faq_data.items()
    }


def print_token_stream(tokens: list[md_it.token.Token], nest_level: int = 0) -> None:
    for token in tokens:
        for i in range(nest_level):
            print(f"{' ' * 2 * i}‾‾‾|")
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


def process_ruling_html(ruling: BeautifulSoup) -> list[str]:
    ruling_sections = []
    for strong in ruling.find_all("strong"):
        stripped_strong = strong.get_text(strip=True).strip(":").lower()
        if stripped_strong in TEXT_TO_RULING_TYPE:
            between = []
            for nxt in strong.find_next_siblings():
                if isinstance(nxt, bs4.Tag):
                    if nxt.name == "strong":
                        break
                    between.append(nxt)
                    between.append(nxt.get_text(strip=True))
                elif isinstance(nxt, bs4.NavigableString):
                    between.append(str(nxt))
            ruling_text = ' '.join(between).strip()
            print(f"Ruling type: {stripped_strong}, Text: {ruling_text}")
            ruling_sections.append(ruling_text)
    return ruling_sections


def process_html_faq_data(
    html_faq_data: dict[str, BeautifulSoup],
) -> dict[str, list[BeautifulSoup]]:
    processed_data = {}

    for card_code, rulings_html in html_faq_data.items():
        # Find all list item tags and create a new BeautifulSoup object for each list item's contents
        rulings = (
            BeautifulSoup("".join(str(content) for content in list_item.contents))
            for list_item in rulings_html.find_all("li")
        )

        for ruling in rulings:
            process_ruling_html(ruling)

        # Add the generator of BeautifulSoup objects to the processed data
        processed_data[card_code] = list(rulings)

        print(f"Rulings for {card_code}:\n")
        for i, ruling in enumerate(processed_data[card_code]):
            print(f"Ruling {i + 1}:\n{ruling.prettify()}\n")
        print(f"\n{'=' * 80}\n\n")

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