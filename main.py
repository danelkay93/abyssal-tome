import asyncio
import json
import logging
import os
import sys
from base64 import b64encode, urlsafe_b64decode, urlsafe_b64encode
from copy import deepcopy
from enum import StrEnum, unique
from pathlib import Path

import clipman
import flet as ft
import flet_fastapi
import regex as reg
import requests
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport as GQL_Transport
from starlette.middleware.cors import CORSMiddleware
from tqdm.auto import tqdm
from whoosh.fields import ID, TEXT, Schema
from whoosh.index import create_in, open_dir
from whoosh.writing import AsyncWriter

from utils import debounce

logging.basicConfig(level=logging.WARNING, stream=sys.stdout)

# set Flet path to an empty string to serve at the root URL (e.g., https://lizards.ai/)
# or a folder/path to serve beneath the root (e.g., https://lizards.ai/ui/path
DEFAULT_FLET_PATH = ""  # or 'ui/path'
DEFAULT_FLET_PORT = 8502

clipman.init()


# from gql.utilities.build_client_schema import GraphQLSchema


schema = Schema(
    card_name=ID(stored=True),
    ruling_text=TEXT,
    card_code=ID(stored=True),
    ruling_type=TEXT,
    ruling_question=TEXT,
    ruling_answer=TEXT,
)
if not Path("indexdir").exists():
    Path("indexdir").mkdir()
ix = create_in("indexdir", schema)


@unique
class EntryType(StrEnum):
    UNKNOWN = "unknown"
    ERRATUM = "erratum"
    QUESTION_ANSWER = "question/answer"
    CLARIFICATION = "clarification"


@unique
class QAType(StrEnum):
    QUESTION = "question"
    ANSWER = "answer"


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

lookahead_markdown = r"""
\[
  (?P<link_text>                   # Start capturing the link text
    [^\[\]]+                  # Match any character except brackets (simplification)
    (?:                       # Start non-capturing group for possible inner brackets
      \[                      # Match an opening bracket
      [^\[\]]+                # Match any character except brackets
      \]                      # Match a closing bracket
      [^\[\]]+                # Match any character except brackets
    )*                        # Repeat the above non-capturing group as needed
  )                           # End capturing the link text
\]
(?=\([^\)]+\))                # Lookahead to assert the link URL follows
\(
  (?P<link_url>                    # Start capturing the link URL
    [^\(\)]+                  # Match any character except parentheses (simplification)
    (?:                       # Start non-capturing group for possible inner parentheses
      \(                      # Match an opening parenthesis
      [^\(\)]+                # Match any character except parentheses
      \)                      # Match a closing parenthesis
      [^\(\)]+                # Match any character except parentheses
    )*                        # Repeat the above non-capturing group as needed
  )                           # End capturing the link URL
"""
LOOKAHEAD_PATTERN = reg.compile(lookahead_markdown)

LINK_PATTERN = reg.compile(
    r"\[(?P<link_text>[^\[\]]+)\](?=\([^\)]+\))\((?P<link_url>[^\(\)]+)\)")
TAG_PATTERN = reg.compile(
    r"(?P<tag>"
    + r"|".join(reg.escape(f"[{tag}]", special_only=True)
                for tag in TAG_TO_LETTER)
    + ")"
)
print(f"{TAG_PATTERN=}")
BOLD_ITALIC_PATTERN = reg.compile(r"\*\*\*(?P<bold_italic>.*?)\*\*\*")
BOLD_PATTERN = reg.compile(r"\*\*(?P<bolded>.*?)\*\*")
ITALIC_PATTERN = reg.compile(r"\*(?P<italics>.*?)\*")
ALL_PATTERN = "|".join(
    [
        pat.pattern
        for pat in (LINK_PATTERN, TAG_PATTERN, BOLD_ITALIC_PATTERN, BOLD_PATTERN, ITALIC_PATTERN)
    ]
)
ALL_PATTERN = reg.compile(ALL_PATTERN)
print(ALL_PATTERN.pattern)
transport = GQL_Transport(url="https://gapi.arkhamcards.com/v1/graphql")
gql_client = Client(transport=transport, fetch_schema_from_transport=True)


def load_json_data() -> dict:
    logging.info("Loading JSON data from file.")
    with open(Path("assets/processed_data.json"), encoding="utf-8") as file:
        data = json.load(file)
    logging.info("JSON data loaded successfully.")
    return data


async def highlight_text(span: ft.TextSpan, search_term: str) -> list[ft.TextSpan]:
    term_pattern = reg.escape(
        search_term, special_only=True, literal_spaces=True)
    for tag in TAG_TO_LETTER:
        if (
            search_term.lower() in tag
            and span.style
            and span.style.font_family == "Arkham Icons"
            and span.text == TAG_TO_LETTER[tag]
        ):
            span.style.bgcolor = ft.colors.with_opacity(
                0.5, ft.colors.TERTIARY)
            return [span]
    reg.compile(term_pattern, reg.IGNORECASE)
    span_text = span.text
    spans = []
    span_style = span.style
    if span_style is None:
        span_style = ft.TextStyle()
    highlight_style = deepcopy(span_style)
    highlight_style.bgcolor = ft.colors.with_opacity(0.5, ft.colors.TERTIARY)
    # highlight_style.weight = ft.FontWeight.BOLD

    if not span_text:
        return []
    # logging.warning(f"highlight_text called with term: {term} and {len(span_text) if span_text else None} characters.")
    remaining_text = span_text

    while match := reg.search(
        term_pattern, remaining_text.lower(), concurrent=True
    ):  # partial=True):
        start, end = match.span()
        if start > 0:
            pre_span = deepcopy(span)
            pre_span.text = remaining_text[:start]
            spans.append(pre_span)

        mid_span = deepcopy(span)
        mid_span.text = remaining_text[start:end]
        mid_span.style = highlight_style
        spans.append(mid_span)

        remaining_text = remaining_text[end:]
        if not remaining_text:
            break

    if remaining_text:
        end_span = deepcopy(span)
        end_span.text = remaining_text
        spans.append(end_span)

    # logging.warning(f"highlight_text returning {len(spans)} spans.")
    return spans


async def highlight_spans(text_spans: list[ft.TextSpan], search_term: str) -> list[ft.TextSpan]:
    # logging.warning(f"highlight_text_span called with term: {term} and {len(text_spans)} spans.")
    highlighted_spans = []
    for span in text_spans:
        highlighted_spans.extend(await highlight_text(span, search_term))
    return highlighted_spans


def append_span(spans, text, style=None, on_click=None) -> None:
    if text:
        spans.append(ft.TextSpan(
            text=text, style=style or ft.TextStyle(), on_click=on_click))


async def replace_special_tags(page: ft.Page, text: str) -> list[ft.TextSpan]:
    logging.info("Replacing special tags in ruling text.")
    spans = []
    if not text:
        # logging.warning("replace_special_tags called with empty ruling_text.")
        return spans

    remaining_text = text

    while match := ALL_PATTERN.search(remaining_text):
        start, end = match.span()
        if start > 0:
            spans.append(ft.TextSpan(text=remaining_text[:start]))

        mid_span = ft.TextSpan()
        groups = match.groupdict()
        # print(groups)
        if (link_text := groups.get("link_text")) and (link_url := groups.get("link_url")):
            # print(f"{remaining_text=}")
            card_id = link_url.split("/")[-1]
            mid_span.text = link_text
            # print(f"{link_text=}")
            mid_span.style = ft.TextStyle(
                decoration=ft.TextDecoration.UNDERLINE,
                color=ft.colors.ON_SURFACE,
            )
            # mid_span.url = link_url
            mid_span.on_click = lambda event, card_code=card_id: asyncio.create_task(
                on_card_click(event, page, card_code)
            )
            # print(f"mid_span.text: {mid_span.text}")
        elif tag := groups.get("tag"):
            # print(f"Tag match: {tag}")
            mid_span.text = TAG_TO_LETTER[tag.replace(
                "[", "").replace("]", "")]
            mid_span.style = ft.TextStyle(size=20, font_family="Arkham Icons")
            mid_span.data = tag

        if text := groups.get("bold_italic"):
            mid_span.text = mid_span.text or text
            style = mid_span.style or ft.TextStyle()
            style.weight = ft.FontWeight.BOLD
            style.italic = True
            mid_span.style = style
        elif text := groups.get("bolded"):
            mid_span.text = mid_span.text or text
            style = mid_span.style or ft.TextStyle()
            style.weight = ft.FontWeight.BOLD
            mid_span.style = style
        elif text := groups.get("italics"):
            mid_span.text = mid_span.text or text
            style = mid_span.style or ft.TextStyle()
            style.italic = True
            mid_span.style = style
        # print(f"mid_span text after: {mid_span.text}")
        # else:
        #     mid_span.text = mid_span.text or remaining_text[start:end],
        #     mid_span.weight = ft.FontWeight.BOLD

        spans.append(mid_span)

        remaining_text = remaining_text[end:]

    if remaining_text:
        spans.append(ft.TextSpan(text=remaining_text))

    if not spans:
        logging.error(f"No spans were created for ruling_text: {ruling_text}")

    return spans


async def on_card_click(event: ft.ControlEvent, page: ft.Page, card_id: str) -> None:
    logging.info(f"Card clicked with ID: {card_id}")
    image_url = await retrieve_image_url(card_id)

    async def close_dialog() -> None:
        dialog.open = False  # Close the Dialog
        await page.close_dialog_async()
        page.dialog = None
        # dialog.visible = False  # Hide the Dialog

        await page.update_async()

    image = await retrieve_image_binary(image_url)
    # print(f"image type: {imghdr.what("", h=image.content)}")
    image_card = ft.Image(src_base64=image, expand=True)

    # Close button to dismiss the Dialog
    close_button = ft.IconButton(
        icon=ft.icons.CLOSE, on_click=lambda e: asyncio.create_task(
            close_dialog())
    )
    # Dialog containing the Card and the Close button
    dialog_content = ft.Card(image_card, expand=True)
    dialog = ft.AlertDialog(
        content=dialog_content,
        actions=[close_button],
        actions_alignment=ft.MainAxisAlignment.START,
        modal=True,
        on_dismiss=lambda e: print("Closed!"),
        shape=ft.RoundedRectangleBorder(radius=ft.border_radius.all(0)),
        content_padding=ft.padding.all(0),
    )
    # Function to add the Dialog to the page's overlay and update the page
    page.dialog = dialog
    page.dialog.open = True

    print("Updating page with image alert dialog")
    await page.update_async()
    await page.dialog.update_async()


async def retrieve_image_binary(image_url: str) -> str:
    # Check that image_url is retrievable and is a valid image using requests and Pillow
    # If not, display an error message instead of the image
    # If it is, display the image in an AlertDialog
    image = requests.get(image_url)
    if image.status_code != 200:
        logging.error(
            f"Image URL: {image_url} returned status code: {image.status_code}")
    else:
        logging.info(
            f"Image URL: {image_url} returned status code: {image.status_code}")
    return b64encode(image.content).decode("ascii")


async def retrieve_image_url(card_id: str) -> str:
    gql_query = gql(
        f"""
        query getCardImageURL {{
            all_card (where: {{code: {{_eq: "{card_id}"}}}}) {{
                imageurl
            }}
        }}
        """
    )
    gql_result = await gql_client.execute_async(gql_query)
    # image_url = gql_result['data']['all_card'][0]['imageurl']
    # print(f"{gql_result=}")
    image_url = gql_result["all_card"][0]["imageurl"]
    if not image_url:
        logging.error(f"No image URL found for card_id: {card_id}")
    return image_url


async def retrieve_card_text(card_id: str) -> dict:
    gql_query = gql(
        f"""
        query getCardText {{
            all_card_text (where: {{id: {{_eq: "{card_id}"}}}}) {{
                back_flavor
                back_name
                back_text
                back_traits
                customization_change
                customization_text
                encounter_name
                taboo_original_back_text
                taboo_original_text
                taboo_text_change
            }}
        }}
        """
    )
    gql_result = await gql_client.execute_async(gql_query)
    results = gql_result["all_card_text"][0]
    if not results:
        logging.error(f"No card text results found for card_id: {card_id}")
    return results


async def copy_ruling_to_clipboard(
    event: ft.ControlEvent, ruling_text: str, button: ft.ElevatedButton
) -> None:
    logging.info("Copying ruling to clipboard.")
    clipman.copy(ruling_text)
    clip.style.shadow = ft.BoxShadow(
        spread_radius=-1,
        blur_radius=10,
        color=ft.colors.BLACK,
        offset=ft.Offset(2, 2),
        blur_style=ft.ShadowBlurStyle.NORMAL,
    )
    await button.update_async()
    await asyncio.sleep(0.3)
    clip.style.shadow = None
    await button.update_async()


async def go_to_card_page(
    event: ft.ControlEvent, page: ft.Page, card_code: str, card_name: str
) -> None:
    await page.go_async(
        f"/card/{urlsafe_b64encode(card_name.encode('ascii')).decode('ascii')}/{card_code}"
    )
    await page.update_async()


class SearchController:
    def __init__(self, page: ft.Page, data: dict[str, list[dict]]) -> None:
        logging.info("Initializing SearchView.")
        self.page = page
        self.page_content: ft.Column = page.views[0].controls[1]
        self.data = data

    async def create_text_spans(
        self,
        ruling_type: EntryType,
        search_term: str,
        ruling_text: str = "",
        question_or_answer: QAType = None,
    ) -> list[ft.TextSpan]:
        if not ruling_text:
            logging.warning(
                # f"create_text_spans called with empty ruling_text for ruling_type: {ruling_type} and question_or_answer: {question_or_answer}"
            )
            return []

        if ruling_type == EntryType.QUESTION_ANSWER:
            if question_or_answer == QAType.QUESTION:
                ruling_type_name = "Question"
            elif question_or_answer == QAType.ANSWER:
                ruling_type_name = "Answer"
        else:
            ruling_type_name = ruling_type.title()

        text_spans = [
            ft.TextSpan(
                text=f"{ruling_type_name}: ",
                style=ft.TextStyle(weight=ft.FontWeight.BOLD),
            )
        ]

        # Replace link and icon tags with their respective controls

        ruling_text_control_spans = await replace_special_tags(self.page, ruling_text)
        # Highlight the spans that match the search term
        if search_term:
            ruling_text_control_spans = await highlight_spans(
                ruling_text_control_spans, search_term
            )

        text_spans.extend(ruling_text_control_spans)

        return text_spans

    async def update_search_view(self, search_term: str) -> None:
        async def create_copy_button(
            ruling_text: str, ruling_question: str, ruling_answer: str
        ) -> ft.IconButton:
            # clip = ft.TextSpan(
            #     text=u"📋",
            #     style=ft.TextStyle(size=20),
            #     on_click=lambda e,
            #                     rules_text=ruling_text or fr"Q: {ruling_question}\n A: {ruling_answer}": asyncio.create_task(
            #         copy_ruling_to_clipboard(e, rules_text, clip)),
            #
            # )
            return ft.IconButton(
                icon=ft.icons.COPY,
                icon_size=20,
                on_click=lambda e,
                rules_text=ruling_text
                or rf"Q: {ruling_question}\n A: {ruling_answer}": asyncio.create_task(
                    copy_ruling_to_clipboard(e, rules_text, clip)
                ),
                style=ft.ButtonStyle(
                    elevation={"pressed": 0, "": 1},
                    animation_duration=500,
                    shape=ft.RoundedRectangleBorder(
                        radius=ft.border_radius.all(10)),
                ),
            )

        self.page_content.scroll = None
        self.page_content.controls.clear()

        # logging.info(f"Updating search view with term: {search_term}")
        content_controls = ft.ListView(
            controls=[], expand=True
        )  # This will hold all the controls to be added to the content
        if not search_term:
            logging.warning(
                "update_search_view called with empty search_term.")

        # Sort the data by card name
        # self.data = dict(sorted(self.data.items()))

        for card_name, card_rulings in tqdm(
            self.data.items(),
            total=len(self.data),
            position=0,
            leave=True,
            desc="Processing all cards",
        ):
            card_added = False
            text = []  # Initialize the text list to hold Text controls for each ruling
            for _i, ruling in tqdm(
                enumerate(card_rulings),
                disable=False,
                total=len(card_rulings),
                position=1,
                leave=False,
                desc="Processing rulings",
            ):
                ruling_content = ruling.get("content", {})
                ruling_type = ruling.get("type", EntryType.UNKNOWN)
                ruling_text = ruling_content.get("text", "")
                ruling_question = ruling_content.get("question", "")
                ruling_answer = ruling_content.get("answer", "")
                card_id = ruling.get("card_code", "")

                text_spans = []

                if ruling_type == EntryType.QUESTION_ANSWER and (
                    not ruling_question or not ruling_answer
                ):
                    # logging.warning(
                    #     f"Question/Answer ruling is missing content for card: {card_name=} {ruling_question=} {ruling_answer=}")
                    ...

                if (
                    not ruling_text.strip()
                    and not ruling_question.strip()
                    and not ruling_answer.strip()
                ):
                    logging.warning(
                        f"Ruling content is empty for card: {card_name}")
                    continue

                # with ix.searcher() as searcher:
                #     query = QueryParser("ruling_text", ix.schema).parse(search_term)
                #     query2 = QueryParser("card_name", ix.schema).parse(search_term)
                #     query3 = QueryParser("question_text", ix.schema).parse(search_term)
                #     query4 = QueryParser("answer_text", ix.schema).parse(search_term)
                #     results = searcher.search(query).docs() or searcher.search(query2).docs() or searcher.search(query3).docs() or searcher.search(query4).docs()
                #     if not results:
                #         continue
                if (
                    search_term.lower() not in ruling_text.lower()
                    and search_term.lower() not in ruling_question.lower()
                    and search_term.lower() not in ruling_answer.lower()
                ):
                    continue

                copy_button = await create_copy_button(ruling_text, ruling_question, ruling_answer)
                text_spans.append(copy_button)

                match ruling_type:
                    case EntryType.UNKNOWN:
                        logging.warning(
                            f"Unknown ruling type for card {card_name=}. Ruling type: {ruling_type=} Ruling text: {ruling_text, ruling_question, ruling_answer=} "
                        )
                        text_spans.append(ft.TextSpan(ruling_text))
                    case EntryType.ERRATUM | EntryType.CLARIFICATION:
                        text_spans.extend(
                            await self.create_text_spans(ruling_type, search_term, ruling_text)
                        )
                    case EntryType.QUESTION_ANSWER:
                        if ruling_question:
                            text_spans.extend(
                                await self.create_text_spans(
                                    ruling_type,
                                    search_term,
                                    ruling_question,
                                    QAType.QUESTION,
                                )
                            )
                            text_spans.append(ft.TextSpan(text="\n"))
                        if ruling_answer:
                            text_spans.extend(
                                await self.create_text_spans(
                                    ruling_type,
                                    search_term,
                                    ruling_answer,
                                    QAType.ANSWER,
                                )
                            )

                        # text_spans.append(ft.Divider())
                if not card_added and text_spans:
                    card_added = True
                    text.append(
                        ft.Text(
                            spans=[
                                ft.TextSpan(
                                    card_name,
                                    style=ft.TextStyle(
                                        color=ft.colors.ON_SURFACE,
                                        decoration_color=ft.colors.ON_SURFACE,
                                        decoration=ft.TextDecoration.UNDERLINE,
                                    ),
                                    on_click=lambda e,
                                    name=card_name,
                                    card_code=card_id: asyncio.create_task(
                                        go_to_card_page(
                                            e, self.page, card_code, name)
                                    ),
                                )
                            ],
                            theme_style=ft.TextThemeStyle.TITLE_MEDIUM,
                            selectable=True,
                        )
                    )

                copy_button = await create_copy_button(ruling_text, ruling_question, ruling_answer)
                text.append(
                    ft.Container(
                        ft.Row(
                            [copy_button, ft.Text(
                                spans=text_spans, selectable=True, expand=True)],
                            scroll=None,
                            expand=True,
                        )
                    )
                )
                col = ft.Column([*text, ft.Divider()]
                                if True else [], scroll=None)
                # col = ft.Column(text + ([ft.Divider()] if (i + 1) < len(card_rulings) else []), scroll=None)

                if text:
                    content_controls.controls.append(col)
                    text = []

            # if card_added:
            # content_controls.controls.append(ft.Divider(thickness=5))

        # Remove the progress ring and text
        self.page_content.controls.clear()
        self.page_content.controls.append(
            ft.Text(
                spans=[
                    ft.TextSpan("Search results for "),
                    ft.TextSpan(
                        f'"{search_term}":',
                    ),
                ],
                theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM,
            )
        )

        # After processing all cards, if no content_controls were added, it means no results were found
        if not content_controls.controls:
            logging.info("No search results found for term: " + search_term)
            content_controls.controls.clear()
            content_controls.controls.append(ft.Text("No results found."))

        self.page_content.controls.append(content_controls)
        # self.page_content.controls = tuple(self.page_content.controls)
        await self.page.update_async()
        await self.page_content.update_async()

    async def get_rulings_for_card(
        self, page: ft.Page, card_name: str, card_code: str, image_binary: str, card_text
    ) -> None:
        async def create_copy_button(
            ruling_text: str, ruling_question: str, ruling_answer: str
        ) -> ft.IconButton:
            return ft.IconButton(
                icon=ft.icons.COPY,
                icon_size=20,
                on_click=lambda e,
                rules_text=ruling_text
                or rf"Q: {ruling_question}\n A: {ruling_answer}": asyncio.create_task(
                    copy_ruling_to_clipboard(e, rules_text, clip)
                ),
                style=ft.ButtonStyle(
                    elevation={"pressed": 0, "": 1},
                    animation_duration=500,
                    shape=ft.RoundedRectangleBorder(
                        radius=ft.border_radius.all(10)),
                ),
            )

        card_rulings = self.data[card_name]
        print(f"{card_rulings=}")
        text = []  # Initialize the text list to hold Text controls for each ruling
        for ruling in card_rulings:
            ruling_content = ruling.get("content", {})
            ruling_type = ruling.get("type", EntryType.UNKNOWN)
            ruling_text = ruling_content.get("text", "")
            ruling_question = ruling_content.get("question", "")
            ruling_answer = ruling_content.get("answer", "")
            ruling.get("card_code", "")
            ruling.get("source", "")

            text_spans = []

            copy_button = await create_copy_button(ruling_text, ruling_question, ruling_answer)
            text_spans.append(copy_button)

            match ruling_type:
                case EntryType.UNKNOWN:
                    logging.warning(
                        f"Unknown ruling type for card {card_name=}. Ruling type: {ruling_type=} Ruling text: {ruling_text, ruling_question, ruling_answer=} "
                    )
                    text_spans.append(ft.TextSpan(ruling_text))
                case EntryType.ERRATUM | EntryType.CLARIFICATION:
                    text_spans.extend(await self.create_text_spans(ruling_type, None, ruling_text))
                case EntryType.QUESTION_ANSWER:
                    if ruling_question:
                        text_spans.extend(
                            await self.create_text_spans(
                                ruling_type,
                                None,
                                ruling_question,
                                QAType.QUESTION,
                            )
                        )
                        text_spans.append(ft.TextSpan(text="\n"))
                    if ruling_answer:
                        text_spans.extend(
                            await self.create_text_spans(
                                ruling_type,
                                None,
                                ruling_answer,
                                QAType.ANSWER,
                            )
                        )

                    text_spans.append(ft.Divider(thickness=10))

            copy_button = await create_copy_button(ruling_text, ruling_question, ruling_answer)
            text.extend(
                [copy_button, ft.Text(
                    spans=[*text_spans, ft.TextSpan("\n")], selectable=True)]
            )
            ft.Column([*text, ft.Divider(thickness=5)], scroll=None)
            if text:
                # content_controls.append(col)
                # text = []
                ...

        return text


class SearchInputController:
    def __init__(self, page: ft.Page, data: dict[str, list[dict]]) -> None:
        logging.info("Initializing SearchInputChanged.")
        self.data = data
        self.page = page

    @debounce(1.0)
    async def search_input_changed(self, event: ft.ControlEvent) -> None:
        if search_term := event.control.value:
            search_view = SearchView(self.page, self.data)
            await search_view.update_search_view(search_term)


async def main(page: ft.Page) -> None:
    print("Main function started.")
    page.title = "FAQ This!"
    page.fonts = {"Arkham Icons": "/fonts/arkham-icons.otf"}
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary="#ff436915",
            on_primary="#ffffffff",
            primary_container="#ffc2f18d",
            on_primary_container="#ff0f2000",
            secondary="#ff57624a",
            on_secondary="#ffffffff",
            secondary_container="#ffdbe7c8",
            on_secondary_container="#ff151e0b",
            tertiary="#ff386663",
            on_tertiary="#ffffffff",
            tertiary_container="#ffbbece8",
            on_tertiary_container="#ff00201f",
            error="#ffba1a1a",
            error_container="#ffffdad6",
            on_error="#ffffffff",
            on_error_container="#ff410002",
            background="#fffdfcf5",
            on_background="#ff1b1c18",
            surface="#fffdfcf5",
            on_surface="#ff1b1c18",
            surface_variant="#ffe1e4d5",
            on_surface_variant="#ff44483d",
            outline="#ff75796c",
            on_inverse_surface="#fff2f1e9",
            inverse_surface="#ff30312c",
            inverse_primary="#ffa7d474",
            shadow="#ff000000",
            surface_tint="#ff436915",
            outline_variant="#ffc5c8ba",
            scrim="#ff000000",
        )
    )

    page_content = ft.Ref[ft.Column]()
    json_data = load_json_data()

    ix = open_dir("indexdir")

    print("Creating index.")
    # Use AsyncWriter to prevent locking issues
    with AsyncWriter(ix) as writer:
        for card_name, card_rulings in tqdm(
            json_data.items(), total=len(json_data), position=0, leave=True, desc="Indexing cards"
        ):
            for ruling in card_rulings:
                ruling_content = ruling.get("content", {})
                ruling_type = ruling.get("type", EntryType.UNKNOWN)
                ruling_text = ruling_content.get("text", "")
                ruling_question = ruling_content.get("question", "")
                ruling_answer = ruling_content.get("answer", "")
                card_id = ruling.get("card_code", "")
                writer.add_document(
                    card_name=card_name,
                    ruling_text=ruling_text,
                    card_code=card_id,
                    ruling_type=ruling_type,
                    ruling_question=ruling_question,
                    ruling_answer=ruling_answer,
                )

    search_input_handler = SearchInputController(page, json_data)

    # search_input_handler = SearchController(page, json_data)

    search_input = ft.TextField(
        hint_text="Type to search...",
        on_change=lambda event: asyncio.create_task(
            search_input_handler.search_input_changed(event)
        ),
        autofocus=True,
        autocorrect=False,
        icon="search",
    )

    root_view = ft.View(
        "/",
        [
            ft.AppBar(title=ft.Text("FAQ This!"),
                      bgcolor=ft.colors.SURFACE_VARIANT),
            ft.Column(ref=page_content, expand=True, scroll=None),
            search_input,
        ],
    )

    async def route_change(route_event: ft.RouteChangeEvent) -> None:
        print("Route change:", route_event.route)

        page.views.clear()
        page.views.append(root_view)
        await page.update_async()

        troute = ft.TemplateRoute(route_event.route)
        if troute.match("/card/:card_name/:card_code"):
            card_code = troute.card_code
            card_name = urlsafe_b64decode(troute.card_name).decode("ascii")
            image_url = await retrieve_image_url(card_code)
            print(f"{image_url=}")
            image_binary = await retrieve_image_binary(image_url)
            print(f"len(image_binary): {len(image_binary)}")
            card_text = await retrieve_card_text(card_code)
            print(f"{card_text=}")

            search_view = SearchView(page, load_json_data())
            search_view = SearchController(page, load_json_data())
            rulings = await search_view.get_rulings_for_card(
                page, card_name, card_code, image_binary, card_text
            )
            print(f"{rulings=}")

            page.views.append(
                ft.View(
                    f"/card/{troute.card_name}/{card_code}",
                    [
                        ft.AppBar(title=ft.Text("Card Details"),
                                  bgcolor=ft.colors.SURFACE_VARIANT),
                        ft.Column(
                            [
                                ft.Text(
                                    card_name, theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM),
                                ft.Row(
                                    [
                                        ft.Column(
                                            [ft.Image(
                                                src_base64=image_binary)],
                                            expand=2,
                                            alignment=ft.MainAxisAlignment.CENTER,
                                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        ft.Column(
                                            [
                                                ft.Text(
                                                    "Rulings",
                                                    theme_style=ft.TextThemeStyle.HEADLINE_SMALL,
                                                    text_align=ft.TextAlign.LEFT,
                                                ),
                                                *rulings,
                                            ],
                                            expand=6,
                                            scroll=ft.ScrollMode.AUTO,
                                        ),
                                    ],
                                    expand=True,
                                ),
                            ],
                            expand=True,
                        ),
                    ],
                )
            )
        await page.update_async()

    async def view_pop(view) -> None:
        page.views.pop()
        top_view = page.views[-1]
        await page.go_async(top_view.route)

    page.on_route_change = lambda route: asyncio.create_task(
        route_change(route))
    page.on_view_pop = lambda view: asyncio.create_task(view_pop(view))
    print("Navigating to route.")
    await page.go_async(page.route)

    # await page.add_async(search_input)
    # await page.update_async()


logging.info("Starting app.")
print("Starting app")
flet_path = os.getenv("FLET_PATH", DEFAULT_FLET_PATH)
flet_port = int(os.getenv("FLET_PORT", DEFAULT_FLET_PORT))
app = flet_fastapi.app(
    main, assets_dir=r"B:\dev\FAQML\assets", web_renderer=ft.WebRenderer.HTML)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
