# symbol.py

from markdown_it.rules_inline import StateInline
from markdown_it.rules_inline.state_inline import Delimiter

TAG_TO_LETTER = {
    "wild": "z",
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
    "fast": "j",
    "action": "i",
}


def tokenize(state: StateInline, silent: bool) -> bool:
    start = state.pos
    if silent or state.src[start] != "[":
        return False

    end = state.src.find("]", start)
    if end == -1 or (end + 1 < len(state.src) and state.src[end + 1] == "("):
        return False

    symbol_name = state.src[start + 1: end]
    if symbol_name not in TAG_TO_LETTER:
        return False

    # Check if the last token's type is 'link_open'
    if state.tokens and state.tokens[-1].type == "link_open":
        return False

    token = state.push("text", "sym", 0)
    token.content = symbol_name
    token.info = TAG_TO_LETTER[symbol_name]

    state.tokens_meta.append({"delimiters": []})

    delim = Delimiter(
        marker=ord("["),
        length=0,
        token=len(state.tokens) - 1,
        end=-1,
        open=True,
        close=True,
    )
    state.delimiters.append(delim)

    state.pos = end + 1
    return True


def postProcess(state: StateInline) -> None:
    print("postProcess called")
    print(f"Number of delimiters method 1: {len(state.delimiters)}")

    for i, delim in enumerate(state.delimiters):
        print(
            f"Delimiter {i}: {delim.marker=}, {delim.length=}, {delim.token=}, {delim.end=}, {delim.open=}, {delim.close=}"
        )
    _postProcess(state, state.delimiters)

    # tokens_meta = state.tokens_meta
    # print(f"Number of tokens_meta: {len(tokens_meta)}")
    # for curr_meta in tokens_meta:
    #     print(f"curr_meta: {curr_meta}")
    #     if curr_meta and "delimiters" in curr_meta:
    #         print(f"Number of delimiters: {len(curr_meta['delimiters'])}")
    #         print("Processing delimiters")
    #         _postProcess(state, curr_meta["delimiters"])


def _postProcess(state: StateInline, delimiters: list[Delimiter]) -> None:
    if not delimiters and not state.delimiters:
        print("No delimiters")
        return

    for startDelim in reversed(state.delimiters):
        print(f"startDelim.marker: {startDelim.marker}, ord('['): {ord('[')}")
        if startDelim.marker != ord("["):
            continue

        # Check if startDelim.token is a valid index in state.tokens
        if startDelim.token >= len(state.tokens):
            print(f"Invalid token index: {startDelim.token}")
            continue

        # Check if startDelim.token + 1 is a valid index in state.tokens
        if startDelim.token + 1 >= len(state.tokens):
            print(f"Invalid next token index: {startDelim.token + 1}")
            continue

        print("Before token modification:")
        print(state.tokens[startDelim.token])
        print(state.tokens[startDelim.token + 1])

        token = state.tokens[startDelim.token]
        token.type = "sym_open"
        token.tag = "sym"
        token.nesting = 1
        token.markup = "["
        token.content = ""

        token = state.tokens[startDelim.token + 1]
        token.type = "sym_close"
        token.tag = "sym"
        token.nesting = -1
        token.markup = "]"
        token.content = ""

        print("After token modification:")
        print(state.tokens[startDelim.token])
        print(state.tokens[startDelim.token + 1])
