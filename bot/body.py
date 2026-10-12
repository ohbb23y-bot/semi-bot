"""공시 원문을 받아 '칸 목록'으로 바꾼다.

DART 원문(document.xml)은 표 중심 XML 이다. 셀 하나하나를 순서대로 뽑으면
'라벨 → 값' 이 이웃한 칸으로 놓여, 라벨을 찾아 다음 칸을 읽는 식으로 항목을
꺼낼 수 있다. 서식이 공시 종류마다 다르므로 해석은 summary.py 가 맡는다.
"""
from __future__ import annotations

import io
import re
import zipfile

from .config import DART_API_KEY
from .sources.dart import BASE
from .sources.http import get_with_retry

_CELL_END = re.compile(r"</(?:TD|TH|TE|TU|P|TR)\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def parse(xml: str) -> list[str]:
    s = _CELL_END.sub("\x00", xml)
    s = _TAG.sub("", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">"))
    return [re.sub(r"\s+", " ", c).strip() for c in s.split("\x00") if c.strip()]


def cells(rcept_no: str) -> list[str] | None:
    """원문이 아직 없거나(014) 형식이 다르면 None."""
    try:
        r = get_with_retry("dart", BASE + "/document.xml",
                           params={"crtfc_key": DART_API_KEY,
                                   "rcept_no": rcept_no}, timeout=60)
    except Exception:                                  # noqa: BLE001
        return None
    if r.content[:2] != b"PK":
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xml = z.read(z.namelist()[0]).decode("utf-8", "ignore")
    except Exception:                                  # noqa: BLE001
        return None
    out = parse(xml)
    # 맨 앞 칸은 서식 CSS 라 버린다
    return out[1:] if out and out[0].lstrip().startswith(".xforms") else out
