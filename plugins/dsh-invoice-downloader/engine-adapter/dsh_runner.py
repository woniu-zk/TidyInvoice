"""DSH-owned NDJSON entry point for the frozen Invoice Downloader engine."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

from invoice_engine.ipc.protocol import IpcChannel

from dsh_scan import run_scan


def run_engine(config_json: str) -> None:
    """Run one adapter-owned, local-only invoice scan."""
    channel = IpcChannel()
    job_id = "unknown"
    try:
        config: dict[str, Any] = json.loads(config_json)
        job_id = str(config.get("jobId", uuid.uuid4()))
        safe_config = {
            key: value
            for key, value in config.items()
            if key not in ("authCode", "apiKey", "glmApiKey")
        }
        channel.send_job_event(job_id, "engine_started", {"config": safe_config})

        email = str(config.get("email") or "")
        auth_code = str(config.get("authCode") or "")
        date_from = str(config.get("dateFrom") or "")
        date_to = str(config.get("dateTo") or "")
        save_path = str(config.get("savePath") or "")
        if not email or not auth_code:
            raise ValueError("email and authCode are required")
        if not date_from or not date_to:
            raise ValueError("dateFrom and dateTo are required")
        if not save_path:
            raise ValueError("savePath is required")

        channel.send_job_event(job_id, "scan_started", {
            "dateFrom": date_from,
            "dateTo": date_to,
            "company": str(config.get("company") or ""),
        })
        channel.send_job_event(job_id, "scan_progress", {"message": "Starting mailbox scan..."})
        result = run_scan(config=config)
        channel.send_job_event(job_id, "scan_progress", {
            "message": f"Scan completed: {result['invoicesProcessed']} invoices processed",
            "invoicesProcessed": result["invoicesProcessed"],
        })
        channel.send_job_result(job_id, result)
    except Exception as exc:
        channel.send_job_error(job_id, "ENGINE_ERROR", str(exc))
    finally:
        channel.close()


if __name__ == "__main__":
    first_line = sys.stdin.readline()
    if not first_line:
        print(json.dumps({"type": "job.error", "errorCode": "NO_CONFIG", "errorMessage": "no config provided on stdin"}))
        raise SystemExit(1)
    run_engine(first_line.strip())
