"""
工单服务模块
统一管理工单的创建、更新和查询
"""

import json
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
import httpx

from app.core.config import settings
from app.models.asset_models import WorkOrder
from app.schemas.asset_schemas import ApiResponse, ResponseCode


async def create_work_order(
    db: Session,
    work_order_type: str,
    business_id: str,
    title: str,
    creator_name: str,
    assignee: str,
    description: str = "",
    operator: Optional[str] = None,
    reviewer: Optional[str] = None,
    inspector: Optional[str] = None,
    remark: Optional[str] = None
) -> Dict[str, Any]:
    """
    创建工单（同时创建外部工单和本地工单记录）
    
    参数:
    - db: 数据库会话
    - work_order_type: 工单类型（receiving/deviceLaunch/configuration）
    - business_id: 业务ID（批次ID）
    - title: 工单标题
    - creator_name: 创建人姓名
    - assignee: 指派人/审核人
    - description: 工单描述
    - operator: 操作人（可选）
    - reviewer: 审核人（可选）
    - inspector: 验收人（可选）
    - remark: 备注（可选）
    
    返回:
    - 包含 success, work_order_number, work_order_id, error 的字典
    """
    work_order_number = None
    work_order_id = None
    external_process_id = None
    external_data = None
    
    # 1. 先调用外部工单系统创建工单
    try:
        # 构建工单请求数据
        process_id_map = {
            "receiving": "receiving",
            "deviceLaunch": "deviceLaunch",
            "racking": "deviceLaunch",  # 设备上架
            "configuration": "accessoryAddition",  # 配件增配
            "power_management": "CabinetOnOff",  # 机柜上下电
            "powerOn": "CabinetOnOff"  # 兼容旧的powerOn
        }
        process_id = process_id_map.get(work_order_type, work_order_type)
        
        work_order_data = {
            "title": title,
            "description": description or "",
            "secretInfo": "11111",
            "creator": settings.WORK_ORDER_CREATOR,
            "creatorName": creator_name,
            "processId": process_id,
            "variables": {
                "assignee": assignee
            },
            "externalBizId": business_id,
            "bussinessMetaData": {
                "orderType": work_order_type,  # 工单类型（我们的operation_type）
                "assignee": assignee
            }
        }
        
        # 发送HTTP请求
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            print(f"[工单创建] 正在连接工单系统: {settings.WORK_ORDER_API_URL}")
            print(f"[工单创建] 请求报文: {json.dumps(work_order_data, ensure_ascii=False)}")
            response = await client.post(
                settings.WORK_ORDER_API_URL,
                headers={
                    "appid": settings.WORK_ORDER_APPID,
                    "username": settings.WORK_ORDER_USERNAME,
                    "Content-Type": "application/json"
                },
                json=work_order_data
            )
            
            response.raise_for_status()
            result = response.json()
            
            # 提取工单号
            if result.get("status") == 0 and result.get("data"):
                work_order_number = result.get("data", {}).get("order_number")
                external_process_id = process_id
                external_data = result.get("data", {})
                
    except httpx.HTTPStatusError as e:
        error_msg = f"工单系统返回错误: {e.response.status_code} - {e.response.text}"
        print(f"[工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "status_code": e.response.status_code,
            "work_order_number": None,
            "work_order_id": None
        }
    except httpx.RequestError as e:
        error_msg = f"工单系统连接失败: {str(e)}"
        error_detail = f"URL: {settings.WORK_ORDER_API_URL}, Error Type: {type(e).__name__}, Detail: {str(e)}"
        print(f"[工单创建失败] {error_msg}")
        print(f"[工单创建失败详情] {error_detail}")
        return {
            "success": False,
            "error": error_msg,
            "error_detail": error_detail,
            "work_order_number": None,
            "work_order_id": None
        }
    except Exception as e:
        error_msg = f"工单创建异常: {str(e)}"
        print(f"[工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "work_order_number": None,
            "work_order_id": None
        }
    
    # 2. 更新 operation_batches 表的工单信息
    try:
        # 如果外部工单创建失败，仍然更新本地记录（状态为pending）
        if not work_order_number:
            print(f"[警告] 外部工单创建失败，但继续更新本地工单记录")
        
        # 查找对应的 work_order
        batch = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.operation_type == work_order_type,
                WorkOrder.batch_id == business_id,
            )
            .first()
        )
        
        if not batch:
            error_msg = f"未找到对应的批次记录: {work_order_type}/{business_id}"
            print(f"[工单创建失败] {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "work_order_number": work_order_number,
                "work_order_id": None
            }
        
        # 更新工单字段
        batch.work_order_number = work_order_number or f"LOCAL-{business_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        batch.work_order_status = "processing"  # 外部工单状态：创建成功即为进行中（只有3个状态：processing/completed/failed）
        batch.work_order_description = description or ""
        batch.process_id = external_process_id
        batch.work_order_remark = remark
        batch.reviewer = reviewer or assignee
        batch.operator = operator or creator_name
        batch.assignee = assignee
        batch.inspector = inspector
        batch.creator = creator_name if not batch.creator else batch.creator
        
        # 将 external_data 存储到 extra 中
        if external_data:
            if not batch.extra:
                batch.extra = {}
            batch.extra["external_data"] = external_data
        
        db.commit()
        db.refresh(batch)
        
        print(f"[工单创建成功] 批次ID: {batch.id}, 工单号: {batch.work_order_number}, 类型: {work_order_type}")
        
        return {
            "success": True,
            "work_order_number": batch.work_order_number,
            "work_order_id": batch.id,  # 返回批次ID作为work_order_id（兼容性）
            "batch": batch,
            "external_data": external_data
        }
        
    except Exception as e:
        db.rollback()
        error_msg = f"更新工单记录失败: {str(e)}"
        print(f"[工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "work_order_number": work_order_number,  # 外部工单可能已创建
            "work_order_id": None
        }


def update_work_order_status(
    db: Session,
    work_order_id: Optional[int] = None,
    work_order_number: Optional[str] = None,
    status: Optional[str] = None,
    operator: Optional[str] = None,
    reviewer: Optional[str] = None,
    inspector: Optional[str] = None,
    completed_time: Optional[datetime] = None,
    close_time: Optional[datetime] = None
) -> Optional[WorkOrder]:
    """
    更新工单状态（直接更新 operation_batches 表）
    
    参数:
    - db: 数据库会话
    - work_order_id: 批次ID（兼容旧参数名，实际是批次ID）
    - work_order_number: 工单号（优先使用）
    - status: 新状态
    - operator: 操作人
    - reviewer: 审核人
    - inspector: 验收人
    - completed_time: 完成时间
    - close_time: 关闭时间
    
    返回:
    - 更新后的批次对象，如果未找到则返回None
    """
    batch = None
    
    if work_order_number:
        batch = db.query(WorkOrder).filter(WorkOrder.work_order_number == work_order_number).first()
    elif work_order_id:
        # work_order_id 现在作为批次ID使用（兼容性）
        batch = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    else:
        return None
    
    if not batch:
        return None
    
    if status:
        batch.work_order_status = status
    if operator:
        batch.operator = operator
    if reviewer:
        batch.reviewer = reviewer
    if inspector:
        batch.inspector = inspector
    if completed_time:
        batch.completed_time = completed_time
    if close_time:
        batch.close_time = close_time
    
    # 如果状态变为processing且start_time为空，设置start_time
    if status == "processing" and not batch.start_time:
        batch.start_time = datetime.now()
    
    db.commit()
    db.refresh(batch)
    
    return batch


def get_work_order(
    db: Session,
    work_order_id: Optional[int] = None,
    work_order_number: Optional[str] = None,
    business_id: Optional[str] = None,
    work_order_type: Optional[str] = None
) -> Optional[WorkOrder]:
    """
    查询工单（从 operation_batches 表查询）
    
    参数:
    - db: 数据库会话
    - work_order_id: 批次ID（兼容旧参数名）
    - work_order_number: 工单号
    - business_id: 业务ID（批次ID）
    - work_order_type: 工单类型
    
    返回:
    - 批次对象，如果未找到则返回None
    """
    query = db.query(WorkOrder)
    
    if work_order_number:
        query = query.filter(WorkOrder.work_order_number == work_order_number)
    elif work_order_id:
        query = query.filter(WorkOrder.id == work_order_id)
    elif business_id and work_order_type:
        query = query.filter(
            WorkOrder.batch_id == business_id,
            WorkOrder.operation_type == work_order_type
        )
    else:
        return None
    
    return query.first()

