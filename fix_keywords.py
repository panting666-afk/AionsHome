#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用哨兵模型（记忆提取 LLM）批量重新提取《核心记忆》关键词，更新数据库。
关键点：批量调用——一批 N 条记忆走一次 LLM，112 条默认 6 次调用即可。
用法（容器内）:
  --preview N:   只处理前 N 条预览，不写库
  --batch N:     每批条数（默认 20）
依赖: import_core_memories.py 提供解析，config/memory 提供哨兵调用。
"""
import sys, json, asyncio

from import_core_memories import parse_blocks, build_memories, ts_to_date_str
from config import get_sentinel_config
from memory import _call_sentinel_text

BATCH_PROMPT = """你是一次处理多条记忆的关键词提取器。

下面用【编号】分隔列出 {n} 条记忆。对每一条，提取 3-5 个稀缺、具体的关键词，用于日后检索。

硬性要求：
1. 每个关键词数组的第一个元素必须是该记忆的日期（YYYY-MM-DD）。
2. 关键词必须是该记忆里的具体对象词/事件词/特征词，例如：高数、二战考研、结扎手术、空耳、哈吉米、初吻、领证结婚、草莓沐浴露、体重54kg 这类。
3. 禁止出现人名（潘婷、金韩彬）和泛词（开心、聊天、回复、知道、然后、喜欢、觉得、今天）。
4. 只能使用对应记忆内容里出现的词，不要编造。

{items}

只输出一个 JSON 对象，键是编号字符串，值是对应关键词数组，例如：
{{"1": ["2026-08-09","空耳","哈吉米"], "2": ["2026-08-08","培根芝士蛋吐司","计算机组成原理"]}}
不要任何解释，不要 Markdown，不要遗漏任何编号。"""


def build_batch_items(mems):
    lines = []
    for m in mems:
        date = ts_to_date_str(m["ts"]) if m["ts"] else ""
        content = m["content"][:600].replace("\n", " ")
        lines.append(f"【{m['idx']}】日期：{date}\n{content}")
    return "\n\n".join(lines)


async def extract_batch(scfg, batch, timeout=120):
    """一次调用返回 {idx: [keywords]}。失败返回 None。"""
    prompt = BATCH_PROMPT.format(n=len(batch), items=build_batch_items(batch))
    try:
        raw = await _call_sentinel_text(scfg, prompt, timeout=timeout)
        if not raw:
            return None
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return None
        out = {}
        for k, v in obj.items():
            if isinstance(v, list):
                kws = [str(x).strip().strip('"\'') for x in v if str(x).strip()]
                out[str(k).strip()] = kws
        return out
    except Exception as e:
        print(f"  批量调用异常: {type(e).__name__}: {e}")
        return None


async def main():
    path = sys.argv[1]
    preview = "--preview" in sys.argv
    batch_size = 20
    limit = 3
    for i, arg in enumerate(sys.argv):
        if arg == "--preview" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                pass
        if arg == "--batch" and i + 1 < len(sys.argv):
            try:
                batch_size = int(sys.argv[i + 1])
            except ValueError:
                pass

    blocks = parse_blocks(open(path, encoding="utf-8-sig").read())
    mems = build_memories(blocks)
    if preview:
        mems = mems[:limit]

    scfg = get_sentinel_config()
    if not scfg.get("api_key"):
        print("哨兵模型未配置 api_key")
        sys.exit(1)

    batches = [mems[i:i + batch_size] for i in range(0, len(mems), batch_size)]
    print(f"{len(mems)} 条记忆，每批 {batch_size} 条 → {len(batches)} 次 LLM 调用\n")

    results = {}   # idx(int) -> keywords
    for bi, batch in enumerate(batches):
        # 确保编号在批内唯一：批内 idx 就是记忆原编号（核心记忆 1-112 全局唯一）
        for attempt in range(3):
            got = await extract_batch(scfg, batch, timeout=120)
            if got:
                break
            print(f"  批 {bi+1}/{len(batches)} 第 {attempt+1} 次尝试失败，重试...")
            await asyncio.sleep(1)
        if got:
            ok = 0
            for m in batch:
                kws = got.get(str(m["idx"]))
                if kws:
                    date = ts_to_date_str(m["ts"]) if m["ts"] else None
                    if date and kws and kws[0] != date:
                        if date in kws:
                            kws.remove(date)
                        kws.insert(0, date)
                    results[m["idx"]] = kws[:8]
                    ok += 1
            print(f"  批 {bi+1}/{len(batches)}: {ok}/{len(batch)} 条成功")
        else:
            print(f"  批 {bi+1}/{len(batches)}: 3 次尝试全部失败，这批跳过（保留原关键词）")
        await asyncio.sleep(0.2)

    print(f"\n成功提取 {len(results)} / {len(mems)} 条")
    if preview:
        for m in mems:
            print(f"  #{m['idx']} {results.get(m['idx'], '（未提取）')}")
        print("[预览模式] 未写库")
        return

    from database import get_db
    content_by_idx = {m["idx"]: m["content"] for m in mems}
    n = 0
    async with get_db() as db:
        for idx, kws in results.items():
            cur = await db.execute(
                "UPDATE memories SET keywords=? WHERE content=? AND type='important'",
                (json.dumps(kws, ensure_ascii=False), content_by_idx[idx]),
            )
            n += cur.rowcount or 0
        await db.commit()
    print(f"更新数据库完成：影响 {n} 行（预期 {len(results)}）")


if __name__ == "__main__":
    asyncio.run(main())
