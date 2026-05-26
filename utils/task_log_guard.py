import re
import time
import threading
from dataclasses import dataclass
from typing import Optional


COUNTABLE_ERROR_LIMIT = 3

_COUNTABLE_RULES = (
    ("curl_timeout", re.compile(r"Failed to perform,\s*curl:\s*\(28\).*Connection timed out", re.IGNORECASE)),
    ("submit_email_409", re.compile(r"提交邮箱环节异常[,，]?\s*返回[:：]\s*409")),
    ("passwordless_send_409", re.compile(r"无密码通道.*邮件发送异常[,，]?\s*返回[:：]\s*409")),
)
_IGNORED_RULES = (
    ("passwordless_oauth_401", re.compile(r"无密码通道OAuth\s*阶段验证失败[:：]\s*401")),
)

_thread_local = threading.local()
_tracker_lock = threading.Lock()
_bucket_counts: dict[str, int] = {}
_aborted_batches: set[str] = set()


@dataclass
class TaskContext:
    bucket_id: str
    label: str
    batch_id: str = ""


class TaskAbortError(BaseException):
    def __init__(self, bucket_id: str, count: int, kind: str, message: str, label: str = "", batch_id: str = ""):
        super().__init__(message)
        self.bucket_id = bucket_id
        self.count = count
        self.kind = kind
        self.message = message
        self.label = label or bucket_id
        self.batch_id = batch_id


class BatchAbortError(BaseException):
    def __init__(self, batch_id: str, bucket_id: str = "", label: str = ""):
        super().__init__(batch_id)
        self.batch_id = batch_id
        self.bucket_id = bucket_id
        self.label = label or bucket_id or batch_id


def start_task(bucket_id: str, label: str = "") -> None:
    if not bucket_id:
        _thread_local.current_task = None
        return
    _thread_local.current_task = TaskContext(bucket_id=bucket_id, label=label or bucket_id)


def bind_task_batch(batch_id: str) -> None:
    context: Optional[TaskContext] = getattr(_thread_local, "current_task", None)
    if context is None:
        return
    context.batch_id = str(batch_id or "").strip()


def end_task() -> None:
    _thread_local.current_task = None


def classify_log_message(message: str) -> Optional[str]:
    text = str(message or "").strip()
    if not text:
        return None

    for kind, pattern in _IGNORED_RULES:
        if pattern.search(text):
            return kind

    for kind, pattern in _COUNTABLE_RULES:
        if pattern.search(text):
            return kind
    return None


def get_bucket_count(bucket_id: str) -> int:
    with _tracker_lock:
        return int(_bucket_counts.get(bucket_id, 0))


def reset_bucket(bucket_id: str) -> None:
    if not bucket_id:
        return
    with _tracker_lock:
        _bucket_counts.pop(bucket_id, None)


def mark_task_success(bucket_id: str) -> None:
    reset_bucket(bucket_id)


def abort_batch(batch_id: str) -> None:
    normalized = str(batch_id or "").strip()
    if not normalized:
        return
    with _tracker_lock:
        _aborted_batches.add(normalized)


def clear_batch(batch_id: str) -> None:
    normalized = str(batch_id or "").strip()
    if not normalized:
        return
    with _tracker_lock:
        _aborted_batches.discard(normalized)


def is_batch_aborted(batch_id: str) -> bool:
    normalized = str(batch_id or "").strip()
    if not normalized:
        return False
    with _tracker_lock:
        return normalized in _aborted_batches


def raise_if_current_batch_aborted() -> None:
    context: Optional[TaskContext] = getattr(_thread_local, "current_task", None)
    if context is None or not context.batch_id:
        return
    if is_batch_aborted(context.batch_id):
        raise BatchAbortError(
            batch_id=context.batch_id,
            bucket_id=context.bucket_id,
            label=context.label,
        )


def sleep_with_batch_abort(total_seconds: float, step_seconds: float = 0.5) -> None:
    remaining = max(0.0, float(total_seconds or 0.0))
    step = max(0.05, float(step_seconds or 0.5))
    while remaining > 0:
        raise_if_current_batch_aborted()
        sleep_chunk = min(step, remaining)
        time.sleep(sleep_chunk)
        remaining -= sleep_chunk


def observe_log_message(message: str) -> None:
    context: Optional[TaskContext] = getattr(_thread_local, "current_task", None)
    if context is None:
        return

    kind = classify_log_message(message)
    if kind is None or kind == "passwordless_oauth_401":
        return

    with _tracker_lock:
        next_count = int(_bucket_counts.get(context.bucket_id, 0)) + 1
        _bucket_counts[context.bucket_id] = next_count

    if next_count >= COUNTABLE_ERROR_LIMIT:
        if context.batch_id:
            abort_batch(context.batch_id)
        raise TaskAbortError(
            bucket_id=context.bucket_id,
            count=next_count,
            kind=kind,
            message=str(message or "").strip(),
            label=context.label,
            batch_id=context.batch_id,
        )
