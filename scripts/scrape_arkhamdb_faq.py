import asyncio
import json
import re

import aiohttp
import requests
import tqdm
from tqdm.asyncio import tqdm_asyncio

# Regex patterns for replacing HTML elements
span_rule = re.compile(r'<span class="icon-([^"]+)"( title="[^"]*")?></span>')
newline_rule = re.compile(r"\r\n")
card_link_rule = re.compile(r"http(s?)://arkhamdb\.com/card/")
rules_link_rule = re.compile(r"http(s?)://arkhamdb.com/rules#")
paragraph_rule = re.compile(r"<p>")
close_paragraph_rule = re.compile(r"</p>")

# Dictionary mapping cycle codes to their names
cycles = {
    "01": "core",
    "02": "dwl",
    "03": "ptc",
    "04": "tfa",
    "05": "tcu",
    "06": "tde",
    "07": "tic",
    "08": "eoe",
    "09": "tsk",
    "50": "rtnotz",
    "51": "rtdwl",
    "52": "rtptc",
    "53": "rttfa",
    "54": "rttcu",
    "60": "investigator",
    "61": "investigator",
    "62": "investigator",
    "63": "investigator",
    "64": "investigator",
    "81": "standalone",
    "82": "standalone",
    "83": "standalone",
    "84": "standalone",
    "85": "standalone",
    "86": "standalone",
    "90": "parallel",
    "98": "books",
    "99": "promo",
}


def fetch_cards():
    uri = "https://arkhamdb.com/api/public/cards/?encounter=1"
    print("Fetching all cards from ArkhamDB.")
    response = requests.get(uri)
    cards = response.json()
    print(f"Got {len(cards)} cards")
    return cards


async def fetch_faq(session, card):
    code = card["code"]
    faq_uri = f"https://arkhamdb.com/api/public/faq/{code}.json"
    async with session.get(faq_uri) as response:
        return await response.json()


def parse_faqs(faqs):
    rulings = {}
    for faq in tqdm.tqdm(faqs, desc="Parsing faqs"):
        if not faq:
            continue
        faq_content = faq[0]
        text = re.sub(span_rule, r"[\1]", faq_content["html"])
        text = re.sub(newline_rule, "\n", text)
        text = re.sub(card_link_rule, "/card/", text)
        text = re.sub(rules_link_rule, "/rules#", text)
        text = re.sub(paragraph_rule, "", text)
        text = re.sub(close_paragraph_rule, "", text)
        entry = {
            "code": faq_content["code"],
            "text": text,
            "updated": faq_content["updated"]["date"],
        }
        rulings[faq_content["code"]] = entry
    return rulings


async def main() -> None:
    cards = fetch_cards()
    # cards = cards[:100]
    tqdm_async = tqdm_asyncio()
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=5, limit_per_host=100)
    ) as session:
        tasks = [asyncio.ensure_future(
            fetch_faq(session, card)) for card in cards]
        responses = await tqdm_async.gather(*tasks)
    faqs = parse_faqs(responses)
    with open("../faqs/faqs.json", "w") as f:
        json.dump(faqs, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
