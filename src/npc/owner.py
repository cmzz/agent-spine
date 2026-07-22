"""owner 存活语义：plan-state 的 owner_pid / owner_heartbeat_at 写入与判定。

单一事实源：
- 写入侧 ``capture_owner_fields()``：当前调用方（npc 子命令进程）的 owner 快照。
  ``owner_pid`` 取 ``os.getppid()``——触发本次子命令调用的父进程（CC 主
  session / shell），而非 npc 子进程自身；每次调用返回最新值，不做缓存。
- 判定侧 ``owner_alive(state)``：pid 探测（``os.kill(pid, 0)``）**只能确认存活、
  不能确认死亡**——真实部署里 npc 经 shell 包装调用，``os.getppid()`` 记录的常是
  每条命令独立的短命子 shell，命令结束后数秒内即死；若把 pid 死亡当作 owner
  死亡，活跃 run 在任意两次子命令之间都会被并发 session 误判为孤儿。因此
  pid 不可确认存活时一律退化为 24 小时心跳新鲜度判定。

崩溃安全：不引入锁文件；owner 崩溃后心跳停止刷新，过期即可被接管
（需立即接管时用 ``npc init --takeover`` 显式旗标）。
"""

from __future__ import annotations

import os
import time
from datetime import datetime

from . import _io

# 心跳新鲜度阈值：24 小时。pid 无法确认存活（缺失/已死/不可探测）时的主判据，
# pid 确认存活但心跳过期时的复用怀疑判据。判死完全由该阈值决定——owner_pid
# 常是短命包装 shell，pid 死亡不构成 owner 死亡的证据。
OWNER_HEARTBEAT_STALENESS_SECONDS = 24 * 60 * 60


def capture_owner_fields(*, now_iso: str | None = None) -> dict:
    """写入侧：当前调用方的 owner 快照（owner_pid + owner_heartbeat_at）。"""
    return {
        "owner_pid": os.getppid(),
        "owner_heartbeat_at": now_iso or _io.now_iso(),
    }


def _heartbeat_fresh(heartbeat: object, now_ts: float) -> bool | None:
    """心跳是否在新鲜度阈值内。

    返回 True/False；心跳缺失或不可解析时返回 None（无法判定）。
    """
    if not isinstance(heartbeat, str) or not heartbeat:
        return None
    try:
        hb_ts = datetime.fromisoformat(heartbeat).timestamp()
    except ValueError:
        return None
    return (now_ts - hb_ts) <= OWNER_HEARTBEAT_STALENESS_SECONDS


def owner_alive(state: dict, *, now_ts: float | None = None) -> bool:
    """判定侧：给定 plan-state dict（骨架或正式 STATE_JSON），判断其 owner 是否存活。

    算法（pid 探测只能确认存活、不能确认死亡）：
      1. owner_pid 缺失/非法 → 仅心跳判定；心跳也缺失 → 不存活
         （向后兼容：本 change 落地前生成的旧 schema 文件视为"无 owner 信息"，
         即孤儿候选，不阻断其被续跑接管）。
      2. owner_pid 存在 → ``os.kill(pid, 0)`` 探测：
         - PermissionError / 无异常 → pid 存活 → 走第 3 步二次确认。
         - ProcessLookupError / 其它 OSError → pid 无法确认存活 → 仅心跳判定
           （同第 1 步）。owner_pid 常是短命包装 shell，pid 死亡不构成 owner
           死亡的证据；心跳新鲜的活跃 run 不得因包装 shell 退出而被抢占。
      3. pid 存活后用心跳新鲜度二次确认（防 pid 复用）：
         - 心跳缺失/不可解析 → 信任 pid 判定，视为存活。
         - 心跳在 OWNER_HEARTBEAT_STALENESS_SECONDS（24h）内 → 存活。
         - 心跳过期 → 不存活（疑似原进程已退出、pid 被复用）。
    """
    if now_ts is None:
        now_ts = time.time()

    pid = state.get("owner_pid")
    heartbeat = state.get("owner_heartbeat_at")

    pid_probeable = isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
    pid_alive = False
    if pid_probeable:
        try:
            os.kill(pid, 0)
            pid_alive = True
        except PermissionError:
            pid_alive = True
        except OSError:
            # ProcessLookupError 在内：pid 无法确认存活 → 退化为仅心跳判定。
            pid_alive = False

    fresh = _heartbeat_fresh(heartbeat, now_ts)

    if pid_alive:
        # pid 存活：心跳缺失/不可解析 → 信任 pid；否则按新鲜度二次确认。
        return fresh is not False
    # pid 缺失/非法/已死/不可探测：仅心跳判定。
    return fresh is True
