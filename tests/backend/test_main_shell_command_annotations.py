"""回归测试：main.py（真壳）里 @ka.command(...)/@filter.* 装饰方法的类型注解，必须能在
AstrBot core 的 inspect.signature(handler, eval_str=True) 内省下解析（见 CHANGELOG v1.0.9）。

背景：tests/backend/test_lifecycle_and_cli.py 只测 kacore/main.py（假壳，装饰器均已注释，
见该文件 docstring），从未触达真壳的框架装饰器注册路径。v1.0.8 里 main.py 把
AstrMessageEvent/ProviderRequest 仅放进 `if TYPE_CHECKING:`，结合 `from __future__ import
annotations`（PEP 563），在 AstrBot core（v4.26.8+）注册 @ka.command(...) 时对字符串注解
调用 inspect.signature(handler, eval_str=True) 会抛 NameError，插件安装即失败——这类"注册期
签名内省"错误对假壳的测试是结构性不可见的。

本文件在进程内搭一个最小 astrbot SDK 桩：所有装饰器原样返回被装饰的函数/方法（不模拟任何真实
框架行为），这样 main.py 能被 import，且 inspect.getmembers 拿到的就是原始函数对象——其
__globals__ 与生产环境完全一致，对它们调用 inspect.signature(fn, eval_str=True) 复现的正是
AstrBot core 内部（star/filter/command.py）用的同一条 stdlib 路径。
"""

from __future__ import annotations

import inspect
import sys
from types import ModuleType


def _build_fake_astrbot_sdk() -> dict[str, ModuleType]:
    astrbot = ModuleType("astrbot")
    api = ModuleType("astrbot.api")
    event_mod = ModuleType("astrbot.api.event")
    provider_mod = ModuleType("astrbot.api.provider")
    star_mod = ModuleType("astrbot.api.star")

    class AstrMessageEvent:
        """占位类型：只用于注解求值，不提供任何真实行为。"""

    class ProviderRequest:
        """占位类型：只用于注解求值，不提供任何真实行为。"""

    class Context:
        """占位类型。"""

    class Star:
        def __init__(self, context: object, config: dict | None = None) -> None:
            self.context = context

    class StarTools:
        @staticmethod
        def get_data_dir(_name: str) -> None:
            return None

    def register(*_args: object, **_kwargs: object):
        def wrap(cls):
            return cls

        return wrap

    def _identity(*_args: object, **_kwargs: object):
        def wrap(fn):
            return fn

        return wrap

    class _CommandGroup:
        """`@filter.command_group("ka")` 的返回值：持有原函数，`.command(...)`/`.group(...)`
        原样透传（`.group(...)` 支持 `@ka.group("zotero")` 这类嵌套子组）。"""

        def __init__(self, fn):
            self._fn = fn

        def command(self, *args: object, **kwargs: object):
            return _identity(*args, **kwargs)

        def group(self, *args: object, **kwargs: object):
            def wrap(fn):
                return _CommandGroup(fn)

            return wrap

        def __call__(self, *args: object, **kwargs: object):
            return self._fn(*args, **kwargs)

    class _Filter:
        on_llm_request = staticmethod(_identity)
        llm_tool = staticmethod(_identity)

        @staticmethod
        def command_group(*_args: object, **_kwargs: object):
            def wrap(fn):
                return _CommandGroup(fn)

            return wrap

    event_mod.AstrMessageEvent = AstrMessageEvent
    event_mod.filter = _Filter()
    provider_mod.ProviderRequest = ProviderRequest
    star_mod.Context = Context
    star_mod.Star = Star
    star_mod.StarTools = StarTools
    star_mod.register = register
    api.event = event_mod
    api.provider = provider_mod
    api.star = star_mod
    astrbot.api = api

    return {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event_mod,
        "astrbot.api.provider": provider_mod,
        "astrbot.api.star": star_mod,
    }


def _check_module_signatures(module: ModuleType) -> tuple[list[str], list[str]]:
    checked: list[str] = []
    errors: list[str] = []

    def _probe(qualname: str, fn: object) -> None:
        checked.append(qualname)
        try:
            inspect.signature(fn, eval_str=True)  # type: ignore[call-overload]
        except Exception as exc:  # noqa: BLE001 - 要捕获全部失败，不只是 NameError
            errors.append(f"{qualname}: {type(exc).__name__}: {exc}")

    for _name, fn in inspect.getmembers(module, inspect.isfunction):
        _probe(f"main.{fn.__qualname__}", fn)

    for _cls_name, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ != module.__name__:
            continue
        for _m_name, fn in inspect.getmembers(cls, inspect.isfunction):
            _probe(f"main.{fn.__qualname__}", fn)

    return checked, errors


def test_main_shell_command_annotations_resolve_under_eval_str() -> None:
    modules_snapshot = dict(sys.modules)
    sys.modules.update(_build_fake_astrbot_sdk())
    sys.modules.pop("main", None)
    try:
        import main as main_shell  # noqa: PLC0415 - 必须等桩装好后才能 import 真壳

        checked, errors = _check_module_signatures(main_shell)
    finally:
        sys.modules.clear()
        sys.modules.update(modules_snapshot)

    assert checked, "未检查到任何函数——main.py 结构可能已漂移，需要同步更新本测试"
    assert not errors, (
        "main.py 里有方法的类型注解在 AstrBot core 的 eval_str=True 签名内省下无法解析，"
        f"会复现 v1.0.8 那类安装期 NameError：{errors}"
    )
