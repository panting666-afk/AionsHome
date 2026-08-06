"""
长期维护：每日备份 + 自动压缩 + VACUUM。

背景：记忆由 digest 自动写入，但压缩（generate_daily_compression_draft →
apply_daily_compression_review）默认需要人工审核后再应用。若不定期应用压缩，
memories 表会无限增长，而每次对话的召回是 O(N) 全表向量比对（见 memory.recall_memories），
多年后会明显变慢。

本模块由 main.py 的后台循环每天执行一次（开机漏跑会自动补跑）：
  1. 先备份 chat.db（SQLite backup API，一致性快照）——压缩前留档，防误删/损坏
  2. 自动压缩：已有草稿超过宽限期（默认 2 天）就应用；没有草稿就生成新草稿
  3. 执行 VACUUM，回收被删除记忆释放的空间

配置（可选，写入 data/settings.json，次日生效）：
  maintenance_enabled      bool   是否启用每日维护，默认 true
  maintenance_backup_dir   str    备份目录，默认 e:/AionsHome/backups；
                                 强烈建议改成另一块盘或云同步文件夹（OneDrive/坚果云等）
  maintenance_keep_backups int    保留最近几份备份，默认 14
  maintenance_grace_days   float  自动应用草稿的宽限期天数，默认 2
  maintenance_auto_apply   bool   是否自动应用草稿，默认 true；设 false 只生成草稿不应用
"""

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

from config import BASE_DIR, DATA_DIR, DB_PATH, load_settings

# 每日状态标记文件（记录上次成功维护的日期，避免一天跑多次）
MAINT_STATE_PATH = DATA_DIR / "maintenance_state.json"

# 自动压缩的默认时间窗：只压缩超过该天数、尚未压缩的日常记忆
DIGEST_WINDOW_DAYS = 15


# ── 配置读取（每次运行时读取，改 settings.json 次日生效）──
def _maint_cfg() -> dict:
    s = load_settings()
    default_backup_dir = str(BASE_DIR.parent / "backups")  # e:/AionsHome/backups
    return {
        "enabled": bool(s.get("maintenance_enabled", True)),
        "backup_dir": str(s.get("maintenance_backup_dir", "")).strip() or default_backup_dir,
        "keep_backups": max(1, int(s.get("maintenance_keep_backups", 14))),
        "grace_days": max(0.5, float(s.get("maintenance_grace_days", 2))),
        "auto_apply": bool(s.get("maintenance_auto_apply", True)),
    }


# ── 每日状态标记 ────────────────────────────────
def load_maintenance_state() -> dict:
    if MAINT_STATE_PATH.exists():
        try:
            return json.loads(MAINT_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_maintenance_state(state: dict):
    try:
        MAINT_STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[memory_maintenance] 写入状态标记失败: {e}")


# ── 备份（SQLite backup API，WAL 安全的一致性快照）──
def _backup_db_sync(backup_dir: Path, keep: int) -> dict:
    if not DB_PATH.exists():
        return {"ok": False, "message": "chat.db 不存在，跳过备份。"}
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"chat-{time.strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    except Exception as exc:
        return {"ok": False, "message": f"备份失败：{exc}"}
    finally:
        dst.close()
        src.close()
    size = os.path.getsize(dest)
    # 清理旧备份，只保留最近 keep 份
    backups = sorted(backup_dir.glob("chat-*.db"))
    removed = 0
    for old in backups[:-keep]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return {"ok": True, "path": str(dest), "size": size, "removed": removed}


# ── VACUUM（回收被删除记忆/消息释放的空间，失败不影响备份与压缩）──
def _vacuum_sync() -> dict:
    if not DB_PATH.exists():
        return {"ok": False, "message": "chat.db 不存在，跳过 VACUUM。"}
    try:
        before = os.path.getsize(DB_PATH)
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
        after = os.path.getsize(DB_PATH)
        return {"ok": True, "before": before, "after": after, "freed": before - after}
    except Exception as exc:
        return {"ok": False, "message": f"VACUUM 失败（不影响备份与压缩）：{exc}"}


# ── 自动压缩 ────────────────────────────────────
async def auto_compress(grace_days: float = 2.0, auto_apply: bool = True) -> dict:
    """
    有草稿且超过宽限期 → 自动应用（应用会删除被覆盖的旧日常记忆，重要记忆自动升级为长期保留）；
    草稿太新 → 等待人工审核，不生成新草稿（避免刷屏）；
    没有草稿 → 生成一份新的。
    """
    from memory import (
        generate_daily_compression_draft,
        apply_daily_compression_review,
        get_latest_daily_compression_review,
    )

    pending = await get_latest_daily_compression_review(target="both")
    now = time.time()
    applied = None
    if pending and pending.get("status") == "draft":
        created = float(pending.get("created_at") or 0)
        age_days = (now - created) / 86400 if created else 9999.0
        if auto_apply and age_days >= grace_days:
            applied = await apply_daily_compression_review(pending["id"])
            print(
                f"[memory_maintenance] 自动应用 {age_days:.1f} 天前的压缩草稿: "
                f"{applied.get('message', '')}"
            )
        else:
            return {
                "ok": True,
                "action": "wait_review",
                "message": f"已有 {age_days:.1f} 天前的压缩草稿待人工审核，"
                           f"{grace_days:.0f} 天宽限期过后才自动应用。",
            }

    gen = await generate_daily_compression_draft(days=DIGEST_WINDOW_DAYS, target="both")
    return {
        "ok": True,
        "applied": bool(applied and applied.get("ok")),
        "draft": bool(gen.get("review")),
        "message": gen.get("message", "已生成新的压缩草稿。"),
    }


# ── 每日维护主流程 ──────────────────────────────
async def run_daily_maintenance() -> dict:
    cfg = _maint_cfg()
    if not cfg["enabled"]:
        return {"ok": True, "message": "每日维护已通过 maintenance_enabled 关闭。"}

    # 顺序：先备份（压缩前留档）→ 再压缩 → 最后 VACUUM 回收空间
    backup = await asyncio.to_thread(_backup_db_sync, Path(cfg["backup_dir"]), cfg["keep_backups"])
    compress = await auto_compress(grace_days=cfg["grace_days"], auto_apply=cfg["auto_apply"])
    vacuum = await asyncio.to_thread(_vacuum_sync)

    return {
        "ok": True,
        "backup": backup,
        "compress": compress,
        "vacuum": vacuum,
        "message": (
            f"备份={'成功' if backup.get('ok') else '失败'}（{backup.get('path', backup.get('message', ''))}），"
            f"{compress.get('message', '')} "
            f"VACUUM={'回收 ' + str(vacuum.get('freed', 0)) + ' B' if vacuum.get('ok') else '未执行'}"
        ),
    }
