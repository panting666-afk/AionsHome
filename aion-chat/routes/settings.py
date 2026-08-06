"""
设置、世界书、模型列表、TTS 路由
"""

import io
import json
import shutil
import time as _time
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

import httpx
from PIL import Image

from config import SETTINGS, save_settings, get_key, get_sentinel_config, load_worldbook, save_worldbook, load_chat_status, TTS_CACHE_DIR, TTS_CACHE_MAX_BYTES, THEATER_TTS_CACHE_DIR, normalize_custom_model_routes, refresh_custom_models, iter_visible_models
from config import PUBLIC_DIR, DATA_DIR, ALLOWED_TYPES
from tts import cleanup_tts_cache_dir
from ws import manager

router = APIRouter()

RELAY_MODEL_PROVIDERS = {"aipro", "custom_openai"}

# ── 模型列表 ──────────────────────────────────────
@router.get("/api/models")
async def list_models():
    rows = [
        {
            "key": k,
            "provider": v["provider"],
            "custom": v.get("provider") == "custom_openai",
            "route_name": v.get("route_name", ""),
        }
        for k, v in iter_visible_models()
    ]
    return sorted(rows, key=lambda item: 1 if item["provider"] in RELAY_MODEL_PROVIDERS else 0)

# ── 设置 ──────────────────────────────────────────
class SettingsUpdate(BaseModel):
    gemini_key: Optional[str] = None
    siliconflow_key: Optional[str] = None
    gemini_free_key: Optional[str] = None
    aipro_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    netease_music_u: Optional[str] = None
    sentinel_base_url: Optional[str] = None
    sentinel_api_key: Optional[str] = None
    sentinel_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_model: Optional[str] = None
    luckin_mcp_enabled: Optional[bool] = None
    luckin_mcp_token: Optional[str] = None
    luckin_default_longitude: Optional[str] = None
    luckin_default_latitude: Optional[str] = None
    luckin_default_shop_keyword: Optional[str] = None
    custom_model_routes: Optional[list[Dict[str, Any]]] = None

class HomeLayoutUpdate(BaseModel):
    version: Optional[int] = 2
    positions: Dict[str, Any] = Field(default_factory=dict)

def _normalize_home_layout(payload: Any) -> Dict[str, Any]:
    positions = payload.get("positions", {}) if isinstance(payload, dict) else {}
    normalized: Dict[str, int] = {}
    if isinstance(positions, dict):
        for app_id, cell in positions.items():
            if not isinstance(app_id, str):
                continue
            try:
                cell_index = int(cell)
            except (TypeError, ValueError):
                continue
            if 0 <= cell_index <= 4095:
                normalized[app_id] = cell_index
    return {"version": 2, "positions": normalized}

@router.get("/api/home/layout")
async def get_home_layout():
    return _normalize_home_layout(SETTINGS.get("home_layout", {}))

@router.put("/api/home/layout")
async def update_home_layout(body: HomeLayoutUpdate):
    payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    layout = _normalize_home_layout(payload)
    SETTINGS["home_layout"] = layout
    save_settings(SETTINGS)
    return {"ok": True, "layout": layout}

@router.get("/api/settings")
async def get_settings():
    def mask(k):
        if not k or len(k) < 8:
            return k
        return k[:4] + "*" * (len(k) - 8) + k[-4:]
    return {
        "gemini_key": SETTINGS.get("gemini_key", ""),
        "siliconflow_key": SETTINGS.get("siliconflow_key", ""),
        "gemini_free_key": SETTINGS.get("gemini_free_key", ""),
        "aipro_key": SETTINGS.get("aipro_key", ""),
        "tavily_api_key": SETTINGS.get("tavily_api_key", ""),
        "netease_music_u": SETTINGS.get("netease_music_u", ""),
        "sentinel_base_url": SETTINGS.get("sentinel_base_url", ""),
        "sentinel_api_key": SETTINGS.get("sentinel_api_key", ""),
        "sentinel_model": SETTINGS.get("sentinel_model", ""),
        "embedding_base_url": SETTINGS.get("embedding_base_url", ""),
        "embedding_api_key": SETTINGS.get("embedding_api_key", ""),
        "embedding_model": SETTINGS.get("embedding_model", ""),
        "luckin_mcp_enabled": SETTINGS.get("luckin_mcp_enabled", False),
        "luckin_mcp_token": SETTINGS.get("luckin_mcp_token", ""),
        "luckin_default_longitude": SETTINGS.get("luckin_default_longitude", ""),
        "luckin_default_latitude": SETTINGS.get("luckin_default_latitude", ""),
        "luckin_default_shop_keyword": SETTINGS.get("luckin_default_shop_keyword", ""),
        "custom_model_routes": normalize_custom_model_routes(SETTINGS.get("custom_model_routes")),
        "gemini_key_masked": mask(SETTINGS.get("gemini_key", "")),
        "siliconflow_key_masked": mask(SETTINGS.get("siliconflow_key", "")),
        "gemini_free_key_masked": mask(SETTINGS.get("gemini_free_key", "")),
        "aipro_key_masked": mask(SETTINGS.get("aipro_key", "")),
        "tavily_api_key_masked": mask(SETTINGS.get("tavily_api_key", "")),
        "netease_music_u_masked": mask(SETTINGS.get("netease_music_u", "")),
        "sentinel_api_key_masked": mask(SETTINGS.get("sentinel_api_key", "")),
        "embedding_api_key_masked": mask(SETTINGS.get("embedding_api_key", "")),
    }

@router.put("/api/settings")
async def update_settings(body: SettingsUpdate):
    luckin_changed = False
    if body.gemini_key is not None:
        SETTINGS["gemini_key"] = body.gemini_key
    if body.siliconflow_key is not None:
        SETTINGS["siliconflow_key"] = body.siliconflow_key
    if body.gemini_free_key is not None:
        SETTINGS["gemini_free_key"] = body.gemini_free_key
    if body.aipro_key is not None:
        SETTINGS["aipro_key"] = body.aipro_key
    if body.tavily_api_key is not None:
        SETTINGS["tavily_api_key"] = body.tavily_api_key
    if body.sentinel_base_url is not None:
        SETTINGS["sentinel_base_url"] = body.sentinel_base_url
    if body.sentinel_api_key is not None:
        SETTINGS["sentinel_api_key"] = body.sentinel_api_key
    if body.sentinel_model is not None:
        SETTINGS["sentinel_model"] = body.sentinel_model
    if body.embedding_base_url is not None:
        SETTINGS["embedding_base_url"] = body.embedding_base_url
    if body.embedding_api_key is not None:
        SETTINGS["embedding_api_key"] = body.embedding_api_key
    if body.embedding_model is not None:
        SETTINGS["embedding_model"] = body.embedding_model
    if body.luckin_mcp_enabled is not None:
        luckin_changed = luckin_changed or SETTINGS.get("luckin_mcp_enabled") != body.luckin_mcp_enabled
        SETTINGS["luckin_mcp_enabled"] = body.luckin_mcp_enabled
    if body.luckin_mcp_token is not None:
        luckin_changed = luckin_changed or SETTINGS.get("luckin_mcp_token", "") != body.luckin_mcp_token
        SETTINGS["luckin_mcp_token"] = body.luckin_mcp_token
    if body.luckin_default_longitude is not None:
        SETTINGS["luckin_default_longitude"] = body.luckin_default_longitude
    if body.luckin_default_latitude is not None:
        SETTINGS["luckin_default_latitude"] = body.luckin_default_latitude
    if body.luckin_default_shop_keyword is not None:
        SETTINGS["luckin_default_shop_keyword"] = body.luckin_default_shop_keyword
    if body.custom_model_routes is not None:
        SETTINGS["custom_model_routes"] = normalize_custom_model_routes(body.custom_model_routes)
        refresh_custom_models()
    if body.netease_music_u is not None:
        old_mu = SETTINGS.get("netease_music_u", "")
        SETTINGS["netease_music_u"] = body.netease_music_u
        if body.netease_music_u != old_mu:
            # MUSIC_U 变更，重新登录 pyncm
            try:
                from music import reload_login
                reload_login()
            except Exception:
                pass
    save_settings(SETTINGS)
    if luckin_changed:
        try:
            from luckin import LUCKIN_SERVER_NAME
            from mcp_client import mcp_manager
            await mcp_manager.disconnect(LUCKIN_SERVER_NAME)
        except Exception:
            pass
    return {"ok": True}

# ── AI 发表情包开关 ─────────────────────────────
class AiStickersToggle(BaseModel):
    enabled: bool

@router.get("/api/settings/ai-stickers")
async def get_ai_stickers_setting():
    return {"enabled": SETTINGS.get("ai_stickers_enabled", True)}

@router.put("/api/settings/ai-stickers")
async def update_ai_stickers_setting(body: AiStickersToggle):
    SETTINGS["ai_stickers_enabled"] = bool(body.enabled)
    save_settings(SETTINGS)
    return {"ok": True, "enabled": bool(body.enabled)}

# ── 气泡主题（预设 + 自定义样式库）────────────────
BUBBLE_THEMES_ALLOWED = {"default", "pink", "blue", "mint", "purple", "sunset", "mono", "wechat"}
BUBBLE_STYLES_FILE = Path(DATA_DIR) / "bubble_styles.json"
MAX_CUSTOM_CSS_LEN = 20000

class BubbleThemeUpdate(BaseModel):
    theme: Optional[str] = None
    custom_css: Optional[str] = None

@router.get("/api/settings/bubble-theme")
async def get_bubble_theme():
    return {
        "theme": SETTINGS.get("bubble_theme", "default"),
        "custom_css": SETTINGS.get("custom_css", ""),
    }

@router.put("/api/settings/bubble-theme")
async def update_bubble_theme(body: BubbleThemeUpdate):
    if body.theme is not None:
        theme = body.theme if body.theme in BUBBLE_THEMES_ALLOWED else "default"
        SETTINGS["bubble_theme"] = theme
    if body.custom_css is not None:
        SETTINGS["custom_css"] = body.custom_css[:MAX_CUSTOM_CSS_LEN]
    save_settings(SETTINGS)
    return {
        "ok": True,
        "theme": SETTINGS.get("bubble_theme", "default"),
        "custom_css": SETTINGS.get("custom_css", ""),
    }


# ── 气泡样式库（多个已命名样式，随时切换）──────────
def _load_bubble_styles() -> dict:
    if BUBBLE_STYLES_FILE.exists():
        try:
            data = json.loads(BUBBLE_STYLES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "styles" in data:
                return data
        except Exception:
            pass
    # 迁移旧配置：bubble_theme + custom_css → 新样式库
    theme = SETTINGS.get("bubble_theme", "default")
    custom_css = (SETTINGS.get("custom_css") or "").strip()
    styles = []
    if custom_css:
        styles.append({"id": "user_custom", "name": "自定义样式", "css": custom_css, "created_at": _time.time()})
        active = theme if theme in BUBBLE_THEMES_ALLOWED else "user_custom"
    else:
        active = theme if theme in BUBBLE_THEMES_ALLOWED else "default"
    data = {"active": active, "styles": styles}
    BUBBLE_STYLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUBBLE_STYLES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _save_bubble_styles(data: dict) -> None:
    BUBBLE_STYLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUBBLE_STYLES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/api/bubble-styles")
async def get_bubble_styles():
    data = _load_bubble_styles()
    return {"active": data.get("active", "default"), "styles": data.get("styles", [])}


class BubbleStyleCreate(BaseModel):
    name: str = ""
    css: str = ""


@router.post("/api/bubble-styles")
async def create_bubble_style(body: BubbleStyleCreate):
    name = (body.name or "").strip()[:30]
    css = (body.css or "").strip()
    if not name or not css:
        raise HTTPException(400, "请填写样式名和 CSS")
    data = _load_bubble_styles()
    sid = f"style_{int(_time.time() * 1000)}"
    data.setdefault("styles", []).append({"id": sid, "name": name, "css": css[:MAX_CUSTOM_CSS_LEN], "created_at": _time.time()})
    _save_bubble_styles(data)
    return {"ok": True, "id": sid, "styles": data["styles"]}


class BubbleStyleActive(BaseModel):
    id: str = "default"


@router.put("/api/bubble-styles/active")
async def set_bubble_style_active(body: BubbleStyleActive):
    data = _load_bubble_styles()
    data["active"] = (body.id or "default")
    _save_bubble_styles(data)
    return {"ok": True, "active": data["active"]}


@router.put("/api/bubble-styles/{sid}")
async def update_bubble_style(sid: str, body: BubbleStyleCreate):
    data = _load_bubble_styles()
    for s in data.get("styles", []):
        if s["id"] == sid:
            if (body.name or "").strip():
                s["name"] = body.name.strip()[:30]
            if body.css is not None:
                s["css"] = (body.css or "").strip()[:MAX_CUSTOM_CSS_LEN]
            _save_bubble_styles(data)
            return {"ok": True, "styles": data["styles"]}
    raise HTTPException(404, "样式不存在")


@router.delete("/api/bubble-styles/{sid}")
async def delete_bubble_style(sid: str):
    data = _load_bubble_styles()
    data["styles"] = [s for s in data.get("styles", []) if s["id"] != sid]
    if data.get("active") == sid:
        data["active"] = "default"
    _save_bubble_styles(data)
    return {"ok": True, "styles": data["styles"], "active": data.get("active", "default")}


# ── 温度设置 ──────────────────────────────────────
class TempUpdate(BaseModel):
    temperature: float

@router.put("/api/settings/temperature")
async def update_temperature(body: TempUpdate):
    SETTINGS["temperature"] = body.temperature
    save_settings(SETTINGS)
    return {"ok": True}

# ── 视频通话开关 ──────────────────────────────────
@router.get("/api/settings/video-call")
async def get_video_call_setting():
    return {"video_call_enabled": SETTINGS.get("video_call_enabled", True)}

class VideoCallToggle(BaseModel):
    enabled: bool

@router.put("/api/settings/video-call")
async def update_video_call_setting(body: VideoCallToggle):
    SETTINGS["video_call_enabled"] = body.enabled
    save_settings(SETTINGS)
    return {"ok": True, "video_call_enabled": body.enabled}

# ── AI 生图开关 + 自定义中转站 ─────────────────────
@router.get("/api/settings/image-gen")
async def get_image_gen_setting():
    return {
        "image_gen_enabled": SETTINGS.get("image_gen_enabled", False),
        "image_gen_base_url": SETTINGS.get("image_gen_base_url", ""),
        "image_gen_api_key": SETTINGS.get("image_gen_api_key", ""),
        "image_gen_model": SETTINGS.get("image_gen_model", ""),
        "image_gen_size": SETTINGS.get("image_gen_size", "1024x1024"),
    }

class ImageGenUpdate(BaseModel):
    enabled: Optional[bool] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    size: Optional[str] = None

@router.get("/api/settings/image-gen/models")
async def image_gen_models(base_url: str = "", api_key: str = ""):
    """从配置的中转站拉取可用模型列表（OpenAI 兼容 /v1/models）。
    优先用请求参数（前端当前输入），否则用已保存的配置。"""
    base = (base_url or SETTINGS.get("image_gen_base_url") or "").strip().rstrip("/")
    key = (api_key or SETTINGS.get("image_gen_api_key") or "").strip()
    if not base:
        return {"models": []}
    if not base.endswith("/v1"):
        base = base + "/v1"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(f"{base}/models", headers=headers)
            if resp.status_code != 200:
                return {"models": []}
            data = resp.json()
            models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
            return {"models": models}
    except Exception:
        return {"models": []}


@router.get("/api/settings/custom-routes/models")
async def custom_route_models(base_url: str = "", api_key: str = ""):
    """从自定义主模型线路的中转站拉取可用模型列表（OpenAI 兼容 /v1/models）。
    优先用请求参数（前端当前输入），否则用已保存的配置。"""
    base = (base_url or "").strip().rstrip("/")
    key = (api_key or "").strip()
    if not base:
        return {"models": [], "error": "缺少 Base URL"}
    if not base.endswith("/v1"):
        base = base + "/v1"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(f"{base}/models", headers=headers)
            if resp.status_code != 200:
                return {"models": [], "error": f"HTTP {resp.status_code}"}
            data = resp.json()
            models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
            return {"models": sorted(set(models))}
    except Exception as e:
        return {"models": [], "error": str(e)}


@router.put("/api/settings/image-gen")
async def update_image_gen_setting(body: ImageGenUpdate):
    if body.enabled is not None:
        SETTINGS["image_gen_enabled"] = body.enabled
    if body.base_url is not None:
        SETTINGS["image_gen_base_url"] = body.base_url.strip()
    if body.api_key is not None:
        SETTINGS["image_gen_api_key"] = body.api_key.strip()
    if body.model is not None:
        SETTINGS["image_gen_model"] = body.model.strip()
    if body.size is not None:
        SETTINGS["image_gen_size"] = (body.size or "1024x1024").strip()
    save_settings(SETTINGS)
    return {
        "ok": True,
        "image_gen_enabled": SETTINGS.get("image_gen_enabled", False),
        "image_gen_base_url": SETTINGS.get("image_gen_base_url", ""),
        "image_gen_api_key": SETTINGS.get("image_gen_api_key", ""),
        "image_gen_model": SETTINGS.get("image_gen_model", ""),
        "image_gen_size": SETTINGS.get("image_gen_size", "1024x1024"),
    }

# ── CLI 工具调用开关（Gemini CLI / Antigravity CLI） ─────────────────
# ── AI song generation toggle ─────────────────────────────────
@router.get("/api/settings/song-gen")
async def get_song_gen_setting():
    return {"song_gen_enabled": SETTINGS.get("song_gen_enabled", False)}

class SongGenToggle(BaseModel):
    enabled: bool

@router.put("/api/settings/song-gen")
async def update_song_gen_setting(body: SongGenToggle):
    SETTINGS["song_gen_enabled"] = body.enabled
    save_settings(SETTINGS)
    return {"ok": True, "song_gen_enabled": body.enabled}

# ── 微信桥接设置 ─────────────────────────────────
class WeChatBridgeSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    transport: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_token: Optional[str] = None
    inbound_token: Optional[str] = None
    openclaw_home: Optional[str] = None
    context_stale_seconds: Optional[int] = None


class WeChatBridgeBindingCreate(BaseModel):
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    ttl_seconds: Optional[int] = None


@router.get("/api/settings/wechat-bridge")
async def get_wechat_bridge_setting():
    from wechat_bridge import public_wechat_bindings
    from wechat_mode import public_wechat_modes

    openclaw_accounts = []
    openclaw_status_error = ""
    try:
        from openclaw_weixin import summarize_accounts

        openclaw_accounts = summarize_accounts(SETTINGS.get("wechat_bridge_openclaw_home") or None)
    except Exception as exc:
        openclaw_status_error = str(exc)

    pending = SETTINGS.get("wechat_bridge_pending_bindings")
    if not isinstance(pending, dict):
        pending = {}
    return {
        "wechat_bridge_enabled": SETTINGS.get("wechat_bridge_enabled", False),
        "wechat_bridge_transport": SETTINGS.get("wechat_bridge_transport", "webhook"),
        "wechat_bridge_webhook_url": SETTINGS.get("wechat_bridge_webhook_url", ""),
        "wechat_bridge_webhook_token": SETTINGS.get("wechat_bridge_webhook_token", ""),
        "wechat_bridge_inbound_token": SETTINGS.get("wechat_bridge_inbound_token", ""),
        "wechat_bridge_openclaw_home": SETTINGS.get("wechat_bridge_openclaw_home", ""),
        "wechat_bridge_context_stale_seconds": SETTINGS.get("wechat_bridge_context_stale_seconds", 15 * 60),
        "wechat_bridge_last_send": SETTINGS.get("wechat_bridge_last_send"),
        "openclaw_accounts": openclaw_accounts,
        "openclaw_status_error": openclaw_status_error,
        "bindings": public_wechat_bindings(settings=SETTINGS),
        "modes": public_wechat_modes(SETTINGS),
        "pending_bindings": list(pending.values()),
    }


@router.put("/api/settings/wechat-bridge")
async def update_wechat_bridge_setting(body: WeChatBridgeSettingsUpdate):
    if body.enabled is not None:
        SETTINGS["wechat_bridge_enabled"] = bool(body.enabled)
    if body.transport is not None:
        transport = body.transport.strip().lower()
        if transport not in ("webhook", "openclaw"):
            raise HTTPException(status_code=400, detail="transport must be webhook or openclaw")
        SETTINGS["wechat_bridge_transport"] = transport
    if body.webhook_url is not None:
        SETTINGS["wechat_bridge_webhook_url"] = body.webhook_url.strip()
    if body.webhook_token is not None:
        SETTINGS["wechat_bridge_webhook_token"] = body.webhook_token.strip()
    if body.inbound_token is not None:
        SETTINGS["wechat_bridge_inbound_token"] = body.inbound_token.strip()
    if body.openclaw_home is not None:
        SETTINGS["wechat_bridge_openclaw_home"] = body.openclaw_home.strip()
    if body.context_stale_seconds is not None:
        SETTINGS["wechat_bridge_context_stale_seconds"] = max(60, int(body.context_stale_seconds))
    save_settings(SETTINGS)
    return {
        "ok": True,
        "wechat_bridge_enabled": SETTINGS.get("wechat_bridge_enabled", False),
        "wechat_bridge_transport": SETTINGS.get("wechat_bridge_transport", "webhook"),
        "wechat_bridge_webhook_url": SETTINGS.get("wechat_bridge_webhook_url", ""),
    }


@router.post("/api/settings/wechat-bridge/bindings")
async def create_wechat_bridge_binding(body: WeChatBridgeBindingCreate):
    from wechat_bridge import create_wechat_pending_binding, get_recorded_wechat_route

    route = get_recorded_wechat_route()
    source_type = (body.source_type or route.get("source_type") or "").strip()
    source_id = (body.source_id or route.get("source_id") or "").strip()
    if not source_type or not source_id:
        raise HTTPException(status_code=400, detail="source_type and source_id are required when no recent WeChat route exists")

    SETTINGS["wechat_bridge_enabled"] = True
    SETTINGS["wechat_bridge_transport"] = "openclaw"
    pending = create_wechat_pending_binding(
        source_type=source_type,
        source_id=source_id,
        ttl_seconds=body.ttl_seconds or 10 * 60,
        settings=SETTINGS,
    )
    save_settings(SETTINGS)
    return {
        "ok": True,
        "code": pending["code"],
        "source_type": pending["source_type"],
        "source_id": pending["source_id"],
        "expires_at": pending["expires_at"],
        "instruction": f"Send this in WeChat: bind {pending['code']}",
    }

@router.get("/api/settings/gemini-cli-tools")
async def get_gemini_cli_tools_setting():
    return {"gemini_cli_tools_enabled": SETTINGS.get("gemini_cli_tools_enabled", False)}

class GeminiCliToolsToggle(BaseModel):
    enabled: bool

@router.put("/api/settings/gemini-cli-tools")
async def update_gemini_cli_tools_setting(body: GeminiCliToolsToggle):
    SETTINGS["gemini_cli_tools_enabled"] = body.enabled
    save_settings(SETTINGS)
    return {"ok": True, "gemini_cli_tools_enabled": body.enabled}

# ── 桌宠开关 ──────────────────────────────────────
@router.get("/api/settings/pet")
async def get_pet_setting():
    return {"pet_enabled": SETTINGS.get("pet_enabled", False)}

class PetToggle(BaseModel):
    enabled: bool

@router.put("/api/settings/pet")
async def update_pet_setting(body: PetToggle):
    SETTINGS["pet_enabled"] = body.enabled
    save_settings(SETTINGS)
    return {"ok": True, "pet_enabled": body.enabled}

# ── 健康数据分享开关 ──────────────────────────────
@router.get("/api/settings/health-share")
async def get_health_share_setting():
    return {"health_share_enabled": SETTINGS.get("health_share_enabled", False)}

class HealthShareToggle(BaseModel):
    enabled: bool

@router.put("/api/settings/health-share")
async def update_health_share_setting(body: HealthShareToggle):
    SETTINGS["health_share_enabled"] = body.enabled
    save_settings(SETTINGS)
    await manager.broadcast({
        "type": "health_share_changed",
        "data": {"health_share_enabled": body.enabled},
    })
    await manager.broadcast({
        "type": "capability_config_changed",
        "data": {"key": "health_context", "enabled": body.enabled},
    })
    return {"ok": True, "health_share_enabled": body.enabled}

# ── 世界书 ────────────────────────────────────────
class WorldBookUpdate(BaseModel):
    ai_persona: str = ""
    user_persona: str = ""
    system_prompt: str = ""
    system_prompt_enabled: bool = True
    ai_name: str = "AI"
    user_name: str = "你"
    persona_schema_version: int = 1
    ai_persona_sections: Dict[str, str] = Field(default_factory=dict)
    user_persona_sections: Dict[str, str] = Field(default_factory=dict)
    creative_rules: str = ""
    persona_section_locks: Dict[str, Any] = Field(default_factory=dict)
    persona_evolution_enabled: bool = False

@router.get("/api/worldbook")
async def get_worldbook():
    return load_worldbook()

@router.put("/api/worldbook")
async def update_worldbook(body: WorldBookUpdate):
    current = load_worldbook()
    payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    current.update(payload)
    save_worldbook(current)
    return {"ok": True}

# ── 聊天状态 ──────────────────────────────────────
@router.get("/api/chat_status")
async def get_chat_status_api():
    return load_chat_status()

# ── TTS 语音合成 ──────────────────────────────────
class TTSRequest(BaseModel):
    text: str
    voice: str = ""
    msg_id: Optional[str] = None

@router.post("/api/tts")
async def tts_synthesize(body: TTSRequest):
    key = get_key("siliconflow")
    if not key:
        return Response(content=json.dumps({"error": "未配置硅基流动 API Key"}), status_code=400, media_type="application/json")
    if not body.text.strip():
        return Response(content=json.dumps({"error": "文本不能为空"}), status_code=400, media_type="application/json")
    if not body.voice:
        return Response(content=json.dumps({"error": "未选择语音"}), status_code=400, media_type="application/json")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.siliconflow.cn/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "FunAudioLLM/CosyVoice2-0.5B",
                    "input": body.text.strip(),
                    "voice": body.voice,
                    "response_format": "mp3",
                    "speed": 1.0,
                    "gain": 0
                }
            )
        if resp.status_code != 200:
            return Response(content=json.dumps({"error": f"TTS API 错误: {resp.status_code}"}), status_code=502, media_type="application/json")
        audio_data = resp.content
        # 如果提供了 msg_id，将音频缓存到服务器
        if body.msg_id:
            import re
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '', body.msg_id)
            if safe_id:
                cache_path = TTS_CACHE_DIR / f"{safe_id}.mp3"
                cache_path.write_bytes(audio_data)
                cleanup_tts_cache_dir(TTS_CACHE_DIR, TTS_CACHE_MAX_BYTES, skip={cache_path})
        return Response(content=audio_data, media_type="audio/mpeg")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}), status_code=500, media_type="application/json")

@router.head("/api/tts/audio/{msg_id}")
@router.get("/api/tts/audio/{msg_id}")
async def tts_audio(msg_id: str):
    import re
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '', msg_id)
    if not safe_id:
        return Response(status_code=404)
    cache_path = TTS_CACHE_DIR / f"{safe_id}.mp3"
    if not cache_path.exists():
        return Response(status_code=404)
    return FileResponse(cache_path, media_type="audio/mpeg", filename=f"{safe_id}.mp3")

@router.head("/api/theater/tts/audio/{msg_id}")
@router.get("/api/theater/tts/audio/{msg_id}")
async def theater_tts_audio(msg_id: str):
    import re
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '', msg_id)
    if not safe_id:
        return Response(status_code=404)
    cache_path = THEATER_TTS_CACHE_DIR / f"{safe_id}.mp3"
    if not cache_path.exists():
        return Response(status_code=404)
    return FileResponse(cache_path, media_type="audio/mpeg", filename=f"{safe_id}.mp3")

@router.get("/api/tts/voices")
async def tts_voice_list():
    key = get_key("siliconflow")
    if not key:
        return {"voices": [], "error": "未配置硅基流动 API Key"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.siliconflow.cn/v1/audio/voice/list",
                headers={"Authorization": f"Bearer {key}"}
            )
        if resp.status_code != 200:
            return {"voices": [], "error": "获取音色列表失败"}
        data = resp.json()
        voices = data.get("result") or data.get("voices") or data.get("data") or []
        return {"voices": voices}
    except Exception as e:
        return {"voices": [], "error": str(e)}


# ── 外观定制：头像 / 图标 / 背景图 ─────────────────
# 上传即覆盖 public/ 里的固定文件名 → 前端所有硬编码引用零改动，全部立即生效。
# 原图首次覆盖前自动备份到 data/appearance_originals/，支持一键恢复默认。
_ORIGINALS_DIR = DATA_DIR / "appearance_originals"
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

ASSET_SPECS = {
    "user_avatar": {
        "label": "你的头像",
        "outputs": [("UserIcon.png", "png", None, None)],
    },
    "ai_avatar": {
        "label": "AI 头像",
        "outputs": [("AIIcon.png", "png", None, None)],
    },
    "app_icon": {
        "label": "App 图标",
        "square": True,
        "outputs": [
            ("icon.png", "png", 512, None),
            ("icon-512.png", "png", 512, None),
            ("icon-192.png", "png", 192, None),
        ],
    },
    "chat_bg_dark": {
        "label": "聊天·黑夜背景",
        "outputs": [("chat-bg-dark.jpg", "jpeg", None, 85)],
    },
    "chat_bg_light": {
        "label": "聊天·白天背景",
        "outputs": [("chat-bg-light.jpg", "jpeg", None, 85)],
    },
    "chatroom_bg_dark": {
        "label": "聊天室·黑夜背景",
        "outputs": [("chatroom-bg-dark.jpg", "jpeg", None, 85)],
    },
    "chatroom_bg_light": {
        "label": "聊天室·白天背景",
        "outputs": [("chatroom-bg-light.jpg", "jpeg", None, 85)],
    },
    "home_bg_dark": {
        "label": "首页·黑夜背景",
        "outputs": [("BackGroundN.png", "png", None, None)],
    },
    "home_bg_light": {
        "label": "首页·白天背景",
        "outputs": [("BackGround.png", "png", None, None)],
    },
    "video_call_avatar": {
        "label": "视频来电头像",
        "outputs": [("视频来电头像.jpg", "jpeg", None, 88)],
    },
}


# 首页 App 图标（与 static/home.html 的 APPS 数组保持一致，新增首页 App 时需同步）
HOME_ICON_FILES = {
    "chat":            ("聊天",     "funIcon_0005_聊天.png"),
    "chatroom":        ("聊天室",   "funIcon_0020_聊天室.png"),
    "memory":          ("记忆库",   "funIcon_0006_日记本.png"),
    "moments":         ("朋友圈",   "funIcon_0010_朋友圈.png"),
    "xhs-lite":        ("小红书",   "funIcon_0024_小红书.png"),
    "wishes":          ("许愿池",   "funIcon_0023_许愿池.png"),
    "worldbook":       ("世界书",   "funIcon_0007_世界书.png"),
    "theater":         ("小剧场",   "funIcon_0009_小剧场.png"),
    "dateTheater":     ("去约会",   "funIcon_0026_去约会.png"),
    "whisper":         ("密语时刻", "funIcon_0011_密语时刻.png"),
    "alarm":           ("闹钟",     "funIcon_0012_闹钟.png"),
    "settings":        ("设置",     "funIcon_0008_设置.png"),
    "capabilities":    ("工具与能力", "funIcon_0025_工具能力.png"),
    "app-supervision": ("监管",     "funIcon_0027_监管.png"),
    "camera":          ("监控摄像头", "funIcon_0014_监控.png"),
    "logs":            ("监控日志", "funIcon_0015_监控日志.png"),
    "location":        ("定位追踪", "funIcon_0013_地图.png"),
    "activity":        ("活动日志", "funIcon_0000_备忘录.png"),
    "health":          ("健康",     "funIcon_0003_健康心.png"),
    "reading":         ("陪伴阅读", "funIcon_0016_陪伴阅读.png"),
    "ghost-forest":    ("奥罗斯幽林", "funIcon_0017_奥罗斯幽林.png"),
    "gift":            ("爱的印记", "funIcon_0018_爱的印记.png"),
    "fund":            ("奥罗斯财团", "funIcon_0019_奥罗斯财团.png"),
    "playground":      ("娱乐室",   "funIcon_0019_娱乐室.png"),
    "doudizhu":        ("斗地主",   "funIcon_0021_斗地主.png"),
    "seeky":           ("Seeky",    "funIcon_0022_Seeky.png"),
}
for _aid, (_label, _fname) in HOME_ICON_FILES.items():
    ASSET_SPECS[f"home_icon_{_aid}"] = {
        "label": f"首页·{_label}",
        "square": True,
        "outputs": [(_fname, "png", None, None)],
    }


def _appearance_preview_url(asset_type: str) -> str:
    spec = ASSET_SPECS.get(asset_type)
    preview_file = spec["outputs"][0][0] if spec else ""
    return f"/public/{preview_file}?v={int(_time.time() * 1000)}"


def _load_appearance_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    return img


def _ensure_chatroom_bg_defaults() -> None:
    """聊天室背景文件不存在时，用聊天背景初始化一份（保持原外观）。"""
    for dark in (True, False):
        src = PUBLIC_DIR / ("chat-bg-dark.jpg" if dark else "chat-bg-light.jpg")
        dst = PUBLIC_DIR / ("chatroom-bg-dark.jpg" if dark else "chatroom-bg-light.jpg")
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
                print(f"[appearance] 已初始化聊天室背景: {dst.name}")
            except OSError:
                pass


_ensure_chatroom_bg_defaults()


def _save_appearance_output(
    img: Image.Image, path: Path, fmt: str,
    size: int | None, quality: int | None, square: bool,
):
    work = img
    if square:
        # 图标类：先中心裁剪为正方形，避免变形
        w, h = work.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        work = work.crop((left, top, left + side, top + side))
    if size:
        work = work.resize((size, size), Image.LANCZOS)
    save_kwargs: dict = {}
    if fmt == "png":
        save_kwargs["optimize"] = True
    else:  # jpeg：不支持透明，先铺白底再转 RGB
        if work.mode == "RGBA":
            bg = Image.new("RGBA", work.size, (255, 255, 255, 255))
            bg.alpha_composite(work)
            work = bg
        work = work.convert("RGB")
        save_kwargs["quality"] = quality or 85
    path.parent.mkdir(parents=True, exist_ok=True)
    work.save(path, format=fmt, **save_kwargs)


def _backup_appearance_originals(spec: dict) -> list[str]:
    """首次覆盖前把 public/ 里现有文件备份一份到 data/appearance_originals/。"""
    _ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
    backed: list[str] = []
    for (name, *_rest) in spec["outputs"]:
        src = PUBLIC_DIR / name
        if not src.exists():
            continue
        dst = _ORIGINALS_DIR / name
        if dst.exists():
            continue
        try:
            shutil.copy2(src, dst)
            backed.append(name)
        except OSError:
            pass
    return backed


@router.post("/api/settings/appearance/{asset_type}")
async def upload_appearance(asset_type: str, file: UploadFile = File(...)):
    spec = ASSET_SPECS.get(asset_type)
    if not spec:
        raise HTTPException(status_code=400, detail=f"未知的资产类型: {asset_type}")
    base_type = (file.content_type or "").split(";")[0].strip()
    if not base_type.startswith("image/") or base_type not in ALLOWED_TYPES:
        return {"ok": False, "error": f"不支持的文件类型: {file.content_type}"}
    content = await file.read()
    if not content:
        return {"ok": False, "error": "文件为空"}
    if len(content) > _MAX_UPLOAD_BYTES:
        return {"ok": False, "error": "图片太大，最大 20MB"}
    try:
        img = _load_appearance_image(content)
    except Exception:
        return {"ok": False, "error": "无法解析图片，请换一张图片"}
    _backup_appearance_originals(spec)
    square = bool(spec.get("square"))
    try:
        for (name, fmt, size, quality) in spec["outputs"]:
            _save_appearance_output(img, PUBLIC_DIR / name, fmt, size, quality, square)
    except Exception as exc:
        return {"ok": False, "error": f"保存图片失败：{exc}"}
    return {
        "ok": True,
        "label": spec["label"],
        "preview_url": _appearance_preview_url(asset_type),
    }


@router.post("/api/settings/appearance/{asset_type}/reset")
async def reset_appearance(asset_type: str):
    spec = ASSET_SPECS.get(asset_type)
    if not spec:
        raise HTTPException(status_code=400, detail=f"未知的资产类型: {asset_type}")
    restored = 0
    for (name, *_rest) in spec["outputs"]:
        src = _ORIGINALS_DIR / name
        dst = PUBLIC_DIR / name
        if src.exists():
            try:
                shutil.copy2(src, dst)
                restored += 1
            except OSError:
                pass
    if not restored:
        return {"ok": False, "error": "没有找到原始图片备份，无法恢复默认。"}
    return {
        "ok": True,
        "label": spec["label"],
        "restored": restored,
        "preview_url": _appearance_preview_url(asset_type),
    }


# ── 锁脸生图参考图上传 ────────────────────────────
_FACE_ANCHOR_PATH = PUBLIC_DIR / "生图锚点.jpg"
_FACE_ANCHOR_MAX_SIDE = 1024

@router.post("/api/settings/face-anchor")
async def upload_face_anchor(file: UploadFile = File(...)):
    base_type = (file.content_type or "").split(";")[0].strip()
    if not base_type.startswith("image/") or base_type not in ALLOWED_TYPES:
        return {"ok": False, "error": f"不支持的文件类型: {file.content_type}"}
    try:
        raw = await file.read()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        return {"ok": False, "error": "无法解析图片文件"}
    # 备份原图
    _ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
    backup = _ORIGINALS_DIR / "生图锚点.jpg"
    if _FACE_ANCHOR_PATH.exists() and not backup.exists():
        try:
            shutil.copy2(_FACE_ANCHOR_PATH, backup)
        except OSError:
            pass
    # 处理：保留完整画面，最长边压到 1024，转 JPEG
    work = img.convert("RGB")
    w, h = work.size
    if max(w, h) > _FACE_ANCHOR_MAX_SIDE:
        scale = _FACE_ANCHOR_MAX_SIDE / max(w, h)
        work = work.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    _FACE_ANCHOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    work.save(_FACE_ANCHOR_PATH, format="jpeg", quality=90)
    print(f"[face-anchor] 锁脸参考图已更新: {_FACE_ANCHOR_PATH}")
    return {
        "ok": True,
        "label": "锁脸参考图",
        "preview_url": f"/public/生图锚点.jpg?v={int(_time.time() * 1000)}",
    }
