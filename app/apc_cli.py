from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

logger = logging.getLogger(__name__)

APCACCESS_BIN = shutil.which('apcaccess') or 'apcaccess'
APCACCESS_TIMEOUT_SECONDS = 10.0


class APCStatusError(Exception):
    pass


async def fetch_status(host: str, port: int) -> dict[str, Any]:
    """Invoke apcaccess CLI and parse key:value lines into a dict.

    Raises APCStatusError if binary fails, times out, or returns no data.
    """
    proc = await asyncio.create_subprocess_exec(
        APCACCESS_BIN,
        '-h', f'{host}:{port}',
        'status',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=APCACCESS_TIMEOUT_SECONDS
        )
    except TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        raise APCStatusError(
            f"apcaccess timed out after {APCACCESS_TIMEOUT_SECONDS}s for {host}:{port}"
        )
    if proc.returncode != 0:
        err_txt = stderr.decode(errors="replace").strip()
        raise APCStatusError(
            f'apcaccess exit {proc.returncode}: {err_txt}'
        )
    text = stdout.decode(errors='replace')
    data: dict[str, Any] = {}
    for line in text.splitlines():
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        key = k.strip()
        val = v.strip()
        data[key] = val
    if not data:
        raise APCStatusError("apcaccess returned no data")
    if 'UPSNAME' not in data and 'NAME' in data:
        data['UPSNAME'] = data['NAME']
    if 'MODEL' in data:
        data['MODEL_NAME'] = data['MODEL']
    return data
