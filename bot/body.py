"""공시 원문을 받아 '칸 목록'으로 바꾼다.

DART 원문(document.xml)은 표 중심 XML 이다. 셀 하나하나를 순서대로 뽑으면
'라벨 → 값' 이 이웃한 칸으로 놓여, 라벨을 찾아 다음 칸을 읽는 식으로 항목을 꺼낼 수 있다.
서식이 공시 종류마다 다르므로 해석은 summary.py 가 맡는다.

원문 API 는 공시가 올라온 뒤 한참 늦게(거래소 공시는 몇 시간) 본문을 내주기도 한다. 그동안에도
DART 웹 화면에는 본문이 이미 있으므로, API 가 못 줄 때는 웹 화면에서 읽는다.
"""
from __future__ import annotations

import io
import re
import zipfile

from .config import DART_API_KEY
from .sources.dart import BASE
from .sources.http import client, get_with_retry

_CELL_END = re.compile(r"</(?:TD|TH|TE|TU|P|TR)\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")
WEB = "https://dart.fss.or.kr"


def parse(xml: str) -> list[str]:
    s = _CELL_END.sub("\x00", xml)
    s = _TAG.sub("", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">"))
    return [re.sub(r"\s+", " ", c).strip() for c in s.split("\x00") if c.strip()]


def _strip_css(out: list[str]) -> list[str]:
    # 맨 앞 칸은 서식 CSS 라 버린다
    return out[1:] if out and out[0].lstrip().startswith(".xforms") else out


def _api_cells(rcept_no: str) -> list[str] | None:
    try:
        r = get_with_retry("dart", BASE + "/document.xml",
                           params={"crtfc_key": DART_API_KEY,
                                   "rcept_no": rcept_no}, timeout=60)
    except Exception:                                  # noqa: BLE001
        return None
    if r.content[:2] != b"PK":                         # 014: 아직 없다
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xml = z.read(z.namelist()[0]).decode("utf-8", "ignore")
    except Exception:                                  # noqa: BLE001
        return None
    return _strip_css(parse(xml))


def _web_cells(rcept_no: str) -> list[str] | None:
    """DART 웹 화면에서 본문을 읽는다. 화면 구조가 바뀌면 None.

    공시가 여러 절로 나뉘어 있으면(임원 소유상황 등) 절마다 따로 받아 이어 붙인다.
    """
    try:
        c = client("dartweb", headers={"Referer": WEB + "/"})
        main = c.get(f"{WEB}/dsaf001/main.do?rcpNo={rcept_no}", timeout=30).text
    except Exception:                                  # noqa: BLE001
        return None
    secs: list[dict] = []
    for m in re.finditer(r"node\d+\['(\w+)'\]\s*=\s*\"([^\"]*)\"", main):
        k, v = m.group(1), m.group(2)
        if k == "text":
            secs.append({})
        elif secs:
            secs[-1][k] = v
    secs = [x for x in secs if x.get("dcmNo")]
    if not secs:                                       # 절 목록이 없으면 첫 문서만
        m = re.search(r'viewDoc\("(\d+)",\s*"(\d+)",\s*"(\d*)",\s*"(\d*)",\s*"(\d*)",\s*"([^"]*)"', main)
        if not m:
            return None
        secs = [dict(zip(("rcpNo", "dcmNo", "eleId", "offset", "length", "dtd"), m.groups()))]
    out: list[str] = []
    for x in secs[:12]:
        try:
            r = c.get(f"{WEB}/report/viewer.do?rcpNo={x.get('rcpNo', rcept_no)}&dcmNo={x['dcmNo']}"
                      f"&eleId={x.get('eleId', '')}&offset={x.get('offset', '')}"
                      f"&length={x.get('length', '')}&dtd={x.get('dtd', '')}", timeout=30)
            r.raise_for_status()
        except Exception:                              # noqa: BLE001
            continue
        out += _strip_css(parse(r.text))
    return out if len(out) >= 5 else None


def cells(rcept_no: str) -> list[str] | None:
    """원문 칸 목록. API 에서 못 받으면 웹 화면에서. 둘 다 안 되면 None."""
    return _api_cells(rcept_no) or _web_cells(rcept_no)
