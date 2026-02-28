"""
统一批次与工单查询接口（合并版）
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.asset_models import WorkOrder
from app.schemas.asset_schemas import ApiResponse, ResponseCode

router = APIRouter()


def _parse_date(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        day = datetime.strptime(value, "%Y-%m-%d")
        return datetime.combine(day, datetime.max.time() if end_of_day else datetime.min.time())
    except ValueError:
        return None


def _serialize_unified(batch: WorkOrder) -> dict:
    """
    序列化批次和工单信息（已合并到 operation_batches 表）
    """
    extra = batch.extra or {}
    
    # 计算持续时间（如果有完成时间）
    duration_seconds = None
    if batch.completed_time and batch.created_at:
        duration_seconds = (batch.completed_time - batch.created_at).total_seconds()
    
    # 计算是否超时
    overtime = False
    sla_deadline = extra.get("sla_deadline")
    if not sla_deadline and batch.expected_completion_time:
        sla_deadline = batch.expected_completion_time
    
    if sla_deadline and batch.completed_time:
        try:
            sla_dt = sla_deadline if isinstance(sla_deadline, datetime) else datetime.fromisoformat(sla_deadline)
            overtime = batch.completed_time > sla_dt
        except (ValueError, TypeError):
            pass
    
    # 合并所有信息
    result = {
        # 批次基础信息
        "batch_id": batch.batch_id,
        "operation_type": batch.operation_type,
        "title": batch.title,
        "status": batch.status,
        "creator": batch.creator,
        "operator": batch.operator,
        "assignee": batch.assignee,
        "receiver": batch.receiver,
        "inspector": batch.inspector,
        "reviewer": batch.reviewer,
        "datacenter": batch.datacenter,
        "room": batch.room,
        "expected_completion_time": batch.expected_completion_time.isoformat()
        if batch.expected_completion_time
        else None,
        "close_time": batch.close_time.isoformat() if batch.close_time else None,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
        "extra": extra,
        
        # 工单信息（已合并到表中）
        "work_order_number": batch.work_order_number,
        "work_order_status": batch.work_order_status,
        "work_order_description": batch.work_order_description,
        "source_order_number": extra.get("source_order_number") or batch.batch_id,
        "priority": extra.get("priority"),
        "sn": extra.get("sn"),
        "sla_deadline": sla_deadline.isoformat() if isinstance(sla_deadline, datetime) else (sla_deadline if sla_deadline else None),
        "start_time": batch.start_time.isoformat() if batch.start_time else None,
        "completed_time": batch.completed_time.isoformat() if batch.completed_time else None,
        "duration_seconds": duration_seconds,
        "overtime": overtime,
        "process_id": batch.process_id,
        "work_order_remark": batch.work_order_remark,
    }
    
    return result


@router.get(
    "/batches",
    summary="查询统一批次与工单列表（合并版）",
    response_model=ApiResponse,
    responses={
        200: {"description": "查询成功"},
        400: {"description": "参数错误"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_operation_batches(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=10000, description="每页大小，最大10000"),
    batch_id: Optional[str] = Query(None, description="批次号（模糊匹配）"),
    operation_type: Optional[str] = Query(None, description="业务类型：receiving（到货）/racking（上架）/configuration（配置）/power_on（上电）/power_off（下电）/network_cable（网线更换）/maintenance（维护）"),
    status: Optional[str] = Query(None, description="批次状态：pending（待处理）/processing（处理中）/completed（已完成）/cancelled（已取消）"),
    work_order_status: Optional[str] = Query(None, description="工单状态：processing（进行中）/completed（已完成）/failed（失败）"),
    title: Optional[str] = Query(None, description="标题（模糊匹配）"),
    creator: Optional[str] = Query(None, description="创建人（模糊匹配）"),
    operator: Optional[str] = Query(None, description="操作人（模糊匹配）"),
    assignee: Optional[str] = Query(None, description="指派人（模糊匹配）"),
    receiver: Optional[str] = Query(None, description="接单人（模糊匹配）"),
    inspector: Optional[str] = Query(None, description="验收人（模糊匹配）"),
    datacenter: Optional[str] = Query(None, description="机房（模糊匹配）"),
    room: Optional[str] = Query(None, description="房间（模糊匹配）"),
    work_order_number: Optional[str] = Query(None, description="工单号（模糊匹配）"),
    source_order_number: Optional[str] = Query(None, description="来源单号（模糊匹配）"),
    sn: Optional[str] = Query(None, description="设备序列号SN（模糊匹配）"),
    created_from: Optional[str] = Query(None, description="创建起始日期，格式：YYYY-MM-DD"),
    created_to: Optional[str] = Query(None, description="创建结束日期，格式：YYYY-MM-DD"),
    close_from: Optional[str] = Query(None, description="结单起始日期，格式：YYYY-MM-DD"),
    close_to: Optional[str] = Query(None, description="结单结束日期，格式：YYYY-MM-DD"),
    expected_from: Optional[str] = Query(None, description="期望完成起始日期，格式：YYYY-MM-DD"),
    expected_to: Optional[str] = Query(None, description="期望完成结束日期，格式：YYYY-MM-DD"),
    completed_from: Optional[str] = Query(None, description="实际完成起始日期，格式：YYYY-MM-DD"),
    completed_to: Optional[str] = Query(None, description="实际完成结束日期，格式：YYYY-MM-DD"),
    deadline_from: Optional[str] = Query(None, description="SLA截止起始日期，格式：YYYY-MM-DD"),
    deadline_to: Optional[str] = Query(None, description="SLA截止结束日期，格式：YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """
    统一查询批次和工单信息（合并版）
    
    功能说明：
    - 统一查询所有类型的工单批次信息
    - 批次和工单信息已合并到operation_batches表
    - 支持多条件组合查询和分页
    - 按创建时间倒序排列
    - 自动计算工单持续时间和是否超时
    
    查询参数说明：
    - page/page_size: 分页参数
    - batch_id: 批次号（模糊匹配）
    - operation_type: 业务类型（receiving/racking/configuration/power_on/power_off/network_cable/maintenance）
    - status: 批次内部状态（pending/processing/completed/cancelled）
    - work_order_status: 工单外部状态（processing/completed/failed）
    - title: 标题（模糊匹配）
    - creator/operator/assignee/receiver/inspector: 人员信息（模糊匹配）
    - datacenter/room: 位置信息（模糊匹配）
    - work_order_number: 工单号（模糊匹配）
    - source_order_number: 来源单号（模糊匹配）
    - sn: 设备序列号（模糊匹配）
    - created_from/created_to: 创建时间范围
    - close_from/close_to: 结单时间范围
    - expected_from/expected_to: 期望完成时间范围
    - completed_from/completed_to: 实际完成时间范围
    - deadline_from/deadline_to: SLA截止时间范围
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 数据对象
      - total: 总记录数
      - page: 当前页码
      - page_size: 每页大小
      - pages: 总页数
      - items: 批次工单列表
        - batch_id: 批次ID
        - operation_type: 业务类型
        - title: 标题
        - status: 批次内部状态
        - creator: 创建人
        - operator: 操作人
        - assignee: 指派人
        - receiver: 接单人
        - inspector: 验收人
        - reviewer: 审核人
        - datacenter: 机房
        - room: 房间
        - expected_completion_time: 期望完成时间（ISO格式）
        - close_time: 结单时间（ISO格式）
        - created_at: 创建时间（ISO格式）
        - updated_at: 更新时间（ISO格式）
        - extra: 扩展信息（JSON）
        - work_order_number: 工单号
        - work_order_status: 工单外部状态
        - work_order_description: 工单描述
        - source_order_number: 来源单号
        - priority: 优先级
        - sn: 设备序列号
        - sla_deadline: SLA截止时间（ISO格式）
        - start_time: 开始时间（ISO格式）
        - completed_time: 完成时间（ISO格式）
        - duration_seconds: 持续时间（秒）
        - overtime: 是否超时（布尔值）
        - process_id: 流程ID
        - work_order_remark: 工单备注
    
    使用场景：
    - 统一查询所有类型工单
    - 工单列表页展示
    - 工单统计分析
    - 按多维度筛选工单
    - 监控工单执行情况
    - 查询超时工单
    
    注意事项：
    - 所有查询参数都是可选的
    - 字符串参数支持模糊匹配
    - 日期参数格式为YYYY-MM-DD
    - 自动计算duration_seconds和overtime字段
    - extra字段包含扩展信息（priority、sn等）
    - 部分过滤条件（source_order_number、sn、deadline等）在内存中过滤
    """
    try:
        # 以 operation_batches 为主表查询
        query = db.query(WorkOrder)

        # 批次过滤条件
        if batch_id:
            query = query.filter(WorkOrder.batch_id.like(f"%{batch_id}%"))
        if operation_type:
            query = query.filter(WorkOrder.operation_type == operation_type)
        if status:
            query = query.filter(WorkOrder.status == status)
        if title:
            query = query.filter(WorkOrder.title.like(f"%{title}%"))
        if creator:
            query = query.filter(WorkOrder.creator.like(f"%{creator}%"))
        if operator:
            query = query.filter(WorkOrder.operator.like(f"%{operator}%"))
        if assignee:
            query = query.filter(WorkOrder.assignee.like(f"%{assignee}%"))
        if receiver:
            query = query.filter(WorkOrder.receiver.like(f"%{receiver}%"))
        if inspector:
            query = query.filter(WorkOrder.inspector.like(f"%{inspector}%"))
        if datacenter:
            query = query.filter(WorkOrder.datacenter.like(f"%{datacenter}%"))
        if room:
            query = query.filter(WorkOrder.room.like(f"%{room}%"))
        if work_order_number:
            query = query.filter(WorkOrder.work_order_number.like(f"%{work_order_number}%"))

        # 日期过滤
        created_from_dt = _parse_date(created_from)
        created_to_dt = _parse_date(created_to, end_of_day=True)
        if created_from_dt:
            query = query.filter(WorkOrder.created_at >= created_from_dt)
        if created_to_dt:
            query = query.filter(WorkOrder.created_at <= created_to_dt)

        close_from_dt = _parse_date(close_from)
        close_to_dt = _parse_date(close_to, end_of_day=True)
        if close_from_dt:
            query = query.filter(WorkOrder.close_time >= close_from_dt)
        if close_to_dt:
            query = query.filter(WorkOrder.close_time <= close_to_dt)

        expected_from_dt = _parse_date(expected_from)
        expected_to_dt = _parse_date(expected_to, end_of_day=True)
        if expected_from_dt:
            query = query.filter(WorkOrder.expected_completion_time >= expected_from_dt)
        if expected_to_dt:
            query = query.filter(WorkOrder.expected_completion_time <= expected_to_dt)

        # 工单状态过滤
        if work_order_status:
            query = query.filter(WorkOrder.work_order_status == work_order_status)
        
        # 先获取总数
        total = query.count()
        
        # 分页查询批次
        batch_records = (
            query.order_by(WorkOrder.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        # 序列化数据
        result = []
        for batch in batch_records:
            entry = _serialize_unified(batch)
            extra = batch.extra or {}
            
            # 额外的过滤条件（在内存中过滤，因为涉及 extra 字段）
            if source_order_number:
                source = extra.get("source_order_number") or batch.batch_id or ""
                if source_order_number not in source:
                    continue
            
            if sn:
                sn_value = extra.get("sn") or ""
                if sn not in sn_value:
                    continue
            
            # SLA 日期过滤
            if deadline_from or deadline_to:
                sla_str = entry.get("sla_deadline")
                if sla_str:
                    try:
                        sla_dt = datetime.fromisoformat(sla_str) if isinstance(sla_str, str) else sla_str
                        if deadline_from:
                            from_dt = _parse_date(deadline_from)
                            if from_dt and sla_dt < from_dt:
                                continue
                        if deadline_to:
                            to_dt = _parse_date(deadline_to, end_of_day=True)
                            if to_dt and sla_dt > to_dt:
                                continue
                    except (ValueError, TypeError):
                        pass
            
            # 完成时间过滤
            if completed_from or completed_to:
                completed_time = entry.get("completed_time")
                if completed_time:
                    try:
                        completed_dt = datetime.fromisoformat(completed_time) if isinstance(completed_time, str) else completed_time
                        if completed_from:
                            from_dt = _parse_date(completed_from)
                            if from_dt and completed_dt < from_dt:
                                continue
                        if completed_to:
                            to_dt = _parse_date(completed_to, end_of_day=True)
                            if to_dt and completed_dt > to_dt:
                                continue
                    except (ValueError, TypeError):
                        pass
            
            result.append(entry)

        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
                "items": result,
            },
        )
    except Exception as exc:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(exc)}",
            data=None,
        )

