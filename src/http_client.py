from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class HttpClient:
    timeout: int
    user_agent: str
    session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=1.0,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
            }
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def get(self, url: str, **kwargs: object) -> requests.Response:
        started = time.monotonic()
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        elapsed = time.monotonic() - started
        LOG.debug("GET %s -> %s em %.2fs", url, response.status_code, elapsed)
        response.raise_for_status()
        return response
