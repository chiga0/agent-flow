from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import RunState
from ..store import RunStore


class RuntimeAdapter(ABC):
    name: str

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def start(self, run: RunState, store: RunStore) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_input(self, run: RunState, prompt: str, store: RunStore) -> None:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, run: RunState, reason: str | None, store: RunStore) -> None:
        raise NotImplementedError

    def resolve_permission(
        self,
        run: RunState,
        permission_id: str,
        payload: dict[str, Any],
        store: RunStore,
    ) -> None:
        store.append_event(
            run.run_id,
            "permission.resolved",
            {
                "permission_id": permission_id,
                "decision": payload["decision"],
                "decided_by": payload.get("decided_by"),
                "reason": payload.get("reason"),
            },
        )
