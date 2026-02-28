"""
服务器网线/光纤更换工单管理API
提供创建服务器网线/光纤更换工单的功能
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_, text
from typing import Optional, Dict, Any, List
from datetime import datetime
import httpx
import json

from app.db.session import get_db
from app.services.asset_service import AssetService
from app.schemas.asset_schemas import ApiResponse, ResponseCode
from app.models.asset_models import WorkOrder, WorkOrderItem, Asset
from app.schemas.network_cable_work_order_schemas import (
    NetworkCableWorkOrderCreate,
    NetworkCableWorkOrderResponse,
    DeviceInfoQueryParams,
    DevicePortUpdate,
    ManualUsbInstallCreate,
    ManualUsbInstallResponse,
    DeviceDetailResponse,
    DeviceBasicInfo,
    LinkedDeviceInfo,
    BatchDeviceQuery,
    BatchDeviceDetailResponse,
    WorkOrderProcessRequest,
    WorkOrderProcessResponse
)
from app.core.config import settings
from app.core.logging_config import get_logger
from app.constants.operation_types import OperationType, OperationResult

router = APIRouter()
logger = get_logger(__name__)

# =====================================================
# 工单系统集成
# =====================================================

async def create_network_cable_work_order(
    work_order_data: NetworkCableWorkOrderCreate,
    creator_name: str = "system"
) -> Dict[str, Any]:
    """
    创建服务器网线/光纤更换工单
    
    参数:
    - work_order_data: 工单数据
    - creator_name: 创建人姓名
    
    返回:
    - 工单创建结果
    """
    try:
        # 构建工单请求数据
        # 注意：BaseSchema 中 use_enum_values=True，因此这里的枚举字段已经是 str
        operation_type = str(work_order_data.operation_type)
        urgency_level = str(work_order_data.urgency_level)
        
        # 英文值转换为中文值
        operation_type_map = {
            "production_network": "生产网线",
            "out_of_band_network": "带外网线",
        }
        urgency_level_map = {
            "normal": "一般",
            "urgent": "紧急",
        }
        # 操作类型映射到外部系统任务分支
        # OOB-C: 带外网线任务分支
        # PNC: 生产网线任务分支
        operation_branch_map = {
            "production_network": "PNC",
            "out_of_band_network": "OOB-C",
        }
        operation_type_cn = operation_type_map.get(operation_type, operation_type)
        urgency_level_cn = urgency_level_map.get(urgency_level, urgency_level)
        operation_branch = operation_branch_map.get(operation_type, "PNC")  # 默认生产网线

        remarks_text = work_order_data.remarks or ""

        work_order_request = {
            "title": work_order_data.title,
            "description": (
                f"操作类型: {operation_type_cn}\n"
                f"紧急程度: {urgency_level_cn}\n"
            ),
            "secretInfo": "11111",
            "creator": settings.WORK_ORDER_CREATOR,
            "creatorName": "协创2",  # 使用固定的创建人名称
            "processId": "cableFiberReplace",  # 服务器网线/光纤更换工单专用流程
            "variables": {
                "assignee": work_order_data.assignee,
                "operation": operation_branch  # OOB-C: 带外网线, PNC: 生产网线
            },
            "externalBizId": f"CFR_{datetime.now().strftime('%Y%m%d%H%M%S')}",  # 外部业务ID，使用CFR前缀
            "bussinessMetaData": {
                "orderType": "server_cable_replacement",  # 服务器网线/光纤更换
                "assignee": work_order_data.assignee,
                "operation": operation_branch
            }
        }
        
        # 如果有设备信息，添加到variables中
        if work_order_data.device_info:
            work_order_request["variables"]["device_info"] = json.dumps(
                work_order_data.device_info, ensure_ascii=False
            )
        
        # 发送HTTP请求（增加超时时间，提高连接稳定性）
        timeout = httpx.Timeout(60.0, connect=30.0)  # 总超时60秒，连接超时30秒
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            print(f"[网线/光纤更换工单创建] 正在连接工单系统: {settings.WORK_ORDER_API_URL}")
            print(f"[网线/光纤更换工单创建] 请求报文: {json.dumps(work_order_request, ensure_ascii=False)}")
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
            
            # 检查响应状态
            response.raise_for_status()
            
            # 解析响应
            result = response.json()
            print(f"[网线/光纤更换工单创建] 外部系统响应: {json.dumps(result, ensure_ascii=False)}")

            # 状态码非0时视为失败，直接返回错误
            if result.get("status") != 0:
                error_msg = result.get("msg") or result.get("message") or "工单系统返回失败"
                print(f"[网线/光纤更换工单创建失败] 状态码: {result.get('status')}, 错误信息: {error_msg}")
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
        print(f"[网线/光纤更换工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "status_code": e.response.status_code
        }
    except httpx.RequestError as e:
        error_detail = str(e) if str(e) else f"连接失败: {type(e).__name__}"
        error_msg = f"工单系统请求失败: {error_detail}"
        error_detail_msg = (
            f"无法连接到工单系统。请检查：\n"
            f"1. 工单系统服务是否运行（URL: {settings.WORK_ORDER_API_URL}）\n"
            f"2. 网络连接是否正常\n"
            f"3. 防火墙是否阻止连接\n"
            f"4. URL配置是否正确"
        )
        print(f"[网线/光纤更换工单创建失败] {error_msg}")
        print(f"[网线/光纤更换工单创建失败] 详细信息: {error_detail_msg}")
        return {
            "success": False,
            "error": error_msg,
            "error_detail": error_detail_msg,
            "url": settings.WORK_ORDER_API_URL
        }
    except Exception as e:
        error_msg = f"工单创建异常: {str(e)}"
        print(f"[网线/光纤更换工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }


async def create_manual_usb_install_order(
    order_data: ManualUsbInstallCreate,
    sn_list: List[str],
    creator_name: str = "system"
) -> Dict[str, Any]:
    """
    创建手工U盘装机工单
    """
    try:
        priority_value = str(order_data.priority)
        remarks_text = order_data.remarks or ""
        os_template = order_data.os_template or ""
        device_sn_text = ", ".join(sn_list)
        description_parts = [
            f"项目需求: {order_data.project_requirement}",
            f"设备SN: {device_sn_text}",
            f"OS模板: {os_template}",
            f"优先级: {priority_value}",
        ]
        if order_data.datacenter:
            description_parts.append(f"机房: {order_data.datacenter}")
        if order_data.room:
            description_parts.append(f"房间: {order_data.room}")
        if order_data.source_order_number:
            description_parts.append(f"来源单号: {order_data.source_order_number}")
        if order_data.operation_type_detail:
            description_parts.append(f"操作类型: {order_data.operation_type_detail}")
        if order_data.is_business_online is not None:
            description_parts.append(
                f"业务是否在线: {'是' if order_data.is_business_online else '否'}"
            )
        description_parts.append(f"备注: {remarks_text}")

        # 构建variables（简化版）
        variables = {
            "assignee": order_data.assignee
        }

        # 构建metadata（简化版）
        metadata = {
            "orderType": "manual_usb_install",  # 手工U盘装机
            "assignee": order_data.assignee
        }

        work_order_request = {
            "title": order_data.title,
            "description": "\n".join(description_parts),
            "secretInfo": "11111",
            "creator": settings.WORK_ORDER_CREATOR,
            "creatorName": creator_name,
            # 使用手工U盘装机专用流程
            "processId": "manualUsbSetup",
            "variables": variables,
            "externalBizId": f"USB_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "bussinessMetaData": metadata
        }

        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            print(f"[手工U盘装机工单创建] 请求报文: {json.dumps(work_order_request, ensure_ascii=False)}")
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

            if result.get("status") != 0:
                error_msg = result.get("message") or "工单系统返回失败"
                return {
                    "success": False,
                    "error": error_msg,
                    "data": result
                }

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
        print(f"[手工U盘装机工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "status_code": e.response.status_code
        }
    except httpx.RequestError as e:
        error_detail = str(e) if str(e) else f"连接失败: {type(e).__name__}"
        error_msg = f"工单系统请求失败: {error_detail}"
        error_detail_msg = (
            f"无法连接到工单系统。请检查：\n"
            f"1. 工单系统服务是否运行（URL: {settings.WORK_ORDER_API_URL}）\n"
            f"2. 网络连接是否正常\n"
            f"3. 防火墙是否阻止连接\n"
            f"4. URL配置是否正确"
        )
        print(f"[手工U盘装机工单创建失败] {error_msg}")
        print(f"[手工U盘装机工单创建失败] 详细信息: {error_detail_msg}")
        return {
            "success": False,
            "error": error_msg,
            "error_detail": error_detail_msg,
            "url": settings.WORK_ORDER_API_URL
        }
    except Exception as e:
        error_msg = f"工单创建异常: {str(e)}"
        print(f"[手工U盘装机工单创建失败] {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }


# =====================================================
# 工单管理接口
# =====================================================

@router.post("/create", summary="创建服务器网线/光纤更换工单",
             response_model=ApiResponse,
             responses={
                 200: {
                     "description": "工单创建成功",
                     "content": {
                         "application/json": {
                             "example": {
                                 "code": 0,
                                 "message": "工单创建成功",
                                 "data": {
                                     "work_order_number": "WO202512051234",
                                     "operation_type": "network_cable",
                                     "title": "服务器网线更换",
                                     "allowed_start_time": "2025-12-05T08:00:00",
                                     "allowed_end_time": "2025-12-05T18:00:00",
                                     "urgency_level": "normal",
                                     "remarks": "需要在业务低峰期操作"
                                 }
                             }
                         }
                     }
                 },
                 400: {"description": "参数错误"},
                 500: {"description": "服务器内部错误"}
             })
async def create_work_order(
    work_order_data: NetworkCableWorkOrderCreate = Body(...,
        example={
            "operation_type": "production_network",
            "title": "服务器网线更换",
            "allowed_start_time": "2025-12-05T08:00:00",
            "allowed_end_time": "2025-12-05T18:00:00",
            "urgency_level": "normal",
            "assignee": "张三",
            "remarks": "需要在业务低峰期操作",
            "device_info": [{"SN": "SN123456", "IP": "192.168.1.100"}]
        }),
    db: Session = Depends(get_db)
):
    """
    创建服务器网线/光纤更换工单
    
    ## 功能说明
    用于创建服务器网线或光纤更换相关的工单。
    
    ## 必填字段
    - **operation_type**: 操作类型
      - production_network: 生产网线
      - oob_network: 带外网线
    - **title**: 工单标题
    - **allowed_start_time**: 允许操作开始时间（ISO 8601格式）
    - **allowed_end_time**: 允许操作结束时间（ISO 8601格式）
    - **urgency_level**: 紧急程度
      - normal: 一般
      - urgent: 紧急
    - **assignee**: 指派人
    
    ## 可选字段
    - **remarks**: 备注（最多140字）
    - **device_info**: 设备信息列表（包含SN、IP等）
    - **creator_name**: 创建人姓名（默认system）
    
    ## 返回字段说明
    - **work_order_number**: 外部工单系统的工单号
    - **operation_type**: 操作类型（network_cable）
    - **title**: 工单标题
    - **allowed_start_time**: 允许操作开始时间
    - **allowed_end_time**: 允许操作结束时间
    - **urgency_level**: 紧急程度
    - **remarks**: 备注
    
    ## 注意事项
    1. 结束时间必须晚于开始时间
    2. 批次ID格式：CFR_YYYYMMDDHHMMSS（CFR = Cable Fiber Replace）
    """
    try:
        # 验证时间范围
        if work_order_data.allowed_end_time < work_order_data.allowed_start_time:
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message="结束时间必须晚于开始时间",
                data=None
            )
        
        # 创建工单
        creator_name = work_order_data.creator_name or "system"
        work_order_result = await create_network_cable_work_order(
            work_order_data,
            creator_name
        )
        
        if not work_order_result.get("success"):
            # 记录工单创建失败日志
            logger.error("服务器网线工单创建失败", extra={
                "operationObject": work_order_data.title,
                "operationType": OperationType.NETWORK_CABLE_WORK_ORDER_CREATE,
                "operator": creator_name,
                "result": OperationResult.FAILED,
                "operationDetail": f"操作类型: {work_order_data.operation_type}, 指派人: {work_order_data.assignee}, 错误: {work_order_result.get('error', '未知错误')}"
            })
            return ApiResponse(
                code=ResponseCode.INTERNAL_ERROR,
                message=work_order_result.get("error", "工单创建失败"),
                data=work_order_result
            )
        
        # 保存工单到本地数据库
        operation_type = "network_cable"  # 标准化的工单类型，用于日志识别
        urgency_level = str(work_order_data.urgency_level)
        work_order_number = work_order_result.get("work_order_number")
        
        # 生成批次ID (使用CFR前缀: Cable Fiber Replace)
        batch_id = f"CFR_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 构建extra字段，只保留必要的数据
        extra_data = {
            "allowed_start_time": work_order_data.allowed_start_time.isoformat(),
            "allowed_end_time": work_order_data.allowed_end_time.isoformat(),
            "user_operation_type": str(work_order_data.operation_type),  # 保存用户输入的操作类型
            "priority": urgency_level  # 保存优先级到extra字段，以便查询时返回
        }
        
        # 如果有设备信息，添加到extra中
        if work_order_data.device_info:
            extra_data["device_info"] = work_order_data.device_info
        
        # 创建本地工单记录
        local_work_order = WorkOrder(
            batch_id=batch_id,
            work_order_number=work_order_number,
            operation_type=operation_type,
            title=work_order_data.title,
            description=f"操作类型: {operation_type}\n允许操作时间: {work_order_data.allowed_start_time.strftime('%Y-%m-%d %H:%M:%S')} 至 {work_order_data.allowed_end_time.strftime('%Y-%m-%d %H:%M:%S')}\n紧急程度: {urgency_level}",
            status="pending",
            creator=creator_name,
            assignee=work_order_data.assignee,
            start_time=work_order_data.allowed_start_time,
            expected_completion_time=work_order_data.allowed_end_time,
            extra=extra_data,
            remark=work_order_data.remarks
        )
        
        try:
            db.add(local_work_order)
            db.commit()
            db.refresh(local_work_order)
            print(f"[网线/光纤更换工单] 本地工单记录已保存: ID={local_work_order.id}, 工单号={work_order_number}")
        except Exception as e:
            db.rollback()
            print(f"[警告] 保存本地工单记录失败: {str(e)}")
            # 不影响外部工单创建的成功返回
        
        # 记录工单创建成功日志
        # 构建备注信息
        remark_parts = []
        if work_order_data.remarks:
            remark_parts.append(work_order_data.remarks)
        else:
            remark_parts.append(f"操作类型: {operation_type}, 指派人: {work_order_data.assignee}, 紧急程度: {urgency_level}")
        
        logger.info("服务器网线工单创建成功", extra={
            "operationObject": work_order_number or batch_id,
            "operationType": OperationType.NETWORK_CABLE_WORK_ORDER_CREATE,
            "operator": creator_name,
            "result": OperationResult.SUCCESS,
            "operationDetail": f"操作内容: 建单(Create Ticket), 工单号: {work_order_number or batch_id}, 工单标题: {work_order_data.title}, 备注: {', '.join(remark_parts)}"
        })
        
        # 构建响应数据
        response_data = NetworkCableWorkOrderResponse(
            work_order_number=work_order_number,
            operation_type=operation_type,
            title=work_order_data.title,
            allowed_start_time=work_order_data.allowed_start_time,
            allowed_end_time=work_order_data.allowed_end_time,
            urgency_level=urgency_level,
            remarks=work_order_data.remarks
        )
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="工单创建成功",
            data=response_data.dict()
        )
        
    except ValueError as e:
        # 记录参数验证失败日志
        logger.error("服务器网线工单创建参数验证失败", extra={
            "operationObject": work_order_data.title if 'work_order_data' in locals() else "未知工单",
            "operationType": OperationType.NETWORK_CABLE_WORK_ORDER_CREATE,
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
        # 记录系统异常日志
        logger.error("服务器网线工单创建系统异常", extra={
            "operationObject": work_order_data.title if 'work_order_data' in locals() else "未知工单",
            "operationType": OperationType.NETWORK_CABLE_WORK_ORDER_CREATE,
            "operator": work_order_data.creator_name if 'work_order_data' in locals() and work_order_data.creator_name else "system",
            "result": OperationResult.FAILED,
            "operationDetail": f"系统异常: {str(e)}"
        })
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"创建工单失败: {str(e)}",
            data=None
        )


# =====================================================
# 设备信息查询接口（支持在工单中查询设备）
# =====================================================

def get_asset_service(db: Session = Depends(get_db)) -> AssetService:
    return AssetService(db)

@router.get("/device/query", summary="查询设备信息（用于工单中设备选择）",
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
                                    "devices": [
                                        {
                                            "serial_number": "SN123456",
                                            "location_abbreviation": "DC01-A-01",
                                            "hostname": None,
                                            "ip_address": "192.168.1.100",
                                            "cabinet": "CAB-001",
                                            "room": "Room-A",
                                            "rack_position": "U10-U12",
                                            "model": "Dell R740",
                                            "network_port": "eth0: port1, eth1: port2",
                                            "action": "add"
                                        }
                                    ],
                                    "total": 1,
                                    "page": 1,
                                    "size": 10,
                                    "pages": 1
                                }
                            }
                        }
                    }
                },
                500: {"description": "服务器内部错误"}
            })
async def query_device_info(
    asset_tag: Optional[str] = Query(None, description="资产标签"),
    serial_number: Optional[str] = Query(None, description="序列号"),
    name: Optional[str] = Query(None, description="设备名称"),
    room_id: Optional[int] = Query(None, description="房间ID"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(10, ge=1, le=10000, description="每页数量"),
    service: AssetService = Depends(get_asset_service),
    db: Session = Depends(get_db)
):
    """
    查询设备信息（支持在新建工单时查询设备）
    
    ## 功能说明
    用于在创建工单时查询和选择设备，返回设备的详细信息包括位置、端口等。
    
    ## 查询参数
    - **asset_tag**: 资产标签（模糊搜索）
    - **serial_number**: 序列号（模糊搜索）
    - **name**: 设备名称（模糊搜索）
    - **room_id**: 房间ID（精确匹配）
    - **page**: 页码（默认1）
    - **size**: 每页数量（默认10，最大100）
    
    ## 返回字段说明
    - **devices**: 设备列表
      - **serial_number**: 设备序列号
      - **location_abbreviation**: 位置缩写
      - **hostname**: 主机名（暂无数据返回null）
      - **ip_address**: IP地址
      - **cabinet**: 机柜编号
      - **room**: 房间名称
      - **rack_position**: 机架位置
      - **model**: 设备型号
      - **network_port**: 网络端口信息
      - **action**: 操作类型（固定为"add"）
    - **total**: 总记录数
    - **page**: 当前页码
    - **size**: 每页数量
    - **pages**: 总页数
    
    ## 注意事项
    1. 端口信息从最近的上架工单记录中获取
    2. 如果设备没有上架记录，机柜、房间、机位、端口信息可能为null
    """
    try:
        from app.schemas.asset_schemas import AssetSearchParams, PaginationParams
        
        search_params = AssetSearchParams(
            asset_tag=asset_tag,
            name=name,
            room_id=room_id
        )
        
        # 如果有序列号，需要特殊处理（因为AssetSearchParams没有serial_number字段）
        if serial_number:
            # 直接查询数据库
            from app.models.asset_models import Asset
            assets = db.query(Asset).filter(
                Asset.serial_number.like(f"%{serial_number}%")
            ).offset((page - 1) * size).limit(size).all()
            total = db.query(Asset).filter(
                Asset.serial_number.like(f"%{serial_number}%")
            ).count()
        else:
            pagination_params = PaginationParams(page=page, size=size)
            assets, total = service.search_assets(search_params, pagination_params)
        
        # 构建返回数据（补充机柜、机架位、端口信息）
        from app.models.asset_models import WorkOrderItem

        device_list = []
        for asset in assets:
            # 查询该资产最近的一条上架工单记录（用于机柜/机位/端口信息展示）
            work_order_item = db.query(WorkOrderItem).join(
                WorkOrder, WorkOrderItem.work_order_id == WorkOrder.id
            ).filter(
                WorkOrderItem.asset_id == asset.id,
                WorkOrder.operation_type == 'racking'
            ).order_by(WorkOrderItem.created_at.desc()).first()

            # 从operation_data JSON字段中提取network_port
            network_port = None
            if work_order_item and work_order_item.operation_data:
                network_port = work_order_item.operation_data.get('network_port')

            device_info = {
                "serial_number": asset.serial_number,
                "location_abbreviation": asset.location_detail,
                "hostname": None,  # hostname字段暂无，返回null
                "ip_address": asset.ip_address,
                "cabinet": work_order_item.item_cabinet if work_order_item else None,
                "room": work_order_item.item_room if work_order_item else None,
                "rack_position": work_order_item.item_rack_position if work_order_item else None,
                "model": asset.model,
                "network_port": network_port,
                "action": "add",
            }
            device_list.append(device_info)
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="查询成功",
            data={
                "devices": device_list,
                "total": total,
                "page": page,
                "size": size,
                "pages": (total + size - 1) // size
            }
        )
        
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询设备信息失败: {str(e)}",
            data=None
        )


# =====================================================
# 设备端口信息管理接口
# =====================================================

@router.post("/device/port", summary="更新设备端口信息",
             response_model=ApiResponse,
             responses={
                 200: {
                     "description": "端口信息更新成功",
                     "content": {
                         "application/json": {
                             "example": {
                                 "code": 0,
                                 "message": "端口信息更新成功",
                                 "data": {
                                     "serial_number": "SN123456",
                                     "network_port": "eth0: port1, eth1: port2",
                                     "updated": True
                                 }
                             }
                         }
                     }
                 },
                 404: {"description": "设备不存在"},
                 500: {"description": "服务器内部错误"}
             })
async def update_device_port(
    port_data: DevicePortUpdate = Body(...,
        example={
            "serial_number": "SN123456",
            "network_port": "eth0: port1, eth1: port2"
        }),
    db: Session = Depends(get_db)
):
    """
    更新设备端口信息
    
    ## 功能说明
    根据设备序列号更新或创建设备的网络端口信息。
    
    ## 必填字段
    - **serial_number**: 设备序列号
    - **network_port**: 端口信息（文本格式，如"eth0: port1, eth1: port2"）
    
    ## 返回字段说明
    - **serial_number**: 设备序列号
    - **network_port**: 端口信息
    - **updated**: 是否更新了现有记录（true表示更新，false表示新建）
    - **created**: 是否创建了新记录（仅在新建时返回）
    
    ## 处理逻辑
    1. 根据序列号查找资产
    2. 查找该资产最近的上架工单记录
    3. 如果存在上架记录，更新其operation_data中的network_port字段
    4. 如果不存在上架记录，创建新的工单和工单明细记录
    
    ## 注意事项
    1. 端口信息存储在工单明细的operation_data JSON字段中
    2. 如果设备不存在，返回404错误
    """
    try:
        from app.models.asset_models import Asset, WorkOrderItem, WorkOrder
        
        # 根据序列号查找资产
        asset = db.query(Asset).filter(
            Asset.serial_number == port_data.serial_number
        ).first()
        
        if not asset:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到序列号为 {port_data.serial_number} 的设备",
                data=None
            )
        
        # 查找该资产最近的一条上架工单记录
        work_order_item = db.query(WorkOrderItem).join(
            WorkOrder, WorkOrderItem.work_order_id == WorkOrder.id
        ).filter(
            WorkOrderItem.asset_id == asset.id,
            WorkOrder.operation_type == 'racking'
        ).order_by(WorkOrderItem.created_at.desc()).first()
        
        if work_order_item:
            # 如果存在上架记录，更新端口信息（存储在operation_data JSON字段中）
            if not work_order_item.operation_data:
                work_order_item.operation_data = {}
            work_order_item.operation_data['network_port'] = port_data.network_port
            work_order_item.updated_at = datetime.now()
            db.commit()
            
            return ApiResponse(
                code=ResponseCode.SUCCESS,
                message="端口信息更新成功",
                data={
                    "serial_number": port_data.serial_number,
                    "network_port": port_data.network_port,
                    "updated": True
                }
            )
        else:
            # 如果不存在上架记录，创建一个新的工单和工单明细
            # 首先创建一个工单
            batch_id = f"PORT_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            work_order = WorkOrder(
                batch_id=batch_id,
                operation_type="network_cable",  # 修复：使用 network_cable 而不是 racking
                title="端口信息录入",
                status="pending",
                creator="system",
                remark="端口信息录入"
            )
            db.add(work_order)
            db.flush()  # 获取工单ID
            
            # 创建工单明细记录
            work_order_item = WorkOrderItem(
                work_order_id=work_order.id,
                asset_id=asset.id,
                asset_sn=asset.serial_number,
                asset_tag=asset.asset_tag,
                operation_data={"network_port": port_data.network_port},
                status="pending"
            )
            db.add(work_order_item)
            db.commit()
            
            return ApiResponse(
                code=ResponseCode.SUCCESS,
                message="端口信息保存成功",
                data={
                    "serial_number": port_data.serial_number,
                    "network_port": port_data.network_port,
                    "created": True
                }
            )
        
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"保存端口信息失败: {str(e)}",
            data=None
        )


@router.post("/manual-usb-install/create", summary="创建手工U盘装机单", 
             response_model=ApiResponse,
             responses={
                 200: {
                     "description": "工单创建成功",
                     "content": {
                         "application/json": {
                             "example": {
                                 "code": 0,
                                 "message": "工单创建成功",
                                 "data": {
                                     "work_order_number": "WO202512051234",
                                     "title": "服务器U盘装机",
                                     "project_requirement": "新项目上线需要装机",
                                     "device_sns": ["SN123456", "SN789012"],
                                     "datacenter": "DC01",
                                     "room": "A区101",
                                     "os_template": "CentOS 7.9",
                                     "priority": "一般",
                                     "source_order_number": "PRJ-2025-001",
                                     "operation_type_detail": "新机装机",
                                     "is_business_online": False,
                                     "remarks": "需要在周末完成"
                                 },
                                 "timestamp": "2025-12-05T10:00:00"
                             }
                         }
                     }
                 },
                 400: {"description": "参数错误"},
                 500: {"description": "服务器内部错误"}
             })
async def create_manual_usb_install(
    order_data: ManualUsbInstallCreate = Body(..., 
        example={
            "title": "服务器U盘装机",
            "project_requirement": "新项目上线需要装机",
            "device_sn_text": "SN123456 SN789012",
            "datacenter": "DC01",
            "room": "A区101",
            "os_template": "CentOS 7.9",
            "priority": "一般",
            "source_order_number": "PRJ-2025-001",
            "operation_type_detail": "新机装机",
            "is_business_online": False,
            "remarks": "需要在周末完成",
            "assignee": "张三",
            "creator_name": "李四"
        }),
    db: Session = Depends(get_db)
):
    """
    创建手工U盘装机单
    
    ## 功能说明
    用于创建手工U盘装机工单，支持批量设备装机。
    
    ## 必填字段
    - **title**: 工单标题
    - **project_requirement**: 项目需求说明
    - **device_sn_text**: 设备SN（支持批量输入，空格或换行分隔）
    - **priority**: 优先级（一般/紧急）
    - **assignee**: 指派人
    
    ## 可选字段
    - **datacenter**: 机房
    - **room**: 房间
    - **os_template**: 操作系统模板
    - **source_order_number**: 来源单号
    - **operation_type_detail**: 操作类型详情
    - **is_business_online**: 业务是否在线
    - **remarks**: 备注（最多200字）
    - **creator_name**: 创建人姓名（默认system）
    
    ## 设备SN输入格式
    支持以下格式：
    - 空格分隔: `SN001 SN002 SN003`
    - 换行分隔: 
      ```
      SN001
      SN002
      SN003
      ```
    - 混合格式: `SN001 SN002\nSN003 SN004`
    
    ## 返回数据
    - **work_order_number**: 工单号
    - **device_sns**: 解析后的设备SN列表
    - 其他工单详细信息
    
    ## 注意事项
    1. 设备SN会自动去除空格和空行
    2. 至少需要输入一个有效的设备SN
    3. 工单创建后会同时保存到本地数据库和外部工单系统
    4. 批次ID格式: USB_YYYYMMDDHHMMSS
    """
    try:
        # 解析SN列表（空格或换行分隔）
        sn_list = [sn.strip() for sn in order_data.device_sn_text.replace("\n", " ").split(" ") if sn.strip()]
        if not sn_list:
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message="设备SN不能为空",
                data=None
            )

        creator_name = order_data.creator_name or "system"
        work_order_result = await create_manual_usb_install_order(
            order_data,
            sn_list,
            creator_name
        )

        if not work_order_result.get("success"):
            # 记录手工U盘装机工单创建失败日志
            logger.error("手工U盘装机工单创建失败", extra={
                "operationObject": order_data.title,
                "operationType": OperationType.MANUAL_USB_INSTALL_CREATE,
                "operator": creator_name,
                "result": OperationResult.FAILED,
                "operationDetail": f"项目需求: {order_data.project_requirement}, 设备SN: {order_data.device_sn_text}, OS模板: {order_data.os_template}, 优先级: {order_data.priority}, 指派人: {order_data.assignee}, 错误: {work_order_result.get('error', '未知错误')}"
            })
            return ApiResponse(
                code=ResponseCode.INTERNAL_ERROR,
                message=work_order_result.get("error", "工单创建失败"),
                data=work_order_result
            )

        # 保存工单到本地数据库
        priority_value = str(order_data.priority)
        work_order_number = work_order_result.get("work_order_number")
        
        # 生成批次ID (使用USB前缀: Manual USB Install)
        batch_id = f"USB_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 构建extra字段，只保留必要的数据
        extra_data = {
            "project_requirement": order_data.project_requirement,
            "device_sns": sn_list,
            "os_template": order_data.os_template,
            "priority": priority_value,
            "device_sn_text": order_data.device_sn_text,
            "datacenter": order_data.datacenter,
            "room": order_data.room,
            "source_order_number": order_data.source_order_number,
            "operation_type_detail": order_data.operation_type_detail,
            "is_business_online": order_data.is_business_online,
        }
        
        # 创建本地工单记录（保存到work_orders表）
        local_work_order = WorkOrder(
            batch_id=batch_id,
            work_order_number=work_order_number,
            operation_type="manual_usb_install",
            title=order_data.title,
            description="\n".join(
                [
                    f"项目需求: {order_data.project_requirement}",
                    f"设备SN: {order_data.device_sn_text}",
                    f"OS模板: {order_data.os_template}",
                    f"优先级: {priority_value}",
                    f"机房: {order_data.datacenter or '未指定'}",
                    f"房间: {order_data.room or '未指定'}",
                    f"来源单号: {order_data.source_order_number or '未提供'}",
                    f"操作类型: {order_data.operation_type_detail or '未指定'}",
                    f"业务是否在线: {('是' if order_data.is_business_online else '否') if order_data.is_business_online is not None else '未说明'}",
                ]
            ),
            status="pending",
            creator=creator_name,
            assignee=order_data.assignee,
            datacenter=order_data.datacenter,
            room=order_data.room,
            source_order_number=order_data.source_order_number,
            remark=order_data.remarks,
            extra=extra_data
        )
        
        try:
            db.add(local_work_order)
            db.flush()  # 先flush获取work_order的id
            
            # 查询设备信息并创建工单明细
            valid_assets = []
            invalid_sns = []
            for sn in sn_list:
                asset = db.query(Asset).filter(Asset.serial_number == sn).first()
                if asset:
                    valid_assets.append(asset)
                else:
                    invalid_sns.append(sn)
            
            # 更新工单的设备数量
            local_work_order.device_count = len(valid_assets)
            
            # 为每个有效设备创建WorkOrderItem
            for asset in valid_assets:
                operation_data = {
                    "serial_number": asset.serial_number,
                    "asset_tag": asset.asset_tag,
                    "asset_name": asset.name,
                    "project_requirement": order_data.project_requirement,
                    "os_template": order_data.os_template,
                    "datacenter": order_data.datacenter,
                    "room": order_data.room,
                    "priority": priority_value,
                    "operation_type_detail": order_data.operation_type_detail,
                    "is_business_online": order_data.is_business_online
                }
                
                work_order_item = WorkOrderItem(
                    work_order_id=local_work_order.id,
                    asset_id=asset.id,
                    asset_sn=asset.serial_number,
                    asset_tag=asset.asset_tag,
                    operation_data=operation_data,
                    status="pending",
                    item_datacenter=order_data.datacenter,
                    item_room=order_data.room
                )
                db.add(work_order_item)
            
            # 如果有无效的SN，记录到extra中
            if invalid_sns:
                extra_data["invalid_sns"] = invalid_sns
                local_work_order.extra = extra_data
            
            db.commit()
            db.refresh(local_work_order)
            
            if invalid_sns:
                print(f"[手工U盘装机工单创建] 警告: 以下SN未找到对应设备: {invalid_sns}")
                
        except Exception as db_error:
            db.rollback()
            print(f"[手工U盘装机工单创建] 数据库保存失败: {str(db_error)}")
            return ApiResponse(
                code=ResponseCode.INTERNAL_ERROR,
                message=f"数据库保存失败: {str(db_error)}",
                data=None
            )

        # 记录手工U盘装机工单创建成功日志
        # 构建备注信息
        remark_parts = []
        if order_data.remarks:
            remark_parts.append(order_data.remarks)
        else:
            remark_parts.append(f"项目需求: {order_data.project_requirement}, 设备数量: {len(sn_list)}, OS模板: {order_data.os_template or '未指定'}")
        
        logger.info("手工U盘装机工单创建成功", extra={
            "operationObject": work_order_number or batch_id,
            "operationType": OperationType.MANUAL_USB_INSTALL_CREATE,
            "operator": creator_name,
            "result": OperationResult.SUCCESS,
            "operationDetail": (
                f"操作内容: 建单(Create Ticket), 工单号: {work_order_number or batch_id}, "
                f"工单标题: {order_data.title}, 机房: {order_data.datacenter or '未指定'}, 房间: {order_data.room or '未指定'}, "
                f"来源单号: {order_data.source_order_number or '未提供'}, 备注: {', '.join(remark_parts)}"
            )
        })
        
        response_data = ManualUsbInstallResponse(
            work_order_number=work_order_number,
            title=order_data.title,
            project_requirement=order_data.project_requirement,
            device_sns=sn_list,
            datacenter=order_data.datacenter,
            room=order_data.room,
            os_template=order_data.os_template,
            priority=priority_value,
            source_order_number=order_data.source_order_number,
            operation_type_detail=order_data.operation_type_detail,
            is_business_online=order_data.is_business_online,
            remarks=order_data.remarks
        )

        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="工单创建成功",
            data=response_data.dict()
        )

    except ValueError as e:
        db.rollback()
        # 记录参数验证失败日志
        logger.error("手工U盘装机工单创建参数验证失败", extra={
            "operationObject": order_data.title if 'order_data' in locals() else "未知工单",
            "operationType": OperationType.MANUAL_USB_INSTALL_CREATE,
            "operator": order_data.creator_name if 'order_data' in locals() and order_data.creator_name else "system",
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
        logger.error("手工U盘装机工单创建系统异常", extra={
            "operationObject": order_data.title if 'order_data' in locals() else "未知工单",
            "operationType": OperationType.MANUAL_USB_INSTALL_CREATE,
            "operator": order_data.creator_name if 'order_data' in locals() and order_data.creator_name else "system",
            "result": OperationResult.FAILED,
            "operationDetail": f"系统异常: {str(e)}"
        })
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"创建工单失败: {str(e)}",
            data=None
        )


@router.post("/device/batch-detail", summary="批量查询设备信息及上下联",
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
                                     "devices": [
                                         {
                                             "basic_info": {
                                                 "serial_number": "SN123456",
                                                 "name": "服务器-01",
                                                 "datacenter": "DC01",
                                                 "room": "Room-A",
                                                 "location_detail": "DC01-A-01",
                                                 "is_company_device": True
                                             },
                                             "linked_devices": {
                                                 "upstream": [
                                                     {
                                                         "serial_number": "SN-SWITCH-001",
                                                         "name": "核心交换机",
                                                         "device_type": "交换机"
                                                     }
                                                 ],
                                                 "downstream": []
                                             }
                                         }
                                     ],
                                     "total": 1,
                                     "success_count": 1,
                                     "failed_count": 0
                                 }
                             }
                         }
                     }
                 },
                 500: {"description": "服务器内部错误"}
             })
async def get_batch_device_detail(
    query_data: BatchDeviceQuery = Body(...,
        example={
            "device_sns": ["SN123456", "SN789012"]
        }),
    db: Session = Depends(get_db)
):
    """
    批量查询设备信息和上下联设备
    
    ## 功能说明
    根据设备SN列表批量查询设备的基本信息和上下联设备信息。
    
    ## 必填字段
    - **device_sns**: 设备SN列表（至少1个）
    
    ## 返回字段说明
    - **devices**: 设备列表
      - **basic_info**: 设备基本信息
        - **serial_number**: 设备序列号
        - **name**: 设备名称
        - **datacenter**: 数据中心
        - **room**: 房间
        - **location_detail**: 位置详情
        - **is_company_device**: 是否为公司设备
      - **linked_devices**: 上下联设备
        - **upstream**: 上联设备列表
        - **downstream**: 下联设备列表
    - **total**: 查询的设备总数
    - **success_count**: 成功查询的设备数
    - **failed_count**: 查询失败的设备数
    
    ## 注意事项
    1. 上下联设备信息从topology表中查询
    2. 如果设备不存在，该设备会被跳过，不影响其他设备的查询
    """
    try:
        devices = []
        
        for sn in query_data.device_sns:
            try:
                # 查询设备基本信息和位置信息
                asset_row = db.execute(
                    text("""
                        SELECT 
                            a.id, 
                            a.serial_number, 
                            a.name,
                            a.room_id, 
                            a.location_detail,
                            a.is_company_device,
                            r.room_full_name,
                            r.datacenter_abbreviation as datacenter,
                            r.building_number,
                            r.floor_number
                        FROM assets a
                        LEFT JOIN rooms r ON a.room_id = r.id
                        WHERE a.serial_number = :sn 
                        LIMIT 1
                    """),
                    {"sn": sn}
                ).mappings().first()

                if not asset_row:
                    continue

                asset_id = asset_row.get("id")
                is_company_device = asset_row.get("is_company_device")
                
                # 查询上架工单信息获取机柜、房间、机位等信息
                from app.models.asset_models import WorkOrderItem, WorkOrder
                work_order_item = db.query(WorkOrderItem).join(
                    WorkOrder, WorkOrderItem.work_order_id == WorkOrder.id
                ).filter(
                    WorkOrderItem.asset_id == asset_id,
                    WorkOrder.operation_type == 'racking'
                ).order_by(WorkOrderItem.created_at.desc()).first()
                
                # 从WorkOrderItem获取位置信息
                datacenter = work_order_item.item_datacenter if work_order_item else None
                room = work_order_item.item_room if work_order_item else None
                cabinet_number = work_order_item.item_cabinet if work_order_item else None
                rack_position = work_order_item.item_rack_position if work_order_item else None
                
                # 从operation_data获取端口信息
                network_port = None
                if work_order_item and work_order_item.operation_data:
                    network_port = work_order_item.operation_data.get('network_port')

                # 查询网络连接设备
                linked_devices = []
                
                # 查询作为源设备的连接（当前设备连接到其他设备）
                source_connections = db.execute(
                    text("""
                        SELECT a.serial_number, a.name, nc.target_port as port, a.is_company_device
                        FROM network_connections nc
                        JOIN assets a ON nc.target_asset_id = a.id
                        WHERE nc.source_asset_id = :asset_id AND nc.status = 1
                    """),
                    {"asset_id": asset_id}
                ).mappings().all()
                
                for row in source_connections:
                    linked_devices.append({
                        "serial_number": row.get("serial_number"),
                        "name": row.get("name"),
                        "port": row.get("port"),
                        "is_company_device": bool(row.get("is_company_device")),
                        "link_type": "downstream"
                    })

                # 查询作为目标设备的连接（其他设备连接到当前设备）
                target_connections = db.execute(
                    text("""
                        SELECT a.serial_number, a.name, nc.source_port as port, a.is_company_device
                        FROM network_connections nc
                        JOIN assets a ON nc.source_asset_id = a.id
                        WHERE nc.target_asset_id = :asset_id AND nc.status = 1
                    """),
                    {"asset_id": asset_id}
                ).mappings().all()
                
                for row in target_connections:
                    linked_devices.append({
                        "serial_number": row.get("serial_number"),
                        "name": row.get("name"),
                        "port": row.get("port"),
                        "is_company_device": bool(row.get("is_company_device")),
                        "link_type": "upstream"
                    })

                # 如果没有上下联设备，返回一个包含null字段的对象
                if not linked_devices:
                    linked_devices = [{
                        "serial_number": None,
                        "name": None,
                        "port": None,
                        "is_company_device": None,
                        "link_type": None
                    }]

                # 构建设备基本信息（使用中文字段名）
                device_info = {
                    "serial_number": asset_row.get("serial_number"),
                    "datacenter": datacenter,
                    "room": room,
                    "cabinet_number": cabinet_number,
                    "rack_position": rack_position,
                    "network_port": network_port,
                    "is_company_device": bool(is_company_device)
                }

                # 构建设备详情响应
                device_detail = {
                    "device": device_info,
                    "linked_devices": linked_devices
                }
                
                devices.append(device_detail)
                
            except Exception as device_error:
                continue

        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="批量查询设备详情成功",
            data={
                "devices": devices
            }
        )

    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"批量查询设备详情失败: {str(e)}",
            data=None
        )


# =====================================================
# 统一工单流程处理接口
# =====================================================

@router.post("/process", summary="统一工单流程处理",
             response_model=ApiResponse,
             responses={
                 200: {
                     "description": "工单处理成功",
                     "content": {
                         "application/json": {
                             "example": {
                                 "code": 0,
                                 "message": "工单处理成功",
                                 "data": {
                                     "order_number": "WO202512051234",
                                     "status": "completed",
                                     "is_complete": 1,
                                     "is_passed": 1,
                                     "updated_at": "2025-12-05T16:00:00"
                                 }
                             }
                         }
                     }
                 },
                 404: {"description": "工单不存在"},
                 500: {"description": "服务器内部错误"}
             })
async def process_work_order(
    process_data: WorkOrderProcessRequest = Body(...,
        example={
            "order_number": "WO202512051234",
            "description": "网线更换已完成",
            "is_passed": 1,
            "is_complete": 1,
            "is_transfer": 0,
            "attachment_urls": [],
            "process_variables": {},
            "feedback_person": "zhangsan",
            "feedback_person_name": "张三"
        }),
    db: Session = Depends(get_db)
):
    """
    统一的工单流程处理接口
    
    ## 功能说明
    支持网线工单和手工U盘装机工单的流程处理，包括接单、处理中、完成、转派等操作。
    
    ## 必填字段
    - **order_number**: 工单号
    - **description**: 处理描述
    - **is_passed**: 是否通过（1-通过, 0-不通过）
    - **is_complete**: 是否完成（1-完成, 0-未完成）
    - **is_transfer**: 是否转派（1-转派, 0-不转派）
    - **feedback_person**: 反馈人账号
    - **feedback_person_name**: 反馈人姓名
    
    ## 可选字段
    - **attachment_urls**: 附件URL列表
    - **process_variables**: 流程变量（字典格式）
    - **failure_reason**: 失败原因（is_passed=0时建议填写）
    - **close_remark**: 关闭备注（is_complete=1时建议填写）
    
    ## 返回字段说明
    - **order_number**: 工单号
    - **status**: 工单状态
      - processing: 处理中
      - completed: 已完成
      - failed: 失败
    - **is_complete**: 是否完成
    - **is_passed**: 是否通过
    - **updated_at**: 更新时间
    
    ## 使用场景
    1. **接单**: is_complete=0, is_passed=1
    2. **处理中**: is_complete=0, is_passed=1
    3. **完成工单**: is_complete=1, is_passed=1
    4. **拒绝工单**: is_complete=1, is_passed=0, 填写failure_reason
    5. **转派工单**: is_transfer=1, 在process_variables中指定新的assignee
    
    ## 注意事项
    1. 会同时更新外部工单系统和本地数据库
    2. failure_reason和close_remark会自动添加到process_variables中
    3. 完成工单时会自动更新completed_time
    """
    try:
        # 构建外部工单系统的请求数据
        process_variables = dict(process_data.process_variables or {})
        if process_data.failure_reason:
            process_variables.setdefault("failure_reason", process_data.failure_reason)
        if process_data.close_remark:
            process_variables.setdefault("close_remark", process_data.close_remark)

        external_request = {
            "orderNumber": process_data.order_number,
            "description": process_data.description,
            "isPassed": process_data.is_passed,
            "isComplete": process_data.is_complete,
            "isTransfer": process_data.is_transfer,
            "attachmentUrls": process_data.attachment_urls,
            "processVariables": process_variables,
            "feedbackPerson": process_data.feedback_person,
            "feedbackPersonName": process_data.feedback_person_name
        }
        
        # 调用外部工单系统的流程处理接口
        timeout = httpx.Timeout(60.0, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            print(f"[工单流程处理] 处理工单: {process_data.order_number}")
            print(f"[工单流程处理] 请求报文: {json.dumps(external_request, ensure_ascii=False)}")
            
            headers = {
                "appid": settings.WORK_ORDER_APPID,
                "username": settings.WORK_ORDER_USERNAME,
                "Content-Type": "application/json"
            }
            if settings.WORK_ORDER_COOKIE:
                headers["Cookie"] = settings.WORK_ORDER_COOKIE

            # 使用外部系统的流程处理接口
            process_url = settings.WORK_ORDER_API_URL.replace("/createWorkOrder", "/processOrder")
            
            response = await client.post(
                process_url,
                headers=headers,
                json=external_request
            )
            
            response.raise_for_status()
            result = response.json()
            
            print(f"[工单流程处理] 外部系统响应: {json.dumps(result, ensure_ascii=False)}")
            
            # 检查外部系统响应
            external_status = result.get("status")
            external_msg = result.get("msg", "未知错误")
            
            if external_status == 0:
                # 更新本地数据库中的工单状态
                try:
                    # 根据工单号查找本地工单记录
                    local_work_order = db.query(WorkOrder).filter(
                        WorkOrder.work_order_number == process_data.order_number
                    ).first()
                    
                    if local_work_order:
                        new_status = "completed" if process_data.is_complete == 1 else "processing"
                        if process_data.is_passed == 0:
                            new_status = "failed"

                        local_work_order.status = new_status
                        if process_data.is_complete == 1:
                            now = datetime.now()
                            local_work_order.completed_time = now
                            local_work_order.close_time = now
                        if process_data.close_remark:
                            local_work_order.remark = process_data.close_remark
                        if process_data.failure_reason:
                            local_work_order.extra = local_work_order.extra or {}
                            local_work_order.extra["failure_reason"] = process_data.failure_reason
                        db.commit()
                        print(f"[工单流程处理] 本地工单状态已更新: {new_status}")
                    
                except Exception as db_error:
                    db.rollback()
                    print(f"[工单流程处理] 更新本地工单状态失败: {str(db_error)}")
                    # 不影响主流程，继续返回成功
                
                # 根据处理结果确定工单状态
                work_order_status = "COMPLETED" if process_data.is_complete == 1 and process_data.is_passed == 1 else \
                                  "FAILED" if process_data.is_passed == 0 else \
                                  "PROCESSING"
                
                # 根据工单类型确定日志消息和操作类型
                work_order_type = local_work_order.get('operation_type') if local_work_order else 'unknown'
                
                if work_order_type == 'network_cable':
                    log_message = "服务器网线工单处理成功"
                    operation_type = OperationType.NETWORK_CABLE_WORK_ORDER_PROCESS
                elif work_order_type == 'manual_usb_install':
                    log_message = "手工U盘装机工单处理成功"
                    operation_type = OperationType.MANUAL_USB_INSTALL_PROCESS
                else:
                    log_message = "工单处理成功"
                    operation_type = OperationType.WORK_ORDER_PROCESS
                
                # 记录工单处理成功日志
                # 确定操作内容
                if process_data.is_complete == 1 and process_data.is_passed == 1:
                    operation_content = "结单(Close Ticket)"
                    process_result = "结单成功"
                    remark = process_data.close_remark or f"工单已完成结单。{process_data.description}"
                elif process_data.is_passed == 0:
                    operation_content = "处理失败(Failed)"
                    process_result = "失败"
                    remark = process_data.failure_reason or f"失败理由: {process_data.description}"
                else:
                    operation_content = "处理中(Processing)"
                    process_result = "处理中"
                    remark = process_data.description
                
                logger.info(log_message, extra={
                    "operationObject": process_data.order_number,
                    "operationType": operation_type,
                    "operator": process_data.feedback_person_name,
                    "result": OperationResult.SUCCESS,
                    "operationDetail": f"操作内容: {operation_content}, 工单号: {process_data.order_number}, 是否结单: {'是' if process_data.is_complete == 1 else '否'}, 处理结果: {process_result}, 备注: {remark}"
                })
                
                # 确定是否结单和失败理由
                is_closed = process_data.is_complete == 1 and process_data.is_passed == 1
                failure_reason = process_data.failure_reason
                if not failure_reason and process_data.is_passed == 0:
                    failure_reason = process_data.description
                
                return ApiResponse(
                    code=ResponseCode.SUCCESS,
                    message="工单流程处理成功",
                    data=WorkOrderProcessResponse(
                        success=True,
                        message=external_msg,
                        work_order_number=process_data.order_number,
                        work_order_status=work_order_status,
                        is_closed=is_closed,
                        failure_reason=failure_reason,
                        close_remark=process_data.close_remark if is_closed else None,
                    )
                )
            else:
                # 处理不同的外部系统错误码
                error_details = {
                    -102: "工单不存在或已被处理",
                    -101: "参数错误",
                    -103: "权限不足",
                    -104: "工单状态不允许处理"
                }
                
                detailed_error = error_details.get(external_status, f"外部系统错误 (状态码: {external_status})")
                full_error_msg = f"{detailed_error}: {external_msg}"
                
                # 记录工单处理失败日志 - 根据工单号前缀判断类型
                if process_data.order_number.startswith('cableFiberReplace'):
                    log_message = "服务器网线工单处理失败"
                    operation_type = OperationType.NETWORK_CABLE_WORK_ORDER_PROCESS
                elif process_data.order_number.startswith('manualUsbSetup'):
                    log_message = "手工U盘装机工单处理失败"
                    operation_type = OperationType.MANUAL_USB_INSTALL_PROCESS
                else:
                    log_message = "工单处理失败"
                    operation_type = OperationType.WORK_ORDER_PROCESS
                
                logger.error(log_message, extra={
                    "operationObject": process_data.order_number,
                    "operationType": operation_type,
                    "operator": process_data.feedback_person_name,
                    "result": OperationResult.FAILED,
                    "operationDetail": f"工单号: {process_data.order_number}, 错误信息: {full_error_msg}, 反馈人: {process_data.feedback_person_name}, 失败原因: {process_data.failure_reason or '未提供'}"
                })
                
                return ApiResponse(
                    code=ResponseCode.INTERNAL_ERROR,
                    message=f"工单流程处理失败: {full_error_msg}",
                    data=WorkOrderProcessResponse(
                        success=False,
                        message=full_error_msg,
                        work_order_number=process_data.order_number,
                        work_order_status="ERROR"
                    )
                )
                
    except httpx.HTTPError as http_error:
        error_msg = f"网络请求失败: {str(http_error)}"
        print(f"[工单流程处理] {error_msg}")
        
        # 记录网络错误日志 - 根据工单号前缀判断类型
        if process_data.order_number.startswith('cableFiberReplace'):
            log_message = "服务器网线工单处理网络异常"
            operation_type = OperationType.NETWORK_CABLE_WORK_ORDER_PROCESS
        elif process_data.order_number.startswith('manualUsbSetup'):
            log_message = "手工U盘装机工单处理网络异常"
            operation_type = OperationType.MANUAL_USB_INSTALL_PROCESS
        else:
            log_message = "工单处理网络异常"
            operation_type = OperationType.WORK_ORDER_PROCESS
        
        logger.error(log_message, extra={
            "operationObject": process_data.order_number,
            "operationType": operation_type,
            "operator": process_data.feedback_person_name,
            "result": OperationResult.FAILED,
            "operationDetail": f"工单号: {process_data.order_number}, 网络错误: {error_msg}, 反馈人: {process_data.feedback_person_name}, 失败原因: {process_data.failure_reason or '未提供'}"
        })
        
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=error_msg,
            data=WorkOrderProcessResponse(
                success=False,
                message=error_msg,
                work_order_number=process_data.order_number,
                work_order_status=None
            )
        )
    except Exception as e:
        error_msg = f"工单流程处理异常: {str(e)}"
        print(f"[工单流程处理] {error_msg}")
        
        # 记录系统异常日志 - 根据工单号前缀判断类型
        if process_data.order_number.startswith('cableFiberReplace'):
            log_message = "服务器网线工单处理系统异常"
            operation_type = OperationType.NETWORK_CABLE_WORK_ORDER_PROCESS
        elif process_data.order_number.startswith('manualUsbSetup'):
            log_message = "手工U盘装机工单处理系统异常"
            operation_type = OperationType.MANUAL_USB_INSTALL_PROCESS
        else:
            log_message = "工单处理系统异常"
            operation_type = OperationType.WORK_ORDER_PROCESS
        
        logger.error(log_message, extra={
            "operationObject": process_data.order_number,
            "operationType": operation_type,
            "operator": process_data.feedback_person_name,
            "result": OperationResult.FAILED,
            "operationDetail": f"工单号: {process_data.order_number}, 系统异常: {error_msg}, 反馈人: {process_data.feedback_person_name}, 失败原因: {process_data.failure_reason or '未提供'}"
        })
        
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=error_msg,
            data=WorkOrderProcessResponse(
                success=False,
                message=error_msg,
                work_order_number=process_data.order_number,
                work_order_status=None
            )
        )

