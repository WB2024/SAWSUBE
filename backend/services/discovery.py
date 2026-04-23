from __future__ import annotations
import asyncio
import logging
import socket
from typing import Any
import httpx

log = logging.getLogger(__name__)

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
ST = "urn:samsung.com:device:RemoteControlReceiver:1"
MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    f"ST: {ST}\r\n\r\n"
).encode()


def _ssdp_scan(timeout: float = 3.0) -> list[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    sock.sendto(MSEARCH, (SSDP_ADDR, SSDP_PORT))
    # Also scan general MediaRenderer for broader Samsung detection
    sock.sendto(
        MSEARCH.replace(ST.encode(), b"ssdp:all"),
        (SSDP_ADDR, SSDP_PORT),
    )
    seen: set[str] = set()
    try:
        while True:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                break
            ip = addr[0]
            if "samsung" in data.decode(errors="ignore").lower():
                seen.add(ip)
    finally:
        sock.close()
    return sorted(seen)


async def discover_tvs(timeout: float = 3.0) -> list[dict[str, Any]]:
    ips = await asyncio.to_thread(_ssdp_scan, timeout)
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=3.0, verify=False) as client:
        for ip in ips:
            info = await _probe(client, ip)
            if info:
                results.append(info)
    return results


async def _probe(client: httpx.AsyncClient, ip: str) -> dict | None:
    for url in (f"http://{ip}:8001/api/v2/", f"https://{ip}:8002/api/v2/"):
        try:
            r = await client.get(url)
            if r.status_code == 200:
                j = r.json()
                dev = j.get("device", {})
                return {
                    "ip": ip,
                    "model": dev.get("modelName"),
                    "name": dev.get("name") or dev.get("FrameTVSupport"),
                    "type": dev.get("type"),
                    "frame": str(dev.get("FrameTVSupport", "")).lower() == "true",
                    "wifi_mac": dev.get("wifiMac"),
                }
        except Exception:
            continue
    return None
