"""
工单管理API
提供统一的工单查询和管理功能
"""

from fastapi import APIRouter, Depends, Query, Path, Body
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from app.db.session import get_db
from app.schemas.asset_schemas import ApiResponse, ResponseCode
from app.models.asset_models import WorkOrder, Asset, WorkOrderItem
from app.models.cabinet_models import Cabinet
from app.services.work_order_service import get_work_order, update_work_order_status
import re

router = APIRouter()


def get_room_cabinets_info(db: Session, room_name: str, work_order_id: int) -> dict:
    """
    获取房间的机柜统计信息（用于电源管理工单审核）
    
    Args:
        db: 数据库会话
        room_name: 房间名称
        work_order_id: 工单ID
        
    Returns:
        dict: 包含房间机柜统计信息
    """
    # 1. 获取该工单涉及的设备和机柜
    work_order_items = db.query(WorkOrderItem).filter(
        WorkOrderItem.work_order_id == work_order_id
    ).all()
    
    # 提取工单涉及的机柜
    work_order_cabinets = set()
    work_order_devices_by_cabinet = {}  # {机柜号: [设备列表]}
    
    for item in work_order_items:
        if item.asset:
            cabinet = None
            # 从location_detail提取机柜信息
            if item.asset.location_detail:
                match = re.search(r'([A-Z0-9\-]+)(?:机柜|柜)', item.asset.location_detail)
                if match:
                    cabinet = match.group(1)
            
            # 如果没有，从operation_data获取
            if not cabinet and item.operation_data:
                cabinet = item.operation_data.get('cabinet_number') or item.operation_data.get('cabinet')
            
            if cabinet:
                work_order_cabinets.add(cabinet)
                if cabinet not in work_order_devices_by_cabinet:
                    work_order_devices_by_cabinet[cabinet] = []
                work_order_devices_by_cabinet[cabinet].append({
                    'serial_number': item.asset.serial_number,
                    'asset_tag': item.asset.asset_tag,
                    'name': item.asset.name,
                    'status': item.status
                })
    
    # 2. 获取该房间的所有设备（按机柜分组）
    from app.models.asset_models import Room
    room = db.query(Room).filter(Room.room_abbreviation == room_name).first()
    
    all_cabinets_in_room = {}  # {机柜号: {total: 总数, in_work_order: 工单中的数量}}
    
    if room:
        # 查询该房间的所有设备
        assets_in_room = db.query(Asset).filter(Asset.room_id == room.id).all()
        
        for asset in assets_in_room:
            cabinet = None
            if asset.location_detail:
                match = re.search(r'([A-Z0-9\-]+)(?:机柜|柜)', asset.location_detail)
                if match:
                    cabinet = match.group(1)
            
            if cabinet:
                if cabinet not in all_cabinets_in_room:
                    all_cabinets_in_room[cabinet] = {
                        'total_devices': 0,
                        'in_work_order': 0,
                        'not_in_work_order': 0
                    }
                all_cabinets_in_room[cabinet]['total_devices'] += 1
                
                if cabinet in work_order_cabinets:
                    all_cabinets_in_room[cabinet]['in_work_order'] += 1
                else:
                    all_cabinets_in_room[cabinet]['not_in_work_order'] += 1
    
    # 3. 从机柜表获取详细信息
    cabinets_in_db = db.query(Cabinet).filter(Cabinet.room == room_name).all()
    cabinets_dict = {cab.cabinet_number: cab for cab in cabinets_in_db}
    
    # 4. 构建返回数据
    cabinets_list = []
    for cabinet_name, stats in all_cabinets_in_room.items():
        cabinet_info = cabinets_dict.get(cabinet_name)
        
        cabinet_data = {
            # 基础信息
            'cabinet_number': cabinet_name,
            'cabinet_name': cabinet_info.cabinet_name if cabinet_info else None,
            
            # 位置信息
            'datacenter': cabinet_info.datacenter if cabinet_info else None,
            'room': room_name,
            'room_number': cabinet_info.room_number if cabinet_info else None,
            
            # 运营商信息
            'operator_cabinet_number': cabinet_info.operator_cabinet_number if cabinet_info else None,
            
            # 电源信息
            'power_type': cabinet_info.power_type if cabinet_info else None,
            'pdu_interface_standard': cabinet_info.pdu_interface_standard if cabinet_info else None,
            
            # 机柜类型
            'cabinet_type': cabinet_info.cabinet_type if cabinet_info else None,
            'cabinet_type_detail': cabinet_info.cabinet_type_detail if cabinet_info else None,
            
            # 物理规格
            'width': cabinet_info.width if cabinet_info else None,
            'size': cabinet_info.size if cabinet_info else None,
            
            # 状态信息
            'power_status': cabinet_info.power_status if cabinet_info else None,
            'usage_status': cabinet_info.usage_status if cabinet_info else None,
            'lifecycle_status': cabinet_info.lifecycle_status if cabinet_info else None,
            'module_construction_status': cabinet_info.module_construction_status if cabinet_info else None,
            
            # 规划信息
            'planning_category': cabinet_info.planning_category if cabinet_info else None,
            'construction_density': cabinet_info.construction_density if cabinet_info else None,
            
            # 操作记录
            'last_power_operation': cabinet_info.last_power_operation if cabinet_info else None,
            'last_power_operation_date': cabinet_info.last_power_operation_date.isoformat() if cabinet_info and cabinet_info.last_power_operation_date else None,
            'last_operation_result': cabinet_info.last_operation_result if cabinet_info else None,
            'last_operation_failure_reason': cabinet_info.last_operation_failure_reason if cabinet_info else None,
            
            # 设备统计
            'total_devices': stats['total_devices'],
            'devices_in_work_order': stats['in_work_order'],
            'devices_not_in_work_order': stats['not_in_work_order'],
            'is_in_work_order': cabinet_name in work_order_cabinets,
            'work_order_devices': work_order_devices_by_cabinet.get(cabinet_name, []),
            
            # 容量信息
            'total_u_count': cabinet_info.total_u_count if cabinet_info else None,
            'used_u_count': cabinet_info.used_u_count if cabinet_info else None,
            'available_u_count': cabinet_info.available_u_count if cabinet_info else None,
            
            # 管理信息
            'responsible_person': cabinet_info.responsible_person if cabinet_info else None,
            'notes': cabinet_info.notes if cabinet_info else None,
        }
        
        cabinets_list.append(cabinet_data)
    
    # 按机柜名称排序
    cabinets_list.sort(key=lambda x: x['cabinet_number'])
    
    return {
        'room_name': room_name,
        'total_cabinets': len(all_cabinets_in_room),
        'cabinets_in_work_order': len(work_order_cabinets),
        'cabinets_not_in_work_order': len(all_cabinets_in_room) - len(work_order_cabinets),
        'cabinets': cabinets_list
    }


@router.get(
    "/",
    summary="查询工单列表",
    response_model=ApiResponse,
    responses={
        200: {"description": "查询成功"},
        400: {"description": "参数错误"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_work_orders(
    work_order_number: Optional[str] = Query(None, description="工单号（支持多个，逗号分隔，如：WO001,WO002,WO003）"),
    batch_id: Optional[str] = Query(None, description="批次ID（内部批次号，精确匹配，如：RECV20251205120000）"),
    work_order_type: Optional[str] = Query(None, description="工单类型（已废弃，请使用operation_type）：receiving（到货）/racking（上架）/configuration（配置）/power_management（电源管理）"),
    operation_type: Optional[str] = Query(None, description="操作类型：receiving（到货）/racking（上架）/configuration（配置）/power_management（电源管理）/network_cable（网线更换）/maintenance（维护）"),
    power_action: Optional[str] = Query(None, description="电源操作类型（仅当operation_type=power_management时有效）：power_on（上电）/power_off（下电）"),
    business_id: Optional[str] = Query(None, description="业务ID（批次ID，精确匹配）"),
    serial_number: Optional[str] = Query(None, description="设备序列号（支持多个，逗号分隔，如：SN001,SN002）"),
    status: Optional[str] = Query(None, description="工单状态：pending（待处理）/processing（处理中）/completed（已完成）/cancelled（已取消）"),
    creator: Optional[str] = Query(None, description="创建人（精确匹配）"),
    assignee: Optional[str] = Query(None, description="指派人（精确匹配）"),
    operator: Optional[str] = Query(None, description="操作人（精确匹配）"),
    created_at_from: Optional[str] = Query(None, description="创建时间（起始），格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD（已废弃，请使用created_at_start）"),
    created_at_to: Optional[str] = Query(None, description="创建时间（结束），格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD（已废弃，请使用created_at_end）"),
    created_at_start: Optional[str] = Query(None, description="创建时间（起始），格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD"),
    created_at_end: Optional[str] = Query(None, description="创建时间（结束），格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD"),
    close_time_from: Optional[str] = Query(None, description="关闭时间（起始），格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD"),
    close_time_to: Optional[str] = Query(None, description="关闭时间（结束），格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=10000, description="每页大小，最大10000"),
    db: Session = Depends(get_db)
):
    """
    查询工单列表（支持多条件筛选和分页）
    
    功能说明：
    - 支持多条件组合查询工单列表
    - 支持分页查询
    - 按创建时间倒序排列
    
    查询参数说明：
    - work_order_number: 工单号（支持多个，逗号分隔，如：WO001,WO002,WO003）
    - batch_id: 批次ID（内部批次号，精确匹配，如：RECV20251205120000）
    - operation_type: 操作类型（推荐使用，精确匹配）
      - receiving: 设备到货
      - racking: 设备上架
      - configuration: 设备配置
      - power_management: 电源管理（包括上电和下电）
      - network_cable: 网线更换
      - maintenance: 设备维护
    - power_action: 电源操作类型（可选，仅当operation_type=power_management时有效）
      - power_on: 只查询上电工单
      - power_off: 只查询下电工单
      - 不传此参数: 查询所有电源管理工单
    - work_order_type: 工单类型（已废弃，向后兼容，建议使用operation_type）
    - business_id: 业务ID/批次ID（精确匹配）
    - serial_number: 设备序列号（支持多个，逗号分隔，如：SN001,SN002，通过工单明细表关联查询）
    - status: 工单状态（pending/processing/completed/cancelled）
    - creator: 创建人（精确匹配）
    - assignee: 指派人（精确匹配）
    - operator: 操作人（精确匹配）
    - created_at_start/created_at_end: 创建时间范围（推荐使用）
    - created_at_from/created_at_to: 创建时间范围（已废弃，向后兼容）
    - close_time_from/close_time_to: 关闭时间范围
    - page: 页码（从1开始）
    - page_size: 每页大小（1-10000）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 数据对象
      - total: 总记录数
      - page: 当前页码
      - page_size: 每页大小
      - pages: 总页数
      - work_orders: 工单列表
        - id: 工单ID
        - batch_id: 批次ID（内部批次号）
        - work_order_number: 工单号（外部工单系统工单号）
        - work_order_type: 工单类型
        - business_id: 业务ID/批次ID
        - title: 工单标题
        - description: 工单描述
        - status: 工单内部状态（pending/processing/completed/cancelled）
        - work_order_status: 工单外部状态
        - creator: 创建人
        - assignee: 指派人
        - operator: 操作人
        - reviewer: 审核人
        - inspector: 验收人
        - datacenter: 机房
        - campus: 园区
        - room: 房间
        - cabinet: 机柜
        - rack_position: 机位（如1-2U）
        - project_number: 项目编号
        - source_order_number: 来源单号/来源业务单号
        - arrival_order_number: 到货单号
        - device_category_level1: 设备一级分类
        - device_category_level2: 设备二级分类
        - device_category_level3: 设备三级分类
        - sla_countdown: SLA倒计时（秒）
        - is_timeout: 是否超时
        - expected_completion_time: 期望完成时间（ISO格式）
        - created_at: 创建时间（ISO格式）
        - start_time: 开始时间（ISO格式）
        - completed_time: 完成时间（ISO格式）
        - close_time: 关闭时间（ISO格式）
        - updated_at: 更新时间（ISO格式）
        - device_count: 设备数量
        - cabinet_count: 机柜数量（电源管理工单特有，统计涉及的机柜数）
        - process_id: 流程ID
        - external_data: 外部数据（JSON）
        - extra: 扩展信息（JSON）
        - remark: 备注
        
    电源管理工单说明：
    - operation_type为power_management时，通过extra或operation_data中的power_action字段区分：
      - power_action: "power_on" 表示上电操作
      - power_action: "power_off" 表示下电操作
    - 上电时可能包含：power_type（电源类型，如AC/DC）
    - 下电时必须包含：reason（下电原因）
    - cabinet_count: 统计本次操作涉及的机柜数量
    
    使用场景：
    - 查询所有工单列表
    - 按工单号查询
    - 按工单类型筛选（如查询所有电源管理工单：operation_type=power_management）
    - 按电源操作类型筛选（如只查询上电工单：operation_type=power_management&power_action=power_on）
    - 按设备序列号筛选（如查询包含某设备的所有工单：serial_number=SN123456）
    - 按状态筛选
    - 按时间范围筛选
    - 按人员筛选（创建人、指派人、操作人）
    
    注意事项：
    - 所有查询参数都是可选的
    - 不传参数时返回所有工单
    - 时间参数需要符合ISO格式
    - 分页参数page_size最大为10000
    - 电源管理工单统一使用operation_type=power_management
    - 可通过power_action参数直接筛选上电/下电工单
    - power_action参数只在operation_type=power_management时有效
    """
    try:
        query = db.query(WorkOrder)
        
        # 筛选条件
        if work_order_number:
            # 支持多个工单号，逗号分隔
            work_order_numbers = [n.strip() for n in work_order_number.split(',') if n.strip()]
            if len(work_order_numbers) == 1:
                query = query.filter(WorkOrder.work_order_number == work_order_numbers[0])
            elif len(work_order_numbers) > 1:
                query = query.filter(WorkOrder.work_order_number.in_(work_order_numbers))
        
        # 批次ID筛选
        if batch_id:
            query = query.filter(WorkOrder.batch_id == batch_id)
        
        # 支持 operation_type 和 work_order_type（向后兼容）
        filter_operation_type = operation_type or work_order_type
        if filter_operation_type:
            query = query.filter(WorkOrder.operation_type == filter_operation_type)
        
        if business_id:
            query = query.filter(WorkOrder.business_id == business_id)
        
        # 按设备序列号筛选（通过工单明细表关联）
        if serial_number:
            # 支持多个序列号，逗号分隔
            serial_numbers = [sn.strip() for sn in serial_number.split(',') if sn.strip()]
            if serial_numbers:
                # 查询包含这些序列号的工单ID
                work_order_ids = db.query(WorkOrderItem.work_order_id).join(
                    Asset, WorkOrderItem.asset_id == Asset.id
                ).filter(
                    Asset.serial_number.in_(serial_numbers)
                ).distinct().all()
                
                work_order_ids = [wid[0] for wid in work_order_ids]
                if work_order_ids:
                    query = query.filter(WorkOrder.id.in_(work_order_ids))
                else:
                    # 如果没有找到匹配的工单，返回空结果
                    return ApiResponse(
                        code=ResponseCode.SUCCESS,
                        message="success",
                        data={
                            "total": 0,
                            "page": page,
                            "page_size": page_size,
                            "pages": 0,
                            "work_orders": []
                        }
                    )
        
        if status:
            query = query.filter(WorkOrder.status == status)
        
        if creator:
            query = query.filter(WorkOrder.creator == creator)
        
        if assignee:
            query = query.filter(WorkOrder.assignee == assignee)
        
        if operator:
            query = query.filter(WorkOrder.operator == operator)
        
        # 创建时间筛选（优先使用新参数 created_at_start/end，兼容旧参数 created_at_from/to）
        start_time_str = created_at_start or created_at_from
        end_time_str = created_at_end or created_at_to
        
        if start_time_str:
            try:
                # 支持多种日期格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD
                start_dt = datetime.fromisoformat(start_time_str.replace('T', ' ').replace('Z', ''))
                query = query.filter(WorkOrder.created_at >= start_dt)
            except ValueError:
                pass  # 忽略无效的日期格式
        
        if end_time_str:
            try:
                end_dt = datetime.fromisoformat(end_time_str.replace('T', ' ').replace('Z', ''))
                query = query.filter(WorkOrder.created_at <= end_dt)
            except ValueError:
                pass
        
        # 关闭时间筛选
        if close_time_from:
            try:
                close_from_dt = datetime.fromisoformat(close_time_from.replace('T', ' ').replace('Z', ''))
                query = query.filter(WorkOrder.close_time >= close_from_dt)
            except ValueError:
                pass
        
        if close_time_to:
            try:
                close_to_dt = datetime.fromisoformat(close_time_to.replace('T', ' ').replace('Z', ''))
                query = query.filter(WorkOrder.close_time <= close_to_dt)
            except ValueError:
                pass
        
        # 电源管理工单：按power_action筛选
        if power_action:
            # 使用JSON查询过滤extra字段中的power_action
            from sqlalchemy import cast, String
            from sqlalchemy.dialects.postgresql import JSONB
            
            # 检查数据库类型，使用相应的JSON查询语法
            # SQLite使用json_extract，PostgreSQL使用->>，MySQL使用JSON_EXTRACT
            try:
                # 尝试PostgreSQL语法
                query = query.filter(WorkOrder.extra['power_action'].astext == power_action)
            except:
                try:
                    # 尝试MySQL语法
                    from sqlalchemy import text
                    query = query.filter(text(f"JSON_EXTRACT(extra, '$.power_action') = '{power_action}'"))
                except:
                    # SQLite或其他：在Python层面过滤
                    pass
        
        # 总数
        total = query.count()
        
        # 分页查询
        work_orders = query.order_by(WorkOrder.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        
        # 如果power_action过滤在数据库层面失败，在Python层面过滤
        if power_action:
            filtered_orders = []
            for wo in work_orders:
                extra_data = wo.extra or {}
                if extra_data.get('power_action') == power_action:
                    filtered_orders.append(wo)
            work_orders = filtered_orders
            # 重新计算总数（这种情况下总数可能不准确，但至少能工作）
            if len(work_orders) < page_size:
                total = (page - 1) * page_size + len(work_orders)
        
        # 构建返回数据
        work_orders_data = []
        for wo in work_orders:
            extra_data = wo.extra or {}
            work_order_item = {
                "id": wo.id,
                "batch_id": wo.batch_id,
                "work_order_number": wo.work_order_number,
                "work_order_type": wo.work_order_type,
                "business_id": wo.business_id,
                "title": wo.title,
                "description": wo.description,
                "status": wo.status,
                "work_order_status": wo.work_order_status,
                "creator": wo.creator,
                "assignee": wo.assignee,
                "operator": wo.operator,
                "reviewer": wo.reviewer,
                "inspector": getattr(wo, "inspector", None),
                # 位置信息
                "datacenter": wo.datacenter,
                "campus": wo.campus,
                "room": wo.room,
                "cabinet": wo.cabinet,
                "rack_position": wo.rack_position,
                # 项目和来源信息
                "project_number": wo.project_number,
                "source_order_number": wo.source_order_number,
                "arrival_order_number": wo.arrival_order_number,
                # 分类信息
                "device_category_level1": wo.device_category_level1,
                "device_category_level2": wo.device_category_level2,
                "device_category_level3": wo.device_category_level3,
                # SLA信息
                "sla_countdown": wo.sla_countdown,
                "is_timeout": wo.is_timeout,
                "expected_completion_time": wo.expected_completion_time.isoformat() if wo.expected_completion_time else None,
                # 时间信息
                "created_at": wo.created_at.isoformat() if wo.created_at else None,
                "start_time": wo.start_time.isoformat() if wo.start_time else None,
                "completed_time": wo.completed_time.isoformat() if wo.completed_time else None,
                "close_time": wo.close_time.isoformat() if wo.close_time else None,
                "updated_at": wo.updated_at.isoformat() if wo.updated_at else None,
                # 其他信息
                "device_count": wo.device_count,
                "cabinet_count": getattr(wo, "cabinet_count", None),
                "process_id": getattr(wo, "process_id", None),
                "external_data": getattr(wo, "external_data", None),
                "extra": wo.extra,
                "remark": wo.remark
            }
            
            # 电源管理工单：提取power_action到顶层，方便前端使用
            if wo.operation_type == "power_management" or wo.work_order_type == "power_management":
                work_order_item["power_action"] = extra_data.get("power_action")
                work_order_item["power_type"] = extra_data.get("power_type")
                work_order_item["power_reason"] = extra_data.get("reason")
            
            work_orders_data.append(work_order_item)
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
                "work_orders": work_orders_data
            }
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.get(
    "/{work_order_id}",
    summary="查询工单详情",
    response_model=ApiResponse,
    responses={
        200: {"description": "查询成功"},
        404: {"description": "工单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_work_order_detail(
    work_order_id: int = Path(..., description="工单ID", example=1),
    db: Session = Depends(get_db)
):
    """
    查询指定工单的详细信息
    
    功能说明：
    - 根据工单ID查询工单的完整详细信息
    - 包含工单基本信息、人员信息、位置信息、时间信息、扩展信息等
    - 适用于所有类型的工单（receiving/racking/configuration/power_management等）
    
    路径参数说明：
    - work_order_id: 工单ID（必填，整数）
    
    返回字段说明：
    - code: 响应码（0表示成功，404表示未找到）
    - message: 响应消息
    - data: 工单详情对象
      - 核心标识：
        - id: 工单ID
        - batch_id: 批次ID（内部批次号，格式：RECV/RACK/CONF/PWR+时间戳）
        - work_order_number: 工单号（外部工单系统工单号）
        - work_order_type: 工单类型（receiving/racking/configuration/power_management等）
        - business_id: 业务ID/批次ID
        - title: 工单标题
        - description: 工单描述
      - 状态信息：
        - status: 工单内部状态（pending/processing/completed/cancelled）
        - work_order_status: 工单外部状态（由外部工单系统更新）
        - is_timeout: 是否超时
        - sla_countdown: SLA倒计时（秒）
      - 人员信息：
        - creator: 创建人
        - assignee: 指派人
        - operator: 当前操作人/结束人
        - reviewer: 审核人
        - inspector: 验收人
      - 位置信息：
        - datacenter: 机房
        - campus: 园区
        - room: 房间
        - cabinet: 机柜
        - rack_position: 机位（如1-2U）
      - 项目和来源信息：
        - project_number: 项目编号
        - source_order_number: 来源单号/来源业务单号
        - arrival_order_number: 到货单号
      - 设备分类信息：
        - device_category_level1: 设备一级分类
        - device_category_level2: 设备二级分类
        - device_category_level3: 设备三级分类
        - device_count: 设备数量
      - 时间信息：
        - created_at: 创建时间（ISO格式）
        - start_time: 开始时间（ISO格式）
        - expected_completion_time: 期望完成时间（ISO格式）
        - completed_time: 实际完成时间（ISO格式）
        - close_time: 结单时间（ISO格式）
        - updated_at: 更新时间（ISO格式）
      - 扩展信息（从extra字段提取）：
        - priority: 优先级
        - operation_type_detail: 操作类型详情
        - is_business_online: 业务是否在线
        - failure_reason: 失败原因
      - 其他信息：
        - device_count: 设备数量
        - cabinet_count: 机柜数量（电源管理工单特有）
        - process_id: 流程ID
        - external_data: 外部数据（JSON）
        - extra: 扩展信息（JSON，包含各类型特有字段）
        - close_remark: 关闭备注
        - remark: 备注
      - 电源管理工单特有字段（operation_type=power_management时）：
        - power_action: 电源操作类型（"power_on"上电/"power_off"下电）
        - power_type: 电源类型（如"AC"交流电/"DC"直流电，上电时有效）
        - power_reason: 下电原因（下电时必填）
        - cabinet_count: 涉及的机柜数量（自动统计）
        - room_cabinets_info: 房间机柜统计信息（供审核人查看）
          - room_name: 房间名称
          - total_cabinets: 房间总机柜数
          - cabinets_in_work_order: 本工单涉及的机柜数
          - cabinets_not_in_work_order: 未涉及的机柜数
          - cabinets: 机柜详细列表
            - cabinet_name: 机柜名称
            - total_devices: 该机柜总设备数
            - devices_in_work_order: 本工单中的设备数
            - devices_not_in_work_order: 不在本工单中的设备数
            - is_in_work_order: 是否在本工单中
            - work_order_devices: 本工单中该机柜的设备列表
    
    使用场景：
    - 查看工单完整详情
    - 获取工单扩展信息
    - 工单详情页展示
    - 查看racking工单的机柜、机位等信息
    - 查看工单的SLA倒计时
    
    注意事项：
    - 工单ID必须存在，否则返回404
    - extra字段包含扩展信息，可能为空
    - 不同类型的工单，某些字段可能为空（如receiving工单没有机柜信息）
    - sla_countdown为秒数，前端需要转换为可读格式
    """
    try:
        work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到ID为 {work_order_id} 的工单",
                data=None
            )
        
        extra_data = work_order.extra or {}

        work_order_data = {
            "id": work_order.id,
            "batch_id": work_order.batch_id,
            "work_order_number": work_order.work_order_number,
            "work_order_type": work_order.work_order_type,
            "business_id": work_order.business_id,
            "title": work_order.title,
            "description": work_order.description,
            "status": work_order.status,
            "work_order_status": work_order.work_order_status,
            "creator": work_order.creator,
            "assignee": work_order.assignee,
            "operator": work_order.operator,
            "reviewer": work_order.reviewer,
            "inspector": getattr(work_order, "inspector", None),
            # 位置信息
            "datacenter": work_order.datacenter,
            "campus": work_order.campus,
            "room": work_order.room,
            "cabinet": work_order.cabinet,
            "rack_position": work_order.rack_position,
            # 项目和来源信息
            "project_number": work_order.project_number,
            "source_order_number": work_order.source_order_number,
            "arrival_order_number": work_order.arrival_order_number,
            # 分类信息
            "device_category_level1": work_order.device_category_level1,
            "device_category_level2": work_order.device_category_level2,
            "device_category_level3": work_order.device_category_level3,
            # SLA信息
            "sla_countdown": work_order.sla_countdown,
            "is_timeout": work_order.is_timeout,
            "expected_completion_time": work_order.expected_completion_time.isoformat() if work_order.expected_completion_time else None,
            # 扩展信息
            "priority": extra_data.get("priority"),
            "operation_type_detail": extra_data.get("operation_type_detail"),
            "is_business_online": extra_data.get("is_business_online"),
            "failure_reason": extra_data.get("failure_reason"),
            # 时间信息
            "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
            "start_time": work_order.start_time.isoformat() if work_order.start_time else None,
            "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
            "close_time": work_order.close_time.isoformat() if work_order.close_time else None,
            "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None,
            # 其他信息
            "device_count": work_order.device_count,
            "cabinet_count": getattr(work_order, "cabinet_count", None),
            "process_id": getattr(work_order, "process_id", None),
            "external_data": getattr(work_order, "external_data", None),
            "extra": work_order.extra,
            "close_remark": work_order.remark,
            "remark": work_order.remark
        }
        
        # 电源管理工单：提取power_action到顶层，方便前端使用
        if work_order.operation_type == "power_management" or work_order.work_order_type == "power_management":
            work_order_data["power_action"] = extra_data.get("power_action")
            work_order_data["power_type"] = extra_data.get("power_type")
            work_order_data["power_reason"] = extra_data.get("reason")
            
            # 获取该房间的机柜统计信息（供审核人查看）
            if work_order.room:
                try:
                    room_cabinets_info = get_room_cabinets_info(db, work_order.room, work_order.id)
                    work_order_data["room_cabinets_info"] = room_cabinets_info
                except Exception as e:
                    # 如果获取机柜信息失败，不影响主流程
                    work_order_data["room_cabinets_info"] = None
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data=work_order_data
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.get(
    "/number/{work_order_number}",
    summary="根据工单号查询工单",
    response_model=ApiResponse,
    responses={
        200: {"description": "查询成功"},
        404: {"description": "工单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_work_order_by_number(
    work_order_number: str = Path(..., description="工单号", example="WO202512050001"),
    db: Session = Depends(get_db)
):
    """
    根据工单号查询工单详情
    
    功能说明：
    - 根据工单号（work_order_number）查询工单的完整详细信息
    - 返回内容与按ID查询相同
    - 包含所有工单字段：核心标识、状态、人员、位置、项目、分类、时间、扩展信息等
    
    路径参数说明：
    - work_order_number: 工单号（必填，字符串，精确匹配，外部工单系统工单号）
    
    返回字段说明：
    - code: 响应码（0表示成功，404表示未找到）
    - message: 响应消息
    - data: 工单详情对象（完整字段列表同 GET /{work_order_id} 接口）
      - 核心标识：id, batch_id, work_order_number, work_order_type, business_id, title, description
      - 状态信息：status, work_order_status, is_timeout, sla_countdown
      - 人员信息：creator, assignee, operator, reviewer, inspector
      - 位置信息：datacenter, campus, room, cabinet, rack_position
      - 项目和来源：project_number, source_order_number, arrival_order_number
      - 设备分类：device_category_level1, device_category_level2, device_category_level3, device_count
      - 时间信息：created_at, start_time, expected_completion_time, completed_time, close_time, updated_at
      - 扩展信息：priority, operation_type_detail, is_business_online, failure_reason
      - 其他：process_id, external_data, extra, close_remark, remark
    
    使用场景：
    - 通过工单号快速查询工单
    - 外部系统通过工单号对接
    - 用户输入工单号查询
    - 扫码查询工单（工单号二维码）
    
    注意事项：
    - 工单号必须精确匹配
    - 工单号不存在时返回404
    - extra字段包含扩展信息，可能为空
    - 不同类型的工单，某些字段可能为空
    """
    try:
        work_order = db.query(WorkOrder).filter(
            WorkOrder.work_order_number == work_order_number
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到工单号为 {work_order_number} 的工单",
                data=None
            )
        
        extra_data = work_order.extra or {}

        work_order_data = {
            "id": work_order.id,
            "batch_id": work_order.batch_id,
            "work_order_number": work_order.work_order_number,
            "work_order_type": work_order.work_order_type,
            "business_id": work_order.business_id,
            "title": work_order.title,
            "description": work_order.description,
            "status": work_order.status,
            "work_order_status": work_order.work_order_status,
            "creator": work_order.creator,
            "assignee": work_order.assignee,
            "operator": work_order.operator,
            "reviewer": work_order.reviewer,
            "inspector": getattr(work_order, "inspector", None),
            # 位置信息
            "datacenter": work_order.datacenter,
            "campus": work_order.campus,
            "room": work_order.room,
            "cabinet": work_order.cabinet,
            "rack_position": work_order.rack_position,
            # 项目和来源信息
            "project_number": work_order.project_number,
            "source_order_number": work_order.source_order_number,
            "arrival_order_number": work_order.arrival_order_number,
            # 分类信息
            "device_category_level1": work_order.device_category_level1,
            "device_category_level2": work_order.device_category_level2,
            "device_category_level3": work_order.device_category_level3,
            # SLA信息
            "sla_countdown": work_order.sla_countdown,
            "is_timeout": work_order.is_timeout,
            "expected_completion_time": work_order.expected_completion_time.isoformat() if work_order.expected_completion_time else None,
            # 扩展信息
            "priority": extra_data.get("priority"),
            "operation_type_detail": extra_data.get("operation_type_detail"),
            "is_business_online": extra_data.get("is_business_online"),
            "failure_reason": extra_data.get("failure_reason"),
            # 时间信息
            "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
            "start_time": work_order.start_time.isoformat() if work_order.start_time else None,
            "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
            "close_time": work_order.close_time.isoformat() if work_order.close_time else None,
            "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None,
            # 其他信息
            "device_count": work_order.device_count,
            "cabinet_count": getattr(work_order, "cabinet_count", None),
            "process_id": getattr(work_order, "process_id", None),
            "external_data": getattr(work_order, "external_data", None),
            "extra": work_order.extra,
            "close_remark": work_order.remark,
            "remark": work_order.remark
        }
        
        # 电源管理工单：提取power_action到顶层，方便前端使用
        if work_order.operation_type == "power_management" or work_order.work_order_type == "power_management":
            work_order_data["power_action"] = extra_data.get("power_action")
            work_order_data["power_type"] = extra_data.get("power_type")
            work_order_data["power_reason"] = extra_data.get("reason")
            
            # 获取该房间的机柜统计信息（供审核人查看）
            if work_order.room:
                try:
                    room_cabinets_info = get_room_cabinets_info(db, work_order.room, work_order.id)
                    work_order_data["room_cabinets_info"] = room_cabinets_info
                except Exception as e:
                    # 如果获取机柜信息失败，不影响主流程
                    work_order_data["room_cabinets_info"] = None
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data=work_order_data
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )



@router.get(
    "/{work_order_id}/room-cabinets",
    summary="获取电源管理工单的房间机柜信息",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "查询成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "success",
                        "data": {
                            "work_order_id": 123,
                            "work_order_number": "WO202512080001",
                            "operation_type": "power_management",
                            "power_action": "power_on",
                            "room_name": "Room-A",
                            "total_cabinets": 5,
                            "cabinets_in_work_order": 2,
                            "cabinets_not_in_work_order": 3,
                            "cabinets": [
                                {
                                    "cabinet_name": "CAB-001",
                                    "total_devices": 10,
                                    "devices_in_work_order": 3,
                                    "devices_not_in_work_order": 7,
                                    "is_in_work_order": True,
                                    "work_order_devices": [
                                        {
                                            "serial_number": "SN001",
                                            "asset_tag": "AT001",
                                            "name": "Dell R740服务器",
                                            "status": "pending"
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        },
        400: {"description": "不是电源管理工单"},
        404: {"description": "工单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_work_order_room_cabinets(
    work_order_id: int = Path(..., description="工单ID", example=123),
    db: Session = Depends(get_db)
):
    """
    获取电源管理工单的房间机柜详细信息
    
    ## 功能说明
    为审核人员提供工单所在房间的完整机柜信息，包括：
    - 房间内所有机柜的统计
    - 每个机柜的设备分布
    - 本工单涉及和未涉及的机柜对比
    - 每个机柜中本工单涉及的具体设备列表
    
    ## 使用场景
    1. **审核界面**：审核人查看工单时，了解完整的房间机柜情况
    2. **风险评估**：评估本次操作的影响范围
    3. **决策支持**：判断是否需要补充或调整操作范围
    
    ## 路径参数
    - **work_order_id**: 工单ID（必填）
    
    ## 返回字段说明
    
    ### 工单信息
    - **work_order_id**: 工单ID
    - **work_order_number**: 工单号
    - **operation_type**: 操作类型（必须是power_management）
    - **power_action**: 电源操作（power_on/power_off）
    - **room_name**: 房间名称
    - **total_cabinets**: 房间总机柜数
    - **cabinets_in_work_order**: 本工单涉及的机柜数
    - **cabinets_not_in_work_order**: 未涉及的机柜数
    
    ### 机柜详细信息（cabinets数组）
    
    #### 基础标识
    - **cabinet_number**: 机柜编号
    - **cabinet_name**: 机柜名称
    
    #### 位置信息
    - **datacenter**: 机房
    - **room**: 房间
    - **room_number**: 房间号
    
    #### 运营商信息
    - **operator_cabinet_number**: 运营商机柜编号
    
    #### 电源信息
    - **power_type**: 电源类型（如：AC/DC/混合）
    - **pdu_interface_standard**: PDU接口标准
    
    #### 机柜类型
    - **cabinet_type**: 机柜类型（如：服务器机柜/网络机柜/存储机柜）
    - **cabinet_type_detail**: 机柜类型明细
    
    #### 物理规格
    - **width**: 宽度（如：600mm）
    - **size**: 大小/高度（如：42U）
    
    #### 状态信息
    - **power_status**: 上下电状态（power_on/power_off/partial）
    - **usage_status**: 使用状态（in_use/idle/reserved/maintenance）
    - **lifecycle_status**: 生命周期状态（与系统生命周期不同）
    - **module_construction_status**: 模块建设状态
    
    #### 规划信息
    - **planning_category**: 规划大类
    - **construction_density**: 建设密度
    
    #### 操作记录
    - **last_power_operation**: 最后一次电源操作（power_on/power_off）
    - **last_power_operation_date**: 实际上下电日期（ISO格式）
    - **last_operation_result**: 处理结果（success/failed/partial）
    - **last_operation_failure_reason**: 失败原因
    
    #### 设备统计
    - **total_devices**: 该机柜总设备数
    - **devices_in_work_order**: 本工单中的设备数
    - **devices_not_in_work_order**: 不在本工单中的设备数
    - **is_in_work_order**: 是否在本工单中
    - **work_order_devices**: 本工单中该机柜的设备列表
      - **serial_number**: 设备序列号
      - **asset_tag**: 资产标签
      - **name**: 设备名称
      - **status**: 设备在工单中的状态
    
    #### 容量信息
    - **total_u_count**: 总U位数
    - **used_u_count**: 已使用U位数
    - **available_u_count**: 可用U位数
    
    #### 管理信息
    - **responsible_person**: 责任人
    - **notes**: 备注
    
    ## 注意事项
    1. 仅支持电源管理工单（operation_type=power_management）
    2. 如果不是电源管理工单，返回400错误
    3. 机柜信息从设备的location_detail字段提取
    4. 按机柜名称排序返回
    
    ## 前端展示建议
    
    ### 概览卡片
    ```
    房间：Room-A
    总机柜：5个
    本次涉及：2个机柜
    未涉及：3个机柜
    ```
    
    ### 机柜列表
    ```
    ✅ CAB-001 (涉及)
       总设备：10台 | 本次操作：3台 | 未操作：7台
       [查看详情]
    
    ✅ CAB-002 (涉及)
       总设备：8台 | 本次操作：2台 | 未操作：6台
       [查看详情]
    
    ⚪ CAB-003 (未涉及)
       总设备：12台
    
    ⚪ CAB-004 (未涉及)
       总设备：15台
    
    ⚪ CAB-005 (未涉及)
       总设备：9台
    ```
    """
    try:
        # 1. 查询工单
        work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到ID为 {work_order_id} 的工单",
                data=None
            )
        
        # 2. 验证是否为电源管理工单
        if work_order.operation_type != "power_management" and work_order.work_order_type != "power_management":
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message="此接口仅支持电源管理工单",
                data=None
            )
        
        # 3. 验证是否有房间信息
        if not work_order.room:
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message="工单未指定房间信息",
                data=None
            )
        
        # 4. 获取房间机柜信息
        room_cabinets_info = get_room_cabinets_info(db, work_order.room, work_order.id)
        
        # 5. 获取工单的power_action
        extra_data = work_order.extra or {}
        power_action = extra_data.get("power_action")
        
        # 6. 构建返回数据
        result = {
            "work_order_id": work_order.id,
            "work_order_number": work_order.work_order_number,
            "operation_type": work_order.operation_type,
            "power_action": power_action,
            "title": work_order.title,
            "status": work_order.status,
            **room_cabinets_info
        }
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data=result
        )
        
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.put(
    "/{work_order_id}/room-cabinets/update",
    summary="更新电源管理工单的机柜信息（审核人使用）",
    response_model=ApiResponse,
    responses={
        200: {"description": "更新成功"},
        400: {"description": "参数错误或包含禁止更新的字段"},
        404: {"description": "工单或机柜不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def update_work_order_cabinets(
    work_order_id: int = Path(..., description="工单ID"),
    cabinet_updates: dict = Body(..., description="机柜更新信息", example={
        "cabinet_number": "A-01",
        "updates": {
            "power_status": "power_on",
            "last_operation_result": "success",
            "notes": "上电操作成功完成",
            "power_type": "AC",
            "pdu_interface_standard": "C13",
            "cabinet_type": "服务器机柜",
            "usage_status": "in_use"
        }
    }),
    db: Session = Depends(get_db)
):
    """
    更新电源管理工单的机柜信息（供审核人使用）
    
    ## 功能说明
    允许审核人员更新机柜的详细信息，包括：
    - 电源状态、类型、PDU接口标准
    - 机柜类型、类型明细
    - 上下电状态、处理结果、失败原因
    - 物理规格（宽度、大小）
    - 生命周期状态、模块建设状态
    - 规划大类、建设密度、使用状态
    - 运营商机柜编号
    - 容量信息、责任人、备注等
    
    ## 禁止更新的字段
    - **room_number**: 房间号（不可更改）
    - **last_power_operation_date**: 实际上下电日期（不可更改）
    
    ## 路径参数
    - **work_order_id**: 工单ID（必填）
    
    ## 请求体参数
    - **cabinet_number**: 机柜编号（必填）
    - **updates**: 要更新的字段（必填），可包含以下字段：
      - **datacenter**: 机房
      - **room**: 房间
      - **operator_cabinet_number**: 运营商机柜编号
      - **power_type**: 电源类型
      - **pdu_interface_standard**: PDU接口标准
      - **cabinet_type**: 机柜类型
      - **cabinet_type_detail**: 机柜类型明细
      - **width**: 宽度
      - **size**: 大小
      - **power_status**: 上下电状态
      - **usage_status**: 使用状态
      - **lifecycle_status**: 生命周期状态
      - **module_construction_status**: 模块建设状态
      - **planning_category**: 规划大类
      - **construction_density**: 建设密度
      - **last_power_operation**: 最后一次电源操作
      - **last_operation_result**: 处理结果
      - **last_operation_failure_reason**: 失败原因
      - **total_u_count**: 总U位数
      - **used_u_count**: 已使用U位数
      - **available_u_count**: 可用U位数
      - **responsible_person**: 责任人
      - **notes**: 备注
    
    ## 使用场景
    1. 审核人更新机柜的电源状态和操作结果
    2. 记录机柜的详细配置信息
    3. 更新机柜的使用状态和容量信息
    
    ## 注意事项
    1. 仅支持电源管理工单
    2. 如果机柜不存在，会自动创建
    3. 禁止更新 room_number 和 last_power_operation_date 字段
    4. 更新时会自动记录更新时间
    """
    try:
        # 定义禁止更新的字段
        FORBIDDEN_FIELDS = {"room_number", "last_power_operation_date"}
        
        # 1. 验证请求参数
        if "cabinet_number" not in cabinet_updates:
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message="缺少必填参数: cabinet_number",
                data=None
            )
        
        if "updates" not in cabinet_updates:
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message="缺少必填参数: updates",
                data=None
            )
        
        cabinet_number = cabinet_updates["cabinet_number"]
        updates = cabinet_updates["updates"]
        
        # 2. 检查是否包含禁止更新的字段
        forbidden_found = FORBIDDEN_FIELDS.intersection(updates.keys())
        if forbidden_found:
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message=f"禁止更新以下字段: {', '.join(forbidden_found)}",
                data={"forbidden_fields": list(forbidden_found)}
            )
        
        # 3. 查询工单
        work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到ID为 {work_order_id} 的工单",
                data=None
            )
        
        # 4. 验证是否为电源管理工单
        if work_order.operation_type != "power_management" and work_order.work_order_type != "power_management":
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message="此接口仅支持电源管理工单",
                data=None
            )
        
        # 5. 查询或创建机柜
        cabinet = db.query(Cabinet).filter(Cabinet.cabinet_number == cabinet_number).first()
        
        if not cabinet:
            # 如果机柜不存在，创建新机柜
            cabinet = Cabinet(
                cabinet_number=cabinet_number,
                datacenter=work_order.datacenter,
                room=work_order.room,
                created_by=work_order.creator
            )
            db.add(cabinet)
            db.flush()  # 获取新创建的ID
        
        # 6. 更新机柜字段
        updated_fields = []
        for field, value in updates.items():
            if hasattr(cabinet, field):
                setattr(cabinet, field, value)
                updated_fields.append(field)
        
        # 7. 提交更新
        db.commit()
        db.refresh(cabinet)
        
        # 8. 返回更新结果
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="机柜信息更新成功",
            data={
                "cabinet_id": cabinet.id,
                "cabinet_number": cabinet.cabinet_number,
                "updated_fields": updated_fields,
                "updated_count": len(updated_fields)
            }
        )
        
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"更新失败: {str(e)}",
            data=None
        )
