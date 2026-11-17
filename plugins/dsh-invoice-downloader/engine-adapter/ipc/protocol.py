"""
Invoice Engine IPC Protocol v1 — engine event framing.

stdin NDJSON protocol for DSH plugin <-> Python engine communication. The
engine performs local-only invoice recognition, so the channel only carries job
lifecycle events: started, progress, result, and error.
"""

import json
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

PROTOCOL_VERSION = 1

class FrameType(str, Enum):
    JOB_START = "job.start"
    JOB_EVENT = "job.event"
    JOB_RESULT = "job.result"
    JOB_ERROR = "job.error"


@dataclass
class Frame:
    type: str
    protocol_version: int = PROTOCOL_VERSION
    job_id: str = ""
    timestamp: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "protocolVersion": self.protocol_version,
            "jobId": self.job_id,
            "timestamp": self.timestamp,
            **self.payload,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "Frame":
        data = json.loads(line.strip())
        frame_type = data.pop("type")
        protocol_version = data.pop("protocolVersion", 0)
        job_id = data.pop("jobId", "")
        timestamp = data.pop("timestamp", 0.0)
        if protocol_version > PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol version: {protocol_version}")
        return cls(type=frame_type, protocol_version=protocol_version, job_id=job_id, timestamp=timestamp, payload=data)


class IpcChannel:
    """Bidirectional NDJSON channel over stdin/stdout."""

    def __init__(self, stdin=None, stdout=None):
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._lock = threading.Lock()
        self._closed = False

    def send(self, frame: Frame) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("channel is closed")
            self._stdout.write(frame.to_json() + "\n")
            self._stdout.flush()

    def send_job_event(self, job_id: str, event: str, data: dict = None) -> None:
        self.send(Frame(
            type=FrameType.JOB_EVENT,
            job_id=job_id,
            payload={"event": event, **(data or {})},
        ))

    def send_job_result(self, job_id: str, result: dict) -> None:
        self.send(Frame(
            type=FrameType.JOB_RESULT,
            job_id=job_id,
            payload={"result": result},
        ))

    def send_job_error(self, job_id: str, error_code: str, error_message: str) -> None:
        self.send(Frame(
            type=FrameType.JOB_ERROR,
            job_id=job_id,
            payload={"errorCode": error_code, "errorMessage": error_message},
        ))

    def read_frame(self, timeout: Optional[float] = None) -> Optional[Frame]:
        """Read one frame from stdin. Returns None on EOF."""
        line = self._stdin.readline()
        if not line:
            return None
        return Frame.from_json(line)

    def close(self) -> None:
        with self._lock:
            self._closed = True
