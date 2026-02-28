"""
统一批次记录服务
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.asset_models import WorkOrder


def merge_extra(base: Optional[Dict[str, Any]], payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if base:
        result.update(base)
    if payload:
        result.update({k: v for k, v in payload.items() if v is not None})
    return result


def upsert_operation_batch(
    db: Session,
    operation_type: str,
    batch_id: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
    merge_extra_fields: bool = True,
    **fields: Any,
) -> WorkOrder:
    """
    创建或更新统一批次记录
    """
    if not batch_id:
        raise ValueError("batch_id is required for operation batch upsert")
    if not operation_type:
        raise ValueError("operation_type is required for operation batch upsert")

    record = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.operation_type == operation_type,
            WorkOrder.batch_id == batch_id,
        )
        .first()
    )

    if not record:
        record = WorkOrder(
            operation_type=operation_type,
            batch_id=batch_id,
        )
        db.add(record)

    for key, value in fields.items():
        if value is None:
            continue
        if hasattr(record, key):
            setattr(record, key, value)

    if extra is not None:
        record.extra = merge_extra(
            record.extra if merge_extra_fields else None,
            extra,
        )

    record.updated_at = datetime.now()
    db.flush()
    return record

