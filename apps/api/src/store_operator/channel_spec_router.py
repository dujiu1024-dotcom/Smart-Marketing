from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.auth.context import AuthContext
from store_operator.auth.errors import ApiError
from store_operator.auth.dependencies import require_store_context
from store_operator.db import get_db
from store_operator.models.channel_spec import ChannelSpec, ChannelSpecVersion

router = APIRouter(prefix="/channels/specs", tags=["channel-specs"])


def _version_payload(version: ChannelSpecVersion) -> dict[str, object]:
    return {
        "id": str(version.id),
        "channel_spec_id": str(version.channel_spec_id),
        "spec_version": version.spec_version,
        "text_constraints": version.text_constraints_json,
        "media_constraints": version.media_constraints_json,
        "hashtag_constraints": version.hashtag_constraints_json,
        "link_constraints": version.link_constraints_json,
        "schedule_constraints": version.schedule_constraints_json,
        "draft_supported": version.draft_supported,
        "publish_supported": version.publish_supported,
        "verification_status": version.verification_status,
        "source_document_ref": version.source_document_ref,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "created_at": version.created_at.isoformat(),
    }


@router.get("")
def list_channel_specs(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, object]]:
    if context.request_store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    specs = db.scalars(
        select(ChannelSpec)
        .where(ChannelSpec.status == "active")
        .order_by(ChannelSpec.channel_key)
    ).all()
    result: list[dict[str, object]] = []
    for spec in specs:
        version = (
            db.scalar(
                select(ChannelSpecVersion).where(
                    ChannelSpecVersion.id == spec.current_version_id,
                    ChannelSpecVersion.channel_spec_id == spec.id,
                )
            )
            if spec.current_version_id
            else None
        )
        result.append(
            {
                "id": str(spec.id),
                "channel_key": spec.channel_key,
                "status": spec.status,
                "current_version": _version_payload(version) if version else None,
            }
        )
    return result


@router.get("/{channel_key}/versions")
def list_channel_spec_versions(
    channel_key: str,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, object]]:
    if context.request_store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    spec = db.scalar(
        select(ChannelSpec).where(
            ChannelSpec.channel_key == channel_key,
            ChannelSpec.status == "active",
        )
    )
    if spec is None:
        raise ApiError(404, "CHANNEL_SPEC_NOT_FOUND", "Channel specification not found")
    versions = db.scalars(
        select(ChannelSpecVersion)
        .where(ChannelSpecVersion.channel_spec_id == spec.id)
        .order_by(ChannelSpecVersion.spec_version.desc())
    ).all()
    return [_version_payload(version) for version in versions]
