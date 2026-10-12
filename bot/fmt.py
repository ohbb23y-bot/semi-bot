"""텔레그램 메시지 모양.

파란 글씨(링크)가 많으면 눈이 어지럽다. 링크는 짧은 '원문'·'기사' 두 글자에만
걸고, 종목명·제목·숫자는 일반 글씨로 둔다. 분류마다 인용 블록(<blockquote>)으로
묶어 왼쪽에 줄이 생기게 한다.

블록은 한 덩어리로 보낸다. 인용 블록 중간에서 4096자 한계로 잘리면 닫는
태그가 없어 텔레그램이 메시지를 통째로 거절한다.
"""
from __future__ import annotations

import re

from .telegram import esc

PER_BLOCK = 10                  # 한 인용 블록에 넣는 최대 항목 수


def short_title(title: str) -> tuple[str, bool]:
    """공시 제목을 줄이고, 정정 여부를 따로 돌려준다."""
    t = re.sub(r"\s+", " ", title or "").strip()
    fixed = bool(re.match(r"^\[(?:기재|첨부|발행조건)?정정\]", t))
    t = re.sub(r"^\[[^\]]*정정\]\s*", "", t)
    t = t.replace("ㆍ", "·")
    t = t.replace("주식등의대량보유상황보고서", "5% 대량보유")
    t = t.replace("임원·주요주주특정증권등소유상황보고서", "임원 소유상황")
    t = t.replace("주요사항보고서", "").strip()
    t = re.sub(r"^\((.+)\)$", r"\1", t)
    return (t[:38] + "…") if len(t) > 38 else t, fixed


def link(url: str, text: str) -> str:
    return f'<a href="{url}">{text}</a>'


def section(icon: str, title: str, items: list[str]) -> list[str]:
    """분류 하나를 블록 여러 개로. 항목 하나는 줄 여러 개일 수 있다."""
    out = []
    for i in range(0, len(items), PER_BLOCK):
        head = f"<b>{icon} {title}</b>" if i == 0 else f"<b>{icon} {title}</b> <i>(이어서)</i>"
        out.append(head + "\n<blockquote>" + "\n".join(items[i:i + PER_BLOCK])
                   + "</blockquote>")
    return out


def article_line(n: dict) -> str:
    press = esc(n.get("press") or "")
    tail = f"<i>{press}</i> · " if press else ""
    return (f"<b>{esc(n['title'][:80])}</b>\n"
            f"{tail}{link(n['url'], '기사')}")


def article_block(n: dict, info: dict | None = None) -> str:
    """제목 · 핵심 · 분석 · 링크. 본문을 못 읽었으면 제목과 링크만.

    인용 블록(<blockquote>)에 넣으면 글씨가 작아지고 답답해 보여서 쓰지 않는다.
    항목 사이를 한 줄씩 띄운다.
    """
    info = info or {}
    parts = [f"<b>📰 {esc((n.get('title') or '')[:90])}</b>"]

    points = info.get("points") or ([info["summary"]] if info.get("summary") else [])
    if points:
        parts.append("<b>💡 핵심</b>\n" + "\n".join(f"• {esc(p)}" for p in points))
    if info.get("analysis"):
        lines = [x for x in info["analysis"].split("\n") if x.strip()]
        parts.append("<b>🔎 분석</b>\n" + "\n".join(f"• {esc(x)}" for x in lines))
    elif info.get("tags"):
        parts.append("<b>🏷 키워드</b>  " + " · ".join(esc(t) for t in info["tags"]))
    if info.get("related"):
        parts.append("<b>📌 관련</b>  " + " · ".join(esc(t) for t in info["related"]))

    press = esc(n.get("press") or "")
    parts.append((f"<i>{press}</i> · " if press else "") + link(n["url"], "기사 원문"))
    return "\n\n".join(parts)
