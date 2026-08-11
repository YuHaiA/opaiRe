import re
import threading
from dataclasses import dataclass
from typing import Optional


COUNTABLE_ERROR_LIMIT = 5
_COUNTABLE_RULES = (
    ("curl_timeout", re.compile(r"Failed to perform,\s*curl:\s*\(28\).*Connection timed out", re.IGNORECASE)),
    ("passwordless_send_409", re.compile(r"无密码通道.*邮件发送异常[,，]?\s*返回[:：]\s*409")),
)
_IGNORED_RULES = (
    ("passwordless_oauth_401", re.compile(r"无密码通道OAuth\s*阶段验证失败[:：]\s*401")),
    ("submit_email_409", re.compile(r"提交邮箱环节异常[,，]?\s*返回[:：]\s*409")),
)
_IGNORED_KINDS = {kind for kind, _ in _IGNORED_RULES}
_thread_local = threading.local()
_lock = threading.Lock()
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
        self.bucket_id, self.count, self.kind = bucket_id, count, kind
        self.message, self.label, self.batch_id = message, label or bucket_id, batch_id


class BatchAbortError(BaseException):
    def __init__(self, batch_id: str, bucket_id: str = "", label: str = ""):
        super().__init__(batch_id)
        self.batch_id = str(batch_id or "")
        self.bucket_id = str(bucket_id or "")
        self.label = label or self.bucket_id or self.batch_id


def start_task(bucket_id: str, label: str = "") -> None:
    _thread_local.current_task = TaskContext(bucket_id, label or bucket_id) if bucket_id else None


def bind_task_batch(batch_id: str) -> None:
    context: Optional[TaskContext] = getattr(_thread_local, "current_task", None)
    if context:
        context.batch_id = str(batch_id or "").strip()


def end_task() -> None:
    _thread_local.current_task = None


def reset_bucket(bucket_id: str) -> None:
    with _lock:
        _bucket_counts.pop(bucket_id, None)


def get_bucket_count(bucket_id: str) -> int:
    with _lock:
        return int(_bucket_counts.get(bucket_id, 0))


def mark_task_success(bucket_id: str) -> None:
    reset_bucket(bucket_id)


def abort_batch(batch_id: str) -> None:
    if batch_id:
        with _lock:
            _aborted_batches.add(str(batch_id))


def clear_batch(batch_id: str) -> None:
    with _lock:
        _aborted_batches.discard(str(batch_id or ""))


def is_batch_aborted(batch_id: str) -> bool:
    with _lock:
        return str(batch_id or "") in _aborted_batches


def raise_if_current_batch_aborted() -> None:
    context = getattr(_thread_local, "current_task", None)
    if context and context.batch_id and is_batch_aborted(context.batch_id):
        raise BatchAbortError(context.batch_id, context.bucket_id, context.label)


def sleep_with_batch_abort(total_seconds: float, step_seconds: float = 0.5) -> None:
    import time
    remaining = max(0.0, float(total_seconds or 0.0))
    step = max(0.05, float(step_seconds or 0.5))
    while remaining > 0:
        raise_if_current_batch_aborted()
        chunk = min(step, remaining)
        time.sleep(chunk)
        remaining -= chunk


def observe_log_message(message: str) -> None:
    context: Optional[TaskContext] = getattr(_thread_local, "current_task", None)
    if not context:
        return
    text = str(message or "").strip()
    ignored = next((name for name, pattern in _IGNORED_RULES if pattern.search(text)), None)
    if ignored:
        return
    kind = next((name for name, pattern in _COUNTABLE_RULES if pattern.search(text)), None)
    if not kind:
        return
    with _lock:
        count = _bucket_counts.get(context.bucket_id, 0) + 1
        _bucket_counts[context.bucket_id] = count
    if count >= COUNTABLE_ERROR_LIMIT:
        abort_batch(context.batch_id)
        raise TaskAbortError(context.bucket_id, count, kind, text, context.label, context.batch_id)
