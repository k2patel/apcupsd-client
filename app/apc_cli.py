from __future__ import annotations
import asyncio
import shutil
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

APCACCESS_BIN = shutil.which('apcaccess') or 'apcaccess'


class APCStatusError(Exception):
    pass


async def fetch_status(host: str, port: int) -> Dict[str, Any]:
    """Invoke apcaccess CLI and parse key:value lines into a dict.

    Raises APCStatusError if binary fails or returns no data.
    """
    proc = await asyncio.create_subprocess_exec(
        APCACCESS_BIN,
        '-h', f'{host}:{port}',
        'status',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err_txt = stderr.decode(errors="replace").strip()
        raise APCStatusError(
            f'apcaccess exit {proc.returncode}: {err_txt}'
        )
    text = stdout.decode(errors='replace')
    data: Dict[str, Any] = {}
    for line in text.splitlines():
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        key = k.strip()
        val = v.strip()
        data[key] = val
    # Normalize expected fields/aliases
    if 'UPSNAME' not in data and 'NAME' in data:
        data['UPSNAME'] = data['NAME']
    if 'MODEL' in data:
        data['MODEL_NAME'] = data['MODEL']
    return data
