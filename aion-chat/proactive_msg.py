"""
AI 定时主动消息：到设定间隔后，由 AI 根据当前时间、最近对话和记忆，主动向用户 Aion 私聊发一条消息。
独立于监控哨兵：只走 schedule_mgr._save_to_private 落库+广播，不触发哨兵/监控链路。
"""

import re
import time
from datetime import datetime

import aiosqlite

from config import DEFAULT_MODEL, SETTINGS, load_worldbook
from database import get_db
from ai_providers import CLI_STATUS_PREFIX, stream_ai
from context_builder import fetch_merged_timeline, render_merged_timeline
from memory import build_surfacing_memories, format_recalled_memories_for_prompt
from schedule import _consume_background_stream, _new_background_meta, schedule_mgr
from web_search import WebCommandStreamFilter

# AI 主动决定"本轮不发"的输出标记
_SKIP_RE = re.compile(r"\[\[\s*SKIP\s*\]\]|\[\s*SKIP\s*\]", re.IGNORECASE)
# 用户近 N 秒内有发言则跳过本轮（不打断正在进行的聊天）
_ACTIVE_SKIP_SECONDS = 600


async def _resolve_target_private() -> dict | None:
    """取最近活跃的 Aion 私聊会话（conversations 表只存私聊）。"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 1"
        )
        conv = await cur.fetchone()
    if not conv:
        return None
    return {
        "conv_id": conv["id"],
        "model_key": conv["model"] or DEFAULT_MODEL,
    }


async def _last_user_msg_ts(conv_id: str) -> float | None:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT created_at FROM messages WHERE conv_id=? AND role='user' "
            "ORDER BY created_at DESC LIMIT 1",
            (conv_id,),
        )
        row = await cur.fetchone()
    if row and row["created_at"]:
        try:
            return float(row["created_at"])
        except (TypeError, ValueError):
            return None
    return None


async def send_proactive_message() -> dict:
    """触发一次 AI 主动消息。返回 {"status": "sent"|"skipped_active"|"ai_skip"|"error", "detail": ...}。"""
    target = await _resolve_target_private()
    if not target:
        return {"status": "error", "detail": "no_conv"}
    conv_id = target["conv_id"]
    model_key = target["model_key"]

    # 用户近 10 分钟在聊 → 跳过，不打断
    last_ts = await _last_user_msg_ts(conv_id)
    if last_ts is not None and (time.time() - last_ts) < _ACTIVE_SKIP_SECONDS:
        return {
            "status": "skipped_active",
            "detail": f"last_user {int(time.time() - last_ts)}s ago",
        }

    wb = load_worldbook()
    ai_name = wb.get("ai_name") or "AI"
    user_name = wb.get("user_name") or "你"

    # 最近上下文
    merged = await fetch_merged_timeline("aion", 20, conv_id=conv_id)
    history = render_merged_timeline(merged, "aion")

    # 人设前缀（仿 schedule.py 主动唤醒写法）
    prefix = []
    if wb.get("ai_persona"):
        prefix.append({"role": "user", "content": f"[系统设定 - {ai_name}人设]\n{wb['ai_persona']}"})
        prefix.append({"role": "assistant", "content": "收到，我会按照设定扮演角色。"})
    if wb.get("user_persona"):
        prefix.append({"role": "user", "content": f"[系统设定 - {user_name}信息]\n{wb['user_persona']}"})
        prefix.append({"role": "assistant", "content": "收到，我会记住你的信息。"})

    # 记忆（无 embedding 配置时也返回近期/未解决事项）
    mem_inject = []
    try:
        surfaced, _ = await build_surfacing_memories(topic="", keywords=None, max_total=8)
        if surfaced:
            mem_text = format_recalled_memories_for_prompt(surfaced)
            mem_inject = [
                {"role": "user", "content": f"[背景记忆]\n以下是你记得的近期事件和需要关注的事项：\n{mem_text}"},
                {"role": "assistant", "content": "收到，我会在合适的时候自然提及。"},
            ]
    except Exception:
        mem_inject = []

    # 触发 prompt：每轮必发，自然回复，像平时聊天一样（可用换行分出多个气泡）
    now_str = datetime.now().strftime("%Y年%m月%d日  %H:%M:%S")
    trigger = (
        "[定时主动消息触发]\n"
        f"现在时间：{now_str}。这是你定时主动联系【{user_name}】的机会。\n"
        "请务必真的发一条消息，用你自己的口吻自然地回复：像平时聊天一样，可以是一两句，也可以是几句、"
        "换行分成几个气泡，贴合当前时间/最近对话/记忆即可。\n"
        "不许跳过、不许回复 [[SKIP]]，也不要以任何理由不开口——哪怕只说一句关心或吐槽也要说。\n"
        "不要输出 [MUSIC]、[ALARM]、[Monitor]、[REMINDER] 等系统指令，只说普通话语。"
    )
    messages = prefix + mem_inject + history + [{"role": "user", "content": trigger}]

    # 生成
    ai_msg_id = f"msg_{int(time.time() * 1000)}_pm"
    usage_meta = _new_background_meta()
    temp = SETTINGS.get("temperature")

    async def content_stream():
        async for chunk in stream_ai(messages, model_key, meta=usage_meta, temperature=temp):
            if chunk.startswith(CLI_STATUS_PREFIX):
                continue
            yield chunk

    try:
        result = await _consume_background_stream(
            content_stream(), WebCommandStreamFilter(), None
        )
    except Exception as exc:
        return {"status": "error", "detail": f"stream_exc:{exc}"}

    full_text = (result.committed_text or "").strip()

    # 守卫：AI 决定本轮不发
    if _SKIP_RE.search(full_text):
        return {"status": "ai_skip", "detail": "model chose not to send"}

    # 守卫：流异常停止 / 空流 / 错误文本 → 不落库
    if result.stop_reason:
        return {"status": "error", "detail": result.stop_reason}
    if not full_text:
        return {"status": "error", "detail": "empty_stream"}
    if full_text.startswith("[") and "错误" in full_text[:40]:
        return {"status": "error", "detail": full_text[:120]}

    # 落库 + 广播（系统行 + AI 消息）
    reasoning = (usage_meta.get("reasoning_content") or "").strip()
    try:
        await schedule_mgr._save_to_private(
            conv_id,
            f"{ai_name}主动联系了你",
            full_text,
            ai_msg_id,
            "[]",
            [],
            reasoning,
        )
    except Exception as exc:
        return {"status": "error", "detail": f"save_exc:{exc}"}
    # 触发 web push 系统推送（锁屏也能收到；force=True 无视在线连接）
    try:
        from routes.chat import _push_new_ai_message
        _push_new_ai_message(full_text, force=True)
    except Exception:
        pass
    return {"status": "sent", "detail": conv_id}
