"""Zotero 本地 API 连接/状态探测（仅状态用途，非主镜像源）。

本地 pull 的主路径是只读 zotero.sqlite（见 sqlite_reader）；本模块只用 localhost:23119
做「Zotero 是否在运行」的轻量探测，供前端展示连接状态。不依赖第三方库。
"""
from __future__ import annotations

import urllib.error
import urllib.request

DEFAULT_PORT = 23119


def probe_connection(port: int = DEFAULT_PORT, timeout: float = 1.0) -> dict[str, object]:
    """探测本地 Zotero API 是否可达。返回 {connected, port, detail}。

    最佳努力：连接失败/超时均视为未连接（不抛异常），因为 Zotero 未运行属正常情形。
    """
    url = f"http://localhost:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (本地回环)
            return {"connected": True, "port": port, "detail": f"HTTP {resp.status}"}
    except urllib.error.HTTPError as exc:
        # 有响应（即使 4xx/404）说明 Zotero 本地服务在监听。
        return {"connected": True, "port": port, "detail": f"HTTP {exc.code}"}
    except Exception as exc:  # 连接被拒/超时/DNS：视为未连接。
        return {"connected": False, "port": port, "detail": str(exc)}


__all__ = ["DEFAULT_PORT", "probe_connection"]
