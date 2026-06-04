"""能力 / 可选依赖管理 API 子门面（mixin，见 ../ARCHITECTURE.md §7 与 api.README.md）。

把「系统能力查询 + 一键安装/重检可选依赖」从巨型业务门面中分离：单一职责、便于阅读。
`KnowledgeRepositoryApi` 通过组合本 mixin 暴露这些方法；运行时依赖（如 self._config）由
`KnowledgeRepositoryApi.__init__` 注入，本 mixin 自身不持状态、不创建依赖。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.capabilities import dependency_statuses, detect_capabilities, resolve_install_spec

if TYPE_CHECKING:  # 仅类型提示：实际实例属性由组合类的 __init__ 注入。
    from core.config import Config

logger = logging.getLogger("KnowledgeRepositoryApi")


class CapabilitiesApiMixin:
    """系统能力查询与可选依赖安装/重检；组合进 KnowledgeRepositoryApi 使用。"""

    _config: Config | None

    def get_capabilities(self) -> dict[str, Any]:
        """数据流各环节状态 + 可选依赖安装状态 + 诊断，供向导页渲染（取代前端字符串匹配）。"""
        if self._config is None:
            raise NotImplementedError("get_capabilities: config unavailable")
        return detect_capabilities(self._config)

    def list_dependencies(self) -> list[dict[str, Any]]:
        """列出可选依赖及其安装/版本状态，供依赖管理面板渲染。"""
        return dependency_statuses()

    def recheck_dependencies(self) -> dict[str, Any]:
        """清除 import 缓存后重新探测，返回最新能力 + 依赖状态（新装包无需重启即可被检出）。"""
        import importlib

        importlib.invalidate_caches()
        if self._config is None:
            return {"dependencies": dependency_statuses()}
        return detect_capabilities(self._config)

    async def install_dependency(self, package: str) -> dict[str, Any]:
        """一键安装清单内的可选依赖；输出实时写入日志缓冲，终端日志页可见。

        package 可为依赖 key（如 "milvus"）或白名单内 pip 规格；非白名单一律拒绝（防注入）。
        运行时已构造的 embedding/vector 单例不会热加载，故安装成功返回 restart_required=True。
        Docker 部署下容器重建可能丢失，建议写入镜像或挂载卷（前端会提示）。
        """
        spec = resolve_install_spec(package)  # 命中白名单，否则抛 ValueError
        return await self._run_pip_install(spec)

    async def _run_pip_install(self, spec: str) -> dict[str, Any]:
        """以 `sys.executable -m pip install <spec>` 安装，逐行把输出转发到 logger。"""
        import sys

        logger.info("Installing optional dependency: %s", spec)
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                spec,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as exc:  # 子进程都拉不起来（极少见）
            logger.error("Failed to launch pip for %s: %s", spec, exc)
            return {"status": "error", "package": spec, "message": str(exc)}

        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if line:
                logger.info("[pip] %s", line)
        returncode = await proc.wait()
        ok = returncode == 0
        if ok:
            logger.info("pip install succeeded: %s (restart plugin to load)", spec)
        else:
            logger.error("pip install failed (exit %s): %s", returncode, spec)
        return {
            "status": "ok" if ok else "error",
            "package": spec,
            "returncode": returncode,
            "restart_required": ok,
            "message": (
                "已安装，需重启插件生效（Docker 部署请注意依赖持久化）"
                if ok
                else f"安装失败，退出码 {returncode}，详见终端日志"
            ),
        }


__all__ = ["CapabilitiesApiMixin"]
