import pytest
import time
import json
from httpx import AsyncClient
from database import get_db, init_db
from main import app

# 初始化数据库
@pytest.fixture(scope="function", autouse=True)
def setup_db():
    import asyncio
    asyncio.run(init_db())
    # 清空 notes 测试数据
    async def clean():
        async with get_db() as db:
            await db.execute("DELETE FROM notes")
            await db.commit()
    asyncio.run(clean())


@pytest.mark.asyncio
async def test_notes_crud_lifecycle():
    # 使用 AsyncClient 访问 FastAPI endpoints
    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:

        # 1. 查询初始列表应当为空
        response = await ac.get("/api/notes")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0
        assert data["has_more"] is False

        # 2. 创建一个带图片的新笔记
        note_data = {
            "title": "测试知识笔记",
            "content": "这是一个包含重要小知识的测试笔记。\n多行内容测试。\n",
            "attachments": ["/uploads/test_image1.png", "/uploads/test_image2.jpg"]
        }
        create_res = await ac.post("/api/notes", json=note_data)
        assert create_res.status_code == 200
        create_data = create_res.json()
        assert create_data["ok"] is True
        note_id = create_data["id"]
        assert note_id.startswith("note_")

        # 3. 再次查询列表，应当出现 1 条记录
        list_res = await ac.get("/api/notes")
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert list_data["total"] == 1
        assert len(list_data["items"]) == 1

        retrieved_note = list_data["items"][0]
        assert retrieved_note["id"] == note_id
        assert retrieved_note["title"] == "测试知识笔记"
        assert retrieved_note["content"] == note_data["content"]
        assert retrieved_note["attachments"] == note_data["attachments"]
        assert retrieved_note["created_at"] > 0
        assert retrieved_note["updated_at"] == retrieved_note["created_at"]

        # 4. 根据关键字搜索
        search_res = await ac.get("/api/notes?keyword=重要小知识")
        assert search_res.status_code == 200
        search_data = search_res.json()
        assert search_data["total"] == 1

        search_empty = await ac.get("/api/notes?keyword=不存在的神秘词汇")
        assert search_empty.status_code == 200
        assert search_empty.json()["total"] == 0

        # 5. 更新笔记 (包括标题、内容、图片附件)
        update_data = {
            "title": "更新后的知识笔记",
            "content": "修改了内容：今天学到了一个关于 SQLite 索引优化的技巧。",
            "attachments": ["/uploads/test_image1.png"]  # 删除了第二张图
        }
        update_res = await ac.put(f"/api/notes/{note_id}", json=update_data)
        assert update_res.status_code == 200
        assert update_res.json()["ok"] is True

        # 6. 获取更新后的列表并校验
        list_res2 = await ac.get("/api/notes")
        list_data2 = list_res2.json()
        assert list_data2["total"] == 1

        updated_note = list_data2["items"][0]
        assert updated_note["title"] == "更新后的知识笔记"
        assert updated_note["content"] == update_data["content"]
        assert updated_note["attachments"] == ["/uploads/test_image1.png"]
        assert updated_note["updated_at"] >= updated_note["created_at"]

        # 7. 删除笔记
        delete_res = await ac.delete(f"/api/notes/{note_id}")
        assert delete_res.status_code == 200
        assert delete_res.json()["ok"] is True

        # 8. 确认删除后列表为空
        list_res3 = await ac.get("/api/notes")
        assert list_res3.json()["total"] == 0
