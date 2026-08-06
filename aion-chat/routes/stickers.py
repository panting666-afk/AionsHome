"""表情包：分组 + 导入 txt + 单个添加/删除 + AI 目录注入"""
import json
import random
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from config import DATA_DIR, SETTINGS

router = APIRouter()

STICKER_FILE = Path(DATA_DIR) / "sticker_packs.json"
STICKER_GROUP_MAX = 500          # 单个分组上限
STICKER_DESC_MAX = 50
STICKER_URL_MAX = 1500


def _load() -> dict:
    try:
        if STICKER_FILE.exists():
            data = json.loads(STICKER_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("groups"), list):
                return data
    except Exception:
        pass
    return {"groups": []}


def _save(data: dict) -> None:
    STICKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    STICKER_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _derive_desc(url: str) -> str:
    """纯 URL 时从文件名猜测描述"""
    tail = url.split("?")[0].rstrip("/").split("/")[-1].split(".")[0]
    try:
        from urllib.parse import unquote
        tail = unquote(tail)
    except Exception:
        pass
    return tail or "表情包"


def _parse_line(line: str) -> Optional[tuple[str, str]]:
    """解析一行「描述：URL」。支持全角/半角冒号，也支持纯 URL 行。"""
    line = line.strip().lstrip("﻿")
    if not line or line.startswith("#") or line.startswith("//"):
        return None
    desc = ""
    url = line
    idx = line.find("：")                      # 全角冒号优先
    if idx < 0:
        idx = line.find(":")                   # 半角冒号（跳过 https:// 里的冒号）
        if idx >= 0 and line[idx + 1:idx + 3] == "//":
            idx = -1
    if idx > 0:
        left, right = line[:idx].strip(), line[idx + 1:].strip()
        if right.startswith("http://") or right.startswith("https://") or \
           right.startswith("/") or right.startswith("data:image"):
            desc, url = left, right
    if not (url.startswith("http://") or url.startswith("https://") or
            url.startswith("/") or url.startswith("data:image")):
        return None
    if not desc:
        desc = _derive_desc(url)
    return desc.strip()[:STICKER_DESC_MAX], url[:STICKER_URL_MAX]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{random.randrange(0, 10000)}"


# ── 查询 ─────────────────────────────────────────
@router.get("/api/stickers")
async def get_stickers():
    return _load()


# ── 分组 ─────────────────────────────────────────
class GroupCreate(BaseModel):
    name: str


@router.post("/api/stickers/groups")
async def create_group(body: GroupCreate):
    name = (body.name or "").strip()[:30]
    if not name:
        raise HTTPException(400, "组名不能为空")
    data = _load()
    if any(g["name"] == name for g in data["groups"]):
        raise HTTPException(400, "已经有同名分组了")
    data["groups"].append({"id": _new_id("g"), "name": name, "stickers": []})
    _save(data)
    return {"ok": True, "groups": data["groups"]}


@router.delete("/api/stickers/groups/{gid}")
async def delete_group(gid: str):
    data = _load()
    data["groups"] = [g for g in data["groups"] if g["id"] != gid]
    _save(data)
    return {"ok": True, "groups": data["groups"]}


# ── 单个表情包 ───────────────────────────────────
class StickerCreate(BaseModel):
    desc: str
    url: str


@router.post("/api/stickers/groups/{gid}/stickers")
async def add_sticker(gid: str, body: StickerCreate):
    data = _load()
    group = next((g for g in data["groups"] if g["id"] == gid), None)
    if not group:
        raise HTTPException(404, "分组不存在")
    parsed = _parse_line(f"{body.desc}：{body.url}")
    if not parsed:
        raise HTTPException(400, "描述或 URL 无效")
    desc, url = parsed
    for s in group["stickers"]:
        if s["url"] == url:
            return {"ok": True, "groups": data["groups"], "duplicate": True}
    if len(group["stickers"]) >= STICKER_GROUP_MAX:
        raise HTTPException(400, f"单个分组最多 {STICKER_GROUP_MAX} 个")
    group["stickers"].append({
        "id": _new_id(f"{gid}_s"),
        "desc": desc,
        "url": url,
    })
    _save(data)
    return {"ok": True, "groups": data["groups"]}


@router.delete("/api/stickers/{sid}")
async def delete_sticker(sid: str):
    data = _load()
    for g in data["groups"]:
        g["stickers"] = [s for s in g["stickers"] if s["id"] != sid]
    _save(data)
    return {"ok": True, "groups": data["groups"]}


# ── 导入 txt ─────────────────────────────────────
@router.post("/api/stickers/groups/{gid}/import")
async def import_stickers(gid: str, file: UploadFile = File(...)):
    data = _load()
    group = next((g for g in data["groups"] if g["id"] == gid), None)
    if not group:
        raise HTTPException(404, "分组不存在")
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    if not any("一" <= ch <= "鿿" for ch in text[:200]) and "：" not in text[:200]:
        # 看起来不像 UTF-8 中文，按 GBK 再试一次
        text = raw.decode("gbk", errors="replace")
    added = 0
    skipped = 0
    errors: list[str] = []
    seen = {s["url"] for s in group["stickers"]}
    for ln in text.splitlines():
        if not ln.strip():
            continue
        parsed = _parse_line(ln)
        if not parsed:
            errors.append(ln.strip()[:40])
            skipped += 1
            continue
        desc, url = parsed
        if url in seen:
            skipped += 1
            continue
        if len(group["stickers"]) >= STICKER_GROUP_MAX:
            errors.append(f"已达上限（{STICKER_GROUP_MAX}），剩余行未导入")
            break
        group["stickers"].append({
            "id": _new_id(f"{gid}_s"),
            "desc": desc,
            "url": url,
        })
        seen.add(url)
        added += 1
    _save(data)
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "errors": errors[:20],
        "groups": data["groups"],
    }


# ── 供 AI 提示词注入：表情包目录 ─────────────────
def build_sticker_catalog(max_items: int = 0) -> str:
    """生成一段给 AI 看的表情包清单（全量列出），返回空串表示还没有表情包或已关闭。
    max_items=0 表示不限制。"""
    if not SETTINGS.get("ai_stickers_enabled", True):
        return ""
    data = _load()
    groups = data.get("groups", [])
    total = sum(len(g.get("stickers", [])) for g in groups)
    if total == 0:
        return ""
    lines = [
        "【表情包库】",
        "你可以给用户发表情包。在回复正文里插入标记 [表情包:描述]，描述必须用下面列表里的完整描述，"
        "就会发出对应的表情包图片。情绪合适就发，别太频繁；如果同时有文字，写在文字前面或后面都行。",
    ]
    shown = 0
    for g in groups:
        stickers = g.get("stickers", [])
        if not stickers:
            continue
        descs = []
        for s in stickers:
            if max_items and shown >= max_items:
                break
            if s.get("desc"):
                descs.append(s["desc"])
                shown += 1
        if descs:
            lines.append(f"- 「{g.get('name', '未命名')}」：{'、'.join(descs)}")
        if max_items and shown >= max_items:
            break
    if max_items and total > shown:
        lines.append(f"（共 {total} 个，仅列出前 {max_items} 个，其余未列出无法发送）")
    return "\n".join(lines)


def find_sticker_by_desc(desc: str) -> Optional[dict]:
    """AI 回复解析用：按描述找表情包，先精确后包含。"""
    desc = (desc or "").strip()
    if not desc:
        return None
    data = _load()
    for g in data.get("groups", []):
        for s in g.get("stickers", []):
            if s.get("desc", "").strip() == desc:
                return {**s, "group": g.get("name", "")}
    for g in data.get("groups", []):
        for s in g.get("stickers", []):
            if desc in s.get("desc", "") or s.get("desc", "") in desc:
                return {**s, "group": g.get("name", "")}
    return None
