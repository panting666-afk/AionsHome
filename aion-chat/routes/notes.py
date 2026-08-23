"""
随手笔记 API：列表查询、新增、编辑、删除。
"""

import json
import time
import uuid
import aiosqlite
from fastapi import APIRouter, Query
from pydantic import BaseModel

from database import get_db

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteCreate(BaseModel):
    title: str = ""
    content: str
    attachments: list[str] = []


class NoteUpdate(BaseModel):
    title: str = ""
    content: str
    attachments: list[str] = []


@router.get("")
async def list_notes(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    keyword: str = Query("", max_length=80),
):
    """分页获取笔记列表，支持关键词模糊搜索标题和内容"""
    offset = (page - 1) * page_size
    where_clause = ""
    params = []

    if keyword:
        # 去除首尾空格，若有内容则进行模糊检索
        keyword_stripped = keyword.strip()
        if keyword_stripped:
            where_clause = "WHERE title LIKE ? OR content LIKE ?"
            like_param = f"%{keyword_stripped}%"
            params.extend([like_param, like_param])

    async with get_db() as db:
        db.row_factory = aiosqlite.Row

        # 获取总记录数
        count_query = f"SELECT COUNT(*) as cnt FROM notes {where_clause}"
        cur = await db.execute(count_query, params)
        total = (await cur.fetchone())["cnt"]

        # 获取分页数据，按更新时间降序排列
        data_query = (
            f"SELECT id, title, content, attachments, created_at, updated_at "
            f"FROM notes {where_clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        )
        cur = await db.execute(data_query, params + [page_size, offset])
        rows = await cur.fetchall()

    items = []
    for r in rows:
        # 解析附件 JSON 列表
        try:
            attachments = json.loads(r["attachments"]) if r["attachments"] else []
        except Exception:
            attachments = []

        items.append({
            "id": r["id"],
            "title": r["title"],
            "content": r["content"],
            "attachments": attachments,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
        "has_more": offset + len(items) < total,
    }


@router.post("")
async def create_note(body: NoteCreate):
    """创建新笔记"""
    note_id = f"note_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    now = time.time()
    attachments_str = json.dumps(body.attachments, ensure_ascii=False)

    async with get_db() as db:
        await db.execute(
            "INSERT INTO notes (id, title, content, attachments, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (note_id, body.title.strip(), body.content, attachments_str, now, now),
        )
        await db.commit()

    return {"ok": True, "id": note_id}


@router.put("/{note_id}")
async def update_note(note_id: str, body: NoteUpdate):
    """修改笔记"""
    now = time.time()
    attachments_str = json.dumps(body.attachments, ensure_ascii=False)

    async with get_db() as db:
        cur = await db.execute("SELECT 1 FROM notes WHERE id=?", (note_id,))
        if not await cur.fetchone():
            return {"error": "笔记不存在", "ok": False}

        await db.execute(
            "UPDATE notes SET title=?, content=?, attachments=?, updated_at=? WHERE id=?",
            (body.title.strip(), body.content, attachments_str, now, note_id),
        )
        await db.commit()

    return {"ok": True}


@router.delete("/{note_id}")
async def delete_note(note_id: str):
    """删除笔记"""
    async with get_db() as db:
        cur = await db.execute("SELECT 1 FROM notes WHERE id=?", (note_id,))
        if not await cur.fetchone():
            return {"error": "笔记不存在", "ok": False}

        await db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        await db.commit()

    return {"ok": True}
