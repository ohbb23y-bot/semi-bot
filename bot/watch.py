"""공시·뉴스 감시 — 새 것이 있을 때만 텔레그램으로 보낸다.

    python -m bot.watch              # 평소 (오늘 공시)
    python -m bot.watch --days 3     # 월요일 아침처럼 공백이 있을 때
    python -m bot.watch --dry        # 보내지 않고 화면에만

공시는 종목 하나에 메시지 하나로 보낸다. 같은 종목의 공시가 여럿이면
한 메시지에 모은다. 기사는 공시와 섞지 않고 따로 보낸다.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, time as dtime

from . import analyst, body, contract, earnings, gitsync, news, state, summary, telegram
from .classify import ORDER, sort_key
from .config import kst_now, universe
from .feed import collect
from .fmt import article_block, link, short_title
from .telegram import esc

MAX_ITEMS = 40                # 한 번에 이보다 많으면 줄인다
NEWS_KEEP = 400               # 이미 보낸 기사 제목 기억 개수
NEWS_WITHIN_MIN = 60          # 이 시간(분) 안에 나온 기사만
NEWS_MAX = 4                  # 한 번에 보내는 기사 수
BODY_WAIT_SEC = 10 * 60       # 본문이 아직 안 올라온 공시를 이만큼까지 기다린다
COMPACT = {"임원지분"}          # 일상 신고는 종목별로 보내면 소음이라 묶어서 한 통으로


def _is_compact(it: dict) -> bool:
    """이름만 묶어 보내는 공시. 지금은 없다 — 지분 공시도 원문에서 핵심을 읽어 종목별로 보낸다."""
    return False


def _entry(it: dict) -> str:
    """공시 한 건 (줄 여러 개일 수 있다)."""
    title, fixed = short_title(it["title"])
    tag = " <i>정정</i>" if fixed else ""
    lines = [f"{it['icon']} <b>{esc(it['category'])}</b>{tag}  {esc(title)}  "
             f"{link(it['url'], '원문')}"]
    if it.get("ir"):
        ln = contract.ir_line(it["ir"])
        if ln:
            lines.append("└ " + ln)
    ci = it.get("contract")
    if ci:
        lines.append("└ " + contract.line(ci))
        what = " · ".join(x for x in (esc(ci.get("item") or "")[:60],
                                      esc(ci.get("party") or "")[:40]) if x)
        if what:
            lines.append("└ " + what)
    elif it.get("want_contract"):
        lines.append("└ 💵 <i>공시 원문 참조</i>")
    for s in it.get("summary") or []:
        lines.append("└ " + s)
    return "\n".join(lines)


def stock_message(name: str, rows: list[dict]) -> str:
    """한 종목의 메시지."""
    head = f"<b>🔔 {esc(name)}</b>  <code>{kst_now():%m/%d %H:%M}</code>"
    return head + "\n<blockquote>" + "\n".join(_entry(r) for r in rows) + "</blockquote>"


DIGEST_LABEL = {"지분변동": "5% 대량보유 (약식)", "임원지분": "임원·주요주주 소유상황"}
DIGEST_PER_MSG = 15           # 링크가 붙어 길어지므로 한 통에 이만큼씩


def digest_message(rows: list[dict], part: int = 0) -> str:
    """지분 공시(약식 대량보유·임원 소유상황). 종목명에 원문 링크를 걸어 한 통으로."""
    cats: dict[str, list[dict]] = {}
    for r in rows:
        cats.setdefault(r["category"], []).append(r)
    parts = []
    for cat, rs in cats.items():
        names = " · ".join(link(r["url"], esc(r["name"])) for r in rs)
        parts.append(f"{rs[0]['icon']} <b>{DIGEST_LABEL.get(cat, cat)}</b> {len(rs)}건\n{names}")
    more = " <i>(이어서)</i>" if part else ""
    return (f"<b>📋 지분 공시</b>{more}  <code>{kst_now():%m/%d %H:%M}</code>\n<blockquote>"
            + "\n\n".join(parts) + "</blockquote>")


def build(items: list[dict], arts: list[dict]) -> list[tuple[str, list[dict]]]:
    """(메시지 본문, 그 메시지에 담긴 공시들) 목록. 순서대로 보낸다."""
    out: list[tuple[str, list[dict]]] = []

    by_stock: dict[str, list[dict]] = {}
    small: list[dict] = []
    for it in items:
        if _is_compact(it):
            small.append(it)
        else:
            by_stock.setdefault(it["ticker"], []).append(it)

    # 중요한 분류가 먼저 가도록, 종목 안에서 가장 높은 순위로 정렬한다
    def rank(rows: list[dict]) -> int:
        return min(ORDER.get(r["category"], 99) for r in rows)

    for ticker, rows in sorted(by_stock.items(),
                               key=lambda kv: (rank(kv[1]), kv[1][0]["name"])):
        rows.sort(key=lambda r: ORDER.get(r["category"], 99))
        out.append((stock_message(rows[0]["name"], rows), rows))
    for p, i in enumerate(range(0, len(small), DIGEST_PER_MSG)):
        chunk = small[i:i + DIGEST_PER_MSG]
        out.append((digest_message(chunk, p), chunk))
    for n in arts:                       # 기사는 한 건에 메시지 한 통
        out.append((article_block(n, n.get("info")), []))
    return out


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--dry", action="store_true", help="보내지 않고 출력만")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--no-insider", action="store_true",
                    help="임원·주요주주 소유상황 신고를 빼고 본다")
    ap.add_argument("--news-test", action="store_true",
                    help="중요한 기사 한 건에 분석을 붙여 보내 본다 (상태는 건드리지 않는다)")
    ap.add_argument("--loop", action="store_true",
                    help="계속 돌면서 새 공시가 뜨는 대로 보낸다 (서버용)")
    ap.add_argument("--every", type=int, default=60, help="--loop 확인 간격(초)")
    ap.add_argument("--news-every", type=int, default=5,
                    help="--loop 에서 기사를 확인하는 주기(회). 5면 5분에 한 번")
    ap.add_argument("--max-minutes", type=int, default=0,
                    help="--loop 를 이 시간(분) 뒤 끝낸다. 0 이면 계속")
    return ap.parse_args()


def main() -> int:
    a = _args()
    if a.news_test:
        return news_test(a)
    if a.loop:
        return loop(a)
    return run_once(a, state.load())


def news_test(a: argparse.Namespace) -> int:
    """기사 분석이 제대로 붙는지 보는 시험. 시간·이미 보낸 기록과 상관없이 한 건만 고른다."""
    names = set(universe().values())
    arts = news.pick(news.sector(limit=40), 1, names=names)
    if not arts:
        print("고를 만한 기사가 없습니다.")
        return 1
    n = arts[0]
    n["info"] = analyst.enrich(n, names)
    eng_name = {"gemini": "Gemini", "claude": "Claude"}.get(n["info"].get("engine"), "규칙(AI 미사용)")
    text = f"🧪 <i>테스트 · 요약 엔진: {eng_name}</i>\n\n" + article_block(n, n["info"])
    print(text)
    eng = n["info"].get("engine")
    has_key = bool((os.getenv("GEMINI_API_KEY") or "").strip())
    print(f"요약 엔진: {eng} | GEMINI_API_KEY: {'있음' if has_key else '없음'}")
    if not a.dry:
        telegram.send_one(text)
        print("채널로 보냈습니다.")
    return 0


def run_once(a: argparse.Namespace, st: dict) -> int:
    # ── 공시 ────────────────────────────────────────────────
    fresh = [d for d in collect(days=a.days) if state.is_new(st, d["rcept_no"])]
    if a.no_insider:
        fresh = [d for d in fresh if d["category"] != "임원지분"]
    fresh.sort(key=sort_key)

    trimmed = fresh[:MAX_ITEMS]
    if len(fresh) > MAX_ITEMS:
        print(f"[알림] 새 공시 {len(fresh)}건 중 상위 {MAX_ITEMS}건만 보냅니다.")

    # 수주는 본문에서 계약금액·매출 대비 비중을, IR 은 일시·목적을 읽어 붙인다.
    # 기사는 공시에 붙이지 않는다. 같은 종목의 다른 기사가 달리면 이번 공시와
    # 엮여 오해를 부른다. 기사는 아래에서 따로 보낸다.
    # DART 는 공시 목록에 올린 뒤 본문(document.xml)을 몇 분 늦게 내준다. 1분 간격으로
    # 확인하면 본문이 아직 없을 때 읽게 되어 요약이 통째로 빠진다. 본문이 없으면 보내지
    # 않고 다음 확인 때 다시 본다. 그래도 BODY_WAIT_SEC 안에 안 나오면 요약 없이 보낸다.
    pend = st.setdefault("pending", {})
    now = time.time()
    ready: list[dict] = []
    for it in trimmed:
        if _is_compact(it):
            ready.append(it)              # 일상 신고는 본문을 읽지 않는다
            continue
        cells = body.cells(it["rcept_no"])
        if cells is None:
            first = pend.setdefault(it["rcept_no"], now)
            if now - first < BODY_WAIT_SEC:
                continue                  # 아직 본문이 없다. 다음에 다시
        pend.pop(it["rcept_no"], None)
        if it["category"] == "수주" and "계약" in it["title"]:
            it["want_contract"] = True
            it["contract"] = contract.parse_cells(cells) if cells else None
        elif it["category"] == "IR":
            it["ir"] = contract.ir_info(cells) if cells else None
        if it["category"] == "실적" and "잠정" in it["title"] and cells:
            it["summary"] = (earnings.lines(it["ticker"], it["title"], cells)
                             or summary.lines(it["category"], it["title"], cells))
        else:
            it["summary"] = summary.lines(it["category"], it["title"], cells)
        ready.append(it)
    trimmed = ready
    for k in [k for k, t in pend.items() if now - t > 24 * 3600]:
        del pend[k]                       # 하루 넘게 남은 기록은 버린다

    # ── 기사 ────────────────────────────────────────────────
    arts: list[dict] = []
    pool: list[dict] = []
    if not a.no_news:
        pool = news.seen_filter(news.fresh(news.sector(limit=40), NEWS_WITHIN_MIN),
                                list(st.get("news_seen") or []))
        names = set(universe().values())
        arts = news.pick(pool, NEWS_MAX, names=names)
        for n in arts:                   # 본문을 읽어 내용·분석을 붙인다
            n["info"] = analyst.enrich(n, names)

    msgs = build(trimmed, arts)

    if not msgs:
        if not a.loop:
            print("새 공시·기사 없음.")
        if not a.dry:
            _remember(st, pool)
            state.save(st)
        return 0

    if a.dry:
        sep = "\n\n──────── (다음 메시지) ────────\n\n"
        print(sep.join(m for m, _ in msgs))
        print(f"\n[미리보기] 메시지 {len(msgs)}개 · 공시 {len(trimmed)}건 · 기사 {len(arts)}건 "
              f"(--dry 라 보내지 않았고 상태도 저장하지 않습니다)")
        return 0

    # 메시지를 보낼 때마다 그 공시를 바로 기록한다. 중간에 실패해도 이미 보낸
    # 공시를 다음 실행에서 다시 보내지 않는다.
    sent = 0
    try:
        for text, rows in msgs:
            telegram.send_one(text)
            sent += 1
            for it in rows:
                state.mark(st, it["rcept_no"])
            time.sleep(telegram.GAP)
    finally:
        _remember(st, pool)         # 후보로 올랐던 기사는 한 번만 심사한다
        state.save(st)

    print(f"공시 {len(trimmed)}건 · 기사 {len(arts)}건 · 메시지 {sent}개 전송")
    return 0


def _remember(st: dict, pool: list[dict]) -> None:
    ns = list(st.get("news_seen") or []) + [n["title"] for n in pool]
    st["news_seen"] = ns[-NEWS_KEEP:]


# ── 계속 돌기 ───────────────────────────────────────────────────
# 공시는 평일 아침부터 저녁까지 나온다. 그 시간대에만 확인하고, 밖에서는 느리게 쉰다.
WINDOW = (dtime(7, 0), dtime(20, 30))
DAILY_AT = dtime(18, 30)


def in_window(now: datetime) -> bool:
    return now.weekday() < 5 and WINDOW[0] <= now.time() <= WINDOW[1]


def _maybe_daily() -> None:
    """평일 18:30 이후 하루 한 번 데일리 리포트."""
    now = kst_now()
    today = now.strftime("%Y-%m-%d")
    if now.weekday() >= 5 or now.time() < DAILY_AT:
        return
    if state.load().get("last_daily") == today:
        return
    from . import daily
    daily.run()


def loop(a: argparse.Namespace) -> int:
    """새 공시가 뜨는 대로 보낸다. 한 번 실패해도 멈추지 않는다.

    연속 10번 실패하면 (토큰 오류처럼 기다려도 안 풀리는 문제) 종료 코드 1 로 끝낸다.
    """
    t0, n, fails = time.time(), 0, 0
    first_days = a.days       # 첫 확인에서만 며칠 전까지 본다 (월요일 아침 등)
    last_push = time.time()
    PUSH_EVERY = 300          # 초. Actions 에서 상태를 이만큼 간격으로만 올린다
    news_off = a.no_news
    print(f"[감시 시작] {a.every}초 간격 · 평일 {WINDOW[0]:%H:%M}~{WINDOW[1]:%H:%M}", flush=True)
    print("[설정] 기사 분석 AI:",
          "Gemini 키 있음" if (os.getenv("GEMINI_API_KEY") or "").strip()
          else ("Claude 키 있음" if (os.getenv("ANTHROPIC_API_KEY") or "").strip()
                else "키 없음 (규칙으로 요약)"), flush=True)
    while True:
        if in_window(kst_now()):
            try:
                a.days = first_days if n == 0 else 1
                a.no_news = news_off or (n % max(1, a.news_every) != 0)
                run_once(a, state.load())
                _maybe_daily()
                fails = 0
            except (Exception, SystemExit) as exc:             # noqa: BLE001
                fails += 1
                print(f"[오류 {fails}회] {type(exc).__name__}: {exc}", flush=True)
                if fails >= 10:
                    if gitsync.enabled():
                        gitsync.push_state()
                    return 1
            n += 1
            gap = a.every
            if gitsync.enabled() and state.DIRTY and time.time() - last_push >= PUSH_EVERY:
                if gitsync.push_state():
                    state.DIRTY = False
                last_push = time.time()
        else:
            gap = 300                                           # 시간 밖에서는 5분마다 시계만 본다
        if a.max_minutes and (time.time() - t0) / 60 + gap / 60 > a.max_minutes:
            if gitsync.enabled():
                gitsync.push_state()
            return 0
        time.sleep(gap)


if __name__ == "__main__":
    raise SystemExit(main())
