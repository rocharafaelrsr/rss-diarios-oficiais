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
    connect_timeout: int = 10
    session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Retentativas curtas. Portais oficiais às vezes ficam lentos, mas quatro
        # tentativas de 35 s por data faziam uma indisponibilidade consumir quase
        # toda a janela do workflow sem aumentar a chance real de sucesso.
        retry = Retry(
            total=1,
            connect=1,
            read=1,
            status=2,
            backoff_factor=1.2,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Connection": "keep-alive",
            }
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    @property
    def request_timeout(self) -> tuple[int, int]:
        return (max(3, min(self.connect_timeout, self.timeout)), self.timeout)

    def get(self, url: str, **kwargs: object) -> requests.Response:
        started = time.monotonic()
        response = self.session.get(url, timeout=self.request_timeout, **kwargs)
        elapsed = time.monotonic() - started
        LOG.debug("GET %s -> %s em %.2fs", url, response.status_code, elapsed)
        response.raise_for_status()
        return response
