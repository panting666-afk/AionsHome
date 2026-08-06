"""
AI 生图模块：Gemini gemini-3.1-flash-lite-image 生成图片
支持 SELFIE（带参考图）和 DRAW（纯文本）两种模式
"""

import base64, time
from pathlib import Path

import httpx

from config import get_key, SETTINGS, UPLOADS_DIR, PUBLIC_DIR

# 参考图位置（用于 SELFIE 模式）
REFERENCE_IMAGE_PATH = PUBLIC_DIR / "生图锚点.jpg"
SECONDARY_REFERENCE_IMAGE_PATH = PUBLIC_DIR / "2号机生图锚点.jpg"
IMAGE_GEN_MODEL = "gemini-3.1-flash-lite-image"
IMAGE_GEN_TIMEOUT = 120  # 生图超时秒数


def _relay_config() -> dict | None:
    """读取自定义中转站生图配置；未配置返回 None。"""
    base = (SETTINGS.get("image_gen_base_url") or "").strip()
    key = (SETTINGS.get("image_gen_api_key") or "").strip()
    model = (SETTINGS.get("image_gen_model") or "").strip()
    if not (base and key and model):
        return None
    return {
        "base": base.rstrip("/"),
        "key": key,
        "model": model,
        "size": (SETTINGS.get("image_gen_size") or "1024x1024").strip(),
    }


def _relay_images_url(cfg: dict, kind: str) -> str:
    """拼中转站生图 URL。kind: generations / edits"""
    base = cfg["base"]
    if not base.endswith("/v1"):
        base = base + "/v1"
    return f"{base}/images/{kind}"


async def _generate_via_relay_generations(prompt: str, cfg: dict) -> str | None:
    """中转站：纯文生图 /images/generations"""
    url = _relay_images_url(cfg, "generations")
    headers = {"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"}
    payload = {"model": cfg["model"], "prompt": prompt, "n": 1, "response_format": "b64_json"}
    if cfg.get("size"):
        payload["size"] = cfg["size"]
    try:
        async with httpx.AsyncClient(timeout=IMAGE_GEN_TIMEOUT) as client:
            print(f"[image_gen] 中转站文生图: {cfg['model']}")
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return await _save_relay_image(resp.json(), client)
    except Exception as e:
        print(f"[image_gen] 中转站文生图失败: {e}")
        return None


async def _generate_via_relay_edits(prompt: str, ref_bytes: bytes, mime: str, cfg: dict) -> str | None:
    """中转站：锁脸生图（带参考图） /images/edits（multipart）"""
    url = _relay_images_url(cfg, "edits")
    headers = {"Authorization": f"Bearer {cfg['key']}"}
    ext = "png" if "png" in mime else "jpg"
    try:
        async with httpx.AsyncClient(timeout=IMAGE_GEN_TIMEOUT) as client:
            print(f"[image_gen] 中转站锁脸生图: {cfg['model']}")
            files = {
                "image": (f"ref.{ext}", ref_bytes, mime),
                "prompt": (None, prompt),
                "model": (None, cfg["model"]),
                "n": (None, "1"),
                "response_format": (None, "b64_json"),
            }
            if cfg.get("size"):
                files["size"] = (None, cfg["size"])
            resp = await client.post(url, files=files, headers=headers)
            resp.raise_for_status()
            return await _save_relay_image(resp.json(), client)
    except Exception as e:
        print(f"[image_gen] 中转站锁脸生图失败: {e}")
        return None


async def _save_relay_image(data: dict, client: httpx.AsyncClient) -> str | None:
    """从 OpenAI 兼容响应里取图并保存，返回文件名。支持 b64_json 或 url。"""
    items = (data or {}).get("data") or []
    if not items:
        print(f"[image_gen] 中转站返回空 data: {str(data)[:200]}")
        return None
    first = items[0]
    b64 = first.get("b64_json")
    if b64:
        filename = f"img_gen_{int(time.time() * 1000)}.png"
        (UPLOADS_DIR / filename).write_bytes(base64.b64decode(b64))
        print(f"[image_gen] 图片已保存: {filename}")
        return filename
    img_url = first.get("url")
    if img_url:
        img_resp = await client.get(img_url)
        img_resp.raise_for_status()
        ctype = img_resp.headers.get("content-type", "")
        ext = "png" if "jpeg" not in ctype and "jpg" not in ctype else "jpg"
        if "webp" in ctype:
            ext = "webp"
        filename = f"img_gen_{int(time.time() * 1000)}.{ext}"
        (UPLOADS_DIR / filename).write_bytes(img_resp.content)
        print(f"[image_gen] 图片已保存: {filename}")
        return filename
    print("[image_gen] 响应中无 b64_json 或 url")
    return None


def _selfie_reference_path(source_identity: str = "") -> Path:
    """Return the SELFIE anchor by stable internal actor identity, not display name."""
    if str(source_identity or "").strip().lower() == "connor":
        return SECONDARY_REFERENCE_IMAGE_PATH
    return REFERENCE_IMAGE_PATH


async def generate_image(prompt: str, is_selfie: bool = False, source_identity: str = "") -> str | None:
    """
    调用 Gemini 生图模型生成图片，保存到 uploads 目录，返回文件名。
    is_selfie=True 时自动附带参考图。
    失败返回 None。
    """
    # ── 自定义中转站优先 ──
    relay = _relay_config()
    if relay:
        if is_selfie:
            reference_image_path = _selfie_reference_path(source_identity)
            if reference_image_path.exists():
                ref_bytes = reference_image_path.read_bytes()
                filename = await _generate_via_relay_edits(prompt, ref_bytes, "image/jpeg", relay)
                if filename:
                    return filename
                print("[image_gen] 中转站锁脸失败，回退 Gemini")
            else:
                print(f"[image_gen] 参考图不存在: {reference_image_path}，降级为 DRAW")
        else:
            filename = await _generate_via_relay_generations(prompt, relay)
            if filename:
                return filename
            print("[image_gen] 中转站生图失败，回退 Gemini")

    api_key = get_key("gemini")
    if not api_key:
        print("[image_gen] 没有 Gemini API Key，无法生图")
        return None

    # 构建请求内容
    parts = [{"text": prompt}]

    # SELFIE 模式：附带参考图
    if is_selfie:
        reference_image_path = _selfie_reference_path(source_identity)
        if reference_image_path.exists():
            ref_bytes = reference_image_path.read_bytes()
            ref_b64 = base64.b64encode(ref_bytes).decode("utf-8")
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": ref_b64
                }
            })
            print(f"[image_gen] SELFIE 模式，已附带参考图: {reference_image_path}")
        else:
            print(f"[image_gen] 参考图不存在: {reference_image_path}，降级为 DRAW 模式")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGE_GEN_MODEL}:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=IMAGE_GEN_TIMEOUT) as client:
            print(f"[image_gen] 开始生图... prompt: {prompt[:80]}")
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            # 解析响应，提取图片
            candidates = data.get("candidates", [])
            if not candidates:
                error_msg = data.get("error", {}).get("message", "未知错误")
                print(f"[image_gen] API 返回空 candidates: {error_msg}")
                return None

            content_parts = candidates[0].get("content", {}).get("parts", [])
            image_data = None
            mime_type = "image/png"

            for part in content_parts:
                inline = part.get("inlineData")
                if inline and inline.get("mimeType", "").startswith("image/"):
                    image_data = inline["data"]
                    mime_type = inline["mimeType"]
                    break

            if not image_data:
                print("[image_gen] 响应中未找到图片数据")
                return None

            # 确定文件扩展名
            ext = "png"
            if "jpeg" in mime_type or "jpg" in mime_type:
                ext = "jpg"
            elif "webp" in mime_type:
                ext = "webp"

            # 保存图片
            filename = f"img_gen_{int(time.time() * 1000)}.{ext}"
            filepath = UPLOADS_DIR / filename
            filepath.write_bytes(base64.b64decode(image_data))
            print(f"[image_gen] 图片已保存: {filepath}")
            return filename

    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:500] if e.response else ""
        print(f"[image_gen] API 请求失败 ({e.response.status_code}): {error_body}")
        return None
    except Exception as e:
        print(f"[image_gen] 生图异常: {e}")
        return None
