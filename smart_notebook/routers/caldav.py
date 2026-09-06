"""Operational API for the dedicated Nextcloud Notizbuch task calendar."""
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel

from ..services.caldav_sync import (CalDAVConfigurationError,CalDAVPreconditionFailed,
    CalDAVProtocolError,NextcloudCalDAVGateway,caldav_status,list_conflicts,
    resolve_conflict,synchronize_caldav)

router=APIRouter(tags=["caldav"])


class SyncRequest(BaseModel):dry_run:bool=False
class ConflictResolution(BaseModel):resolution:str


@router.get("/api/caldav/status")
async def get_caldav_status():return caldav_status()


@router.post("/api/caldav/discover")
async def discover_caldav():
    try:
        gateway=NextcloudCalDAVGateway()
        try:return await gateway.discover()
        finally:await gateway.close()
    except CalDAVConfigurationError as exc:raise HTTPException(503,str(exc)) from exc
    except CalDAVProtocolError as exc:raise HTTPException(502,str(exc)) from exc


@router.post("/api/caldav/sync")
async def sync_caldav(request:SyncRequest):
    try:return await synchronize_caldav(request.dry_run)
    except CalDAVConfigurationError as exc:raise HTTPException(503,str(exc)) from exc
    except CalDAVPreconditionFailed as exc:raise HTTPException(409,str(exc)) from exc
    except CalDAVProtocolError as exc:raise HTTPException(502,str(exc)) from exc


@router.get("/api/caldav/conflicts")
async def get_caldav_conflicts():return {"conflicts":list_conflicts()}


@router.post("/api/caldav/conflicts/{conflict_id}/resolve")
async def resolve_caldav_conflict(conflict_id:int,request:ConflictResolution):
    try:item=resolve_conflict(conflict_id,request.resolution)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    if item is None:raise HTTPException(404,"CalDAV conflict not found")
    return item
