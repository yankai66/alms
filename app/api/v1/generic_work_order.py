"""
万能类操作工单管理API
提供创建、查询、处理万能类操作工单的功能

使用示例：
1. 创建工单：POST /api/v1/network-issue-work-order/create
   {
     "title": "核心交换机故障处理",
     "datacenter": "DC01",
     "priority": "urgent",  # normal-一般, urgent-紧急
     "business_type": "fault_support",  # fault_support-故障支持, change_support-变更支持, other-其他
     "device_sns": ["SN001"],
     "service_content": "检查交换机日志并更换故障模块",  # 必填
     "assignee": "张三",  # 必填
     "operation_type": "production_network"  # 可选：production_network-生产网线, oob_network-带外网线
   }

2. 查询工单：GET /api/v1/network-issue-work-order/query?datacenter=DC01&priority=urgent

3. 查询详情：GET /api/v1/network-issue-work-order/detail/{batch_id}

4. 处理工单：POST /api/v1/network-issue-work-order/process
   {
     "batch_id": "GEN_20231205143022",
     "operator": "王五",
     "processing_result": "已完成故障排查，系统恢复正常",
     "is_complete": true
   }
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func, cast, String
from typing import Optional, Dict, Any, List
from datetime import datetime
import httpx
import json

from app.db.session import get_db
from app.models.asset_models import Asset, WorkOrder, WorkOrderItem, Room
from app.schemas.asset_schemas import ApiResponse, ResponseCode
from app.schemas.generic_work_order_schemas import (
    GenericWorkOrderCreate,
    GenericWorkOrderResponse,
    GenericWorkOrderQuery,
    GenericWorkOrderProcess
)
from app.core.config import settings
from app.core.logging_config import get_logger
from app.constants.operation_types import OperationType, OperationResult

router = APIRouter()
logger = get_logger(__name__)

# =====================================================
# 工单系统集成
# =====================================================

async def create_external_generic_work_order(
    work_order_data: GenericWorkOrderCreate,
    batch_id: str,
    creator_name: str = "system"
) -> Dict[str, Any]:
    """
    调用外部工单系统创建万能类操作工单
    
    参数:
    - work_order_data: 工单数据
    - batch_id: 批次ID
    - creator_name: 创建人姓名
    
    返回:
    - 工单创建结果
    """
    try:
        # 构建工单请求数据
        priority_value = str(work_order_data.priority)
        work_order_type_value = str(work_order_data.work_order_type)
        business_type_value = str(work_order_data.business_type)
        operation_type_value = str(work_order_data.operation_type) if work_order_data.operation_type else None
        device_sns = work_order_data.device_sns or []
        device_sn_text = ", ".join(device_sns) if device_sns else "无"
        
        # 构建描述信息
        description_parts = [
            f"工单类型: {work_order_type_value}",
            f"业务类型: {business_type_value}",
            f"机房: {work_order_data.datacenter}",
            f"优先级: {priority_value}",
        ]
        if device_sns:
            description_parts.append(f"设备SN: {device_sn_text}")
        
        if operation_type_value:
            description_parts.insert(1, f"操作类型: {operation_type_value}")
        
        if work_order_data.source_order_number:
            description_parts.append(f"来源单号: {work_order_data.source_order_number}")
        if work_order_data.operation_type_detail:
            description_parts.append(f"操作类型: {work_order_data.operation_type_detail}")
        if work_order_data.is_business_online is not None:
            description_parts.append(f"业务是否在线: {'是' if work_order_data.is_business_online else '否'}")
        if work_order_data.service_content:
            description_parts.append(f"服务内容: {work_order_data.service_content}")
        if work_order_data.remark:
            description_parts.append(f"备注: {work_order_data.remark}")
        
        # 构建variables
        variables = {
            "assignee": work_order_data.assignee
        }
        
        # 构建metadata（简化版）
        metadata = {
            "orderType": "universal_order",  # 万能类操作工单
            "assignee": work_order_data.assignee
        }
        
        work_order_request = {
            "title": work_order_data.title,
            "description": "\n".join(description_parts),
            "secretInfo": "11111",
            "creator": settings.WORK_ORDER_CREATOR,
            "creatorName": creator_name,
            "processId": "universalOrder",  # 万能类操作工单专用流程
            "variables": variables,
            "externalBizId": batch_id,
            "bussinessMetaData": metadata
        }
        
        # 发送HTTP请求
        timeout = httpx.Timeout(60.0, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            print(f"[万能类操作工单创建] 正在连接工单系统: {settings.WORK_ORDER_API_URL}")
            print(f"[万能类操作工单创建] 请求报文: {json.dumps(work_order_request, ensure_ascii=False)}")
            
            headers = {
                "appid": settings.WORK_ORDER_APPID,
                "username": settings.WORK_ORDER_USERNAME,
                "Content-Type": "application/json"
            }
            if settings.WORK_ORDER_COOKIE:
                headers["Cookie"] = settings.WORK_ORDER_COOKIE

            response = await client.post(
                settings.WORK_ORDER_API_URL,
                headers=headers,
                json=work_order_request
            )
            
            response.raise_for_status()
            result = response.json()
            print(f"[万能类操作工单创建] 外部系统响应: {json.dumps(result, ensure_ascii=False)}")

            # 检查响应状态
            if result.get("status") != 0:
                error_msg = result.get("msg") or result.get("message") or "工单系统返回失败"
                print(f"[万能类操作工单创建失败] 状态码: {result.get('status')}, 错误信息: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "data": result
                }

            # 提取工单号
            work_order_number = None
            if result.get("data"):
                work_order_number = result.get("data", {}).get("order_number")

            return {
                "success": True,
                "data": result,
                "work_order_number": work_order_number
            }
            
    except httpx.HTTPStatusError as e:
        error_msg = f"工单系统返回错误: {e.response.status_code} - {e.response.text}"
        print(f"[万能类操作工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "status_code": e.response.status_code
        }
    except httpx.RequestError as e:
        error_detail = str(e) if str(e) else f"连接失败: {type(e).__name__}"
        error_msg = f"工单系统请求失败: {error_detail}"
        print(f"[万能类操作工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "url": settings.WORK_ORDER_API_URL
        }
    except Exception as e:
        error_msg = f"工单创建异常: {str(e)}"
        print(f"[万能类操作工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }


# =====================================================
# 工单管理接口
# =====================================================

@router.post("/create", summary="创建万能类操作工单",
             response_model=ApiResponse,
             responses={
                 200: {
                     "description": "工单创建成功",
                     "content": {
                         "application/json": {
                             "examples": {
                                 "operation": {
                                     "summary": "操作类工单示例",
                                     "value": {
                                         "code": 0,
                                         "message": "工单创建成功",
                                         "data": {
                                             "work_order_number": "WO202512051234",
                                             "batch_id": "GEN_20251205120000",
                                             "title": "设备巡检",
                                             "work_order_type": "operation",
                                             "operation_sub_type": "inspection",
                                             "estimated_operation_time": "2025-12-10 14:00",
                                             "sop": "1. 检查设备\n2. 记录结果",
                                             "remark": "定期巡检"
                                         }
                                     }
                                 },
                                 "non_operation": {
                                     "summary": "非操作类工单示例",
                                     "value": {
                                         "code": 0,
                                         "message": "工单创建成功",
                                         "data": {
                                             "work_order_number": "WO202512051235",
                                             "batch_id": "GEN_20251205120001",
                                             "title": "设备维护",
                                             "work_order_type": "non_operation",
                                             "operation_sub_type": "inspection",
                                             "estimated_operation_time": "2025-12-10 14:00",
                                             "execution_location": "DC01-园区A-包间B",
                                             "remark": "定期维护",
                                             "precautions": "注意安全"
                                         }
                                     }
                                 }
                             }
                         }
                     }
                 },
                 400: {"description": "参数错误"},
                 404: {"description": "设备SN不存在"},
                 500: {"description": "服务器内部错误"}
             })
async def create_generic_work_order(
    work_order_data: GenericWorkOrderCreate = Body(...,
        examples={
            "operation": {
                "summary": "操作类工单",
                "value": {
                    "title": "设备巡检",
                    "datacenter": "DC01",
                    "work_order_type": "operation",
                    "device_sns": ["SN123456"],
                    "assignee": "张三",
                    "operation_sub_type": "inspection",
                    "estimated_operation_time": "2025-12-10 14:00",
                    "sop": "1. 检查设备外观\n2. 检查设备运行状态\n3. 记录巡检结果",
                    "remark": "定期巡检"
                }
            },
            "non_operation": {
                "summary": "非操作类工单",
                "value": {
                    "title": "设备维护",
                    "datacenter": "DC01",
                    "work_order_type": "non_operation",
                    "device_sns": ["SN123456"],
                    "assignee": "李四",
                    "operation_sub_type": "inspection",
                    "estimated_operation_time": "2025-12-10 14:00",
                    "execution_location": "DC01-园区A-包间B",
                    "remark": "定期维护",
                    "precautions": "注意安全，断电操作"
                }
            },
            "asset": {
                "summary": "资产类工单",
                "value": {
                    "title": "资产盘点",
                    "datacenter": "DC01",
                    "work_order_type": "asset",
                    "device_sns": ["SN123456", "SN789012"],
                    "assignee": "王五",
                    "operation_sub_type": "asset_collaboration",
                    "estimated_operation_time": "2025-12-10 14:00",
                    "execution_location": "DC01-园区A-包间B",
                    "remark": "年度资产盘点",
                    "precautions": "仔细核对资产信息"
                }
            }
        }),
    db: Session = Depends(get_db)
):
    """
    创建万能类操作工单
    
    ## 工单类型
    系统支持三种工单类型，每种类型的必填字段不同：
    
    ### 1. 操作类工单 (work_order_type="operation")
    **必填字段 (9个):**
    - title: 工单标题
    - datacenter: 机房
    - work_order_type: 工单类型 (operation)
    - device_sns: 设备SN列表
    - assignee: 指派人
    - operation_sub_type: 操作子类型 (project_follow/inspection/onsite_collaboration等)
    - estimated_operation_time: 预计操作时间 (格式: YYYY-MM-DD HH:MM)
    - sop: SOP标准操作流程
    - remark: 备注
    
    ### 2. 非操作类工单 (work_order_type="non_operation")
    **必填字段 (9个):**
    - title: 工单标题
    - datacenter: 机房
    - work_order_type: 工单类型 (non_operation)
    - device_sns: 设备SN列表
    - assignee: 指派人
    - operation_sub_type: 操作类型
    - estimated_operation_time: 预计操作时间
    - execution_location: 执行包间（包括机房、园区、包间）
    - remark: 备注
    - precautions: 注意事项
    
    ### 3. 资产类工单 (work_order_type="asset")
    **必填字段 (9个):** 与非操作类工单完全相同
    
    ## 可选字段
    - priority: 优先级 (normal/urgent)
    - business_type: 业务类型 (fault_support/change_support/other)
    - service_content: 服务内容
    - source_order_number: 来源单号
    - operation_type: 操作类型 (production_network/oob_network)
    - operation_type_detail: 操作类型详情
    - is_business_online: 业务是否在线
    - creator_name: 创建人姓名
    
    ## 返回数据
    - work_order_number: 外部工单系统返回的工单号
    - batch_id: 本地批次ID (格式: GEN_YYYYMMDDHHMMSS)
    - 其他工单详细信息
    
    ## 注意事项
    1. 所有设备SN必须在系统中存在
    2. 不同工单类型的必填字段不同，请参考上述说明
    3. operation_sub_type 字段在操作类工单中称为"操作子类型"，在非操作类/资产类工单中称为"操作类型"
    4. 工单创建后会同时保存到本地数据库和外部工单系统
    """
    try:
        # 操作类工单,校验device_sns参数
        if work_order_data.work_order_type == "operation" and not work_order_data.device_sns:
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message=f"设备信息 '{work_order_data.device_sns}' 不存在",
                data={"device_sns": "List should have at least 1 item"}
            )

        # 1. 验证机房是否存在
        datacenter_exists = db.query(Room).filter(
            Room.datacenter_abbreviation == work_order_data.datacenter
        ).first()
        
        if not datacenter_exists:
            # 获取所有可用的机房列表
            valid_datacenters = db.query(Room.datacenter_abbreviation).distinct().all()
            valid_list = [dc[0] for dc in valid_datacenters if dc[0]]
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message=f"机房 '{work_order_data.datacenter}' 不存在",
                data={"valid_datacenters": valid_list[:20]}
            )

        # 2. 验证设备是否存在（如果提供了SN）
        missing_sns = []
        existing_assets = {}

        device_sns = work_order_data.device_sns or []
        for sn in device_sns:
            asset = db.query(Asset).filter(Asset.serial_number == sn).first()
            if not asset:
                missing_sns.append(sn)
            else:
                existing_assets[sn] = asset
        
        if missing_sns:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"以下设备SN不存在: {', '.join(missing_sns[:10])}{'...' if len(missing_sns) > 10 else ''}",
                data={"missing_sns": missing_sns}
            )
        
        # 2. 生成批次ID (使用NIC前缀: Network Issue Coordination)
        batch_id = f"GEN_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 3. 创建外部工单
        creator_name = work_order_data.creator_name or "system"
        work_order_result = await create_external_generic_work_order(
            work_order_data,
            batch_id,
            creator_name
        )
        
        if not work_order_result.get("success"):
            # 记录工单创建失败日志
            operation_type_log = f", 操作类型: {work_order_data.operation_type}" if work_order_data.operation_type else ""
            logger.error("万能类操作工单创建失败", extra={
                "operationObject": work_order_data.title,
                "operationType": OperationType.GENERIC_WORK_ORDER_CREATE,
                "operator": creator_name,
                "result": OperationResult.FAILED,
                "operationDetail": f"机房: {work_order_data.datacenter}, 优先级: {work_order_data.priority}, 业务类型: {work_order_data.business_type}{operation_type_log}, 指派人: {work_order_data.assignee}, 错误: {work_order_result.get('error', '未知错误')}"
            })
            return ApiResponse(
                code=ResponseCode.INTERNAL_ERROR,
                message=work_order_result.get("error", "工单创建失败"),
                data=work_order_result
            )
        
        # 4. 保存工单到本地数据库
        work_order_number = work_order_result.get("work_order_number")
        
        # 构建extra字段
        extra_data = {
            "priority": str(work_order_data.priority),
            "work_order_type": str(work_order_data.work_order_type),
            "business_type": str(work_order_data.business_type),
            "device_sns": device_sns,
            "service_content": work_order_data.service_content,
            "operation_type_detail": work_order_data.operation_type_detail,
            "is_business_online": work_order_data.is_business_online,
            "operation_sub_type": str(work_order_data.operation_sub_type) if work_order_data.operation_sub_type else None,
            "estimated_operation_time": work_order_data.estimated_operation_time,
            "sop": work_order_data.sop,
            "execution_location": work_order_data.execution_location,
            "precautions": work_order_data.precautions
        }
        
        if work_order_data.operation_type:
            extra_data["operation_type"] = str(work_order_data.operation_type)
        
        # 创建本地工单记录
        description_text = f"工单类型: {work_order_data.work_order_type}\n业务类型: {work_order_data.business_type}\n机房: {work_order_data.datacenter}\n优先级: {work_order_data.priority}\n设备数量: {len(device_sns)}"
        if work_order_data.operation_type:
            description_text = f"工单类型: {work_order_data.work_order_type}\n业务类型: {work_order_data.business_type}\n操作类型: {work_order_data.operation_type}\n机房: {work_order_data.datacenter}\n优先级: {work_order_data.priority}\n设备数量: {len(device_sns)}"
        
        # 根据工单类型设置operation_type
        operation_type_mapping = {
            "operation": "generic_operation",  # 操作类工单
            "non_operation": "generic_non_operation",  # 非操作类工单
            "asset": "generic_asset"  # 资产类工单
        }
        operation_type_value = operation_type_mapping.get(str(work_order_data.work_order_type), "generic_request")
        
        local_work_order = WorkOrder(
            batch_id=batch_id,
            work_order_number=work_order_number,
            operation_type=operation_type_value,
            title=work_order_data.title,
            description=description_text,
            status="pending",
            creator=creator_name,
            assignee=work_order_data.assignee,
            datacenter=work_order_data.datacenter,
            source_order_number=work_order_data.source_order_number,
            device_count=len(device_sns),
            extra=extra_data,
            remark=work_order_data.remark
        )
        
        try:
            db.add(local_work_order)
            db.flush()  # 获取工单ID
            
            # 5. 创建工单明细（每台设备一条，如果有SN的话）
            for sn in device_sns:
                asset = existing_assets[sn]
                
                # 构建operation_data
                operation_data = {
                    "serial_number": sn,
                    "asset_tag": asset.asset_tag,
                    "asset_name": asset.name,
                    "datacenter": work_order_data.datacenter,
                    "priority": str(work_order_data.priority),
                    "business_type": str(work_order_data.business_type),
                    "service_content": work_order_data.service_content,
                    "operation_type_detail": work_order_data.operation_type_detail,
                    "is_business_online": work_order_data.is_business_online
                }
                
                if work_order_data.operation_type:
                    operation_data["operation_type"] = str(work_order_data.operation_type)
                
                work_order_item = WorkOrderItem(
                    work_order_id=local_work_order.id,
                    asset_id=asset.id,
                    asset_sn=sn,
                    asset_tag=asset.asset_tag,
                    operation_data=operation_data,
                    status="pending",
                    item_datacenter=work_order_data.datacenter
                )
                db.add(work_order_item)
            
            db.commit()
            db.refresh(local_work_order)
            print(f"[万能类操作工单] 本地工单记录已保存: ID={local_work_order.id}, 工单号={work_order_number}")
            
        except Exception as e:
            db.rollback()
            print(f"[警告] 保存本地工单记录失败: {str(e)}")
            # 不影响外部工单创建的成功返回
        
        # 6. 记录工单创建成功日志
        remark_parts = []
        if work_order_data.remark:
            remark_parts.append(work_order_data.remark)
        else:
            remark_parts.append(f"机房: {work_order_data.datacenter}, 优先级: {work_order_data.priority}, 设备数量: {len(device_sns)}")
        
        logger.info("万能类操作工单创建成功", extra={
            "operationObject": work_order_number or batch_id,
            "operationType": OperationType.GENERIC_WORK_ORDER_CREATE,
            "operator": creator_name,
            "result": OperationResult.SUCCESS,
            "operationDetail": (
                f"操作内容: 建单(Create Ticket), 工单号: {work_order_number or batch_id}, "
                f"工单标题: {work_order_data.title}, 机房: {work_order_data.datacenter}, "
                f"来源单号: {work_order_data.source_order_number or '未提供'}, 备注: {', '.join(remark_parts)}"
            )
        })
        
        # 7. 构建响应数据
        response_data = GenericWorkOrderResponse(
            work_order_number=work_order_number,
            batch_id=batch_id,
            title=work_order_data.title,
            datacenter=work_order_data.datacenter,
            priority=str(work_order_data.priority),
            work_order_type=str(work_order_data.work_order_type),
            business_type=str(work_order_data.business_type),
            operation_type=str(work_order_data.operation_type) if work_order_data.operation_type else None,
            source_order_number=work_order_data.source_order_number,
            operation_type_detail=work_order_data.operation_type_detail,
            is_business_online=work_order_data.is_business_online,
            operation_sub_type=str(work_order_data.operation_sub_type) if work_order_data.operation_sub_type else None,
            estimated_operation_time=work_order_data.estimated_operation_time,
            sop=work_order_data.sop,
            execution_location=work_order_data.execution_location,
            precautions=work_order_data.precautions,
            device_sns=device_sns,
            service_content=work_order_data.service_content,
            assignee=work_order_data.assignee,
            status="pending",
            remark=work_order_data.remark,
            created_at=local_work_order.created_at if local_work_order else datetime.now()
        )
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="工单创建成功",
            data=response_data.dict()
        )
        
    except ValueError as e:
        # 记录参数验证失败日志
        logger.error("万能类操作工单创建参数验证失败", extra={
            "operationObject": work_order_data.title if 'work_order_data' in locals() else "未知工单",
            "operationType": OperationType.GENERIC_WORK_ORDER_CREATE,
            "operator": work_order_data.creator_name if 'work_order_data' in locals() and work_order_data.creator_name else "system",
            "result": OperationResult.FAILED,
            "operationDetail": f"参数验证失败: {str(e)}"
        })
        return ApiResponse(
            code=ResponseCode.PARAM_ERROR,
            message=f"参数验证失败: {str(e)}",
            data=None
        )
    except Exception as e:
        db.rollback()
        # 记录系统异常日志
        logger.error("万能类操作工单创建系统异常", extra={
            "operationObject": work_order_data.title if 'work_order_data' in locals() else "未知工单",
            "operationType": OperationType.GENERIC_WORK_ORDER_CREATE,
            "operator": work_order_data.creator_name if 'work_order_data' in locals() and work_order_data.creator_name else "system",
            "result": OperationResult.FAILED,
            "operationDetail": f"系统异常: {str(e)}"
        })
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"创建工单失败: {str(e)}",
            data=None
        )


@router.get("/query", summary="查询万能类操作工单",
            response_model=ApiResponse,
            responses={
                200: {
                    "description": "查询成功",
                    "content": {
                        "application/json": {
                            "example": {
                                "code": 0,
                                "message": "查询成功",
                                "data": {
                                    "work_orders": [
                                        {
                                            "work_order_number": "WO202512051234",
                                            "batch_id": "GEN_20251205120000",
                                            "title": "设备巡检",
                                            "work_order_type": "operation",
                                            "status": "pending",
                                            "assignee": "张三",
                                            "created_at": "2025-12-05T10:00:00"
                                        }
                                    ],
                                    "total": 100,
                                    "page": 1,
                                    "size": 10,
                                    "pages": 10
                                }
                            }
                        }
                    }
                }
            })
async def query_generic_work_orders(
    work_order_number: Optional[str] = Query(None, description="工单号（精确匹配）", example="WO202512051234"),
    batch_id: Optional[str] = Query(None, description="批次ID（精确匹配）", example="GEN_20251205120000"),
    datacenter: Optional[str] = Query(None, description="机房（模糊匹配）", example="DC01"),
    priority: Optional[str] = Query(None, description="优先级（normal/urgent）", example="urgent"),
    work_order_type: Optional[str] = Query(None, description="工单类型（operation/non_operation/asset）", example="operation"),
    business_type: Optional[str] = Query(None, description="业务类型（fault_support/change_support/other）", example="fault_support"),
    operation_type: Optional[str] = Query(None, description="操作类型（production_network/oob_network）", example="production_network"),
    operation_sub_type: Optional[str] = Query(None, description="操作子类型", example="inspection"),
    status: Optional[str] = Query(None, description="状态（pending/processing/completed）", example="pending"),
    assignee: Optional[str] = Query(None, description="指派人（模糊匹配）", example="张三"),
    device_sn: Optional[str] = Query(None, description="设备SN（通过工单明细关联查询）", example="SN123456"),
    created_from: Optional[datetime] = Query(None, description="创建时间起始", example="2025-12-01T00:00:00"),
    created_to: Optional[datetime] = Query(None, description="创建时间结束", example="2025-12-31T23:59:59"),
    page: int = Query(1, ge=1, description="页码（从1开始）", example=1),
    size: int = Query(10, ge=1, le=10000, description="每页数量（1-10000）", example=10),
    db: Session = Depends(get_db)
):
    """
    查询万能类操作工单列表
    
    ## 查询条件
    
    ### 精确匹配
    - **work_order_number**: 工单号
    - **batch_id**: 批次ID
    - **priority**: 优先级
    - **work_order_type**: 工单类型
    - **business_type**: 业务类型
    - **operation_type**: 操作类型
    - **operation_sub_type**: 操作子类型
    - **status**: 工单状态
    
    ### 模糊匹配
    - **datacenter**: 机房（支持部分匹配）
    - **assignee**: 指派人（支持部分匹配）
    
    ### 关联查询
    - **device_sn**: 设备SN（通过工单明细表关联查询）
    
    ### 时间范围
    - **created_from**: 创建时间起始（包含）
    - **created_to**: 创建时间结束（包含）
    
    ## 分页参数
    - **page**: 页码（从1开始，默认1）
    - **size**: 每页数量（1-100，默认10）
    
    ## 返回数据
    - **work_orders**: 工单列表
    - **total**: 总记录数
    - **page**: 当前页码
    - **size**: 每页数量
    - **pages**: 总页数
    
    ## 使用示例
    ```
    # 查询所有操作类工单
    GET /api/v1/generic-work-order/query?work_order_type=operation
    
    # 查询指定机房的紧急工单
    GET /api/v1/generic-work-order/query?datacenter=DC01&priority=urgent
    
    # 查询指定设备的工单
    GET /api/v1/generic-work-order/query?device_sn=SN123456
    
    # 查询时间范围内的工单
    GET /api/v1/generic-work-order/query?created_from=2025-12-01T00:00:00&created_to=2025-12-31T23:59:59
    ```
    
    ## 注意事项
    1. 所有查询条件都是可选的，不提供条件则查询所有工单
    2. 多个条件之间是AND关系
    3. 结果按创建时间倒序排列
    4. 支持查询所有三种工单类型（operation/non_operation/asset）
    """
    try:
        # 构建查询条件 - 查询所有万能工单类型
        query = db.query(WorkOrder).filter(
            WorkOrder.operation_type.in_([
                "generic_operation",
                "generic_non_operation", 
                "generic_asset",
                "generic_request"  # 兼容旧数据
            ])
        )
        
        if work_order_number:
            query = query.filter(WorkOrder.work_order_number == work_order_number)
        
        if batch_id:
            query = query.filter(WorkOrder.batch_id == batch_id)
        
        if datacenter:
            query = query.filter(WorkOrder.datacenter.like(f"%{datacenter}%"))
        
        if status:
            query = query.filter(WorkOrder.status == status)
        
        if assignee:
            query = query.filter(WorkOrder.assignee.like(f"%{assignee}%"))
        
        if created_from:
            query = query.filter(WorkOrder.created_at >= created_from)
        
        if created_to:
            query = query.filter(WorkOrder.created_at <= created_to)
        
        # 通过extra字段过滤 (使用cast来处理JSON字段)
        if priority:
            query = query.filter(cast(WorkOrder.extra['priority'], String) == priority)
        
        if work_order_type:
            query = query.filter(cast(WorkOrder.extra['work_order_type'], String) == work_order_type)
        
        if business_type:
            query = query.filter(cast(WorkOrder.extra['business_type'], String) == business_type)
        
        if operation_type:
            query = query.filter(cast(WorkOrder.extra['operation_type'], String) == operation_type)
        
        if operation_sub_type:
            query = query.filter(cast(WorkOrder.extra['operation_sub_type'], String) == operation_sub_type)
        
        # 如果指定了设备SN，需要通过工单明细关联查询
        if device_sn:
            query = query.join(WorkOrderItem).filter(
                WorkOrderItem.asset_sn == device_sn
            )
        
        # 统计总数
        total = query.count()
        
        # 分页查询
        work_orders = query.order_by(WorkOrder.created_at.desc()).offset((page - 1) * size).limit(size).all()
        
        # 构建响应数据
        work_orders_data = []
        for wo in work_orders:
            # 获取设备SN列表
            device_sns = wo.extra.get('device_sns', []) if wo.extra else []
            
            work_orders_data.append({
                "work_order_number": wo.work_order_number,
                "batch_id": wo.batch_id,
                "title": wo.title,
                "datacenter": wo.datacenter,
                "priority": wo.extra.get('priority') if wo.extra else None,
                "work_order_type": wo.extra.get('work_order_type') if wo.extra else None,
                "business_type": wo.extra.get('business_type') if wo.extra else None,
                "operation_type": wo.extra.get('operation_type') if wo.extra else None,
                "operation_sub_type": wo.extra.get('operation_sub_type') if wo.extra else None,
                "estimated_operation_time": wo.extra.get('estimated_operation_time') if wo.extra else None,
                "sop": wo.extra.get('sop') if wo.extra else None,
                "execution_location": wo.extra.get('execution_location') if wo.extra else None,
                "precautions": wo.extra.get('precautions') if wo.extra else None,
                "source_order_number": wo.source_order_number,
                "operation_type_detail": wo.extra.get('operation_type_detail') if wo.extra else None,
                "is_business_online": wo.extra.get('is_business_online') if wo.extra else None,
                "device_sns": device_sns,
                "device_count": wo.device_count,
                "service_content": wo.extra.get('service_content') if wo.extra else None,
                "assignee": wo.assignee,
                "status": wo.status,
                "work_order_status": wo.work_order_status,
                "remark": wo.remark,  # 创建时的备注
                "processing_result": wo.extra.get('processing_result') if wo.extra else None,  # 处理结果
                "failure_reason": wo.extra.get('failure_reason') if wo.extra else None,  # 失败原因
                "accept_remark": wo.extra.get('accept_remark') if wo.extra else None,  # 接单备注
                "creator": wo.creator,
                "operator": wo.operator,  # 处理人
                "created_at": wo.created_at.isoformat() if wo.created_at else None,
                "completed_time": wo.completed_time.isoformat() if wo.completed_time else None,
                "close_time": wo.close_time.isoformat() if wo.close_time else None
            })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="查询成功",
            data={
                "work_orders": work_orders_data,
                "total": total,
                "page": page,
                "size": size,
                "pages": (total + size - 1) // size
            }
        )
        
    except Exception as e:
        logger.error(f"查询万能类操作工单失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询工单失败: {str(e)}",
            data=None
        )


@router.get("/detail/{batch_id}", summary="查询万能类操作工单详情",
            response_model=ApiResponse,
            responses={
                200: {
                    "description": "查询成功",
                    "content": {
                        "application/json": {
                            "example": {
                                "code": 0,
                                "message": "查询成功",
                                "data": {
                                    "work_order_number": "WO202512051234",
                                    "batch_id": "GEN_20251205120000",
                                    "title": "设备巡检",
                                    "datacenter": "DC01",
                                    "work_order_type": "operation",
                                    "operation_sub_type": "inspection",
                                    "estimated_operation_time": "2025-12-10 14:00",
                                    "sop": "1. 检查设备\n2. 记录结果",
                                    "remark": "定期巡检",
                                    "assignee": "张三",
                                    "status": "pending",
                                    "created_at": "2025-12-05T10:00:00",
                                    "devices": [
                                        {
                                            "serial_number": "SN123456",
                                            "asset_tag": "AT123456",
                                            "asset_name": "测试服务器",
                                            "item_status": "pending",
                                            "result": None,
                                            "error_message": None
                                        }
                                    ],
                                    "device_count": 1
                                }
                            }
                        }
                    }
                },
                404: {"description": "工单不存在"}
            })
async def get_generic_work_order_detail(
    batch_id: str = Path(..., description="批次ID", example="GEN_20251205120000"),
    db: Session = Depends(get_db)
):
    """
    查询万能类操作工单详情（包含设备明细）
    
    ## 功能说明
    根据批次ID查询工单的完整信息，包括：
    - 工单基本信息
    - 工单状态和处理信息
    - 关联的设备列表及每个设备的处理状态
    
    ## 路径参数
    - **batch_id**: 批次ID（必填）
      - 格式: GEN_YYYYMMDDHHMMSS
      - 示例: GEN_20251205120000
    
    ## 返回数据
    
    ### 工单基本信息
    - work_order_number: 工单号
    - batch_id: 批次ID
    - title: 工单标题
    - datacenter: 机房
    - work_order_type: 工单类型
    - status: 工单状态
    - assignee: 指派人
    - creator: 创建人
    - operator: 处理人
    
    ### 工单类型相关字段
    **操作类工单:**
    - operation_sub_type: 操作子类型
    - estimated_operation_time: 预计操作时间
    - sop: SOP标准操作流程
    - remark: 备注
    
    **非操作类/资产类工单:**
    - operation_sub_type: 操作类型
    - estimated_operation_time: 预计操作时间
    - execution_location: 执行包间
    - remark: 备注
    - precautions: 注意事项
    
    ### 处理信息
    - processing_result: 处理结果
    - failure_reason: 失败原因
    - accept_remark: 接单备注
    - close_remark: 结单备注
    
    ### 时间信息
    - created_at: 创建时间
    - completed_time: 完成时间
    - close_time: 结单时间
    
    ### 设备明细
    - devices: 设备列表
      - serial_number: 设备SN
      - asset_tag: 资产标签
      - asset_name: 设备名称
      - item_status: 设备处理状态
      - result: 处理结果
      - error_message: 错误信息
      - executed_at: 执行时间
      - executed_by: 执行人
    - device_count: 设备总数
    
    ## 使用示例
    ```
    GET /api/v1/generic-work-order/detail/GEN_20251205120000
    ```
    
    ## 注意事项
    1. batch_id 必须是有效的批次ID
    2. 返回的字段根据工单类型会有所不同
    3. 设备明细包含每个设备的独立处理状态
    """
    try:
        # 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.batch_id == batch_id,
            WorkOrder.operation_type.in_([
                "generic_operation",
                "generic_non_operation",
                "generic_asset",
                "generic_request"  # 兼容旧数据
            ])
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到批次ID为 {batch_id} 的工单",
                data=None
            )
        
        # 查询工单明细
        items = db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == work_order.id
        ).all()
        
        # 构建设备明细列表
        devices_data = []
        for item in items:
            asset = item.asset
            devices_data.append({
                "serial_number": item.asset_sn,
                "asset_tag": item.asset_tag,
                "asset_name": asset.name if asset else None,
                "item_status": item.status,
                "result": item.result,
                "error_message": item.error_message,
                "operation_data": item.operation_data,
                "executed_at": item.executed_at.isoformat() if item.executed_at else None,
                "executed_by": item.executed_by
            })
        
        # 构建响应数据
        response_data = {
            "work_order_number": work_order.work_order_number,
            "batch_id": work_order.batch_id,
            "title": work_order.title,
            "datacenter": work_order.datacenter,
            "priority": work_order.extra.get('priority') if work_order.extra else None,
            "work_order_type": work_order.extra.get('work_order_type') if work_order.extra else None,
            "business_type": work_order.extra.get('business_type') if work_order.extra else None,
            "operation_type": work_order.extra.get('operation_type') if work_order.extra else None,
            "source_order_number": work_order.source_order_number,
            "operation_type_detail": work_order.extra.get('operation_type_detail') if work_order.extra else None,
            "is_business_online": work_order.extra.get('is_business_online') if work_order.extra else None,
            "operation_sub_type": work_order.extra.get('operation_sub_type') if work_order.extra else None,
            "estimated_operation_time": work_order.extra.get('estimated_operation_time') if work_order.extra else None,
            "sop": work_order.extra.get('sop') if work_order.extra else None,
            "execution_location": work_order.extra.get('execution_location') if work_order.extra else None,
            "precautions": work_order.extra.get('precautions') if work_order.extra else None,
            "service_content": work_order.extra.get('service_content') if work_order.extra else None,
            "assignee": work_order.assignee,
            "status": work_order.status,
            "work_order_status": work_order.work_order_status,
            "remark": work_order.remark,  # 创建时的备注
            "processing_result": work_order.extra.get('processing_result') if work_order.extra else None,  # 处理结果
            "failure_reason": work_order.extra.get('failure_reason') if work_order.extra else None,  # 失败原因
            "accept_remark": work_order.extra.get('accept_remark') if work_order.extra else None,  # 接单备注
            "close_remark": work_order.description if work_order.status == 'completed' else None,  # 结单备注
            "creator": work_order.creator,
            "operator": work_order.operator,  # 处理人
            "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
            "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
            "close_time": work_order.close_time.isoformat() if work_order.close_time else None,
            "devices": devices_data,
            "device_count": len(devices_data)
        }
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="查询成功",
            data=response_data
        )
        
    except Exception as e:
        logger.error(f"查询万能类操作工单详情失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询工单详情失败: {str(e)}",
            data=None
        )


@router.post("/process", summary="处理万能类操作工单",
             response_model=ApiResponse,
             responses={
                 200: {
                     "description": "处理成功",
                     "content": {
                         "application/json": {
                             "examples": {
                                 "processing": {
                                     "summary": "处理中",
                                     "value": {
                                         "code": 0,
                                         "message": "工单处理成功",
                                         "data": {
                                             "batch_id": "GEN_20251205120000",
                                             "work_order_number": "WO202512051234",
                                             "status": "processing",
                                             "processing_result": "正在处理中",
                                             "is_complete": False
                                         }
                                     }
                                 },
                                 "completed": {
                                     "summary": "已完成",
                                     "value": {
                                         "code": 0,
                                         "message": "工单处理成功",
                                         "data": {
                                             "batch_id": "GEN_20251205120000",
                                             "work_order_number": "WO202512051234",
                                             "status": "completed",
                                             "processing_result": "处理完成",
                                             "is_complete": True
                                         }
                                     }
                                 }
                             }
                         }
                     }
                 },
                 404: {"description": "工单不存在"}
             })
async def process_generic_work_order(
    process_data: GenericWorkOrderProcess = Body(...,
        examples={
            "processing": {
                "summary": "处理中（未完成）",
                "value": {
                    "batch_id": "GEN_20251205120000",
                    "operator": "张三",
                    "processing_result": "已开始处理，预计明天完成",
                    "accept_remark": "已接单，正在处理",
                    "is_complete": False
                }
            },
            "completed": {
                "summary": "处理完成",
                "value": {
                    "batch_id": "GEN_20251205120000",
                    "operator": "张三",
                    "processing_result": "所有设备已完成巡检，运行正常",
                    "is_complete": True
                }
            },
            "failed": {
                "summary": "处理失败",
                "value": {
                    "batch_id": "GEN_20251205120000",
                    "operator": "张三",
                    "processing_result": "处理失败",
                    "failure_reason": "设备故障，无法完成操作",
                    "is_complete": True
                }
            }
        }),
    db: Session = Depends(get_db)
):
    """
    处理万能类操作工单
    
    ## 功能说明
    用于更新工单的处理状态和结果，支持：
    - 接单确认
    - 处理进度更新
    - 完成工单
    - 记录失败原因
    
    ## 必填参数
    - **batch_id**: 批次ID（必填）
    - **operator**: 操作人（必填）
    - **processing_result**: 处理结果描述（必填）
    - **is_complete**: 是否完成工单（必填，true/false）
    
    ## 可选参数
    - **failure_reason**: 失败原因
      - 当处理结果为失败时建议填写
      - 帮助记录问题原因
    - **accept_remark**: 接单备注
      - 接单时的备注信息
    
    ## 处理流程
    
    ### 1. 接单（第一次处理）
    ```json
    {
      "batch_id": "GEN_20251205120000",
      "operator": "张三",
      "processing_result": "已接单",
      "accept_remark": "收到工单，开始处理",
      "is_complete": false
    }
    ```
    - 工单状态变为 "processing"
    - 记录接单备注
    
    ### 2. 进度更新（处理中）
    ```json
    {
      "batch_id": "GEN_20251205120000",
      "operator": "张三",
      "processing_result": "已完成50%，预计明天完成",
      "is_complete": false
    }
    ```
    - 工单保持 "processing" 状态
    - 更新处理结果
    
    ### 3. 完成工单（成功）
    ```json
    {
      "batch_id": "GEN_20251205120000",
      "operator": "张三",
      "processing_result": "所有设备已完成巡检，运行正常",
      "is_complete": true
    }
    ```
    - 工单状态变为 "completed"
    - 记录完成时间
    
    ### 4. 完成工单（失败）
    ```json
    {
      "batch_id": "GEN_20251205120000",
      "operator": "张三",
      "processing_result": "处理失败",
      "failure_reason": "设备故障，无法完成操作",
      "is_complete": true
    }
    ```
    - 工单状态变为 "completed"
    - 记录失败原因
    
    ## 返回数据
    - batch_id: 批次ID
    - work_order_number: 工单号
    - status: 更新后的工单状态
    - processing_result: 处理结果
    - is_complete: 是否已完成
    - updated_at: 更新时间
    
    ## 注意事项
    1. 同一个工单可以多次调用此接口更新进度
    2. is_complete=true 时工单将被标记为完成，无法再次处理
    3. 处理结果会同时更新工单主表和所有关联的设备明细
    4. 建议在处理失败时填写 failure_reason
    """
    try:
        # 1. 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.batch_id == process_data.batch_id,
            WorkOrder.operation_type.in_([
                "generic_operation",
                "generic_non_operation",
                "generic_asset",
                "generic_request"  # 兼容旧数据
            ])
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到批次ID为 {process_data.batch_id} 的工单",
                data=None
            )
        
        # 2. 更新工单状态
        if process_data.is_complete:
            work_order.status = "completed"
            work_order.completed_time = datetime.now()
            work_order.close_time = datetime.now()
        else:
            work_order.status = "processing"
        
        work_order.operator = process_data.operator
        
        # 3. 更新extra字段中的处理信息
        if not work_order.extra:
            work_order.extra = {}
        
        work_order.extra['processing_result'] = process_data.processing_result
        if process_data.failure_reason:
            work_order.extra['failure_reason'] = process_data.failure_reason
        if process_data.accept_remark:
            work_order.extra['accept_remark'] = process_data.accept_remark
        
        # 4. 更新工单明细状态
        items = db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == work_order.id
        ).all()
        
        for item in items:
            if process_data.is_complete:
                item.status = "completed"
                item.result = process_data.processing_result
                if process_data.failure_reason:
                    item.error_message = process_data.failure_reason
            else:
                item.status = "processing"
            
            item.executed_at = datetime.now()
            item.executed_by = process_data.operator
        
        db.commit()
        db.refresh(work_order)
        
        # 5. 记录日志
        operation_content = "结单(Close Ticket)" if process_data.is_complete else "处理中(Processing)"
        remark = process_data.accept_remark or process_data.processing_result
        
        logger.info("万能类操作工单处理成功", extra={
            "operationObject": work_order.work_order_number or work_order.batch_id,
            "operationType": OperationType.GENERIC_WORK_ORDER_PROCESS,
            "operator": process_data.operator,
            "result": OperationResult.SUCCESS,
            "operationDetail": (
                f"操作内容: {operation_content}, 工单号: {work_order.work_order_number or work_order.batch_id}, "
                f"是否结单: {'是' if process_data.is_complete else '否'}, "
                f"处理结果: {process_data.processing_result}, 备注: {remark}"
            )
        })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="工单处理成功",
            data={
                "batch_id": work_order.batch_id,
                "work_order_number": work_order.work_order_number,
                "status": work_order.status,
                "processing_result": process_data.processing_result,
                "is_complete": process_data.is_complete,
                "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None
            }
        )
        
    except Exception as e:
        db.rollback()
        logger.error("万能类操作工单处理失败", extra={
            "operationObject": process_data.batch_id,
            "operationType": OperationType.GENERIC_WORK_ORDER_PROCESS,
            "operator": process_data.operator,
            "result": OperationResult.FAILED,
            "operationDetail": f"系统异常: {str(e)}"
        })
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"工单处理失败: {str(e)}",
            data=None
        )
