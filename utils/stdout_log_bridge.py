import sys
import threading
from typing import Callable, TextIO


class LogMirrorStream:
    def __init__(self, stream: TextIO, append_log: Callable[[str], None]):
        self._stream = stream
        self._append_log = append_log
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, data: str) -> int:
        written = self._stream.write(data)
        self._stream.flush()
        self._capture(data)
        return written

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._stream, "isatty", lambda: False)())

    def fileno(self) -> int:
        return self._stream.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._stream, "encoding", "utf-8")

    def _capture(self, data: str) -> None:
        if not data:
            return
        with self._lock:
            self._buffer += data
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._append_line(line)

    def _append_line(self, line: str) -> None:
        message = line.strip()
        if not message:
            return
        try:
            self._append_log(message)
        except Exception:
            pass


def install_stdout_log_bridge(append_log: Callable[[str], None]) -> None:
    if not isinstance(sys.stdout, LogMirrorStream):
        sys.stdout = LogMirrorStream(sys.stdout, append_log)
    if not isinstance(sys.stderr, LogMirrorStream):
        sys.stderr = LogMirrorStream(sys.stderr, append_log)
