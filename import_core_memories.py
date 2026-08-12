#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入《金韩彬_潘婷_核心记忆.txt》到 memories 表（一次性脚本）
用法:
  parse-only:  python import_core_memories.py <txt> --parse-only   # 只解析验证，不写入
  插入(容器内): python import_core_memories.py <txt>               # 生成 embedding 并写入
内容原封不动保留；关键词/时间戳自动整理。
"""
import sys, re, json, time, asyncio

# ── 时间戳解析 ─────────────────────────────
# 支持: [2026/8/9 09:40:32]、[2026/7/31]、【2026/8/3 23:37:50】、日期区间 [2026/7/27-7/28]
TS_RE = re.compile(
    r'[\[【]\s*(\d{4})[年/\-\.](\d{1,2})[月/\-\.](\d{1,2})'
    r'(?:\s*-\s*\d{1,2}[月/\-\.]\d{1,2})?'
    r'(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?\s*[\]】]'
)
# 散文式日期：2026年4月25日 在公寓楼下...
DATE_LINE_RE = re.compile(r'^[^\d]*(\d{4})年(\d{1,2})月(\d{1,2})日')
# 记忆块标记：记忆 001 / 记忆 1
BLOCK_RE = re.compile(r'^\s*记忆\s*([0-9０-９]+)\s*[：:．.]?\s*$')


def _i(v):
    return int(v) if v else 0


def parse_ts(y, mo, d, hh=0, mm=0, ss=0):
    try:
        return time.mktime((int(y), int(mo), int(d), _i(hh), _i(mm), _i(ss), 0, 0, -1))
    except Exception:
        return None


def ts_to_date_str(ts):
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def parse_blocks(text):
    """按 '记忆 NNN' 切块，保留每块原始行（含时间戳行）。"""
    blocks = []
    cur = None
    for ln in text.splitlines():
        m = BLOCK_RE.match(ln)
        if m:
            cur = {"idx": int(m.group(1).replace("０", "0").replace("１", "1")
                                  .replace("２", "2").replace("３", "3").replace("４", "4")
                                  .replace("５", "5").replace("６", "6").replace("７", "7")
                                  .replace("８", "8").replace("９", "9")),
                   "lines": []}
            blocks.append(cur)
        elif cur is not None:
            cur["lines"].append(ln)
    return blocks


def extract_timestamp(lines):
    """返回 (ts_float|None)。优先方括号时间戳行，其次散文日期行。"""
    for ln in lines:
        m = TS_RE.search(ln)
        if m:
            return parse_ts(m.group(1), m.group(2), m.group(3),
                            m.group(4), m.group(5), m.group(6))
    for ln in lines:
        m = DATE_LINE_RE.search(ln)
        if m:
            return parse_ts(m.group(1), m.group(2), m.group(3))
    return None


STOPWORDS = set("""的 了 和 在 是 我 你 她 他 我们 你们 他们 一个 一种 因为 所以 但是 就是 这个 那个
与 及 并 对 向 为 被 把 也 都 还 而 很 非常 已经 将 会 能够 不会 不要 以及 之后 之前 目前 现在
自己 用户 进行 一些 之间 其中 表示 认为 觉得 知道 喜欢 想要 需要 希望 说 叫 常 曾 时 后 里 上 下
老婆 老公 双方 彼此 两个 一起 一直 已经 通过 决定 承诺 表达 告诉 详细 描述 理解 支持 希望 强调
被问及 与用户 用户向 向用户 称 并 表示 其 本 就 更 最 只 该 些 这 那 么 吗 呢 吧 啊 啦 哦 嗯 呀
天 月 年 日 时 分 秒 号 周 岁 个 条 张 次 公斤 公分 厘米 码 公里""".split())

CJK = re.compile(r'[一-鿿]{2,}')


def extract_keywords(content, ts=None):
    """轻量关键词：CJK 连续片段频次，过滤停用词，取最高频。"""
    cands = {}
    for seg in CJK.findall(content):
        for i in range(len(seg) - 1):
            bi = seg[i:i + 2]
            if bi in STOPWORDS or len(bi) < 2:
                continue
            cands[bi] = cands.get(bi, 0) + 1
    # 也收录 3-4 字词
    for seg in CJK.findall(content):
        if len(seg) >= 3:
            tri = seg[:3]
            if tri not in STOPWORDS:
                cands[tri] = cands.get(tri, 0) + 1
    top = sorted(cands.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    kws = [w for w, _ in top]
    if ts:
        kws.insert(0, ts_to_date_str(ts))
    return kws


def build_memories(blocks):
    mems = []
    now = time.time()
    for b in blocks:
        lines = b["lines"]
        # 过滤水印行
        clean = [ln for ln in lines if not (("核心记忆" in ln) and ("｜" in ln or "|" in ln))]
        # 提取时间戳（行保留在内容里原样展示）
        ts = extract_timestamp(clean)
        # 内容：跳过时间戳标记行本身，其余原封不动
        content_lines = []
        for ln in clean:
            if TS_RE.search(ln):
                # 时间戳行：若同行带正文（如 "：1. xxx"）则保留冒号后正文
                after = TS_RE.sub("", ln).lstrip("：: ")
                if after:
                    content_lines.append(after)
                continue
            if ln.strip():
                content_lines.append(ln.rstrip())
        content = "\n".join(content_lines).strip()
        if not content:
            content = "\n".join(l for l in clean if l.strip()).strip()
        created = ts if ts else now
        kws = extract_keywords(content, ts)
        mems.append({
            "idx": b["idx"],
            "content": content,
            "ts": ts,
            "created_at": created,
            "keywords": kws,
            "type": "important",
            "importance": 0.9,
        })
    return mems


def parse_only(path):
    text = open(path, encoding="utf-8-sig").read()
    blocks = parse_blocks(text)
    mems = build_memories(blocks)
    print(f"解析到记忆块: {len(blocks)} 条")
    print(f"生成待导入条目: {len(mems)} 条")
    print("=" * 60)
    for m in mems:
        import datetime
        ts_lbl = ts_to_date_str(m["ts"]) if m["ts"] else "无时间戳"
        lines = len(m["content"].splitlines())
        print(f"#{m['idx']:>3} [{ts_lbl}] {lines}行 | 关键词: {m['keywords']}")
        print(f"   内容预览: {m['content'][:60].replace(chr(10),' / ')}")
    # 校验: 内容是否含遗漏标记
    return mems


if __name__ == "__main__":
    path = sys.argv[1]
    if "--parse-only" in sys.argv:
        parse_only(path)
        sys.exit(0)
    # 容器内插入模式
    import asyncio
    async def main():
        from memory import get_embedding, _pack_embedding
        from database import get_db
        mems = parse_only(path)
        print("\n开始写入...")
        n = 0
        for i, m in enumerate(mems):
            content = m["content"]
            vec = await get_embedding(content)
            emb = _pack_embedding(vec) if vec else None
            mem_id = f"mem_{int(time.time()*1000)}_{i:04d}"
            kws_json = json.dumps(m["keywords"], ensure_ascii=False)
            ts = m["ts"] or m["created_at"]
            try:
                async with get_db() as db:
                    await db.execute(
                        "INSERT INTO memories ("
                        "id, content, type, created_at, source_conv, embedding, keywords, importance, "
                        "source_start_ts, source_end_ts, unresolved, source_msg_id, evidence_summary, evidence_detail_level"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            mem_id, content, m["type"], m["created_at"], None,
                            emb, kws_json, m["importance"],
                            ts, ts, 0, None, content[:900], "summary",
                        ),
                    )
                    await db.commit()
                n += 1
                if n % 20 == 0:
                    print(f"  已写入 {n}/{len(mems)}")
            except Exception as e:
                print(f"  #{m['idx']} 写入失败: {type(e).__name__}: {e}")
        print(f"完成：成功写入 {n} / {len(mems)} 条")
        emb_cnt = sum(1 for m in mems if True)
    asyncio.run(main())
