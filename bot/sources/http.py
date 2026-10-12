"""공용 HTTP 클라이언트.

일시적인 네트워크 오류는 지수 백오프로 다시 시도한다. 회사망처럼 TLS 검사를
하는 환경에서도 돌도록 truststore 가 있으면 운영체제 인증서 저장소를 쓴다
(서버·GitHub Actions 에서는 없어도 된다).
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any

try:                                   # 선택 사항
    import truststore
    truststore.inject_into_ssl()
except Exception:                      # noqa: BLE001
    pass

import httpx  # noqa: E402

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_clients: dict[str, httpx.Client] = {}
_lock = threading.Lock()


def client(name: str = "default", **kwargs) -> httpx.Client:
    """이름별로 연결을 재사용한다."""
    with _lock:
        if name not in _clients:
            headers = {"User-Agent": BROWSER_UA}
            headers.update(kwargs.pop("headers", {}))
            _clients[name] = httpx.Client(
                headers=headers,
                timeout=kwargs.pop("timeout", 20.0),
                follow_redirects=True,
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4,
                                    keepalive_expiry=5.0),
                **kwargs,
            )
        return _clients[name]


TRANSIENT = (
    httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout,
    httpx.ConnectError, httpx.PoolTimeout, httpx.ReadError,
)


def get_with_retry(name: str, url: str, params: dict | None = None,
                   attempts: int = 4, timeout: float | None = None) -> httpx.Response:
    last: Exception | None = None
    for i in range(attempts):
        try:
            kw: dict[str, Any] = {"params": params}
            if timeout is not None:
                kw["timeout"] = timeout
            return client(name).get(url, **kw)
        except TRANSIENT as exc:
            last = exc
            time.sleep(0.4 * (2 ** i) + random.random() * 0.3)
    raise last if last else RuntimeError("요청 실패")
