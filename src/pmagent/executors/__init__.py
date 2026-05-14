from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutorResult:
    content: str
    session_id: str


class ExecutorError(RuntimeError):
    pass


from .registry import (  # noqa: E402
    is_inside_agent,
    normalize_executor_id,
    precheck_executor,
    precheck_executor_plan,
    resolve_available_backend,
    run_executor,
)

__all__ = [
    "ExecutorError",
    "ExecutorResult",
    "is_inside_agent",
    "normalize_executor_id",
    "precheck_executor",
    "precheck_executor_plan",
    "resolve_available_backend",
    "run_executor",
]
