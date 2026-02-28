"""
设备上架管理API
提供设备上架的查询和管理功能
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import json
import httpx

from app.db.session import get_db
from app.services.work_order_service import create_work_order as create_work_order_service, update_work_order_status
from app.services.operation_batch_service import upsert_operation_batch
from app.schemas.asset_schemas import ApiResponse, ResponseCode
from app.models.asset_models import (
    Asset,
    AssetCategory,
    Room,
    RackingBatch,
    RackingBatchItem,
    WorkOrder
)
from app.core.config import settings

router = APIRouter()

RACKING_BATCH_PREFIX = "RACK"

def _generate_racking_batch_id(db: Session) -> str:
    """生成带前缀的上架批次ID，格式：RACKYYYYMMDDNNN"""
    today = datetime.now().strftime('%Y%m%d')
    sequence = db.query(RackingBatch).filter(
        RackingBatch.batch_id.like(f"{RACKING_BATCH_PREFIX}{today}%")
    ).count() + 1

    while True:
        batch_id = f"{RACKING_BATCH_PREFIX}{today}{str(sequence).zfill(3)}"
        existing = db.query(RackingBatch).filter(
            RackingBatch.batch_id == batch_id
        ).first()
        if not existing:
            return batch_id
        sequence += 1


# =====================================================
# 工单系统集成（已迁移到 work_order_service）
# =====================================================


# =====================================================
# 请求/响应模型
# =====================================================

class RackingItemCreate(BaseModel):
    """创建设备上架请求（业务字段）"""
    sn: str = Field(..., description="设备序列号（SN）*")
    datacenter: Optional[str] = Field(None, description="机房（机房缩写）")
    room_number: Optional[str] = Field(None, description="房间号")
    cabinet_number: Optional[str] = Field(None, description="机柜编号")
    rack_position: Optional[str] = Field(None, description="机位信息（格式：1-2 或 1）")
    remark: Optional[str] = Field(None, description="备注")


class RackingBatchCreate(BaseModel):
    """创建上架批次请求"""
    title: str = Field(..., description="上架单标题*")
    assignee: str = Field(..., description="指派人*")
    remark: Optional[str] = Field(None, description="备注")


class BatchRackingRequest(BaseModel):
    """批量上架请求"""
    title: str = Field(..., description="上架单标题*")
    assignee: str = Field(..., description="指派人*")
    items: List[RackingItemCreate] = Field(..., description="上架设备列表")
    remark: Optional[str] = Field(None, description="批次备注")


# =====================================================
# 设备上架管理接口
# =====================================================

@router.post("/batches", summary="创建上架批次")
async def create_racking_batch(
    batch_data: RackingBatchCreate,
    db: Session = Depends(get_db)
):
    """创建新的上架批次"""
    try:
        batch_id = _generate_racking_batch_id(db)
        
        # 创建批次记录（使用上架单标题作为备注）
        batch_remark = f"{batch_data.title}"
        if batch_data.remark:
            batch_remark += f" | {batch_data.remark}"
        
        racking_batch = RackingBatch(
            batch_id=batch_id,
            status="pending",
            operator=batch_data.assignee,
            remark=batch_remark
        )
        
        db.add(racking_batch)
        upsert_operation_batch(
            db,
            operation_type="racking",
            batch_id=batch_id,
            title=batch_data.title,
            status=racking_batch.status,
            creator=batch_data.assignee,
            operator=batch_data.assignee,
            assignee=batch_data.assignee,
            extra={"remark": batch_data.remark},
        )
        db.commit()
        db.refresh(racking_batch)

        work_order_result = None
        try:
            work_order_result = await create_work_order_service(
                db=db,
                work_order_type="racking",
                business_id=batch_id,
                title="机柜上电",
                creator_name=batch_data.assignee,
                assignee=batch_data.assignee,
                description=batch_data.remark or "",
                operator=batch_data.assignee
            )

            if work_order_result and work_order_result.get("success"):
                racking_batch.work_order_id = work_order_result.get("work_order_id")
                racking_batch.work_order_number = work_order_result.get("work_order_number")
                racking_batch.status = "processing"  # 内部状态：处理中
                racking_batch.work_order_status = "processing"  # 外部工单状态：进行中
                db.commit()
                db.refresh(racking_batch)
                print(f"[上架工单创建成功] 批次ID: {batch_id}, 工单ID: {work_order_result.get('work_order_id')}, 工单号: {work_order_result.get('work_order_number')}")
        except Exception as work_order_error:
            print(f"[上架工单创建失败] 批次ID: {batch_id}, 错误: {str(work_order_error)}")
            work_order_result = {
                "success": False,
                "error": str(work_order_error)
            }
        
        response_data = {
            "batch_id": batch_id,
            "id": racking_batch.id,
            "title": batch_data.title,
            "assignee": batch_data.assignee,
            "status": racking_batch.status,
            "work_order_number": racking_batch.work_order_number or ""
        }

        if work_order_result:
            response_data["work_order"] = work_order_result
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="上架批次创建成功",
            data=response_data
        )
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"创建失败: {str(e)}",
            data=None
        )


def _parse_u_position(u_position: str) -> tuple[int, int]:
    """解析机位字符串，返回(起始U位, 结束U位)"""
    u_position = u_position.strip()
    if '-' in u_position:
        parts = u_position.split('-')
        if len(parts) != 2:
            raise ValueError(f"机位格式错误: {u_position}，应为 '1-2' 或 '1'")
        start = int(parts[0].strip())
        end = int(parts[1].strip())
        return start, end
    else:
        # 单个U位
        u = int(u_position)
        return u, u


def _find_asset_by_sn(db: Session, sn: str) -> Optional[Asset]:
    """根据序列号查找资产"""
    return db.query(Asset).filter(Asset.serial_number == sn).first()


@router.post("/batch", summary="批量设备上架")
async def batch_racking(
    request: BatchRackingRequest,
    db: Session = Depends(get_db)
):
    """批量设备上架（创建一个批次，包含多个设备）
    
    请求体字段：
    - title: 上架单标题（必填）
    - assignee: 指派人（必填）
    - items: 上架设备列表
      - sn: 设备序列号（必填）
      - datacenter: 机房（可选）
      - room_number: 房间号（可选）
      - cabinet_number: 机柜编号（可选）
      - u_position: 机位，格式：1-2 或 1（必填）
      - remark: 备注（可选）
    - remark: 批次备注（可选）
    """
    try:
        batch_id = _generate_racking_batch_id(db)
        
        # 创建批次记录（使用上架单标题作为备注）
        batch_remark = f"{request.title}"
        if request.remark:
            batch_remark += f" | {request.remark}"
        
        racking_batch = RackingBatch(
            batch_id=batch_id,
            status="pending",
            operator=request.assignee,
            remark=batch_remark
        )
        db.add(racking_batch)
        db.flush()
        
        upsert_operation_batch(
            db,
            operation_type="racking",
            batch_id=batch_id,
            title=request.title,
            status=racking_batch.status,
            creator=request.assignee,
            operator=request.assignee,
            assignee=request.assignee,
            extra={
                "remark": request.remark,
                "total_items": len(request.items),
                "priority": "normal",
                "source_order_number": batch_id,
            },
        )
        
        success_count = 0
        failed_count = 0
        errors = []
        items_created = []
        
        # 逐条处理上架设备
        for idx, item_data in enumerate(request.items):
            try:
                # 只检查SN的有效性
                asset = _find_asset_by_sn(db, item_data.sn)
                if not asset:
                    errors.append({
                        "index": idx + 1,
                        "sn": item_data.sn,
                        "error": f"未找到序列号为 {item_data.sn} 的资产"
                    })
                    failed_count += 1
                    continue
                
                # SN有效，尝试查找和创建上架记录（不强制验证）
                u_position_start = 1
                u_position_end = 1
                u_count = 1

                if item_data.rack_position:
                    try:
                        u_position_start, u_position_end = _parse_u_position(item_data.rack_position)
                        u_count = max(1, u_position_end - u_position_start + 1)
                    except Exception:
                        u_position_start = 1
                        u_position_end = 1
                        u_count = 1

                batch_item = RackingBatchItem(
                    batch_id=racking_batch.id,
                    asset_id=asset.id,
                    cabinet_id=None,
                    cabinet_number=item_data.cabinet_number,
                    datacenter=item_data.datacenter,
                    room_number=item_data.room_number,
                    rack_position=item_data.rack_position,
                    u_position_start=u_position_start,
                    u_position_end=u_position_end,
                    u_count=u_count,
                    front_or_back="front",
                    status="pending",
                    error=item_data.remark
                )

                db.add(batch_item)

                items_created.append({
                    "sn": item_data.sn,
                    "asset_id": asset.id,
                    "asset_tag": asset.asset_tag,
                    "cabinet_number": item_data.cabinet_number,
                    "rack_position": item_data.rack_position
                })

                success_count += 1
                
            except Exception as e:
                errors.append({
                    "index": idx + 1,
                    "sn": item_data.sn if hasattr(item_data, 'sn') else None,
                    "error": str(e)
                })
                failed_count += 1
                continue
        
        # 如果存在任何失败，整批回滚
        if failed_count > 0 or success_count == 0:
            db.rollback()
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message="批量上架失败",
                data={
                    "total": len(request.items),
                    "success": success_count,
                    "failed": failed_count,
                    "errors": errors
                }
            )
        
        # 全量成功时提交事务
        db.commit()
        db.refresh(racking_batch)

        work_order_result = None
        try:
            work_order_result = await create_work_order_service(
                db=db,
                work_order_type="racking",
                business_id=batch_id,
                title="机柜上电",
                creator_name=request.assignee,
                assignee=request.assignee,
                description=request.remark or "",
                operator=request.assignee
            )

            if work_order_result and work_order_result.get("success"):
                racking_batch.work_order_id = work_order_result.get("work_order_id")
                racking_batch.work_order_number = work_order_result.get("work_order_number")
                racking_batch.status = "processing"  # 内部状态：处理中
                racking_batch.work_order_status = "processing"  # 外部工单状态：进行中
                db.commit()
                db.refresh(racking_batch)
                print(f"[上架工单创建成功] 批次ID: {batch_id}, 工单ID: {work_order_result.get('work_order_id')}, 工单号: {work_order_result.get('work_order_number')}")
        except Exception as work_order_error:
            print(f"[上架工单创建失败] 批次ID: {batch_id}, 错误: {str(work_order_error)}")
            work_order_result = {
                "success": False,
                "error": str(work_order_error)
            }
        
        response_data = {
            "batch_id": batch_id,
            "title": request.title,
            "assignee": request.assignee,
            "total": len(request.items),
            "success": success_count,
            "failed": failed_count,
            "items": items_created,
            "work_order_number": racking_batch.work_order_number or ""
        }

        if work_order_result:
            response_data["work_order"] = work_order_result
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="批量上架成功",
            data=response_data
        )
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"批量上架失败: {str(e)}",
            data=None
        )




@router.put("/items/{item_id}/complete", summary="完成设备上架")
async def complete_racking_item(
    item_id: int,
    db: Session = Depends(get_db)
):
    """标记设备上架完成"""
    try:
        item = db.query(RackingBatchItem).filter(RackingBatchItem.id == item_id).first()
        if not item:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到ID为 {item_id} 的上架记录",
                data=None
            )
        
        # 更新状态
        old_status = item.status
        item.status = "completed"
        item.updated_at = datetime.now()
        
        # 如果批次内所有设备都已完成，更新批次状态
        batch = item.batch
        if batch:
            all_items = batch.items or []
            all_completed = all(item.status == "completed" for item in all_items)
            if all_completed:
                batch.status = "completed"
                batch.racking_time = datetime.now()
                batch.updated_at = datetime.now()
        
        db.commit()
        if batch:
            upsert_operation_batch(
                db,
                operation_type="racking",
                batch_id=batch.batch_id,
                status=batch.status,
                operator=batch.operator,
                assignee=getattr(batch, "assignee", None),
                receiver=batch.operator,
                inspector=batch.inspector,
                close_time=batch.racking_time,
                extra={"completed_count": sum(1 for itm in (batch.items or []) if itm.status == "completed")},
            )
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="上架完成",
            data={
                "item_id": item_id,
                "old_status": old_status,
                "new_status": "completed"
            }
        )
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"更新失败: {str(e)}",
            data=None
        )


@router.get("/batches", summary="查询上架批次列表")
async def get_racking_batches(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=10000, description="每页大小"),
    batch_id: Optional[str] = Query(None, description="批次ID（模糊搜索）"),
    status: Optional[str] = Query(None, description="状态"),
    operator: Optional[str] = Query(None, description="操作人（模糊搜索）"),
    work_order_number: Optional[str] = Query(None, description="工单号（模糊搜索）"),
    db: Session = Depends(get_db)
):
    """查询上架批次列表（分页+多条件筛选）"""
    try:
        query = db.query(RackingBatch).options(
            joinedload(RackingBatch.items).joinedload(RackingBatchItem.asset)
        )
        
        if batch_id:
            query = query.filter(RackingBatch.batch_id.like(f"%{batch_id}%"))
        
        if status:
            query = query.filter(RackingBatch.status == status)
        
        if operator:
            query = query.filter(RackingBatch.operator.like(f"%{operator}%"))

        if work_order_number:
            query = query.filter(RackingBatch.work_order_number.like(f"%{work_order_number}%"))
        
        batches = query.order_by(RackingBatch.created_at.desc()).all()
        
        if not batches:
            return ApiResponse(
                code=ResponseCode.SUCCESS,
                message="暂无上架批次",
                data={
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "batches": []
                }
            )
        
        batches_list = []
        for batch in batches:
            items = batch.items or []
            batches_list.append({
                "batch_id": batch.batch_id,
                "excel_batch_number": batch.excel_batch_number,
                "work_order_number": batch.work_order_number,
                "status": batch.status,
                "operator": batch.operator,
                "reviewer": batch.reviewer,
                "inspector": batch.inspector,
                "racking_time": batch.racking_time.isoformat() if batch.racking_time else None,
                "device_count": len(items),
                "completed_count": sum(1 for item in items if item.status == "completed"),
                "pending_count": sum(1 for item in items if item.status == "pending"),
                "created_at": batch.created_at.isoformat() if batch.created_at else None
            })
        
        # 分页
        total = len(batches_list)
        start = (page - 1) * page_size
        end = start + page_size
        batches_page = batches_list[start:end]
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
                "batches": batches_page
            }
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.get("/items", summary="查询已上架设备列表")
async def get_racking_items(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=10000, description="每页大小"),
    sn: Optional[str] = Query(None, description="设备序列号（模糊搜索）"),
    cabinet_number: Optional[str] = Query(None, description="机柜编号（模糊搜索）"),
    status: Optional[str] = Query(None, description="状态：pending-待上架, racking-上架中, completed-已完成, cancelled-已取消"),
    batch_id: Optional[str] = Query(None, description="批次ID（模糊搜索）"),
    work_order_number: Optional[str] = Query(None, description="工单号（模糊搜索）"),
    operator: Optional[str] = Query(None, description="操作人（模糊搜索）"),
    created_at_from: Optional[str] = Query(None, description="开始时间（格式：YYYY-MM-DD）"),
    created_at_to: Optional[str] = Query(None, description="结束时间（格式：YYYY-MM-DD）"),
    close_time_from: Optional[str] = Query(None, description="结单时间开始（格式：YYYY-MM-DD）"),
    close_time_to: Optional[str] = Query(None, description="结单时间结束（格式：YYYY-MM-DD）"),
    db: Session = Depends(get_db)
):
    """查询已上架设备列表（分页+多条件筛选）"""
    try:
        query = db.query(RackingBatchItem).options(
            joinedload(RackingBatchItem.asset)
        )
        joined_batch = False
        
        # 按状态筛选
        if status:
            query = query.filter(RackingBatchItem.status == status)
        
        # 按SN筛选
        if sn:
            query = query.join(Asset).filter(Asset.serial_number.like(f"%{sn}%"))
        
        # 按机柜编号筛选
        if cabinet_number:
            query = query.filter(RackingBatchItem.cabinet_number.like(f"%{cabinet_number}%"))

        # 按批次ID筛选
        if batch_id:
            if not joined_batch:
                query = query.join(RackingBatch)
                joined_batch = True
            query = query.filter(RackingBatch.batch_id.like(f"%{batch_id}%"))

        if work_order_number:
            if not joined_batch:
                query = query.join(RackingBatch)
                joined_batch = True
            query = query.filter(RackingBatch.work_order_number.like(f"%{work_order_number}%"))
        
        # 按操作人筛选
        if operator:
            if not joined_batch:
                query = query.join(RackingBatch)
                joined_batch = True
            query = query.filter(RackingBatch.operator.like(f"%{operator}%"))
        
        # 按创建时间范围筛选
        if created_at_from:
            try:
                from_date = datetime.strptime(created_at_from, "%Y-%m-%d")
                query = query.filter(RackingBatchItem.created_at >= from_date)
            except ValueError:
                pass
        
        if created_at_to:
            try:
                to_date = datetime.strptime(created_at_to, "%Y-%m-%d")
                to_date = datetime.combine(to_date, datetime.max.time())
                query = query.filter(RackingBatchItem.created_at <= to_date)
            except ValueError:
                pass
        
        # 按结单时间范围筛选
        if close_time_from or close_time_to:
            if not joined_batch:
                query = query.join(RackingBatch)
                joined_batch = True
            
            if close_time_from:
                try:
                    from_date = datetime.strptime(close_time_from, "%Y-%m-%d")
                    query = query.filter(RackingBatch.close_time >= from_date)
                except ValueError:
                    pass
            
            if close_time_to:
                try:
                    to_date = datetime.strptime(close_time_to, "%Y-%m-%d")
                    to_date = datetime.combine(to_date, datetime.max.time())
                    query = query.filter(RackingBatch.close_time <= to_date)
                except ValueError:
                    pass
        
        total = query.count()
        items = query.order_by(RackingBatchItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        
        items_list = []
        now = datetime.now()
        for item in items:
            batch = item.batch
            # 计算SLA倒计时（秒）
            sla_countdown = None
            if batch and batch.sla_deadline:
                delta = batch.sla_deadline - now
                sla_countdown = int(delta.total_seconds()) if delta.total_seconds() > 0 else 0
            
            items_list.append({
                "item_id": item.id,
                "batch_id": batch.batch_id if batch else None,
                "batch_title": batch.remark.split(" | ")[0] if batch and batch.remark else None,
                "asset_id": item.asset.id if item.asset else None,
                "asset_tag": item.asset.asset_tag if item.asset else None,
                "sn": item.asset.serial_number if item.asset else None,
                "asset_name": item.asset.name if item.asset else None,
                "cabinet_number": item.cabinet_number,
                "room_number": item.room_number,
                "datacenter": item.datacenter,
                "rack_position": item.rack_position,  # 机位
                "project_number": batch.project_number if batch else None,  # 项目编号
                "source_order_number": batch.source_order_number if batch else None,  # 来源单号
                "close_time": batch.close_time.isoformat() if batch and batch.close_time else None,  # 结单时间
                "sla_countdown": sla_countdown,  # SLA倒计时（秒）
                "network_racking_order_number": batch.network_racking_order_number if batch else None,  # 网络设备上架单号
                "power_connection_order_number": batch.power_connection_order_number if batch else None,  # 插线通电单号
                "inbound_order_number": batch.inbound_order_number if batch else None,  # 入库单号
                "outbound_order_number": batch.outbound_order_number if batch else None,  # 出库单号
                "operator": batch.operator if batch and batch.operator else "",
                "work_order_number": batch.work_order_number if batch and batch.work_order_number else "",
                "status": item.status,
                "remark": item.error,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None
            })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
                "items": items_list
            }
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.get("/batches/{batch_id}", summary="查询指定批次的上架设备列表")
async def get_racking_batch_devices(
    batch_id: str,
    db: Session = Depends(get_db)
):
    """根据批次ID查询该批次上架的所有设备"""
    try:
        batch = db.query(RackingBatch).filter(
            RackingBatch.batch_id == batch_id
        ).first()
        
        if not batch:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到批次ID为 {batch_id} 的批次记录",
                data=None
            )
        
        items = db.query(RackingBatchItem).options(
            joinedload(RackingBatchItem.asset)
        ).filter(
            RackingBatchItem.batch_id == batch.id
        ).all()
        
        if not items:
            return ApiResponse(
                code=ResponseCode.SUCCESS,
                message="该批次暂无上架设备",
                data={
                    "batch_id": batch.batch_id,
                    "operator": batch.operator,
                    "reviewer": batch.reviewer,
                    "status": batch.status,
                    "total": 0,
                    "devices": []
                }
            )
        
        devices = []
        now = datetime.now()
        # 计算SLA倒计时（秒）
        sla_countdown = None
        if batch.sla_deadline:
            delta = batch.sla_deadline - now
            sla_countdown = int(delta.total_seconds()) if delta.total_seconds() > 0 else 0
        
        for item in items:
            devices.append({
                "item_id": item.id,
                "asset_id": item.asset.id if item.asset else None,
                "asset_tag": item.asset.asset_tag if item.asset else None,
                "asset_name": item.asset.name if item.asset else None,
                "cabinet_number": item.cabinet_number,
                "datacenter": item.datacenter,
                "room_number": item.room_number,
                "rack_position": item.rack_position,  # 机位
                "project_number": batch.project_number,  # 项目编号
                "source_order_number": batch.source_order_number,  # 来源单号
                "close_time": batch.close_time.isoformat() if batch.close_time else None,  # 结单时间
                "sla_countdown": sla_countdown,  # SLA倒计时（秒）
                "network_racking_order_number": batch.network_racking_order_number,  # 网络设备上架单号
                "power_connection_order_number": batch.power_connection_order_number,  # 插线通电单号
                "inbound_order_number": batch.inbound_order_number,  # 入库单号
                "outbound_order_number": batch.outbound_order_number,  # 出库单号
                "operator": batch.operator if batch and batch.operator else "",
                "work_order_number": batch.work_order_number if batch and batch.work_order_number else "",
                "power_supply": item.power_supply,
                "network_port": item.network_port,
                "status": item.status,
                "remark": item.error,
                "created_at": item.created_at.isoformat() if item.created_at else None
            })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "batch_id": batch.batch_id,
                "operator": batch.operator,
                "reviewer": batch.reviewer,
                "status": batch.status,
                "racking_time": batch.racking_time.isoformat() if batch.racking_time else None,
                "total": len(devices),
                "devices": devices
            }
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.delete("/batches/{batch_id}", summary="删除上架批次")
async def delete_racking_batch(
    batch_id: str,
    force: bool = Query(False, description="是否强制删除（包含已完成的上架记录）"),
    db: Session = Depends(get_db)
):
    """删除指定的上架批次"""
    try:
        batch = db.query(RackingBatch).options(
            joinedload(RackingBatch.items)
        ).filter(
            RackingBatch.batch_id == batch_id
        ).first()
        
        if not batch:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到批次ID为 {batch_id} 的记录",
                data=None
            )
        
        items = batch.items or []
        completed_items = [item for item in items if item.status == "completed"]
        
        if completed_items and not force:
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message="批次存在已完成的上架记录，如需删除请设置 force=true",
                data={
                    "batch_id": batch_id,
                    "completed_count": len(completed_items),
                    "force_required": True
                }
            )
        
        batch_info = {
            "batch_id": batch.batch_id,
            "status": batch.status,
            "items_total": len(items),
            "completed_count": len(completed_items)
        }
        
        db.delete(batch)
        db.commit()
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="批次已删除",
            data=batch_info
        )
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"删除失败: {str(e)}",
            data=None
        )

