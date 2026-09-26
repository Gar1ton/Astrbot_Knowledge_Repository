"""AstrBot Embedding 相关测试替身（无网络、无真实凭据）。

测试环境不装 AstrBot：`FakeAstrEmbeddingBase` 代替 AstrBot 的 `EmbeddingProvider` 抽象类
（适配器的 `embedding_type` 参数注入它）。`FAKE_SECRET` 是明显的假凭据，测试用它断言
密钥绝不出现在错误信息 / 身份 / 缓存 key / 指纹 / 日志里。

`FakeAstrContext` 复刻 AstrBot Context 的两个公开接口（`get_provider_by_id` /
`get_all_embedding_providers`），并复刻一个真实行为：热重载后旧实例仍留在 embedding 列表里。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

FAKE_SECRET = "sk-FAKE-TEST-SECRET-0000"


class FakeAstrEmbeddingBase:
    """代替 AstrBot 的 EmbeddingProvider 抽象类，仅用于 isinstance 判型。"""


class FakeAstrEmbeddingProvider(FakeAstrEmbeddingBase):
    """可控的 AstrBot Embedding provider 桩；记录适配器对它做过的每一次公开调用。"""

    def __init__(
        self,
        provider_id: str = "emb-a",
        *,
        adapter_type: str = "openai_embedding",
        model: str = "model-a",
        declared_dim: int = 4,
        actual_dim: int | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.adapter_type = adapter_type
        self._model = model
        self._declared_dim = declared_dim
        self.actual_dim = declared_dim if actual_dim is None else actual_dim
        # 真实 provider 的 provider_config 里躺着 API Key；适配器不得读取/外泄它。
        self.provider_config = {
            "id": provider_id,
            "type": adapter_type,
            "embedding_api_key": FAKE_SECRET,
            "embedding_model": model,
        }
        self.calls: list[tuple[str, Any]] = []
        self.query_result: Any = None
        self.documents_result: Any = None
        self.raise_error: Exception | None = None

    # 适配器绝不该碰底层 SDK client。
    @property
    def client(self) -> Any:
        raise AssertionError("适配器不得访问 provider.client")

    def meta(self) -> SimpleNamespace:
        return SimpleNamespace(id=self.provider_id, model=self._model, type=self.adapter_type)

    def get_model(self) -> str:
        return self._model

    def get_dim(self) -> int:
        return self._declared_dim

    def reconfigure(self, *, model: str | None = None, declared_dim: int | None = None) -> None:
        """模拟用户在 AstrBot 里改了配置（不计入适配器的调用记录）。"""
        if model is not None:
            self._model = model
        if declared_dim is not None:
            self._declared_dim = declared_dim

    async def get_embedding(self, text: str) -> Any:
        self.calls.append(("get_embedding", text))
        if self.raise_error is not None:
            raise self.raise_error
        if self.query_result is not None:
            return self.query_result
        return [0.1] * self.actual_dim

    async def get_embeddings(self, text: list[str]) -> Any:
        self.calls.append(("get_embeddings", list(text)))
        if self.raise_error is not None:
            raise self.raise_error
        if self.documents_result is not None:
            return self.documents_result
        return [[(index + 1) / 10.0] * self.actual_dim for index in range(len(text))]

    # 以下三个是「共享 provider 的生命周期操作」：适配器绝不该调用。
    async def terminate(self) -> None:
        self.calls.append(("terminate", None))

    def set_model(self, model_name: str) -> None:
        self.calls.append(("set_model", model_name))
        self._model = model_name

    async def close(self) -> None:
        self.calls.append(("close", None))

    def called(self, name: str) -> list[Any]:
        return [arg for call, arg in self.calls if call == name]


class FakeAstrChatProvider:
    """聊天 provider：有 meta()，但不是 EmbeddingProvider。"""

    def __init__(self, provider_id: str = "chat-a") -> None:
        self.provider_id = provider_id

    def meta(self) -> SimpleNamespace:
        return SimpleNamespace(id=self.provider_id, model="chat-model", type="openai_chat")

    async def text_chat(self, *args: Any, **kwargs: Any) -> str:
        return "hello"


class FakeAstrDuckTypedProvider:
    """有 get_embedding/get_embeddings/get_dim 却不继承 EmbeddingProvider：必须被拒绝。"""

    def meta(self) -> SimpleNamespace:
        return SimpleNamespace(id="duck", model="", type="duck_embedding")

    async def get_embedding(self, text: str) -> list[float]:
        return [0.1]

    async def get_embeddings(self, text: list[str]) -> list[list[float]]:
        return [[0.1] for _ in text]

    def get_dim(self) -> int:
        return 1


class FakeAstrContext:
    """AstrBot Context 的两个 provider 接口：inst_map（按 ID 取）+ embedding 实例列表。"""

    def __init__(self, *providers: Any) -> None:
        self._inst_map: dict[str, Any] = {}
        self._embedding_list: list[Any] = []
        for provider in providers:
            self.add(provider)

    def add(self, provider: Any) -> None:
        self._inst_map[provider.provider_id] = provider
        if isinstance(provider, FakeAstrEmbeddingBase):
            self._embedding_list.append(provider)

    def replace(self, provider: Any) -> None:
        """热重载：新实例进 inst_map；旧实例仍留在 embedding 列表（AstrBot 的真实行为）。"""
        self._inst_map[provider.provider_id] = provider
        self._embedding_list.append(provider)

    def remove(self, provider_id: str) -> None:
        self._inst_map.pop(provider_id, None)

    def get_provider_by_id(self, provider_id: str) -> Any:
        return self._inst_map.get(provider_id)

    def get_all_embedding_providers(self) -> list[Any]:
        return list(self._embedding_list)
