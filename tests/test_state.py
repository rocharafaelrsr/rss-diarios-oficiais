from datetime import datetime
from zoneinfo import ZoneInfo

from models import FeedItem
from state import merge_items


def make_item(guid: str, published: str, title: str) -> FeedItem:
    return FeedItem(guid, "atub", "ATUB", 10, "dodf", "DODF", title, "https://x", published, published, "", "", None, "x", ["x"])


def test_merge_deduplicates_and_updates():
    now = datetime(2026, 7, 27, tzinfo=ZoneInfo("America/Sao_Paulo"))
    old = [make_item("1", now.isoformat(), "antigo")]
    new = [make_item("1", now.isoformat(), "novo")]
    merged = merge_items(old, new, now=now, retention_days=30)
    assert len(merged) == 1
    assert merged[0].title == "novo"
