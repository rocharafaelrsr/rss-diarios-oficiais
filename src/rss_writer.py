from __future__ import annotations

from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from models import FeedItem


def _sub(parent: ET.Element, tag: str, text: object = "") -> ET.Element:
    node = ET.SubElement(parent, tag)
    node.text = "" if text is None else str(text)
    return node


def write_rss(
    output: Path,
    *,
    title: str,
    description: str,
    link: str,
    items: list[FeedItem],
    last_build: datetime,
) -> None:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    _sub(channel, "title", title)
    _sub(channel, "link", link)
    _sub(channel, "description", description)
    _sub(channel, "language", "pt-BR")
    _sub(channel, "lastBuildDate", format_datetime(last_build))
    _sub(channel, "generator", "rss-diarios-oficiais/1.1")
    _sub(channel, "ttl", "60")

    for item in items:
        node = ET.SubElement(channel, "item")
        _sub(node, "title", item.title)
        _sub(node, "link", item.link)
        guid = _sub(node, "guid", item.guid)
        guid.set("isPermaLink", "false")
        published = datetime.fromisoformat(item.published_at)
        _sub(node, "pubDate", format_datetime(published))
        _sub(node, "category", item.category_label)
        # O Portal RSR já exibe fonte, categoria e data em campos próprios. A
        # descrição deve conter apenas o objeto da publicação, em uma frase curta.
        _sub(node, "description", item.excerpt)

    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(rss, space="  ")
    tree = ET.ElementTree(rss)
    tree.write(output, encoding="utf-8", xml_declaration=True)
