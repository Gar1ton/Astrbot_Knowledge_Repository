"""repository 支撑：保留 Lite 服务所有者，避免依赖重导入丢失释放入口。"""
from __future__ import annotations

import logging
import threading
from typing import Any


class _StartupFailureCapture(logging.Handler):
    """SDK 将启动异常写入日志后返回 None；仅捕获本开库线程的异常。"""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._thread_id = threading.get_ident()
        self.failure: BaseException | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread == self._thread_id and record.exc_info:
            self.failure = record.exc_info[1]


class MilvusLiteService:
    """惰性获取并保留实际启动服务的管理器；关闭仅释放本库。

    AstrBot 可替换 sys.modules 中的依赖，但旧管理器仍通过 atexit 持有服务。
    开库与释放必须使用同一管理器对象，不能在关闭时重新导入当前单例。
    构造客户端失败也保留释放入口；本类不删除库、集合或 LOCK 文件。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._manager: Any = None

    def open_client(self) -> Any:
        """先启动本管理器的服务再建 RPC 客户端，失败保留底层异常与释放入口。"""
        from pymilvus import MilvusClient

        if self._manager is None:
            from milvus_lite.server_manager import server_manager_instance

            self._manager = server_manager_instance

        capture = _StartupFailureCapture()
        sdk_logger = logging.getLogger("milvus_lite.server_manager")
        sdk_logger.addHandler(capture)
        try:
            uri = self._manager.start_and_get_uri(self._db_path)
        finally:
            sdk_logger.removeHandler(capture)
            capture.close()
        if uri is None:
            failure = capture.failure
            detail = f": {type(failure).__name__}: {failure}" if failure else ""
            raise RuntimeError(f"Open local milvus failed{detail}") from failure
        return MilvusClient(uri)

    def release(self) -> None:
        """释放本库服务；从未尝试开库时无副作用，不影响其他路径。"""
        if self._manager is not None:
            self._manager.release_server(self._db_path)


__all__ = ["MilvusLiteService"]
