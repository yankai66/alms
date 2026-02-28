"""
一次性迁移历史批次数据到统一 operation_batches 表。

运行方式：
    python -m app.scripts.operation_batch_migration
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import joinedload

from app.db.session import SessionLocal
from app.models.asset_models import (
    ConfigurationBatch,
    ConfigurationBatchItem,
    PowerOnBatch,
    PowerOnBatchItem,
    RackingBatch,
    RackingBatchItem,
    ReceivingBatch,
    ReceivingBatchItem,
    WorkOrder,
    WorkOrderStatusEnum,
    WorkOrderTypeEnum,
)
from app.services.operation_batch_service import upsert_operation_batch


def _first_datacenter_from_receiving(batch: ReceivingBatch) -> Optional[str]:
    items = batch.items or []
    if not items:
        return None
    item = items[0]
    if item.room and item.room.datacenter_abbreviation:
        return item.room.datacenter_abbreviation
    if item.room_abbreviation:
        return item.room_abbreviation
    specs = item.specifications or {}
    return specs.get("机房")


def _map_work_order_status(value: Optional[str]) -> str:
    if not value:
        return WorkOrderStatusEnum.PENDING.value
    normalized = value.strip().lower()
    mapping = {
        "completed": WorkOrderStatusEnum.COMPLETED.value,
        "complete": WorkOrderStatusEnum.COMPLETED.value,
        "received": WorkOrderStatusEnum.APPROVED.value,
        "approved": WorkOrderStatusEnum.APPROVED.value,
        "processing": WorkOrderStatusEnum.PROCESSING.value,
        "reviewing": WorkOrderStatusEnum.REVIEWING.value,
        "racking": WorkOrderStatusEnum.PROCESSING.value,
        "pending": WorkOrderStatusEnum.PENDING.value,
        "cancelled": WorkOrderStatusEnum.CANCELLED.value,
        "canceled": WorkOrderStatusEnum.CANCELLED.value,
        "rejected": WorkOrderStatusEnum.REJECTED.value,
    }
    return mapping.get(normalized, WorkOrderStatusEnum.PENDING.value)


def _ensure_work_order(
    db,
    *,
    work_order_type: str,
    batch_id: str,
    title: str,
    status: str,
    creator: Optional[str],
    assignee: Optional[str],
    operator: Optional[str],
    reviewer: Optional[str],
    inspector: Optional[str],
    work_order_number: Optional[str],
    created_at: Optional[datetime],
    close_time: Optional[datetime],
    remark: Optional[str] = None,
) -> WorkOrder:
    work_order = None
    if work_order_number:
        work_order = (
            db.query(WorkOrder)
            .filter(WorkOrder.work_order_number == work_order_number)
            .first()
        )
    if not work_order:
        work_order = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.work_order_type == work_order_type,
                WorkOrder.business_id == batch_id,
            )
            .first()
        )

    if not work_order:
        work_order = WorkOrder(
            work_order_number=work_order_number
            or f"MIG-{work_order_type}-{batch_id}",
            work_order_type=work_order_type,
            business_id=batch_id,
            title=title,
            status=status,
            creator=creator,
            assignee=assignee or creator,
            operator=operator or assignee or creator,
            reviewer=reviewer or assignee,
            inspector=inspector,
            remark=remark,
            created_at=created_at or datetime.now(),
            close_time=close_time,
        )
        db.add(work_order)
        db.flush()
    else:
        # 更新关键字段保持最新
        work_order.title = work_order.title or title
        work_order.status = status or work_order.status
        if work_order_number and not work_order.work_order_number:
            work_order.work_order_number = work_order_number
        work_order.creator = work_order.creator or creator
        work_order.assignee = work_order.assignee or assignee or creator
        work_order.operator = operator or work_order.operator
        work_order.reviewer = reviewer or work_order.reviewer
        work_order.inspector = inspector or work_order.inspector
        if close_time and not work_order.close_time:
            work_order.close_time = close_time
        if created_at and not work_order.created_at:
            work_order.created_at = created_at
        db.flush()

    return work_order


def migrate_receiving(db):
    batches = db.query(ReceivingBatch).options(
        joinedload(ReceivingBatch.items).joinedload(ReceivingBatchItem.room)
    ).all()
    for batch in batches:
        extra = {
            "excel_batch_number": batch.excel_batch_number,
            "device_count": len(batch.items or []),
            "import_file_name": batch.import_file_name,
        }
        upsert_operation_batch(
            db,
            operation_type=WorkOrderTypeEnum.RECEIVING.value,
            batch_id=batch.batch_id,
            title=f"设备到货-{batch.excel_batch_number or batch.batch_id}",
            status=batch.status,
            creator=batch.receiver,
            operator=batch.receiver,
            assignee=batch.reviewer,
            receiver=batch.receiver,
            inspector=batch.inspector,
            datacenter=_first_datacenter_from_receiving(batch),
            work_order_id=batch.work_order_id,
            work_order_number=batch.work_order_number,
            expected_completion_time=batch.import_time,
            close_time=batch.close_time,
            extra=extra,
        )
        work_order = _ensure_work_order(
            db,
            work_order_type=WorkOrderTypeEnum.RECEIVING.value,
            batch_id=batch.batch_id,
            title=f"设备到货-{batch.excel_batch_number or batch.batch_id}",
            status=_map_work_order_status(batch.status),
            creator=batch.receiver,
            assignee=batch.reviewer,
            operator=batch.receiver,
            reviewer=batch.reviewer,
            inspector=batch.inspector,
            work_order_number=batch.work_order_number,
            created_at=batch.created_at,
            close_time=batch.close_time,
            remark=batch.remark,
        )
        if not batch.work_order_id:
            batch.work_order_id = work_order.id
        if not batch.work_order_number and work_order.work_order_number:
            batch.work_order_number = work_order.work_order_number


def _aggregate_racking_datacenter(batch: RackingBatch) -> Optional[str]:
    items = batch.items or []
    if not items:
        return None
    for item in items:
        if item.datacenter:
            return item.datacenter
    return None


def migrate_racking(db):
    batches = db.query(RackingBatch).options(
        joinedload(RackingBatch.items).joinedload(RackingBatchItem.asset)
    ).all()
    for batch in batches:
        items = batch.items or []
        extra = {
            "device_count": len(items),
            "completed_count": sum(1 for item in items if item.status == "completed"),
            "remark": batch.remark,
        }
        upsert_operation_batch(
            db,
            operation_type=WorkOrderTypeEnum.RACKING.value,
            batch_id=batch.batch_id,
            title=batch.remark.split(" | ")[0] if batch.remark else f"设备上架-{batch.batch_id}",
            status=batch.status,
            creator=batch.operator,
            operator=batch.operator,
            assignee=batch.operator,
            receiver=batch.operator,
            inspector=batch.inspector,
            datacenter=_aggregate_racking_datacenter(batch),
            work_order_id=batch.work_order_id,
            work_order_number=batch.work_order_number,
            expected_completion_time=batch.racking_time,
            close_time=batch.close_time,
            extra=extra,
        )
        work_order = _ensure_work_order(
            db,
            work_order_type=WorkOrderTypeEnum.RACKING.value,
            batch_id=batch.batch_id,
            title=batch.remark.split(" | ")[0] if batch.remark else f"设备上架-{batch.batch_id}",
            status=_map_work_order_status(batch.status),
            creator=batch.operator,
            assignee=batch.reviewer or batch.operator,
            operator=batch.operator,
            reviewer=batch.reviewer,
            inspector=batch.inspector,
            work_order_number=batch.work_order_number,
            created_at=batch.created_at,
            close_time=batch.close_time or batch.racking_time,
            remark=batch.remark,
        )
        if not batch.work_order_id:
            batch.work_order_id = work_order.id
        if not batch.work_order_number and work_order.work_order_number:
            batch.work_order_number = work_order.work_order_number


def migrate_configuration(db):
    batches = db.query(ConfigurationBatch).options(
        joinedload(ConfigurationBatch.items)
    ).all()
    for batch in batches:
        items = batch.items or []
        extra = {
            "parent_sn": batch.parent_sn,
            "component_quantity": sum((item.quantity or 0) for item in items),
            "project_number": batch.project_number,
        }
        upsert_operation_batch(
            db,
            operation_type=WorkOrderTypeEnum.CONFIGURATION.value,
            batch_id=batch.batch_id,
            title=f"设备增配-{batch.batch_id}",
            status=batch.status,
            creator=batch.assignee or batch.operator,
            operator=batch.operator,
            assignee=batch.assignee,
            receiver=batch.operator,
            inspector=None,
            datacenter=None,
            work_order_id=batch.work_order_id,
            work_order_number=batch.work_order_number,
            expected_completion_time=batch.operation_end_time,
            close_time=batch.close_time,
            extra=extra,
        )
        work_order = _ensure_work_order(
            db,
            work_order_type=WorkOrderTypeEnum.CONFIGURATION.value,
            batch_id=batch.batch_id,
            title=f"设备增配-{batch.batch_id}",
            status=_map_work_order_status(batch.status),
            creator=batch.operator,
            assignee=batch.assignee,
            operator=batch.operator,
            reviewer=batch.assignee,
            inspector=None,
            work_order_number=batch.work_order_number,
            created_at=batch.created_at,
            close_time=batch.close_time,
            remark=batch.remark,
        )
        if not batch.work_order_id:
            batch.work_order_id = work_order.id
        if not batch.work_order_number and work_order.work_order_number:
            batch.work_order_number = work_order.work_order_number


def migrate_power_on(db):
    batches = db.query(PowerOnBatch).options(
        joinedload(PowerOnBatch.items)
    ).all()
    for batch in batches:
        items = batch.items or []
        extra = {
            "cabinet_total": len(items),
            "completed_cabinets": sum(1 for item in items if item.status == "completed"),
            "remark": batch.remark,
        }
        upsert_operation_batch(
            db,
            operation_type=WorkOrderTypeEnum.POWER_ON.value,
            batch_id=batch.batch_id,
            title=batch.title,
            status=batch.status,
            creator=batch.creator,
            operator=batch.operator,
            assignee=batch.assignee,
            receiver=batch.receiver,
            inspector=batch.inspector,
            datacenter=batch.datacenter,
            work_order_id=batch.work_order_id,
            work_order_number=batch.work_order_number,
            expected_completion_time=batch.expected_completion_time,
            close_time=batch.close_time,
            extra=extra,
        )
        work_order = _ensure_work_order(
            db,
            work_order_type=WorkOrderTypeEnum.POWER_ON.value,
            batch_id=batch.batch_id,
            title=batch.title or f"设备上电-{batch.batch_id}",
            status=_map_work_order_status(batch.status),
            creator=batch.creator,
            assignee=batch.assignee,
            operator=batch.operator,
            reviewer=batch.assignee,
            inspector=batch.inspector,
            work_order_number=batch.work_order_number,
            created_at=batch.created_at,
            close_time=batch.close_time,
            remark=batch.remark,
        )
        if not batch.work_order_id:
            batch.work_order_id = work_order.id
        if not batch.work_order_number and work_order.work_order_number:
            batch.work_order_number = work_order.work_order_number


def main():
    db = SessionLocal()
    try:
        print("开始迁移到货批次...")
        migrate_receiving(db)
        print("开始迁移上架批次...")
        migrate_racking(db)
        print("开始迁移增配批次...")
        migrate_configuration(db)
        print("开始迁移上电批次...")
        migrate_power_on(db)
        db.commit()
        print("统一批次迁移完成。")
    except Exception as exc:
        db.rollback()
        print(f"迁移失败: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

