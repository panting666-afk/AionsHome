"""Web Push（PWA 系统级推送）：VAPID 密钥 + 订阅存储 + 发送"""
import base64
import json
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from config import DATA_DIR

router = APIRouter()

VAPID_FILE = Path(DATA_DIR) / "vapid_keys.json"
SUB_FILE = Path(DATA_DIR) / "push_subscriptions.json"
VAPID_SUBJECT = "mailto:aion@example.com"


# ── VAPID 密钥 ────────────────────────────────────
def _private_raw_b64_from_pem(pem: str) -> str:
    """PEM 私钥 → 原始 32 字节私钥（base64url），pywebpush 只认这个格式。"""
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _load_keys() -> dict:
    if VAPID_FILE.exists():
        try:
            data = json.loads(VAPID_FILE.read_text(encoding="utf-8"))
            if data.get("private_pem") and data.get("application_server_key"):
                if not data.get("private_raw_b64"):
                    data["private_raw_b64"] = _private_raw_b64_from_pem(data["private_pem"])
                    VAPID_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                return data
        except Exception:
            pass
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    private_key = ec.generate_private_key(ec.SECP256R1())
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    # applicationServerKey：未压缩公钥点 → URL-safe base64（无填充）
    pub_point = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    app_key = base64.urlsafe_b64encode(pub_point).decode().rstrip("=")
    raw_b64 = _private_raw_b64_from_pem(priv_pem)
    data = {
        "private_pem": priv_pem,
        "public_pem": pub_pem,
        "application_server_key": app_key,
        "private_raw_b64": raw_b64,
    }
    VAPID_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


# ── 订阅存储 ──────────────────────────────────────
def _load_subs() -> list:
    if SUB_FILE.exists():
        try:
            data = json.loads(SUB_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_subs(subs: list) -> None:
    SUB_FILE.write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 发送 ──────────────────────────────────────────
def send_web_push(title: str, body: str, data: dict | None = None, timeout: float = 8.0) -> int:
    """给所有已订阅设备推送一条通知，返回成功发送数。"""
    keys = _load_keys()
    subs = _load_subs()
    if not subs:
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except Exception as e:
        print(f"[push] pywebpush 不可用，推送已跳过（请确认已安装 pywebpush）：{e}")
        return 0
    payload = json.dumps({"title": title, "body": body, "data": data or {}}, ensure_ascii=False)
    vapid_key = keys.get("private_raw_b64") or keys.get("private_pem")
    sent = 0
    stale = []
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=vapid_key,
                vapid_claims={"sub": VAPID_SUBJECT},
                timeout=timeout,
            )
            sent += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                stale.append(sub)
            else:
                print(f"[push] 发送失败（{e.response.status_code if e.response else e.errno}）: {str(e)[:200]}")
        except Exception as e:
            print(f"[push] 发送异常: {str(e)[:200]}")
    if stale:
        _save_subs([s for s in subs if s not in stale])
    return sent


def send_web_push_async(title: str, body: str, data: dict | None = None):
    """异步调用版本：不阻塞主流程"""
    import asyncio
    try:
        asyncio.get_running_loop().run_in_executor(None, send_web_push, title, body, data)
    except Exception:
        pass


# ── API ───────────────────────────────────────────
class PushSubscribe(BaseModel):
    endpoint: str
    keys: Dict[str, str] = Field(default_factory=dict)
    expirationTime: Optional[float] = None


@router.get("/api/push/vapid-public-key")
async def vapid_public_key():
    keys = _load_keys()
    return {"key": keys["application_server_key"]}


@router.post("/api/push/subscribe")
async def subscribe(body: PushSubscribe):
    print(f"[push] 收到订阅请求: {str(body.endpoint)[:80]}")
    sub = {
        "endpoint": body.endpoint,
        "keys": body.keys,
        "expirationTime": body.expirationTime,
    }
    subs = _load_subs()
    subs = [s for s in subs if s.get("endpoint") != body.endpoint]
    subs.append(sub)
    _save_subs(subs)
    return {"ok": True, "count": len(subs)}


@router.post("/api/push/unsubscribe")
async def unsubscribe(body: PushSubscribe):
    subs = _load_subs()
    subs = [s for s in subs if s.get("endpoint") != body.endpoint]
    _save_subs(subs)
    return {"ok": True, "count": len(subs)}


@router.post("/api/push/test")
async def test_push():
    n = send_web_push("🔔 测试推送", "如果能看到这条，说明 Web Push 成功了！", {"url": "/chat"})
    return {"ok": True, "sent": n, "subs": len(_load_subs())}
