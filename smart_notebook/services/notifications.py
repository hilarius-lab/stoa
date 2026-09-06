"""Central privacy-safe system notifications through a configurable ntfy server."""
from urllib.parse import quote

import httpx

from ..config import NTFY_ACCESS_TOKEN,NTFY_ERROR_TOPIC,NTFY_SERVER_URL,NTFY_TIMEOUT_SECONDS


def ntfy_configured():
    return bool(NTFY_SERVER_URL and NTFY_ERROR_TOPIC)


async def send_system_error(component,error_type,consecutive_failures):
    """Send metadata only; exception messages and user content never leave the server."""
    if not ntfy_configured():return {"outcome":"disabled"}
    headers={"Title":f"Smart Notebook: {component}","Priority":"high","Tags":"warning"}
    if NTFY_ACCESS_TOKEN:headers["Authorization"]=f"Bearer {NTFY_ACCESS_TOKEN}"
    body=f"{component} failed {consecutive_failures} times consecutively. Error type: {error_type}."
    url=f"{NTFY_SERVER_URL}/{quote(NTFY_ERROR_TOPIC,safe='')}"
    async with httpx.AsyncClient(timeout=NTFY_TIMEOUT_SECONDS,trust_env=False) as client:
        response=await client.post(url,content=body.encode("utf-8"),headers=headers)
        response.raise_for_status()
    return {"outcome":"delivered","status_code":response.status_code}
