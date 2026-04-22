import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from transformerlab.routers.auth import get_user_and_team
from transformerlab.services import upload_service

router = APIRouter(prefix="/upload", tags=["upload"])


class InitRequest(BaseModel):
    filename: str
    total_size: int


class CompleteRequest(BaseModel):
    total_chunks: int


@router.post("/init")
async def init_upload(
    body: InitRequest,
    user_and_team=Depends(get_user_and_team),
):
    return await upload_service.init_upload(body.filename, body.total_size)


@router.put("/{upload_id}/chunk")
async def upload_chunk(
    upload_id: str,
    chunk_index: int,
    total_chunks: int,
    request: Request,
    user_and_team=Depends(get_user_and_team),
):
    data = await request.body()
    try:
        received = await upload_service.save_chunk(upload_id, chunk_index, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"received": received}


@router.get("/{upload_id}/status")
async def get_upload_status(
    upload_id: str,
    user_and_team=Depends(get_user_and_team),
):
    try:
        return await upload_service.get_status(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{upload_id}/complete")
async def complete_upload(
    upload_id: str,
    body: CompleteRequest,
    user_and_team=Depends(get_user_and_team),
):
    try:
        temp_path = await asyncio.to_thread(upload_service.assemble_upload_sync, upload_id, body.total_chunks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"temp_path": temp_path}


@router.delete("/{upload_id}")
async def delete_upload(
    upload_id: str,
    user_and_team=Depends(get_user_and_team),
):
    await upload_service.delete_upload(upload_id)
    return {"status": "deleted"}
