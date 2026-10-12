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
    m = re.match(r"^\d{4}\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일$", s) or         re.match(r"^\d{4}[.\-](\d{1,2})[.\-](\d{1,2})\.?$", s)
    return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}" if m else s


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

    # 세부 변동 내역. 행마다 [구분(+/-), 변동일, 종류, 변동전, 증감, 변동후, 단가, 비고…, 거래계획일]
    details: list[str] = []
    n = _rx(c, r"^다\. 세부변동내역", m)
    h = _idx(c, "변동후", n) if n >= 0 else -1
    if h >= 0:
        rows: list[list[str]] = []
        cur: list[str] | None = None
        for x in c[h + 1:h + 120]:
            if x == "합 계" or x.startswith("*"):
                break
            if re.search(r"\([+-]\)$", x):                  # 새 행: '장내매수(+)' '장내매도(-)'
                cur = [x]
                rows.append(cur)
            elif cur is not None:
                cur.append(x)
        for r in rows[:3]:
            cat = r[0]
            date = r[1] if len(r) > 1 else ""
            delta = r[4] if len(r) > 4 else ""
            price = r[6] if len(r) > 6 and re.fullmatch(r"[\d,]+", r[6] or "") else ""
            remark = " ".join(x for x in r[7:-1] if x not in ("-", ""))
            details.append(_ln(_kr_md(date), esc(cat),
                               f"{_signed(delta, cat)}주" if delta else "",
                               f"단가 {price}원" if price else "",
                               esc(_clean(remark, 40))))
        if len(rows) > 3 and details:
            details[-1] += f" 외 {len(rows) - 3}건"
    out = [a, _ln(own, chg)] + details
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


def major_change(c: list[str], title: str) -> list[str]:
    """최대주주 변경(변경이 확정된 뒤 내는 공시): 누가 누구로, 지분은 얼마, 왜."""
    i, j = _idx(c, "변경전"), _idx(c, "변경후")
    if i < 0 or j < 0:
        return []

    def pick(k: int) -> tuple[str, str, str]:
        name = c[k + 2] if k + 2 < len(c) else ""
        return name, _next(c, "소유주식수(주)", k), _next(c, "소유비율(%)", k)

    nb, sb, pb = pick(i)
    na, sa, pa = pick(j)
    a = f"{esc(nb)} → {esc(na)}" if nb and na else ""
    if sb and sb == sa and pb == pa:
        own = f"{sa}주({pa}%) 그대로 이전"
    else:
        own = f"{sb or '-'}주({pb or '-'}%) → {sa or '-'}주({pa or '-'}%)"
    when = _next(c, "4. 변경일자")
    why = _next(c, "2. 변경사유")
    purpose = _next(c, "3. 지분인수목적")
    fund = _num(_next(c, "자기자금(원)"))
    debt = _num(_next(c, "차입금(원)"))
    out = [a,
           _ln(own, f"변경일 {when}" if when else ""),
           _ln(f"목적 {esc(purpose)}" if purpose else "",
               f"인수자금 {_won(fund)}" if fund else "",
               f"차입 {_won(debt)}" if debt else ""),
           f"사유 {esc(_clean(why, 80))}" if why else ""]
    return [x for x in out if x]


def transfer(c: list[str], title: str) -> list[str]:
    """최대주주 변경을 수반하는 주식 양수도 계약."""
    seller, buyer = _next(c, "-양도인"), _next(c, "-양수인")
    if not seller and not buyer:
        return major_change(c, title)
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


def short_loan(c: list[str], title: str) -> list[str]:
    """단기차입금 증가 결정."""
    amt = _num(_next(c, "차입금액(원)"))
    pct = _next(c, "자기자본대비(%)")
    why = _next(c, "3. 차입목적")
    how = _next(c, "4. 차입형태")
    a = _ln(f"차입 {_won(amt)}" if amt else "", f"자기자본 대비 {pct}%" if pct else "", esc(how))
    b = f"목적 {esc(_clean(why, 70))}" if why else ""
    return [x for x in (a, b) if x]


def earnings_notice(c: list[str], title: str) -> list[str]:
    """결산실적 공시 예고: 언제 발표하나."""
    s, e = _next(c, "시작일"), _next(c, "종료일")
    when = _next(c, "3. 결산실적 공시예정일")
    a = _ln(f"대상 {s} ~ {e}" if s and e else "", f"공시 예정 {when}" if when else "")
    return [a] if a else []


def issue_result(c: list[str], title: str) -> list[str]:
    """증권 발행 결과 (유상증자 납입 완료 등)."""
    kind = c[0] if c and len(c[0]) < 20 else ""
    way = _next(c, "2. 발행방법")
    shares = _num(_next(c, "실제발행주식수(주)"))
    amt = _num(_next(c, "실제발행금액(원)"))
    pay = _next(c, "납입일")
    listing = _next(c, "4. 상장예정 여부")
    a = _ln(esc(way), f"{shares:,.0f}주" if shares else "", _won(amt) if amt else "")
    b = _ln(f"납입일 {pay}" if pay else "", f"상장예정 {listing}" if listing else "")
    return [x for x in (a, b) if x] or ([esc(kind)] if kind else [])


def notice(c: list[str], title: str) -> list[str]:
    """투자유의 안내 · 상장폐지 우려 예고처럼 제목 줄과 '내용'이 있는 공시."""
    head = c[0] if c and len(c[0]) >= 12 else ""
    body_ = _next(c, "2. 내용") or _next(c, "2. 주요내용")
    out = [esc(_clean(head, 100))] if head else []
    if body_:
        out.append(esc(_clean(body_, 110)))
    return out


def bonus_issue(c: list[str], title: str) -> list[str]:
    """무상증자 결정."""
    new = _num(_seek(c, "1. 신주의 종류와 수", "보통주식 (주)"))
    before = _num(_seek(c, "3. 증자전 발행주식총수", "보통주식 (주)"))
    ratio = _seek(c, "5. 1주당 신주배정 주식수", "보통주식 (주)")
    base = _next(c, "4. 신주배정기준일")
    a = _ln(f"신주 {new:,.0f}주" if new else "", f"기존 1주당 {ratio}주 배정" if ratio else "",
            f"기존 대비 {new / before * 100:.0f}%" if new and before else "")
    b = f"신주배정 기준일 {base}" if base else ""
    return [x for x in (a, b) if x]


# 범용: 전용 규칙이 없는 서식에서 금액·일자·목적 같은 핵심 항목을 자동으로 뽑는다.
_FACT_KEY = re.compile(r"금액|총액|주식수|수량|비율|일자|기간|목적|사유|내용|방법|형태|상대|대상|가액|가격|한도|이율")
_SUBLABELS = {"시작일", "종료일", "금액", "비율", "해지 전", "해지 후", "변경전", "변경후", "정정전", "정정후",
              "종류", "주식수", "구분", "항목", "비고", "내용", "합계", "해당", "미해당"}
_FACT_SKIP = re.compile(r"^(\d+\.\s*)?(기타|※|관련공시|참석|불참)|사외이사|감사|확인|서명|담당|전화|이메일")


def _fact_label(lb: str) -> str:
    lb = re.sub(r"^(?:[\d.\s\-]+|[가-하]\.\s*)+", "", lb)
    return re.sub(r"\s*\((원|주|%)\)\s*$", "", lb).strip()


def generic(c: list[str], title: str, limit: int = 5) -> list[str]:
    """제목 줄(있으면) + '라벨 값' 형태의 핵심 항목 몇 개."""
    out: list[str] = []
    head = c[0] if c and 12 <= len(c[0]) <= 90 and not re.match(r"^\d+\.", c[0]) else ""
    if re.search(r"\d\.\d\s|귀중|거래소 신고의무|주요사항보고서\s*/|정\s*정\s*신\s*고", head):
        head = ""
    if head and "(" in head or (head and not _FACT_KEY.search(head)):
        out.append(esc(_clean(head, 90)))
    facts: list[str] = []
    seen: set[str] = set()
    for i in range(len(c) - 1):
        lb, v = c[i], c[i + 1]
        if len(lb) > 45 or not v or v == "-" or len(v) > 90:
            continue
        if not _FACT_KEY.search(lb) or _FACT_SKIP.search(lb):
            continue
        if re.match(r"^\d+\.\s", v) or re.search(r"\((원|주|%)\)$", v) or v == lb or v in _SUBLABELS:
            continue                                         # 값 칸이 또 다른 라벨이다
        key = _fact_label(lb)
        if not key or key in seen:
            continue
        seen.add(key)
        num = _num(v)
        if num is not None and "(원)" in lb and abs(num) >= 1e7:
            val = _won(num)
        else:
            val = _clean(v, 60)
        # 숫자 없는 짧은 값('주식의 종류', '처분대상')은 표 머리글일 가능성이 크다
        if not re.search(r"\d", val) and len(val) <= 8 and not re.search(r"방법|형태|목적|사유|상대|대상|내용", key):
            continue
        facts.append(f"{esc(key)} {esc(val)}")
        if len(facts) >= limit:
            break
    for k in range(0, len(facts), 2):                           # 한 줄에 두 개씩
        out.append(" · ".join(facts[k:k + 2]))
    return out[:4]


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
    if has_reason_col and not any("→" in x for x in out):
        row = c[i + 1:i + 5]                                  # 항목, 정정사유, 정정전, 정정후
        if len(row) == 4 and all(len(x) < 60 for x in row) and not re.match(r"^\d+\.", row[0]):
            out.append(f"{esc(row[0])}  {esc(row[2])} → {esc(row[3])} — {esc(row[1])}")
    return out


# 제목에 이 패턴이 있으면 해당 해석기를 쓴다. 위에서부터 먼저 맞는 것.
RULES: list[tuple[re.Pattern, Callable[[list[str], str], list[str]]]] = [
    (re.compile(r"유상증자결정"), rights_issue),
    (re.compile(r"무상증자결정"), bonus_issue),
    (re.compile(r"(전환사채권|신주인수권부사채권|교환사채권)발행결정"), convertible),
    (re.compile(r"신규시설투자"), facility),
    (re.compile(r"유형자산.*(양수|양도|취득|처분)결정"), asset_deal),
    (re.compile(r"자기주식.*(취득|처분|소각)결정"), treasury),
    (re.compile(r"배당결정"), dividend),
    (re.compile(r"영업\(잠정\)|잠정실적"), earnings),
    (re.compile(r"결산실적공시예고"), earnings_notice),
    (re.compile(r"대량보유"), holding),
    (re.compile(r"불성실공시"), unfaithful),
    (re.compile(r"임원.*주요주주.*소유상황"), insider),
    (re.compile(r"의결권대리행사권유"), proxy),
    (re.compile(r"주식양수도|최대주주.*변경"), transfer),
    (re.compile(r"풍문|조회공시|해명"), rumor),
    (re.compile(r"단기차입금증가"), short_loan),
    (re.compile(r"증권발행결과"), issue_result),
    (re.compile(r"투자유의안내|상장폐지|관리종목|회생절차"), notice),
]
_FIXED = re.compile(r"^\[[^\]]*정정\]")


def lines(category: str, title: str, c: list[str] | None) -> list[str]:
    """요약 줄들 (HTML). 읽지 못하면 빈 목록.

    순서: 정정 → 서식별 전용 규칙 → '주요내용' 칸 → 범용 핵심 항목.
    앞 단계가 비어 있으면 다음 단계로 넘어간다. 틀린 숫자를 만드느니 비우는 쪽이 낫다.
    """
    if not c:
        return []
    steps: list[Callable[[], list[str]]] = []
    if _FIXED.match(title.strip()):
        steps.append(lambda: correction(c, title))
    else:
        for pat, fn in RULES:
            if pat.search(title):
                steps.append(lambda fn=fn: fn(c, title))
                break
    if category in ("위험신호", "지배구조", "증설·CAPEX", "자금조달", "주주환원", "해명"):
        steps.append(lambda: freetext(c, title))
    if category not in ("수주", "IR"):                        # 이 둘은 전용 줄(계약·일정)이 따로 있다
        steps.append(lambda: generic(c, title))
    for step in steps:
        try:
            out = step()
        except Exception:                                  # noqa: BLE001
            continue
        if out:
            return out
    return []
