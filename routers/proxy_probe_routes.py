import asyncio
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from global_state import engine, verify_token
from utils.raw_proxy_probe import probe_raw_proxy_pool


router = APIRouter()


class RawProxyProbeRequest(BaseModel):
    proxy_list: List[str] = Field(default_factory=list)
    sample_size: int = 20
    timeout_sec: float = 8.0


@router.post("/api/proxy/raw/test")
async def test_raw_proxy_pool(req: RawProxyProbeRequest, token: str = Depends(verify_token)):
    if engine.is_running():
        return {
            "status": "warning",
            "message": "主任务正在运行，请先停止任务再测试代理，避免额外测活影响注册。",
            "data": None,
        }

    result = await asyncio.to_thread(
        probe_raw_proxy_pool,
        req.proxy_list,
        sample_size=req.sample_size,
        timeout_sec=req.timeout_sec,
    )
    if result.get("valid_count", 0) <= 0:
        return {
            "status": "warning",
            "message": "没有识别到可测试的代理，请检查输入格式。",
            "data": result,
        }

    ok_count = int(result.get("ok_count") or 0)
    sampled_count = int(result.get("sampled_count") or 0)
    status = "success" if ok_count > 0 else "warning"
    return {
        "status": status,
        "message": result.get("recommendation") or f"代理抽测完成：{ok_count}/{sampled_count} 可用。",
        "data": result,
    }
