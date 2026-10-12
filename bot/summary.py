"""공시 원문에서 핵심만 뽑아 두세 줄로 요약한다.

서식이 공시마다 달라서 분류별로 읽는 법을 따로 둔다. 읽지 못하면 빈 목록을
돌려주고, 호출부는 제목과 원문 링크만 보낸다. 틀린 숫자를 보내느니 비우는 쪽이
낫다.
"""
from __future__ import annotations

import re
from typing import Callable

from .telegram import esc

MAXLEN = 110


def _clean(s: str, n: int = MAXLEN) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def _num(s: str) -> float | None:
    s = (s or "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _idx(c: list[str], label: str, start: int = 0) -> int:
    """라벨이 있는 칸의 위치. 서식마다 띄어쓰기가 달라서 공백은 무시하고 비교한다."""
    key = label.replace(" ", "")
    for i in range(start, len(c)):
        if c[i] == label or c[i].replace(" ", "") == key:
            return i
    return -1


def _rx(c: list[str], pat: str, start: int = 0) -> int:
    """정규식에 처음 맞는 칸의 위치."""
    rg = re.compile(pat)
    for i in range(start, len(c)):
        if rg.search(c[i]):
            return i
    return -1


def _next(c: list[str], label: str, start: int = 0) -> str:
    i = _idx(c, label, start)
    if i < 0 or i + 1 >= len(c):
        return ""
    return "" if c[i + 1] == "-" else c[i + 1]


def _val(c: list[str], pat: str, start: int = 0) -> str:
    """정규식 라벨 다음 칸."""
    i = _rx(c, pat, start)
    if i < 0 or i + 1 >= len(c):
        return ""
    return "" if c[i + 1] == "-" else c[i + 1]


def _seek(c: list[str], section: str, label: str) -> str:
    """section 라벨 뒤에서 처음 나오는 label 의 다음 칸."""
    i = _idx(c, section)
    return _next(c, label, i) if i >= 0 else ""


def _won(v: float | None) -> str:
    if v is None:
        return ""
    e = v / 1e8
    return f"{e:,.0f}억원" if e >= 100 else f"{e:,.1f}억원"


def _ln(*parts: str) -> str:
    return " · ".join(p for p in parts if p)


def _purposes(c: list[str], head: str, tail: str) -> tuple[float, list[str]]:
    """'자금조달의 목적' 표에서 금액이 있는 항목과 합계."""
    i, j = _idx(c, head), _idx(c, tail)
    total, uses = 0.0, []
    if 0 <= i < j:
        for k in range(i + 1, j - 1, 2):
            lb, v = c[k], _num(c[k + 1])
            if v and lb.endswith("(원)"):
                uses.append(lb.replace(" (원)", "").replace("(원)", "").strip())
                total += v
    return total, uses


# ── 분류별 ────────────────────────────────────────────────────

def rights_issue(c: list[str], title: str) -> list[str]:
    new = _num(_seek(c, "1. 신주의 종류와 수", "보통주식 (주)"))
    before = _num(_seek(c, "3. 증자전 발행주식총수 (주)", "보통주식 (주)"))
    price = _num(_seek(c, "6. 신주 발행가액", "보통주식 (원)"))
    way = _next(c, "5. 증자방식")
    total, uses = _purposes(c, "4. 자금조달의 목적", "5. 증자방식")
    out = [_ln(f"신주 {new:,.0f}주" if new else "",
               f"기존 대비 {new / before * 100:.1f}%" if new and before else "",
               f"발행가 {price:,.0f}원" if price else ""),
           _ln(way, f"조달 {_won(total)}" if total else "",
               f"({', '.join(uses)})" if uses else "")]
    return [x for x in out if x]


def convertible(c: list[str], title: str) -> list[str]:
    """전환사채 · 신주인수권부사채 · 교환사채 발행결정."""
    face = _num(_val(c, r"^2\. 사채의 권면"))
    how = _next(c, "8. 사채발행방법")
    coupon = _next(c, "표면이자율 (%)")
    ytm = _next(c, "만기이자율 (%)")
    due = _next(c, "5. 사채만기일")
    price = _num(_val(c, r"^(전환|행사|교환)가액 \(원/주\)"))
    shares = _num(_next(c, "주식수"))
    share_pct = _next(c, "주식총수 대비비율(%)")
    total, uses = _purposes(c, "3. 자금조달의 목적", "4. 사채의 이율")
    a = _ln(f"권면 {_won(face)}" if face else "", how,
            f"표면 {coupon}% / 만기 {ytm}%" if coupon and ytm else "",
            f"만기 {due}" if due else "")
    b = _ln(f"전환·행사가 {price:,.0f}원" if price else "",
            f"주식 {shares:,.0f}주" if shares else "",
            f"(총수 대비 {share_pct}%)" if share_pct else "",
            f"용도 {', '.join(uses)}" if uses else "")
    return [x for x in (a, b) if x]


def facility(c: list[str], title: str) -> list[str]:
    """신규시설투자등."""
    i = _rx(c, r"1\. 투자구분$")
    if i < 0:
        return []
    kind = c[i + 1] if i + 1 < len(c) and c[i + 1] != "-" else ""
    amt = _num(_next(c, "투자금액(원)", i))
    pct = _next(c, "자기자본대비(%)", i)
    why = _next(c, "3. 투자목적", i)
    j = _idx(c, "4. 투자기간", i)
    period = ""
    if j >= 0:
        s, e = _next(c, "시작일", j), _next(c, "종료일", j)
        period = f"{s} ~ {e}" if s and e else ""
    out = [_ln(esc(_clean(kind, 40)), _won(amt) if amt else "",
               f"자기자본 대비 {pct}%" if pct else ""),
           _ln(esc(_clean(why, 60)), period)]
    return [x for x in out if x]


def asset_deal(c: list[str], title: str) -> list[str]:
    """유형자산 양수·양도·취득·처분."""
    kind = _next(c, "1. 자산구분")
    name = _next(c, "- 자산명")
    amt = _num(_val(c, r"^(양수|양도|취득|처분)금액\(원\)$"))
    pct = _val(c, r"^자산총액대비\(%\)$")
    why = _val(c, r"^\d\. (양수|양도|취득|처분)목적$")
    out = [_ln(esc(_clean(kind, 30)), _won(amt) if amt else "",
               f"자산총액 대비 {pct}%" if pct else ""),
           _ln(esc(_clean(name, 50)), esc(_clean(why, 60)))]
    return [x for x in out if x]


def treasury(c: list[str], title: str) -> list[str]:
    """자기주식 취득·처분."""
    def sec(pat: str) -> str:
        i = _rx(c, pat)
        return _next(c, "보통주식", i) if i >= 0 else ""
    shares = _num(sec(r"^\d+\. (취득|처분|소각)예정주식\(주\)$"))
    amt = _num(sec(r"^\d+\. (취득|처분|소각)예정금액\(원\)$"))
    why = _val(c, r"^\d+\. (취득|처분|소각)목적$")
    a = _ln(f"{shares:,.0f}주" if shares else "", _won(amt) if amt else "")
    b = f"목적 {esc(_clean(why, 60))}" if why else ""
    return [x for x in (a, b) if x]


def dividend(c: list[str], title: str) -> list[str]:
    kind = c[0] if c and len(c[0]) < 12 else ""
    per = _num(_seek(c, "3. 1주당 배당금(원)", "보통주식"))
    yld = _seek(c, "4. 시가배당률(%)", "보통주식")
    tot = _num(_next(c, "5. 배당금총액(원)"))
    base = _next(c, "6. 배당기준일")
    pay = _next(c, "7. 배당금지급 예정일자")
    a = _ln(esc(kind), f"주당 {per:,.0f}원" if per else "",
            f"시가배당률 {yld}%" if yld else "")
    b = _ln(f"총액 {_won(tot)}" if tot else "", f"기준일 {base}" if base else "",
            f"지급 {pay}" if pay else "")
    return [x for x in (a, b) if x]


def earnings(c: list[str], title: str) -> list[str]:
    """영업(잠정)실적."""
    unit_cell = next((x for x in c if x.startswith("단위 :")), "")
    m = re.search(r"단위\s*:\s*([^,\s]+)", unit_cell)
    unit = m.group(1) if m else ""
    base = _idx(c, "1. 연결실적내용")
    if base < 0:
        base = _idx(c, "2. 별도실적내용")
    base = max(base, 0)

    parts = []
    for lb, short in (("매출액", "매출"), ("영업이익", "영업이익"), ("당기순이익", "순이익")):
        i = _idx(c, lb, base)
        if i < 0 or c[i + 1:i + 2] != ["당해실적"]:
            continue
        v = c[i + 2:i + 9]
        if len(v) < 6 or _num(v[0]) is None:
            continue
        s = f"{short} {v[0]}{unit}"
        if _num(v[5]) is not None:
            s += f" (전년 {_num(v[5]):+.1f}%)"
        elif len(v) > 6 and v[6] not in ("-", ""):
            s += f" ({v[6]})"
        parts.append(s)
    return [" · ".join(parts)] if parts else []


def holding(c: list[str], title: str) -> list[str]:
    """5% 대량보유 보고."""
    who = _next(c, "보고자 :")
    rel = _next(c, "발행회사와의 관계")
    kind = _next(c, "보고구분")
    i = _idx(c, "보유주식등의 수 및 보유비율")
    ratio = ""
    if i >= 0:
        p, q = _idx(c, "직전 보고서", i), _idx(c, "이번 보고서", i)
        if p >= 0 and q >= 0 and q + 2 < len(c):
            ratio = f"보유 {c[p + 2]}% → {c[q + 2]}%" + (
                f" ({c[q + 1]}주)" if c[q + 1] != "-" else "")
    why = re.sub(r"^[-\s]+", "", _next(c, "보고사유"))
    purpose = _next(c, "보유목적")
    a = _ln(f"보고자 {esc(who)}" if who else "", esc(rel), esc(kind))
    b = _ln(ratio, f"목적 {esc(purpose)}" if purpose else "",
            f"사유 {esc(_clean(why, 60))}" if why else "")
    return [x for x in (a, b) if x]


def unfaithful(c: list[str], title: str) -> list[str]:
    """불성실공시법인 지정예고."""
    kind = _next(c, "불성실공시 유형")
    what = _next(c, "내용")
    pts = _val(c, r"^3\. 최근 1년간 불성실공시법인 부과벌점")
    due = _next(c, "2. 불성실공시법인지정여부 결정시한")
    a = _ln(esc(kind), esc(_clean(what, 70)))
    b = _ln(f"부과벌점 {pts}점" if pts else "", f"지정 결정시한 {due}" if due else "")
    return [x for x in (a, b) if x]


def rumor(c: list[str], title: str) -> list[str]:
    """풍문·보도 해명, 조회공시 답변."""
    item = _next(c, "1. 풍문 또는 보도의 내용")
    media = _next(c, "2. 풍문 또는 보도의 매체")
    answer = _next(c, "4. 풍문 또는 보도의 내용에 대한 해명내용")
    if not item:                         # 조회공시 답변: 첫 칸이 무엇에 대한 답인지
        item = c[0] if c and len(c[0]) > 8 else ""
        answer = _next(c, "2. 내용") or _next(c, "2. 답변내용")
    again = _next(c, "5. 재공시예정일") or _next(c, "3. 재공시예정일")
    a = _ln(esc(_clean(item, 80)), esc(media))
    answer = re.sub(r"^[-\s]+", "", answer)
    b = f"해명 {esc(_clean(answer, 120))}" if answer else ""
    d = f"재공시 예정 {again}" if again else ""
    return [x for x in (a, b, d) if x]


_DATE_KR = re.compile(r"^\d{4}년 \d{2}월 \d{2}일$")


def _kr_md(s: str) -> str:
    """'2026년 10월 02일' → '10/02'"""
    m = re.match(r"^\d{4}년 (\d{2})월 (\d{2})일$", s)
    return f"{m.group(1)}/{m.group(2)}" if m else s


def _signed(num: str, category: str) -> str:
    """'4,305' + '장내매도(-)' → '-4,305'.  (+)/(-) 표시가 없으면 그대로."""
    n = num.strip()
    if not n or n == "-" or n[0] in "+-":
        return n
    if "(-)" in category:
        return "-" + n
    if "(+)" in category:
        return "+" + n
    return n


def _name(s: str) -> str:
    """'배 종 석' → '배종석'. DART 는 한 글자씩 띄워 적는 경우가 있다."""
    parts = (s or "").split()
    return "".join(parts) if len(parts) >= 2 and all(len(x) == 1 for x in parts) else (s or "")


def insider(c: list[str], title: str) -> list[str]:
    """임원·주요주주 특정증권등 소유상황 보고서: 누가, 얼마나 사고팔았나."""
    who = _next(c, "보고자 :")
    kind = _val(c, r"보고구분$")
    pos = _next(c, "직위명")
    reg = _next(c, "임원(등기여부)").replace("임원", "")
    major = _next(c, "주요주주")
    role = f"{pos}({reg})" if pos and reg else (pos or ("주요주주" if major else ""))
    a = _ln(esc(_name(who)), esc(role), f"{esc(kind)} 보고" if kind else "")

    m = _rx(c, r"^3\. 특정증권등의 소유상황")
    if m < 0:
        return [a] if a else []
    prev, this, dlt = _idx(c, "직전보고서", m), _idx(c, "이번보고서", m), _idx(c, "증 감", m)
    own = ""
    if this >= 0 and this + 3 < len(c):
        now, now_r = c[this + 2], c[this + 3]
        was, was_r = (c[prev + 2], c[prev + 3]) if prev >= 0 and prev + 3 < len(c) else ("-", "-")
        if was == "-":
            own = f"보유 {now}주({now_r}%)"
        else:
            own = f"보유 {was}주({was_r}%) → {now}주({now_r}%)"
    chg = ""
    if dlt >= 0 and dlt + 1 < len(c):
        d = _num(c[dlt + 1])
        if d is not None and this >= 0 and prev >= 0:
            wn, tn = _num(c[prev + 2]) or 0.0, _num(c[this + 2]) or 0.0
            chg = f"증감 {tn - wn:+,.0f}주"
        elif c[dlt + 1] not in ("-", ""):
            chg = f"증감 {c[dlt + 1]}주"

    # 세부 변동 내역: 변동일, 종류, 변동전, 증감, 변동후, 단가, 비고…
    detail = ""
    n = _rx(c, r"^다\. 세부변동내역", m)
    h = _idx(c, "변동후", n) if n >= 0 else -1
    if h >= 0 and h + 1 < len(c):
        cat = c[h + 1]
        rows, cur = [], []
        for x in c[h + 2:h + 40]:
            if x == "합 계" or x.startswith("*"):
                break
            if _DATE_KR.match(x):
                if cur:
                    rows.append(cur)
                cur = [x]
            elif cur:
                cur.append(x)
        if cur:
            rows.append(cur)
        if rows:
            r = rows[0]
            price = r[5] if len(r) > 5 and re.fullmatch(r"[\d,]+", r[5] or "") else ""
            remark = " ".join(x for x in r[6:-1] if x not in ("-", ""))
            detail = _ln(_kr_md(r[0]), esc(cat), f"{_signed(r[3], cat)}주" if len(r) > 3 else "",
                         f"단가 {price}원" if price else "", esc(_clean(remark, 50)))
            if len(rows) > 1:
                detail += f" 외 {len(rows) - 1}건"
    out = [a, _ln(own, chg), detail]
    return [x for x in out if x]


def proxy(c: list[str], title: str) -> list[str]:
    """의결권 대리행사 권유 참고서류: 주총일, 안건."""
    who = _next(c, "가. 권유자")
    meet = _next(c, "라. 주주총회일")
    start = _next(c, "마. 권유 시작일")
    why = _next(c, "가. 권유취지")
    i = _idx(c, "3. 주주총회 목적사항")
    items: list[str] = []
    if i >= 0:
        for x in c[i + 1:i + 10]:
            if not x.startswith("□"):
                break
            items.append(x.lstrip("□ ").strip())
    a = _ln(f"권유자 {esc(who)}" if who else "", f"주총일 {_kr_md(meet)}" if meet else "",
            f"권유 시작 {_kr_md(start)}" if start else "")
    b = ("안건 " + " · ".join(esc(x) for x in items[:4])) if items else ""
    d = f"취지 {esc(_clean(why, 60))}" if why else ""
    return [x for x in (a, b, d) if x]


def transfer(c: list[str], title: str) -> list[str]:
    """최대주주 변경을 수반하는 주식 양수도 계약."""
    seller, buyer = _next(c, "-양도인"), _next(c, "-양수인")
    shares = _num(_next(c, "양수도 주식수(주)"))
    price = _num(_next(c, "1주당 가액(원)"))
    amt = _num(_next(c, "양수도 대금(원)"))
    pct = _next(c, "-예정 소유비율(%)")
    when = _next(c, "-변경 예정일자")
    a = f"{esc(seller)} → {esc(buyer)}" if seller and buyer else ""
    b = _ln(f"{shares:,.0f}주" if shares else "", f"지분 {pct}%" if pct else "",
            _won(amt) if amt else "", f"주당 {price:,.0f}원" if price else "",
            f"변경예정 {when}" if when else "")
    return [x for x in (a, b) if x]


def freetext(c: list[str], title: str) -> list[str]:
    """서식이 제각각인 공시: '주요내용' 칸을 그대로."""
    for lb in ("2. 주요내용", "주요내용", "2. 주요 내용", "주요 내용", "1. 제목"):
        v = _next(c, lb)
        if v:
            return [esc(_clean(v))]
    return []


def _pretty(v: str) -> str:
    """정정표 값 정리: '-. 12,000,000,000 -. 15,031,589,000' → '120억원 / 150.3억원'."""
    out = []
    for tok in [t for t in re.split(r"(?:^|\s)-\.\s*", v) if t.strip()] or [v]:
        t = tok.strip()
        n = _num(t)
        if n is not None and abs(n) >= 1e8 and re.fullmatch(r"-?[\d,]+", t):
            out.append(_won(n))
        else:
            out.append(t)
    return " / ".join(out)


def correction(c: list[str], title: str) -> list[str]:
    """정정 공시: 사유와 바뀐 항목(전 → 후)."""
    def sq(s: str) -> str:
        return re.sub(r"\s+", "", s)

    def label(lb: str) -> str:
        lb = re.sub(r"^[\d.\s]+", "", lb)                   # 앞의 번호
        return re.sub(r"\s+-\s+", " · ", lb).strip()          # '신주의 종류와 수 - 보통주식(주)'

    i = next((k for k, x in enumerate(c) if sq(x) == "정정후"), -1)
    out: list[str] = []
    if i < 2:
        return out
    # 서식 ① 항목·정정사유·정정전·정정후  ② 정정항목·정정전·정정후.
    # ①은 사유 칸이 합쳐진 행이 있어 열 수가 들쭉날쭉하다. '1. ' '9. ' 같은
    # 행 머리말로 행을 나누고, 뒤에서 두 칸을 전·후로 읽는다.
    has_reason_col = sq(c[i - 1]) == "정정전" and sq(c[i - 2]) == "정정사유"
    if not has_reason_col:
        why = _next(c, "3. 정정사유") or _next(c, "정정사유")
        if why and sq(why) not in ("정정전", "정정후"):
            out.append(f"정정사유 {esc(_clean(why, 80))}")

    head = re.compile(r"^\d+\.\s")
    rows: list[list[str]] = []
    for x in c[i + 1:]:
        if head.match(x):
            if re.match(r"^\d+\. 기타", x):
                break
            rows.append([x])
        elif rows:
            rows[-1].append(x)
    for row in rows[:3]:
        lb, vals = row[0], row[1:]
        if not 2 <= len(vals) <= 4:                      # 읽는 법이 불확실하면 비운다
            continue
        why = ""
        if len(vals) == 4:
            if vals[0] != vals[2]:
                continue
            lb, was, now = f"{label(lb)} {vals[0]}", vals[1], vals[3]   # '주식수 a / 주식수 b'
        else:
            was, now = vals[-2], vals[-1]
            if has_reason_col and len(vals) >= 3 and vals[0] not in ("-", ""):
                why = f" — {esc(_clean(vals[0], 30))}"
        was, now = _pretty(was), _pretty(now)
        if len(was) > 50 or len(now) > 50:
            continue
        out.append(f"{esc(_clean(label(lb), 40))}  {esc(was)} → {esc(now)}{why}")
    return out


# 제목에 이 패턴이 있으면 해당 해석기를 쓴다. 위에서부터 먼저 맞는 것.
RULES: list[tuple[re.Pattern, Callable[[list[str], str], list[str]]]] = [
    (re.compile(r"유상증자결정"), rights_issue),
    (re.compile(r"(전환사채권|신주인수권부사채권|교환사채권)발행결정"), convertible),
    (re.compile(r"신규시설투자"), facility),
    (re.compile(r"유형자산.*(양수|양도|취득|처분)결정"), asset_deal),
    (re.compile(r"자기주식.*(취득|처분|소각)결정"), treasury),
    (re.compile(r"배당결정"), dividend),
    (re.compile(r"영업\(잠정\)|잠정실적"), earnings),
    (re.compile(r"대량보유"), holding),
    (re.compile(r"불성실공시"), unfaithful),
    (re.compile(r"임원.*주요주주.*소유상황"), insider),
    (re.compile(r"의결권대리행사권유"), proxy),
    (re.compile(r"주식양수도|최대주주.*변경"), transfer),
    (re.compile(r"풍문|조회공시|해명"), rumor),
]
_FIXED = re.compile(r"^\[[^\]]*정정\]")


def lines(category: str, title: str, c: list[str] | None) -> list[str]:
    """요약 줄들 (HTML). 읽지 못하면 빈 목록."""
    if not c:
        return []
    try:
        if _FIXED.match(title.strip()):
            return correction(c, title)
        for pat, fn in RULES:
            if pat.search(title):
                return fn(c, title)
        if category in ("위험신호", "지배구조", "증설·CAPEX", "자금조달", "주주환원"):
            return freetext(c, title)
    except Exception:                                      # noqa: BLE001
        return []
    return []
