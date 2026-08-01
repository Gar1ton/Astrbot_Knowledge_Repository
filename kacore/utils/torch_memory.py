"""torch 加速器显存的读取与释放（utils 层·无业务规则）。

为何存在：embedding 与 rerank 两条本地模型链路都需要「卸载后真正把显存还给驱动」和
「读一眼当前占用」，此前这两段代码各写各的——`reranker/bge_local.py` 里有唯一一份
`empty_cache()`，`embedding/local.py` 只有一份仅用于日志的 `torch` 诊断，且卸载路径压根
不释放显存。两处收敛到这里。

契约：torch 未安装、无 CUDA、驱动异常等一切情况都**不抛异常**——本模块只服务于可观测性
与尽力而为的资源回收，绝不能因为读不到显存就打断一次正常的检索。
"""
from __future__ import annotations

import gc
from typing import Any

__all__ = ["accelerator_snapshot", "release_accelerator_cache"]


def release_accelerator_cache() -> None:
    """回收 Python 引用并清空 CUDA 缓存分配器。

    只 `del` 模型引用不足以让 `nvidia-smi` 的占用回落——torch 的缓存分配器会把显存留在
    自己的池子里。手动卸载的意义正在于把这块让给同时运行的本地大模型，故必须 empty_cache。
    """
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except (ImportError, RuntimeError, AttributeError, OSError):
        return


def accelerator_snapshot() -> dict[str, Any] | None:
    """返回当前 CUDA 设备的显存快照；无 torch / 无 CUDA / 读取失败一律返回 None。

    `total_bytes` / `free_bytes` 是**整卡**口径（含其他进程，正是判断「能否再开一个本地
    大模型」所需），`allocated_bytes` / `reserved_bytes` 是本进程 torch 的口径。
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        return {
            "device": torch.cuda.get_device_name(0),
            "total_bytes": int(total_bytes),
            "free_bytes": int(free_bytes),
            "used_bytes": int(total_bytes - free_bytes),
            "allocated_bytes": int(torch.cuda.memory_allocated()),
            "reserved_bytes": int(torch.cuda.memory_reserved()),
            "torch_version": str(torch.__version__),
        }
    except (ImportError, RuntimeError, AttributeError, OSError):
        return None
