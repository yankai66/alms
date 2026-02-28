"""
修复历史设备到货批次的 batch_id，统一增加 RCV 前缀，并同步更新关联表。

运行方式：
    python -m app.scripts.fix_receiving_batch_ids
"""

from __future__ import annotations

from typing import Dict

from sqlalchemy import and_

from app.db.session import SessionLocal
from app.api.v1.receiving import RECEIVING_BATCH_PREFIX, _generate_receiving_batch_id
from app.models.asset_models import (
    ReceivingBatch,
    WorkOrder,
    WorkOrderTypeEnum,
    OperationBatch,
)


def _build_new_batch_id(db, old_batch_id: str) -> str:
    base_candidate = f"{RECEIVING_BATCH_PREFIX}{old_batch_id}"
    exists = (
        db.query(ReceivingBatch)
        .filter(ReceivingBatch.batch_id == base_candidate)
        .first()
    )
    if not exists:
        return base_candidate
    # fallback：若冲突，使用生成器产生一个唯一的 batch_id
    return _generate_receiving_batch_id(db)


def main():
    db = SessionLocal()
    try:
        updated_batches: Dict[str, str] = {}
        receiving_batches = db.query(ReceivingBatch).all()
        for batch in receiving_batches:
            if not batch.batch_id:
                continue
            if batch.batch_id.startswith(RECEIVING_BATCH_PREFIX):
                continue
            old_batch_id = batch.batch_id
            new_batch_id = _build_new_batch_id(db, old_batch_id)
            batch.batch_id = new_batch_id
            updated_batches[old_batch_id] = new_batch_id
            print(f"[ReceivingBatch] {old_batch_id} -> {new_batch_id}")

        # 同步 work_orders
        if updated_batches:
            for old_batch_id, new_batch_id in updated_batches.items():
                db.query(WorkOrder).filter(
                    and_(
                        WorkOrder.business_id == old_batch_id,
                        WorkOrder.work_order_type == WorkOrderTypeEnum.RECEIVING.value,
                    )
                ).update(
                    {"business_id": new_batch_id},
                    synchronize_session=False,
                )
                db.query(OperationBatch).filter(
                    and_(
                        OperationBatch.batch_id == old_batch_id,
                        OperationBatch.operation_type == WorkOrderTypeEnum.RECEIVING.value,
                    )
                ).update(
                    {"batch_id": new_batch_id},
                    synchronize_session=False,
                )

        db.commit()
        print(f"完成：共更新 {len(updated_batches)} 条到货批次记录。")
    except Exception as exc:
        db.rollback()
        print(f"修复批次ID失败: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

