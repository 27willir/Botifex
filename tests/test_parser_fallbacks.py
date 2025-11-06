import json

from lxml import html
from bs4 import BeautifulSoup

from scrapers.craigslist import _parse_json_listings as parse_craigslist_json
from scrapers.ebay import _parse_json_listings as parse_ebay_json, _parse_price_value as ebay_parse_price


def test_craigslist_json_parser_extracts_listing():
    payload = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "item": {
                    "@type": "Product",
                    "name": "Test Car",
                    "url": "https://craigslist.org/test-car",
                    "offers": {"price": "3500"},
                    "image": "https://images.craigslist.org/test.jpg",
                },
            }
        ],
    }
    markup = f'<html><head><script type="application/ld+json">{json.dumps(payload)}</script></head></html>'
    tree = html.fromstring(markup)

    listings = parse_craigslist_json(tree)

    assert len(listings) == 1
    listing = listings[0]
    assert listing["title"] == "Test Car"
    assert listing["link"] == "https://craigslist.org/test-car"
    assert listing["price"] == 3500


def test_ebay_json_parser_extracts_listing():
    payload = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "item": {
                    "@type": "Product",
                    "name": "Test Camera",
                    "url": "https://www.ebay.com/itm/123",
                    "offers": {"price": "120.00"},
                    "image": "https://i.ebayimg.com/images/g/test.jpg",
                },
            }
        ],
    }
    markup = f'<html><head><script type="application/ld+json">{json.dumps(payload)}</script></head></html>'
    soup = BeautifulSoup(markup, "html.parser")

    listings = parse_ebay_json(soup)

    assert len(listings) == 1
    listing = listings[0]
    assert listing["title"] == "Test Camera"
    assert listing["link"] == "https://www.ebay.com/itm/123"
    assert listing["price"] == 120


def test_ebay_price_parser_handles_range_strings():
    assert ebay_parse_price("$120.00 to $150.00") == 120

