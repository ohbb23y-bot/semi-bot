"""하루 한 번 — 업황 지표와 종목군 등락을 보낸다.

    python -m bot.daily          # 보낸다
    python -m bot.daily --dry    # 화면에만
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from .sources import naver

from . import macro, news, state, telegram
from .config import kst_now, universe
from .fmt import article_line


def pct(v) -> str:
    if v is None:
        return "-"
    return f"{v:+.1f}%"


def board() -> dict:
    """우리 388종목의 오늘 등락.

    네이버 전종목 시세는 시총 순으로 상위부터 준다. 기본 12페이지(시장당
    1,200종목)로는 코스닥 소형주가 잘려서 80여 개가 빠졌다. 20페이지로
    늘려 대부분 채우고, 그래도 없는 것만 일봉 두 개로 등락을 계산한다.
    quote() 에는 등락률이 없어서 일봉을 봐야 한다.
    """
    uni = universe()
    rows = [r for r in naver.universe(pages=20) if r["ticker"] in uni]
    got = {r["ticker"] for r in rows}

    missing = [t for t in uni if t not in got]
    if missing:
        end = date.today().strftime("%Y%m%d")
        begin = (date.today() - timedelta(days=12)).strftime("%Y%m%d")
        for t in missing:
            try:
                bars = naver.ohlcv(t, begin, end)
            except Exception:                           # noqa: BLE001
                continue                                # 거래정지·상폐는 넘긴다
            if len(bars) < 2:
                continue
            prev, last = bars[-2]["close"], bars[-1]["close"]
            if not prev:
                continue
            rows.append({"ticker": t, "name": uni[t], "close": last,
                         "market_cap": None,
                         "change_pct": (last / prev - 1) * 100})

    live = [r for r in rows if r.get("change_pct") is not None]
    live.sort(key=lambda r: r["change_pct"], reverse=True)
    ups = [r for r in live if r["change_pct"] > 0]
    downs = [r for r in live if r["change_pct"] < 0]
    avg = sum(r["change_pct"] for r in live) / len(live) if live else None
    # 시총 가중 평균도 같이 본다. 단순 평균은 소형주가 끌고 가서
    # "섹터가 올랐다"는 인상을 과장한다.
    cap = [r for r in live if r.get("market_cap")]
    wavg = (sum(r["change_pct"] * r["market_cap"] for r in cap)
            / sum(r["market_cap"] for r in cap)) if cap else None
    return {
        "n": len(live), "up": len(ups), "down": len(downs),
        "avg": avg, "wavg": wavg,
        "top": live[:5], "bottom": live[-5:][::-1],
        "missing": len(uni) - len(live),
    }


def build(b: dict, mac: list[dict], arts: list[dict]) -> list[str]:
    """블록 목록. 링크는 '기사' 두 글자에만 건다."""
    now = kst_now().strftime("%Y-%m-%d (%a)")
    blocks = [f"<b>🌡 반도체 데일리</b>  <code>{now}</code>"]

    head = [f"<b>종목 {b['n']}개</b>  상승 {b['up']} · 하락 {b['down']}",
            f"단순평균 {pct(b['avg'])} · 시총가중 {pct(b['wavg'])}"]
    if b["missing"]:
        head.append(f"<i>시세 못 받은 종목 {b['missing']}개</i>")
    ups = " · ".join(f"{telegram.esc(r['name'])} {pct(r['change_pct'])}" for r in b["top"])
    downs = " · ".join(f"{telegram.esc(r['name'])} {pct(r['change_pct'])}" for r in b["bottom"])
    blocks.append("\n".join(head) + f"\n<blockquote>▲ {ups}\n▼ {downs}</blockquote>")

    lines = []
    for m in mac:
        if m.get("error"):
            lines.append(f"{m['name']}  <i>{m['error']}</i>")
            continue
        lines.append(f"<b>{m['name']}</b> {m['value']} <i>({m['period']})</i>\n"
                     f"└ 전월 {pct(m['mom'])} · 전년 {pct(m['yoy'])}")
    blocks.append("<b>📈 업황</b>  <i>한국은행 · 월간</i>\n<blockquote>"
                  + "\n".join(lines) + "</blockquote>\n"
                  "<i>수출금액 ≈ 물량 × 가격. 물량만 늘고 가격이 빠지면 공급과잉, "
                  "둘 다 오르면 업턴.</i>")

    if arts:
        blocks.append("<b>📰 오늘의 주요 기사</b>\n<blockquote>"
                      + "\n\n".join(article_line(n) for n in arts) + "</blockquote>")
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    return run(dry=a.dry)


def run(dry: bool = False) -> int:
    b = board()
    mac = macro.snapshot()
    # 데일리는 하루치에서 고른다 (30분 감시는 최근 1시간).
    today = kst_now().strftime("%Y-%m-%d")
    pool = [n for n in news.sector(limit=40)
            if (n.get("datetime") or "").startswith(today)]
    arts = news.pick(pool, 4, names=set(universe().values()))

    blocks = build(b, mac, arts)
    if dry:
        print("\n\n".join(blocks))
        return 0

    sent = telegram.send(blocks)
    st = state.load()
    st["last_daily"] = today
    state.save(st)
    print(f"데일리 전송 완료 (메시지 {sent}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
