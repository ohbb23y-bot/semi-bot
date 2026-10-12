"""GitHub Actions 에서 '어디까지 보냈는지'를 저장소에 올린다.

러너는 실행마다 빈 디스크로 시작한다. 보낸 기록(state.json)을 저장소에 커밋해 두어야
다음 실행이 같은 공시를 다시 보내지 않는다.

계속 도는 작업(--loop)은 몇 시간 동안 떠 있으므로, 그동안 누군가 코드를 푸시했을 수 있다.
상태 파일 하나만 최신 main 위에 얹어서 올린다. 예전 코드로 되돌리는 일이 없다.
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone

from .config import ROOT, STATE_PATH

BRANCH = os.getenv("GITHUB_REF_NAME") or "main"


def enabled() -> bool:
    return os.getenv("GITHUB_ACTIONS") == "true"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def push_state() -> bool:
    """state.json 이 바뀌었으면 커밋하고 올린다. 올렸거나 바뀐 게 없으면 True."""
    rel = STATE_PATH.relative_to(ROOT).as_posix()
    _git("config", "user.name", "github-actions[bot]")
    _git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    _git("add", rel)
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return True
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    _git("commit", "-m", f"상태 갱신 ({stamp})")

    for _ in range(3):
        if _git("pull", "--rebase", "origin", BRANCH).returncode != 0:
            # 상태 파일이 서로 충돌하면 우리 것을 최신 main 위에 다시 얹는다
            _git("rebase", "--abort")
            mine = STATE_PATH.read_bytes()
            _git("fetch", "origin", BRANCH)
            _git("reset", "--hard", f"origin/{BRANCH}")
            STATE_PATH.write_bytes(mine)
            _git("add", rel)
            _git("commit", "-m", f"상태 갱신 ({stamp})")
        if _git("push", "origin", f"HEAD:{BRANCH}").returncode == 0:
            return True
        time.sleep(5)
    print("[경고] 상태를 저장소에 올리지 못했습니다. 다음 실행이 같은 공시를 다시 보낼 수 있습니다.",
          flush=True)
    return False


if __name__ == "__main__":
    raise SystemExit(0 if push_state() else 1)
