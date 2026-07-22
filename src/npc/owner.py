"""owner 存活语义：plan-state 的 owner_pid / owner_heartbeat_at 写入与判定。

单一事实源：
- 写入侧 ``capture_owner_fields()``：当前调用方（npc 子命令进程）的 owner 快照。
  ``owner_pid`` 取 ``os.getppid()``——触发本次子命令调用的父进程（CC 主
  session / shell），而非 npc 子进程自身；每次调用返回最新值，不做缓存。
- 判定侧 ``owner_alive(state)``：pid 探测（``os.kill(pid, 0)``）为主判据，
  24 小时心跳新鲜度为兜底（防 pid 复用误判）。

崩溃安全：不引入锁文件；owner 进程崩溃后 pid 立即不可探测，无需显式清理。
"""

from __future__ import annotations

import os
import time
from datetime import datetime

from . import _io

# 心跳新鲜度阈值：24 小时。仅作用于"pid 存活但可能是复用 / pid 不可探测"
# 的兜底场景；pid 确认死亡（ProcessLookupError）时立即判死，不受此阈值影响。
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

    算法：
      1. owner_pid 缺失/非法 → 退化为仅心跳判定；心跳也缺失 → 不存活
         （向后兼容：本 change 落地前生成的旧 schema 文件视为"无 owner 信息"，
         即孤儿候选，不阻断其被续跑接管）。
      2. owner_pid 存在 → ``os.kill(pid, 0)`` 探测：
         - ProcessLookupError → pid 确认死亡 → 不存活（不受心跳阈值影响）。
         - PermissionError / 无异常 → pid 存活 → 走第 3 步二次确认。
         - 其它 OSError → pid 不可探测 → 退化为仅心跳判定（同第 1 步）。
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
        except ProcessLookupError:
            return False
        except PermissionError:
            pid_alive = True
        except OSError:
            pid_alive = False  # 不可探测 → 退化为仅心跳判定

    fresh = _heartbeat_fresh(heartbeat, now_ts)

    if pid_alive:
        # pid 存活：心跳缺失/不可解析 → 信任 pid；否则按新鲜度二次确认。
        return fresh is not False
    # pid 缺失/非法/不可探测：仅心跳判定。
    return fresh is True
