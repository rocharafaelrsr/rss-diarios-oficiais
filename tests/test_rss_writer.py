from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from models import FeedItem
from rss_writer import write_rss


def test_writes_valid_rss(tmp_path: Path):
    now = datetime(2026, 7, 27, 11, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    item = FeedItem(
        guid="abc",
        category="atub",
        category_label="Concurso ATUB",
        priority=10,
        source="dodf",
        source_label="DODF",
        title="[DODF] Nomeação",
        link="https://example.org/doc.pdf#page=2",
        published_at=now.isoformat(),
        collected_at=now.isoformat(),
        edition="DODF 100",
        section="",
        page=2,
        excerpt="Trecho relevante.",
        matched_terms=["auditor fiscal de atividades urbanas"],
    )
    output = tmp_path / "feed.xml"
    write_rss(output, title="Teste", description="Descrição", link="https://example.org/feed.xml", items=[item], last_build=now)
    root = ET.parse(output).getroot()
    assert root.tag == "rss"
    assert root.findtext("./channel/item/guid") == "abc"
    assert root.findtext("./channel/item/link").endswith("#page=2")
