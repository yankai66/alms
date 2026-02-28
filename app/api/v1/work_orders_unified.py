"""
统一工单管理API
支持所有类型的工单创建：设备到货、上架、上下电、增配等
"""

from fastapi import APIRouter, Depends, HTTPException, Form, Query, Body, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, validator, model_validator
from datetime import datetime
import pandas as pd
import io
from urllib.parse import quote

from app.db.session import get_db
from app.models.asset_models import Asset, Room, WorkOrder, WorkOrderItem, AssetConfiguration, NetworkConnection
from app.models.cabinet_models import Cabinet
from app.schemas.asset_schemas import ApiResponse, ResponseCode
from app.constants.operation_types import OPERATION_CATEGORY_OPTIONS
from app.utils.dict_helper import validate_dict_value, DictTypeCode
from app.core.logging_config import get_logger
from app.core.config import settings
from app.services.genericWorkOrderService import GenericWorkOrderService

router = APIRouter()
logger = get_logger(__name__)


def calculate_sla_countdown(work_order: WorkOrder) -> Optional[int]:
    """
    计算 SLA 倒计时（秒）
    
    逻辑：
    1. 如果有 expected_completion_time，使用它作为截止时间
    2. 如果没有 expected_completion_time，使用创建时间 + DEFAULT_SLA_HOURS 作为截止时间
    3. 如果工单已完成，返回 None
    4. 返回从当前时间到截止时间的秒数（可能为负数，表示已超时）
    
    Args:
        work_order: 工单对象
        
    Returns:
        int: SLA 倒计时秒数，None 表示工单已完成或无法计算
    """
    # 如果工单已完成，不需要计算倒计时
    if work_order.status in ['completed', 'cancelled']:
        return None
    
    # 确定截止时间
    deadline = None
    if work_order.expected_completion_time:
        deadline = work_order.expected_completion_time
    elif work_order.created_at:
        # 使用创建时间 + 默认 SLA 小时数
        from datetime import timedelta
        deadline = work_order.created_at + timedelta(hours=settings.DEFAULT_SLA_HOURS)
    
    if not deadline:
        return None
    
    # 计算倒计时（秒）
    # 确保 deadline 是 naive datetime（没有时区信息）
    if hasattr(deadline, 'tzinfo') and deadline.tzinfo is not None:
        deadline = deadline.replace(tzinfo=None)
    
    now = datetime.now()
    countdown = int((deadline - now).total_seconds())
    
    # 调试日志
    logger.debug(f"SLA计算 - 工单ID: {work_order.id}, 批次: {work_order.batch_id}, "
                f"创建时间: {work_order.created_at}, 期望完成: {work_order.expected_completion_time}, "
                f"截止时间: {deadline}, 当前时间: {now}, 倒计时: {countdown}秒")
    
    return countdown

STATUS_DISPLAY_MAP = {
    "pending": "进行中",
    "processing": "进行中",
    "approved": "进行中",
    "completed": "完成",
    "complete": "完成",
    "failed": "失败",
    "rejected": "失败",
    "reject": "失败",
    "cancelled": "失败",
}


def format_status_label(status: Optional[str]) -> Optional[str]:
    if not status:
        return status
    return STATUS_DISPLAY_MAP.get(status.lower(), status)


@router.get("/operation-types/options", summary="获取操作类型两级联动数据",
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
                                    "receiving": {
                                        "label": "到货",
                                        "value": "receiving",
                                        "children": []
                                    },
                                    "racking": {
                                        "label": "上架",
                                        "value": "racking",
                                        "children": []
                                    }
                                }
                            }
                        }
                    }
                }
            })
async def get_operation_type_options():
    """
    获取操作类型两级联动数据
    
    ## 功能说明
    返回所有可用的工单操作类型及其子类型的二级联动配置数据。
    
    ## 返回字段说明
    - **data**: 操作类型配置对象
      - 每个操作类型包含：
        - **label**: 显示名称
        - **value**: 操作类型值
        - **children**: 子类型列表（如果有）
    
    ## 注意事项
    1. 用于前端下拉框的级联选择
    2. 数据来自OPERATION_CATEGORY_OPTIONS常量
    """
    return {
        "code": 0,
        "message": "success",
        "data": OPERATION_CATEGORY_OPTIONS,
    }


class WorkOrderItemCreate(BaseModel):
    """工单明细创建Schema"""
    asset_identifier: str = Field(..., description="资产标识（序列号或资产ID）")
    operation_data: Dict[str, Any] = Field(..., description="操作数据（根据operation_type不同）")


class WorkOrderCreateRequest(BaseModel):
    """统一工单创建请求"""
    operation_type: str = Field(..., description="操作类型")
    title: str = Field(..., max_length=200, description="工单标题")
    creator: str = Field(..., max_length=100, description="创建人")
    assignee: Optional[str] = Field(None, max_length=100, description="指派人（电源管理工单必填）")
    description: Optional[str] = Field(None, description="工单描述")
    datacenter: Optional[str] = Field(None, max_length=50, description="机房")
    room: Optional[str] = Field(None, max_length=50, description="房间（电源管理工单必填）")
    expected_completion_time: Optional[datetime] = Field(None, description="期望完成时间（电源管理工单必填）")
    # 设备增配工单特定字段
    parent_device_sn: Optional[str] = Field(None, description="父设备SN（增配工单必需）")
    vendor_onsite: Optional[bool] = Field(None, description="厂商是否上门（增配工单必需）")
    parent_device_can_shutdown: Optional[bool] = Field(None, description="父设备能否关机（增配工单必需）")
    allowed_operation_start_time: Optional[datetime] = Field(None, description="允许操作开始时间（增配工单必需）")
    allowed_operation_end_time: Optional[datetime] = Field(None, description="允许操作结束时间（增配工单必需）")
    is_optical_module_upgrade: Optional[bool] = Field(None, description="是否光模块增配（增配工单必需）")
    is_project_upgrade: Optional[bool] = Field(None, description="是否项目增配（增配工单必需）")
    project_number: Optional[str] = Field(None, description="项目编号（增配工单可选）")
    remark: Optional[str] = Field(None, description="备注")
    # 机房上下电特定字段
    power_action: Optional[str] = Field(None, description="电源操作：power_on(上电) 或 power_off(下电)，机房级别上下电时必填")
    power_type: Optional[str] = Field(None, description="电源类型：AC(交流电) 或 DC(直流电)，默认AC")
    reason: Optional[str] = Field(None, description="操作原因（可选，下电时建议填写，如未填写会使用remark或description）")
    items: Optional[List[WorkOrderItemCreate]] = Field(None, description="工单明细（设备级别操作时必填，机房级别操作时可选）")
    
    @validator('operation_type')
    def validate_operation_type(cls, v):
        # 这里应该验证字典，暂时硬编码
        valid_types = ['receiving', 'racking', 'power_management', 'configuration', 'network_cable', 'maintenance']
        if v not in valid_types:
            raise ValueError(f'无效的操作类型: {v}')
        return v
    
    @model_validator(mode='after')
    def validate_required_fields(self):
        """验证不同工单类型的必需字段"""
        
        # 增配工单必填字段验证
        if self.operation_type == 'configuration':
            if not self.parent_device_sn:
                raise ValueError('增配工单必须提供parent_device_sn（父设备SN）')
            if self.vendor_onsite is None:
                raise ValueError('增配工单必须提供vendor_onsite（厂商是否上门）')
            if self.parent_device_can_shutdown is None:
                raise ValueError('增配工单必须提供parent_device_can_shutdown（父设备能否关机）')
            if not self.allowed_operation_start_time:
                raise ValueError('增配工单必须提供allowed_operation_start_time（允许操作开始时间）')
            if not self.allowed_operation_end_time:
                raise ValueError('增配工单必须提供allowed_operation_end_time（允许操作结束时间）')
            if self.is_optical_module_upgrade is None:
                raise ValueError('增配工单必须提供is_optical_module_upgrade（是否光模块增配）')
            if self.is_project_upgrade is None:
                raise ValueError('增配工单必须提供is_project_upgrade（是否项目增配）')
        
        # 电源管理工单必填字段验证
        elif self.operation_type == 'power_management':
            if not self.assignee:
                raise ValueError('电源管理工单必须提供assignee（指派人）')
            if not self.room:
                raise ValueError('电源管理工单必须提供room（房间）')
            if not self.expected_completion_time:
                raise ValueError('电源管理工单必须提供expected_completion_time（期望完成时间）')
            
            # 机房级别上下电：不提供items时，必须提供power_action
            if not self.items or len(self.items) == 0:
                if not self.power_action:
                    raise ValueError('机房级别上下电必须提供power_action（power_on或power_off）')
                if self.power_action not in ['power_on', 'power_off']:
                    raise ValueError('power_action必须是power_on或power_off')
                # 下电时，reason改为可选，如果没有reason会使用remark或description作为原因
        
        # 其他工单类型必须提供items
        else:
            if not self.items or len(self.items) == 0:
                raise ValueError(f'{self.operation_type}工单必须提供items（工单明细）')
        
        return self


def generate_batch_id(operation_type: str) -> str:
    """生成批次ID"""
    prefix_map = {
        'receiving': 'RECV',
        'racking': 'RACK',
        'power_management': 'PWR',
        'configuration': 'CONF',
        'network_cable': 'NET',
        'maintenance': 'MAINT'
    }
    
    prefix = prefix_map.get(operation_type, 'WO')
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    return f"{prefix}{timestamp}"


def find_asset_by_identifier(db: Session, identifier: str) -> Asset:
    """根据标识符查找资产（支持SN或asset_id）"""
    
    # 尝试按序列号查找
    asset = db.query(Asset).filter(Asset.serial_number == identifier).first()
    if asset:
        return asset
    
    # 尝试按资产ID查找
    try:
        asset_id = int(identifier)
        asset = db.query(Asset).get(asset_id)
        if asset:
            return asset
    except ValueError:
        pass
    
    # 尝试按资产标签查找
    asset = db.query(Asset).filter(Asset.asset_tag == identifier).first()
    if asset:
        return asset
    
    return None


def validate_operation_data(operation_type: str, operation_data: Dict[str, Any], db: Session, asset: Asset = None) -> Dict[str, Any]:
    """验证和标准化操作数据"""
    
    validated_data = operation_data.copy()
    
    if operation_type == "receiving":
        # 设备到货验证
        if 'target_room_id' in operation_data:
            room = db.query(Room).get(operation_data['target_room_id'])
            if not room:
                raise ValueError(f"目标房间ID不存在: {operation_data['target_room_id']}")
            validated_data['target_room_name'] = room.room_abbreviation
            validated_data['target_room_full_name'] = room.room_full_name
        
        elif 'target_room_name' in operation_data:
            room = db.query(Room).filter(
                Room.room_abbreviation == operation_data['target_room_name']
            ).first()
            if not room:
                raise ValueError(f"目标房间不存在: {operation_data['target_room_name']}")
            validated_data['target_room_id'] = room.id
            validated_data['target_room_full_name'] = room.room_full_name
        else:
            raise ValueError("设备到货必须指定target_room_id或target_room_name")
    
    elif operation_type == "racking":
        # 设备上架验证
        # operation_data支持的字段：
        # - datacenter: 机房（可选）
        # - room_name/room_id: 房间（可选）
        # - cabinet_number: 机柜编号（可选）
        # - u_position/rack_position: 机位（可选，支持"1"或"1-2"格式）
        # - remark: 备注（可选）
        
        # 验证房间（room_id和room_name都是可选的，但如果提供了非空值则验证）
        room_id = operation_data.get('room_id')
        room_name = operation_data.get('room_name')
        
        if room_id:
            room = db.query(Room).get(room_id)
            if not room:
                raise ValueError(f"房间ID不存在: {room_id}")
            validated_data['room_name'] = room.room_abbreviation
            validated_data['room_id'] = room.id
            validated_data['datacenter'] = room.datacenter if hasattr(room, 'datacenter') else None
        elif room_name:  # 只有room_name非空时才验证
            room = db.query(Room).filter(
                Room.room_abbreviation == room_name
            ).first()
            if not room:
                raise ValueError(f"房间不存在: {room_name}")
            validated_data['room_id'] = room.id
            validated_data['room_name'] = room_name
            validated_data['datacenter'] = room.datacenter if hasattr(room, 'datacenter') else None
        
        # 解析U位（支持"1"或"1-2"格式）
        u_position = operation_data.get('u_position')
        if u_position:
            u_pos_str = str(u_position)
            try:
                if '-' in u_pos_str:
                    u_start, u_end = map(int, u_pos_str.split('-'))
                else:
                    u_start = u_end = int(u_pos_str)
                
                # 验证U位合理性
                if u_start > u_end:
                    raise ValueError("起始U位不能大于结束U位")
                if u_start < 1 or u_end > 48:
                    raise ValueError("U位范围应在1-48之间")
                
                validated_data['u_position_start'] = u_start
                validated_data['u_position_end'] = u_end
                validated_data['u_count'] = u_end - u_start + 1
            except ValueError as e:
                # 如果不能转换为数字，保存原始字符串
                validated_data['u_position'] = u_pos_str
        
        # 机柜编号（可选）
        if 'cabinet_number' in operation_data:
            validated_data['cabinet_number'] = operation_data['cabinet_number']
        
        # 备注
        if 'remark' in operation_data:
            validated_data['remark'] = operation_data['remark']
    
    elif operation_type == "power_management":
        # 电源管理验证
        # operation_data支持的字段：
        # - power_action: 动作类型，"power_on"(上电) 或 "power_off"(下电)，必填
        # - power_type: 电源类型，如"AC"(交流电)、"DC"(直流电)，默认"AC"
        # - reason: 操作原因（下电时必填）
        # - remark: 备注（可选）
        
        if 'power_action' not in operation_data:
            raise ValueError("电源管理必须指定power_action: 'power_on'或'power_off'")
        
        power_action = operation_data['power_action']
        if power_action not in ['power_on', 'power_off']:
            raise ValueError("power_action必须是'power_on'或'power_off'")
        
        validated_data['power_action'] = power_action
        
        if power_action == 'power_on':
            # 上电：设置默认电源类型
            if 'power_type' not in operation_data:
                validated_data['power_type'] = 'AC'
        elif power_action == 'power_off':
            # 下电：必须提供原因
            if 'reason' not in operation_data or not operation_data['reason']:
                raise ValueError("设备下电必须提供原因")
            validated_data['reason'] = operation_data['reason']
        
        # 备注（可选）
        if 'remark' in operation_data:
            validated_data['remark'] = operation_data['remark']
    
    elif operation_type == "configuration":
        # 设备增配验证
        # 有SN的配件
        if 'sn' in operation_data:
            if 'quantity' not in operation_data:
                raise ValueError("有SN的配件必须指定quantity（配件数量）")
            validated_data['sn'] = operation_data['sn']
            validated_data['slot'] = operation_data.get('slot', '')  # 增配槽位
            validated_data['quantity'] = operation_data['quantity']
            validated_data['port'] = operation_data.get('port', '')  # 增配端口
        # 无SN的配件
        else:
            validated_data['title'] = operation_data.get('title', '')
            validated_data['slot'] = operation_data.get('slot', '')
            validated_data['port'] = operation_data.get('port', '')
    
    return validated_data


@router.post("/create", summary="创建工单（通用）",
             response_model=ApiResponse,
             responses={
                 200: {
                     "description": "工单创建成功",
                     "content": {
                         "application/json": {
                             "examples": {
                                 "racking": {
                                     "summary": "上架工单创建成功",
                                     "value": {
                                         "code": 0,
                                         "message": "工单创建成功",
                                         "data": {
                                             "batch_id": "RACK_20251205120000",
                                             "operation_type": "racking",
                                             "title": "服务器上架",
                                             "status": "pending",
                                             "created_items": 2,
                                             "failed_items": 0,
                                             "datacenter": "DC01",
                                             "room": "Room-A",
                                             "device_count": 2,
                                             "creator": "张三",
                                             "created_at": "2025-12-05T12:00:00"
                                         }
                                     }
                                 },
                                 "power_management": {
                                     "summary": "电源管理工单创建成功",
                                     "value": {
                                         "code": 0,
                                         "message": "工单创建成功",
                                         "data": {
                                             "batch_id": "PWR_20251205120000",
                                             "operation_type": "power_management",
                                             "title": "服务器上电",
                                             "status": "pending",
                                             "created_items": 1,
                                             "failed_items": 0,
                                             "power_action": "power_on",
                                             "device_count": 1
                                         }
                                     }
                                 },
                                 "configuration": {
                                     "summary": "设备增配工单创建成功",
                                     "value": {
                                         "code": 0,
                                         "message": "工单创建成功",
                                         "data": {
                                             "batch_id": "CONF_20251205120000",
                                             "operation_type": "configuration",
                                             "title": "服务器内存增配",
                                             "status": "pending",
                                             "created_items": 2,
                                             "failed_items": 0,
                                             "parent_device_sn": "SN-PARENT-001",
                                             "vendor_onsite": True,
                                             "is_optical_module_upgrade": False
                                         }
                                     }
                                 }
                             }
                         }
                     }
                 },
                 400: {
                     "description": "参数错误",
                     "content": {
                         "application/json": {
                             "example": {
                                 "code": 400,
                                 "message": "以下资产标识不存在: SN123456",
                                 "data": None
                             }
                         }
                     }
                 },
                 404: {"description": "设备不存在"},
                 500: {"description": "服务器内部错误"}
             })
async def create_work_order(
    request: WorkOrderCreateRequest = Body(...,
        examples={
            "racking": {
                "summary": "上架工单示例",
                "value": {
                    "operation_type": "racking",
                    "title": "服务器上架",
                    "creator": "张三",
                    "assignee": "李四",
                    "datacenter": "DC01",
                    "room": "Room-A",
                    "items": [
                        {
                            "asset_identifier": "SN123456",
                            "operation_data": {
                                "room_name": "Room-A",
                                "cabinet_number": "CAB-001",
                                "u_position": "10-12",
                                "remark": "靠近冷通道"
                            }
                        }
                    ]
                }
            },
            "power_on": {
                "summary": "上电工单示例",
                "value": {
                    "operation_type": "power_management",
                    "title": "服务器上电",
                    "creator": "张三",
                    "assignee": "李四",
                    "room": "Room-A",
                    "expected_completion_time": "2025-12-05T18:00:00",
                    "items": [
                        {
                            "asset_identifier": "SN123456",
                            "operation_data": {
                                "power_action": "power_on",
                                "power_type": "AC",
                                "remark": "业务上线需要"
                            }
                        }
                    ]
                }
            },
            "power_off": {
                "summary": "下电工单示例",
                "value": {
                    "operation_type": "power_management",
                    "title": "服务器下电",
                    "creator": "张三",
                    "assignee": "李四",
                    "room": "Room-A",
                    "expected_completion_time": "2025-12-05T20:00:00",
                    "items": [
                        {
                            "asset_identifier": "SN123456",
                            "operation_data": {
                                "power_action": "power_off",
                                "reason": "设备维护需要下电",
                                "remark": "计划维护窗口"
                            }
                        }
                    ]
                }
            },
            "configuration": {
                "summary": "设备增配工单示例",
                "value": {
                    "operation_type": "configuration",
                    "title": "服务器内存增配",
                    "creator": "张三",
                    "assignee": "李四",
                    "description": "业务扩容，增加内存和风扇",
                    "datacenter": "DC01",
                    "room": "A101",
                    "parent_device_sn": "SN-PARENT-001",
                    "vendor_onsite": True,
                    "parent_device_can_shutdown": False,
                    "allowed_operation_start_time": "2025-12-05T20:00:00",
                    "allowed_operation_end_time": "2025-12-06T06:00:00",
                    "is_optical_module_upgrade": False,
                    "is_project_upgrade": True,
                    "project_number": "PROJ-2025-001",
                    "remark": "维护窗口操作",
                    "items": [
                        {
                            "asset_identifier": "SN-MEM-001",
                            "operation_data": {
                                "sn": "SN-MEM-001",
                                "slot": "DIMM-A1",
                                "quantity": 1,
                                "port": ""
                            }
                        },
                        {
                            "asset_identifier": "SN-PARENT-001",
                            "operation_data": {
                                "title": "散热风扇",
                                "slot": "FAN-1",
                                "port": ""
                            }
                        }
                    ]
                }
            }
        }),
    db: Session = Depends(get_db)
):
    """
    创建统一工单
    
    ## 功能说明
    支持多种类型工单的统一创建接口，可以创建上架、电源管理、设备增配等各类工单。
    
    **重要提示**：设备到货建议使用专用的Excel批量导入接口：POST /api/v1/work-orders/receiving/import
    
    ## 适用场景
    - 单台或少量设备操作  
    - 需要精确控制参数的场景
    - 非标准化操作
    - 需要自定义operation_data的场景
    
    ## 支持的操作类型
    - **receiving**: 设备到货（建议用Excel导入）
    - **racking**: 设备上架
    - **power_management**: 电源管理（上电/下电）
    - **configuration**: 设备增配
    - **network_cable**: 网线更换
    - **maintenance**: 设备维护
    
    ## 通用必填字段
    - **operation_type**: 操作类型（从上述支持的类型中选择）
    - **title**: 工单标题（最多200字符）
    - **creator**: 创建人（最多100字符）
    - **items**: 工单明细列表（至少1个）
      - **asset_identifier**: 资产标识（可以是序列号或资产ID）
      - **operation_data**: 操作数据（字典格式，根据operation_type不同而不同）
    
    ## 通用可选字段
    - **assignee**: 指派人（最多100字符）
    - **description**: 工单描述
    - **datacenter**: 机房（最多50字符）
    - **room**: 房间（最多50字符）
    - **expected_completion_time**: 期望完成时间（ISO 8601格式）
    - **project_number**: 项目编号
    - **remark**: 备注
    
    ## 电源管理工单特定必填字段（operation_type=power_management时）
    - **assignee**: 指派人（必填）
    - **room**: 房间（必填）
    - **expected_completion_time**: 期望完成时间（必填，ISO 8601格式）
    - **items[].operation_data.power_action**: 电源操作类型（必填）
      - "power_on": 上电
      - "power_off": 下电
    
    ## 增配工单特定必填字段（operation_type=configuration时）
    - **parent_device_sn**: 父设备SN（要增配的目标设备）
    - **vendor_onsite**: 厂商是否上门（布尔值）
    - **parent_device_can_shutdown**: 父设备能否关机（布尔值）
    - **allowed_operation_start_time**: 允许操作开始时间（ISO 8601格式）
    - **allowed_operation_end_time**: 允许操作结束时间（ISO 8601格式）
    - **is_optical_module_upgrade**: 是否光模块增配（布尔值）
    - **is_project_upgrade**: 是否项目增配（布尔值）
    
    ## 增配工单特定可选字段（operation_type=configuration时）
    - **project_number**: 项目编号（字符串）
    
    ## operation_data详细说明
    
    ### 1. racking（上架工单）
    **可选字段**：
    - **room_name**: 房间名称（字符串）
    - **room_id**: 房间ID（整数）
    - **cabinet_number**: 机柜编号（字符串）
    - **u_position**: U位（字符串，如"10-12"表示占用U10到U12，或"10"表示占用U10）
    - **rack_position**: 机架位置（字符串）
    - **remark**: 备注（字符串）
    
    **示例**：
    ```json
    {
      "room_name": "Room-A",
      "cabinet_number": "CAB-001",
      "u_position": "10-12",
      "remark": "靠近冷通道"
    }
    ```
    
    ### 2. power_management（电源管理工单）
    **必填字段**：
    - **power_action**: 动作类型（字符串）
      - "power_on": 上电
      - "power_off": 下电
    
    **上电时可选字段**：
    - **power_type**: 电源类型（字符串，默认"AC"）
      - "AC": 交流电
      - "DC": 直流电
    - **remark**: 备注（字符串）
    
    **下电时必填字段**：
    - **reason**: 下电原因（字符串，必须说明为什么要下电）
    
    **下电时可选字段**：
    - **remark**: 备注（字符串）
    
    **上电示例**：
    ```json
    {
      "power_action": "power_on",
      "power_type": "AC",
      "remark": "业务上线需要"
    }
    ```
    
    **下电示例**：
    ```json
    {
      "power_action": "power_off",
      "reason": "设备维护需要下电",
      "remark": "计划维护窗口"
    }
    ```
    
    ### 3. configuration（设备增配工单）
    **有SN的配件（必填字段）**：
    - **sn**: 配件序列号（字符串）
    - **quantity**: 配件数量（整数）
    
    **有SN的配件（可选字段）**：
    - **slot**: 增配槽位（字符串，如"DIMM-A1"）
    - **port**: 增配端口（字符串）
    
    **无SN的配件（可选字段）**：
    - **title**: 配件名称（字符串，如"散热风扇"）
    - **slot**: 增配槽位（字符串）
    - **port**: 增配端口（字符串）
    
    **有SN配件示例**：
    ```json
    {
      "sn": "SN-MEM-001",
      "slot": "DIMM-A1",
      "quantity": 1,
      "port": ""
    }
    ```
    
    **无SN配件示例**：
    ```json
    {
      "title": "散热风扇",
      "slot": "FAN-1",
      "port": ""
    }
    ```
    
    ## 返回字段说明
    - **batch_id**: 批次ID（格式：前缀_YYYYMMDDHHMMSS）
      - RECV: 设备到货
      - RACK: 设备上架
      - PWR: 电源管理
      - CONF: 设备增配
      - NET: 网线更换
      - MAINT: 设备维护
    - **operation_type**: 操作类型
    - **title**: 工单标题
    - **status**: 工单状态（pending-待处理）
    - **created_items**: 成功创建的明细数量
    - **failed_items**: 创建失败的明细数量
    - **datacenter**: 机房
    - **room**: 房间
    - **device_count**: 设备数量
    - **creator**: 创建人
    - **created_at**: 创建时间
    - **power_action**: 电源操作（仅电源管理工单）
    - **parent_device_sn**: 父设备SN（仅增配工单）
    - **vendor_onsite**: 厂商是否上门（仅增配工单）
    - **is_optical_module_upgrade**: 是否光模块增配（仅增配工单）
    
    ## 注意事项
    1. asset_identifier可以是设备的序列号（serial_number）或资产ID
    2. 电源管理工单必须提供：assignee（指派人）、room（房间）、expected_completion_time（期望完成时间）
    3. 电源管理工单的operation_data必须包含power_action字段
    4. 下电操作必须提供reason字段说明原因
    5. 增配工单中，有SN的配件必须在资产表中存在
    6. 增配工单中，无SN的配件会关联到父设备
    7. 批次ID会根据operation_type自动生成对应前缀
    8. 所有资产标识必须在系统中存在，否则会返回400错误
    """
    
    try:
        # 1. 验证操作类型（这里应该调用字典验证）
        # if not validate_dict_value(db, DictTypeCode.WORK_ORDER_OPERATION_TYPE, request.operation_type):
        #     raise HTTPException(400, f"无效的操作类型: {request.operation_type}")
        
        # 2. 生成批次ID
        batch_id = generate_batch_id(request.operation_type)
        
        # 3. 机房级别上下电：不需要验证资产
        is_room_level_power = (
            request.operation_type == 'power_management' and 
            (not request.items or len(request.items) == 0)
        )
        
        # 4. 验证资产是否存在（机房级别上下电跳过）
        assets_map = {}
        missing_identifiers = []
        validated_items = []
        
        if not is_room_level_power:
            # 增配工单特殊处理：验证父设备，有SN的配件验证资产存在
            if request.operation_type == 'configuration':
                # 验证父设备存在
                parent_asset = find_asset_by_identifier(db, request.parent_device_sn)
                if not parent_asset:
                    return ApiResponse(
                        code=1002,
                        message=f"父设备不存在: {request.parent_device_sn}",
                        data=None
                    )
                
                # 验证配件：有SN的需要在资产表中存在，无SN的不需要
                for item in request.items:
                    if 'sn' in item.operation_data and item.operation_data['sn']:
                        # 有SN的配件：验证资产存在
                        component_asset = find_asset_by_identifier(db, item.operation_data['sn'])
                        if not component_asset:
                            missing_identifiers.append(item.operation_data['sn'])
                        else:
                            assets_map[item.asset_identifier] = component_asset
                    else:
                        # 无SN的配件：使用父设备
                        assets_map[item.asset_identifier] = parent_asset
                
                if missing_identifiers:
                    return ApiResponse(
                        code=1002,
                        message=f"以下配件SN不存在: {', '.join(missing_identifiers[:10])}{'...' if len(missing_identifiers) > 10 else ''}",
                        data=None
                    )
            else:
                # 其他工单类型：验证所有资产存在
                for item in request.items:
                    asset = find_asset_by_identifier(db, item.asset_identifier)
                    if not asset:
                        missing_identifiers.append(item.asset_identifier)
                    else:
                        assets_map[item.asset_identifier] = asset
                
                if missing_identifiers:
                    return ApiResponse(
                        code=1002,
                        message=f"以下资产标识不存在: {', '.join(missing_identifiers[:10])}{'...' if len(missing_identifiers) > 10 else ''}",
                        data=None
                    )
            
            # 5. 验证操作数据
            for item in request.items:
                try:
                    validated_data = validate_operation_data(
                        request.operation_type, 
                        item.operation_data, 
                        db,
                        assets_map[item.asset_identifier]
                    )
                    validated_items.append({
                        'asset': assets_map[item.asset_identifier],
                        'operation_data': validated_data
                    })
                except ValueError as e:
                    return ApiResponse(
                        code=1001,
                        message=f"资产 {item.asset_identifier} 的操作数据验证失败: {str(e)}",
                        data=None
                    )
        
        # 6. 创建WorkOrder（根据operation_type设置不同字段）
        work_order_data = {
            'batch_id': batch_id,
            'operation_type': request.operation_type,
            'title': request.title,
            'description': request.description,
            'status': 'pending',
            'work_order_status': 'processing',  # 外部工单状态：创建成功即为进行中
            'creator': request.creator,
            'assignee': request.assignee,
            'datacenter': request.datacenter,
            'room': request.room,
            'expected_completion_time': request.expected_completion_time,
            'device_count': len(validated_items) if not is_room_level_power else 0,  # 设备数量
            'remark': request.remark
        }
        
        # 电源管理工单特殊处理
        if request.operation_type == 'power_management':
            if is_room_level_power:
                # 机房级别上下电：保存power_action等信息到extra字段
                work_order_data['extra'] = {
                    'power_action': request.power_action,
                    'power_type': request.power_type or 'AC',
                    'reason': request.reason,
                    'power_reason': request.reason,
                    'level': 'room'  # 标记为机房级别
                }
                work_order_data['description'] = request.description or f"机房{request.room}{'上电' if request.power_action == 'power_on' else '下电'}操作"
                if request.reason:
                    work_order_data['description'] += f"，原因：{request.reason}"
                # remark保留用户输入的备注
                work_order_data['remark'] = request.remark
            else:
                # 设备级别上下电：统计机柜数量
                cabinets = set()
                for item_data in validated_items:
                    asset = item_data['asset']
                    # 从资产的location_detail中提取机柜信息，或从operation_data中获取
                    cabinet = None
                    if asset.location_detail:
                        # 尝试从location_detail解析机柜号（假设格式如"CAB-001机柜，10-12U"）
                        import re
                        match = re.search(r'([A-Z0-9\-]+)(?:机柜|柜)', asset.location_detail)
                        if match:
                            cabinet = match.group(1)
                    
                    # 如果从资产信息中没有获取到，尝试从operation_data获取
                    if not cabinet:
                        operation_data = item_data['operation_data']
                        cabinet = operation_data.get('cabinet_number') or operation_data.get('cabinet')
                    
                    if cabinet:
                        cabinets.add(cabinet)
                
                work_order_data['cabinet_count'] = len(cabinets) if cabinets else 0
        
        # 根据不同的operation_type设置特定字段
        if request.operation_type == 'receiving':
            # 设备到货工单特定字段
            # device_category_level1 可以从第一个设备的分类获取
            first_asset = validated_items[0]['asset']
            if hasattr(first_asset, 'category') and first_asset.category:
                work_order_data['device_category_level1'] = first_asset.category.name
        
        elif request.operation_type == 'racking':
            # 设备上架工单特定字段
            # 从第一个item的operation_data中提取
            first_op_data = validated_items[0]['operation_data']
            work_order_data['cabinet'] = first_op_data.get('cabinet_number')
            work_order_data['rack_position'] = first_op_data.get('rack_position')
            # 可以设置默认SLA倒计时（如2小时 = 7200秒）
            work_order_data['sla_countdown'] = 7200
            work_order_data['is_timeout'] = False
        
        elif request.operation_type == 'configuration':
            # 设备增配工单特定字段（从request中获取必需字段）
            work_order_data['parent_device_sn'] = request.parent_device_sn
            work_order_data['vendor_onsite'] = request.vendor_onsite
            work_order_data['parent_device_can_shutdown'] = request.parent_device_can_shutdown
            work_order_data['allowed_operation_start_time'] = request.allowed_operation_start_time
            work_order_data['allowed_operation_end_time'] = request.allowed_operation_end_time
            work_order_data['is_optical_module_upgrade'] = request.is_optical_module_upgrade
            work_order_data['is_project_upgrade'] = request.is_project_upgrade
            work_order_data['project_number'] = request.project_number
            work_order_data['remark'] = request.remark
            
            # 统计所有配件的总数量
            total_quantity = 0
            for item_data in validated_items:
                operation_data = item_data['operation_data']
                quantity = operation_data.get('quantity', 1)  # 默认为1
                total_quantity += quantity
            work_order_data['component_quantity'] = total_quantity
        
        work_order = WorkOrder(**work_order_data)
        db.add(work_order)
        db.flush()
        
        # 7. 创建WorkOrderItem（机房级别上下电不需要创建明细）
        created_items = []
        if not is_room_level_power:
            for item_data in validated_items:
                asset = item_data['asset']
                operation_data = item_data['operation_data']
                
                # 添加资产基础信息到operation_data
                operation_data.update({
                    'serial_number': asset.serial_number,
                    'asset_tag': asset.asset_tag,
                    'asset_name': asset.name,
                    'current_room_id': asset.room_id,
                    'current_room_name': asset.room.room_abbreviation if asset.room else None,
                    'current_lifecycle_status': asset.lifecycle_status
                })
                
                # 创建工单明细，包含冗余字段
                work_order_item = WorkOrderItem(
                    work_order_id=work_order.id,
                    asset_id=asset.id,
                    asset_sn=asset.serial_number,  # 冗余字段，便于查询
                    asset_tag=asset.asset_tag,  # 冗余字段
                    operation_data=operation_data,
                status="pending",
                # 设置明细级别的位置信息（如果有）
                item_datacenter=operation_data.get('datacenter'),
                item_room=operation_data.get('room') or operation_data.get('target_room_name'),
                item_cabinet=operation_data.get('cabinet_number'),
                item_rack_position=operation_data.get('rack_position')
            )
            db.add(work_order_item)
            
            created_items.append({
                'asset_identifier': asset.serial_number,
                'asset_tag': asset.asset_tag,
                'asset_name': asset.name,
                'operation_summary': get_operation_summary(request.operation_type, operation_data)
            })
        
        # 7. 先flush但不commit，等待外部工单创建成功后再提交
        db.flush()
        
        # 8. 调用外部工单系统创建工单
        from app.services.work_order_service import create_work_order as create_external_work_order
        
        external_work_order_result = await create_external_work_order(
            db=db,
            work_order_type=request.operation_type,
            business_id=batch_id,
            title=request.title,
            creator_name=request.creator,
            assignee=request.assignee or request.creator,
            description=request.description or f"{request.operation_type}工单，共{len(created_items)}项"
        )
        
        # 9. 检查外部工单创建结果
        if not external_work_order_result or not external_work_order_result.get("success"):
            # 外部工单创建失败，回滚整个事务
            db.rollback()
            error_msg = external_work_order_result.get('error') if external_work_order_result else '外部工单系统无响应'
            logger.error(f"外部工单创建失败，回滚事务: {error_msg}")
            return ApiResponse(
                code=5002,
                message=f"工单创建失败: {error_msg}",
                data=None
            )
        
        # 10. 外部工单创建成功，提交事务
        db.commit()
        db.refresh(work_order)
        logger.info(f"外部工单创建成功: {external_work_order_result.get('work_order_number')}")
        
        # 11. 记录日志到ES
        from app.constants.operation_types import OperationType, OperationResult
        
        # 电源管理工单使用专用的操作类型
        if request.operation_type == 'power_management':
            log_operation_type = OperationType.POWER_MANAGEMENT_SUBMIT  # 提单
            power_action_desc = "上电" if request.power_action == "power_on" else "下电"
            log_detail = f"提交电源管理工单（{power_action_desc}），房间: {request.room}"
        else:
            log_operation_type = OperationType.WORK_ORDER_CREATE
            log_detail = f"创建{request.operation_type}工单，共{len(created_items)}项"
        
        logger.info(f"Work order created", extra={
            "operationObject": batch_id,
            "operationType": log_operation_type,
            "operator": request.creator,
            "result": OperationResult.SUCCESS,
            "operationDetail": log_detail,
            "remark": request.remark
        })
        
        return ApiResponse(
            code=0,
            message="工单创建成功",
            data={
                "batch_id": batch_id,
                "work_order_id": work_order.id,
                "work_order_number": work_order.work_order_number,  # 返回外部工单号
                "operation_type": request.operation_type,
                "title": request.title,
                "status": "pending",
                "work_order_status": work_order.work_order_status,
                "items_count": len(created_items),
                "external_work_order_created": True,  # 外部工单创建成功
                "items": created_items
            }
        )
        
    except Exception as e:
        logger.error(f"Create work order failed: {str(e)}")
        return ApiResponse(
            code=5000,
            message=f"创建工单失败: {str(e)}",
            data=None
        )


def get_operation_summary(operation_type: str, operation_data: Dict[str, Any]) -> str:
    """生成操作摘要"""
    
    if operation_type == "receiving":
        return f"到货至: {operation_data.get('target_room_name', '未知房间')}"
    
    elif operation_type == "racking":
        cabinet = operation_data.get('cabinet_number', '未知机柜')
        u_start = operation_data.get('u_position_start', '?')
        u_end = operation_data.get('u_position_end', '?')
        return f"上架至: {cabinet} U{u_start}-U{u_end}"
    
    elif operation_type == "power_management":
        power_action = operation_data.get('power_action', 'unknown')
        if power_action == 'power_on':
            return f"上电: {operation_data.get('power_type', 'AC')}电源"
        elif power_action == 'power_off':
            return f"下电: {operation_data.get('reason', '未知原因')}"
        else:
            return f"电源管理: {power_action}"
    
    elif operation_type == "configuration":
        config_type = operation_data.get('config_type', '未知配置')
        return f"配置: {config_type}"
    
    elif operation_type == "manual_usb_install":
        os_template = operation_data.get('os_template', '未指定')
        project_req = operation_data.get('project_requirement', '')
        if project_req:
            return f"U盘装机: {os_template}, {project_req[:20]}..."
        return f"U盘装机: {os_template}"
    
    else:
        return f"{operation_type}操作"


@router.get("/by-sn/{serial_number}", summary="通过SN查询工单",
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
                                    "serial_number": "SN123456",
                                    "asset_tag": "AT001",
                                    "asset_name": "Dell服务器R740",
                                    "work_orders_count": 2,
                                    "work_orders": [
                                        {
                                            "batch_id": "RACK_20251205120000",
                                            "work_order_number": "WO202512051234",
                                            "operation_type": "racking",
                                            "title": "服务器上架",
                                            "status": "completed",
                                            "work_order_status": "已完成",
                                            "creator": "张三",
                                            "assignee": "李四",
                                            "created_at": "2025-12-05T12:00:00",
                                            "completed_time": "2025-12-05T14:00:00",
                                            "item_status": "completed",
                                            "item_result": "上架成功",
                                            "operation_data": {
                                                "cabinet_number": "CAB-001",
                                                "u_position": "10-12"
                                            }
                                        },
                                        {
                                            "batch_id": "PWR_20251204100000",
                                            "work_order_number": "WO202512041000",
                                            "operation_type": "power_management",
                                            "title": "服务器上电",
                                            "status": "completed",
                                            "work_order_status": "已完成",
                                            "creator": "王五",
                                            "assignee": "赵六",
                                            "created_at": "2025-12-04T10:00:00",
                                            "completed_time": "2025-12-04T10:30:00",
                                            "item_status": "completed",
                                            "item_result": "上电成功",
                                            "operation_data": {
                                                "power_action": "power_on",
                                                "power_type": "AC"
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    }
                },
                404: {
                    "description": "设备不存在",
                    "content": {
                        "application/json": {
                            "example": {
                                "code": 404,
                                "message": "设备不存在: SN123456",
                                "data": None
                            }
                        }
                    }
                },
                500: {"description": "服务器内部错误"}
            })
async def get_work_orders_by_sn(
    serial_number: str = Path(..., description="设备序列号", example="SN123456"),
    operation_type: Optional[str] = Query(None, description="工单类型筛选（可选）", example="racking"),
    status: Optional[str] = Query(None, description="工单状态筛选（可选）", example="completed"),
    db: Session = Depends(get_db)
):
    """
    通过设备SN查询关联的工单
    
    ## 功能说明
    根据设备序列号查询该设备相关的所有工单记录，包括上架、电源管理、增配等各类工单。
    
    ## 路径参数
    - **serial_number**: 设备序列号（必填）
    
    ## 查询参数
    - **operation_type**: 工单类型筛选（可选）
      - receiving: 设备到货
      - racking: 设备上架
      - power_management: 电源管理
      - configuration: 设备增配
      - network_cable: 网线更换
      - maintenance: 设备维护
    - **status**: 工单状态筛选（可选）
      - pending: 待处理
      - processing: 处理中
      - completed: 已完成
      - cancelled: 已取消
    
    ## 返回字段说明
    - **serial_number**: 设备序列号
    - **asset_tag**: 资产标签
    - **asset_name**: 资产名称
    - **work_orders_count**: 关联的工单数量
    - **work_orders**: 工单列表
      - **batch_id**: 批次ID
      - **work_order_number**: 外部工单号
      - **operation_type**: 操作类型
      - **title**: 工单标题
      - **status**: 工单状态
      - **work_order_status**: 工单状态描述
      - **creator**: 创建人
      - **assignee**: 指派人
      - **created_at**: 创建时间
      - **completed_time**: 完成时间
      - **item_status**: 该设备在此工单中的状态
      - **item_result**: 该设备在此工单中的处理结果
      - **operation_data**: 该设备在此工单中的操作数据
    
    ## 使用场景
    1. 查看某台设备的完整工单历史
    2. 追踪设备的操作记录
    3. 审计设备的变更历史
    
    ## 注意事项
    1. 如果设备不存在，返回404错误
    2. 如果设备存在但没有关联工单，返回空列表
    3. 工单按创建时间倒序排列（最新的在前）
    4. operation_data包含该设备在该工单中的具体操作信息
    """
    
    # 1. 验证资产是否存在
    asset = db.query(Asset).filter(Asset.serial_number == serial_number).first()
    if not asset:
        raise HTTPException(404, f"设备不存在: {serial_number}")
    
    # 2. 查询该设备相关的所有工单明细
    query = db.query(WorkOrderItem).filter(
        WorkOrderItem.asset_id == asset.id
    )
    
    work_order_items = query.all()
    
    if not work_order_items:
        return {
            "code": 0,
            "message": "未找到相关工单",
            "data": {
                "serial_number": serial_number,
                "asset_tag": asset.asset_tag,
                "asset_name": asset.name,
                "work_orders": []
            }
        }
    
    # 3. 获取所有关联的工单
    work_order_ids = [item.work_order_id for item in work_order_items]
    work_orders_query = db.query(WorkOrder).filter(WorkOrder.id.in_(work_order_ids))
    
    # 应用筛选条件
    if operation_type:
        work_orders_query = work_orders_query.filter(WorkOrder.operation_type == operation_type)
    if status:
        work_orders_query = work_orders_query.filter(WorkOrder.status == status)
    
    work_orders = work_orders_query.order_by(WorkOrder.created_at.desc()).all()
    
    # 4. 构建返回数据
    work_orders_data = []
    for work_order in work_orders:
        # 找到该工单中对应的明细
        item = next((i for i in work_order_items if i.work_order_id == work_order.id), None)
        
        work_orders_data.append({
            "batch_id": work_order.batch_id,
            "work_order_number": work_order.work_order_number,
            "operation_type": work_order.operation_type,
            "title": work_order.title,
            "status": work_order.status,
            "work_order_status": work_order.work_order_status,
            "creator": work_order.creator,
            "assignee": work_order.assignee,
            "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
            "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
            # 该设备在此工单中的信息
            "item_status": item.status if item else None,
            "item_result": item.result if item else None,
            "operation_data": item.operation_data if item else None
        })
    
    return {
        "code": 0,
        "message": "查询成功",
        "data": {
            "serial_number": serial_number,
            "asset_tag": asset.asset_tag,
            "asset_name": asset.name,
            "work_orders_count": len(work_orders_data),
            "work_orders": work_orders_data
        }
    }


@router.get("/by-work-order-number/{work_order_number}", summary="通过工单号查询工单详情和设备列表",
            response_model=ApiResponse,
            responses={
                200: {
                    "description": "查询成功",
                    "content": {
                        "application/json": {
                            "examples": {
                                "manual_usb_install": {
                                    "summary": "U盘装机工单示例（包含位置和端口信息）",
                                    "value": {
                                        "code": 0,
                                        "message": "查询成功",
                                        "data": {
                                            "work_order_number": "manualUsbSetup1765361663942",
                                            "batch_id": "USB_20251210181426",
                                            "operation_type": "manual_usb_install",
                                            "title": "测试U盘装机工单",
                                            "status": "pending",
                                            "datacenter": "DC01",
                                            "room": "A101",
                                            "device_count": 1,
                                            "items_count": 1,
                                            "items": [
                                                {
                                                    "id": 71,
                                                    "asset_identifier": "SN123456",
                                                    "asset_tag": "AT123456",
                                                    "asset_name": "测试服务器",
                                                    "datacenter": "DC01",
                                                    "room": "A101",
                                                    "cabinet": "TEST-CAB-001",
                                                    "rack_position": "10-11U",
                                                    "location_detail": "TEST-CAB-001 U10-U11",
                                                    "port_info": [
                                                        {
                                                            "source_port": "eth0",
                                                            "target_port": "port1",
                                                            "target_asset_sn": "SW001",
                                                            "connection_type": "ethernet",
                                                            "cable_type": "Cat6"
                                                        }
                                                    ],
                                                    "status": "pending",
                                                    "operation_data": {
                                                        "serial_number": "SN123456",
                                                        "os_template": "CentOS 7.9",
                                                        "project_requirement": "新项目上线需要装机测试"
                                                    },
                                                    "operation_summary": "U盘装机: CentOS 7.9, 新项目上线需要装机测试...",
                                                    "result": None,
                                                    "error_message": None
                                                }
                                            ]
                                        }
                                    }
                                },
                                "racking": {
                                    "summary": "上架工单示例（包含设备详细信息和上下联设备）",
                                    "value": {
                                        "code": 0,
                                        "message": "查询成功",
                                        "data": {
                                            "work_order_number": "WO202512051234",
                                            "batch_id": "RACK_20251205120000",
                                            "operation_type": "racking",
                                            "title": "服务器上架",
                                            "status": "completed",
                                            "device_count": 2,
                                            "items_count": 2,
                                            "items": [
                                                {
                                                    "id": 1,
                                                    "asset_identifier": "SN123456",
                                                    "asset_tag": "AT001",
                                                    "asset_name": "Dell服务器R740",
                                                    "asset_id": 100,
                                                    "sn": "SN123456",
                                                    "serial_number": "SN123456",
                                                    "is_company_device": True,
                                                    "datacenter": "DC01",
                                                    "room": "A101",
                                                    "cabinet": "CAB-001",
                                                    "rack_position": "10-12U",
                                                    "location_detail": "CAB-001机柜 10-12U",
                                                    "port_info": None,
                                                    "category_level1": "服务器",
                                                    "category_level2": "机架式服务器",
                                                    "category_level3": "2U机架式服务器",
                                                    "device_category_level1": "服务器",
                                                    "device_category_level2": "机架式服务器",
                                                    "device_category_level3": "2U机架式服务器",
                                                    "vendor": "Dell",
                                                    "vendor_name": "Dell",
                                                    "vendor_id": 1,
                                                    "model": "PowerEdge R740",
                                                    "vendor_standard_model": "Dell R740",
                                                    "order_number": "RK202512050001",
                                                    "target_datacenter": "DC01",
                                                    "target_room": "A101",
                                                    "target_cabinet": "CAB-001",
                                                    "target_rack_position": "10-12",
                                                    "outbound_order_number": None,
                                                    "inbound_order_number": "receiving1765248024499",
                                                    "network_racking_order_number": None,
                                                    "power_order_number": "PWR20251209174250",
                                                    "power_connection_order_number": "PWR20251209174250",
                                                    "connected_devices": [
                                                        {"sn": "SW-CORE-001", "is_company_device": True, "device_type": "upstream"},
                                                        {"sn": "STORAGE-001", "is_company_device": False, "device_type": "downstream"}
                                                    ],
                                                    "status": "completed",
                                                    "operation_data": {
                                                        "cabinet_number": "CAB-001",
                                                        "u_position": "10-12"
                                                    },
                                                    "operation_summary": "上架至: CAB-001 U10-U12",
                                                    "result": "上架成功",
                                                    "error_message": None
                                                }
                                            ]
                                        }
                                    }
                                },
                                "power_management": {
                                    "summary": "电源管理工单示例（包含机柜信息）",
                                    "value": {
                                        "code": 0,
                                        "message": "查询成功",
                                        "data": {
                                            "work_order_number": "WO202512051234",
                                            "batch_id": "PWR_20251205120000",
                                            "operation_type": "power_management",
                                            "title": "A101房间设备上电",
                                            "status": "processing",
                                            "room": "A101",
                                            "power_action": "power_on",
                                            "power_type": "AC",
                                            "cabinet_count": 2,
                                            "device_count": 3,
                                            "items_count": 3,
                                            "room_cabinets_info": {
                                                "room_name": "A101",
                                                "total_cabinets": 5,
                                                "cabinets_in_work_order": 2,
                                                "cabinets_not_in_work_order": 3,
                                                "cabinets": [
                                                    {
                                                        "cabinet_number": "CAB-001",
                                                        "cabinet_name": "机柜001",
                                                        "power_status": "on",
                                                        "total_devices": 10,
                                                        "devices_in_work_order": 3,
                                                        "is_in_work_order": True
                                                    }
                                                ]
                                            },
                                            "items": [
                                                {
                                                    "id": 1,
                                                    "asset_identifier": "SN123456",
                                                    "asset_tag": "AT001",
                                                    "asset_name": "Dell服务器R740",
                                                    "datacenter": "DC01",
                                                    "room": "A101",
                                                    "cabinet": "CAB-001",
                                                    "rack_position": "10-12U",
                                                    "location_detail": "CAB-001机柜 10-12U",
                                                    "port_info": None,
                                                    "status": "pending",
                                                    "operation_data": {"power_action": "power_on"},
                                                    "operation_summary": "上电: AC电源",
                                                    "result": None,
                                                    "error_message": None
                                                }
                                            ]
                                        }
                                    }
                                },
                                "asset_accounting": {
                                    "summary": "资产出入门工单示例",
                                    "value": {
                                        "code": 0,
                                        "message": "查询成功",
                                        "data": {
                                            "work_order_number": "assetAccounting1765412345678",
                                            "batch_id": "AEE_20251210120000",
                                            "arrival_order_number": None,
                                            "source_order_number": None,
                                            "operation_type": "asset_accounting",
                                            "title": "服务器设备搬入",
                                            "description": "出入类型: 搬入\n出入范围: 出入机房\n出入原因: 新设备采购到货\n出入日期: 2025-12-10\n机房: DC01\n设备数量: 2",
                                            "status": "pending",
                                            "work_order_status": "processing",
                                            "is_timeout": False,
                                            "sla_countdown": None,
                                            "creator": "李四",
                                            "operator": None,
                                            "assignee": "张三",
                                            "reviewer": None,
                                            "datacenter": "DC01",
                                            "campus": None,
                                            "room": None,
                                            "cabinet": None,
                                            "rack_position": None,
                                            "project_number": None,
                                            "start_time": None,
                                            "expected_completion_time": None,
                                            "completed_time": None,
                                            "close_time": None,
                                            "created_at": "2025-12-10T12:00:00",
                                            "updated_at": "2025-12-10T12:00:00",
                                            "device_count": 2,
                                            "items_count": 2,
                                            "remark": "请提前准备好机柜空间",
                                            "priority": "normal",
                                            "operation_type_detail": None,
                                            "is_business_online": None,
                                            "failure_reason": None,
                                            "attachments": ["https://example.com/attachment1.pdf"],
                                            "business_type": "other",
                                            "service_content": "新采购服务器搬入机房上架",
                                            "entry_exit_type": "move_in",
                                            "entry_exit_scope": "datacenter",
                                            "entry_exit_reason": "新设备采购到货，需搬入机房进行上架部署",
                                            "entry_exit_date": "2025-12-10",
                                            "device_sns": ["SN123456", "SN789012"],
                                            "creator_name": "李四",
                                            "campus_auth_order_number": None,
                                            "campus_auth_status": None,
                                            "device_type": None,
                                            "items": [
                                                {
                                                    "id": 1,
                                                    "asset_identifier": "SN123456",
                                                    "asset_tag": "ASSET-001",
                                                    "asset_name": "Dell服务器R740",
                                                    "datacenter": "DC01",
                                                    "room": "A101",
                                                    "cabinet": "CAB-001",
                                                    "rack_position": "10-12U",
                                                    "location_detail": "CAB-001机柜 10-12U",
                                                    "port_info": None,
                                                    "status": "pending",
                                                    "operation_data": {
                                                        "serial_number": "SN123456",
                                                        "asset_tag": "ASSET-001",
                                                        "asset_name": "Dell服务器R740",
                                                        "datacenter": "DC01",
                                                        "entry_exit_type": "move_in",
                                                        "entry_exit_scope": "datacenter",
                                                        "entry_exit_reason": "新设备采购到货，需搬入机房进行上架部署",
                                                        "entry_exit_date": "2025-12-10"
                                                    },
                                                    "operation_summary": "搬入: 出入机房",
                                                    "result": None,
                                                    "error_message": None
                                                },
                                                {
                                                    "id": 2,
                                                    "asset_identifier": "SN789012",
                                                    "asset_tag": "ASSET-002",
                                                    "asset_name": "Dell服务器R750",
                                                    "datacenter": "DC01",
                                                    "room": "A101",
                                                    "cabinet": "CAB-002",
                                                    "rack_position": "15-17U",
                                                    "location_detail": "CAB-002机柜 15-17U",
                                                    "port_info": None,
                                                    "status": "pending",
                                                    "operation_data": {
                                                        "serial_number": "SN789012",
                                                        "asset_tag": "ASSET-002",
                                                        "asset_name": "Dell服务器R750",
                                                        "datacenter": "DC01",
                                                        "entry_exit_type": "move_in",
                                                        "entry_exit_scope": "datacenter",
                                                        "entry_exit_reason": "新设备采购到货，需搬入机房进行上架部署",
                                                        "entry_exit_date": "2025-12-10"
                                                    },
                                                    "operation_summary": "搬入: 出入机房",
                                                    "result": None,
                                                    "error_message": None
                                                }
                                            ]
                                        }
                                    }
                                },
                                "configuration": {
                                    "summary": "设备增配工单示例（包含sn配件列表和无sn配件列表）",
                                    "value": {
                                        "code": 0,
                                        "message": "查询成功",
                                        "data": {
                                            "work_order_number": "configuration1765412345678",
                                            "batch_id": "CONF_20251212120000",
                                            "operation_type": "configuration",
                                            "title": "服务器内存和风扇增配",
                                            "status": "pending",
                                            "datacenter": "DC01",
                                            "room": "A101",
                                            "parent_device_sn": "SN-SERVER-001",
                                            "vendor_onsite": True,
                                            "parent_device_can_shutdown": False,
                                            "allowed_operation_start_time": "2025-12-12T20:00:00",
                                            "allowed_operation_end_time": "2025-12-13T06:00:00",
                                            "is_optical_module_upgrade": False,
                                            "is_project_upgrade": True,
                                            "component_quantity": 4,
                                            "device_count": 4,
                                            "items_count": 4,
                                            "sn_components_count": 2,
                                            "no_sn_components_count": 2,
                                            "sn_components": [
                                                {
                                                    "id": 1,
                                                    "sn": "SN-MEM-001",
                                                    "asset_identifier": "SN-MEM-001",
                                                    "asset_tag": "MEM-001",
                                                    "asset_name": "DDR4内存条32GB",
                                                    "quantity": 1,
                                                    "device_category_level1": "配件",
                                                    "device_category_level2": "内存",
                                                    "device_category_level3": "DDR4内存",
                                                    "configuration_datacenter": "DC01",
                                                    "configuration_room": "A101",
                                                    "component_model": "DDR4-3200-32GB",
                                                    "mpn": "MPN-MEM-001",
                                                    "slot": "DIMM-A1",
                                                    "port": "",
                                                    "status": "pending",
                                                    "result": None,
                                                    "error_message": None
                                                },
                                                {
                                                    "id": 2,
                                                    "sn": "SN-MEM-002",
                                                    "asset_identifier": "SN-MEM-002",
                                                    "asset_tag": "MEM-002",
                                                    "asset_name": "DDR4内存条32GB",
                                                    "quantity": 1,
                                                    "device_category_level1": "配件",
                                                    "device_category_level2": "内存",
                                                    "device_category_level3": "DDR4内存",
                                                    "configuration_datacenter": "DC01",
                                                    "configuration_room": "A101",
                                                    "component_model": "DDR4-3200-32GB",
                                                    "mpn": "MPN-MEM-002",
                                                    "slot": "DIMM-A2",
                                                    "port": "",
                                                    "status": "pending",
                                                    "result": None,
                                                    "error_message": None
                                                }
                                            ],
                                            "no_sn_components": [
                                                {
                                                    "id": 3,
                                                    "title": "散热风扇",
                                                    "quantity": 1,
                                                    "device_category_level1": "配件",
                                                    "device_category_level2": "散热设备",
                                                    "device_category_level3": "风扇",
                                                    "configuration_datacenter": "DC01",
                                                    "configuration_room": "A101",
                                                    "component_model": "FAN-120MM",
                                                    "mpn": None,
                                                    "slot": "FAN-1",
                                                    "port": "",
                                                    "parent_device_sn": "SN-SERVER-001",
                                                    "status": "pending",
                                                    "result": None,
                                                    "error_message": None
                                                },
                                                {
                                                    "id": 4,
                                                    "title": "RAID控制器电池",
                                                    "quantity": 1,
                                                    "device_category_level1": "配件",
                                                    "device_category_level2": "存储配件",
                                                    "device_category_level3": "RAID电池",
                                                    "configuration_datacenter": "DC01",
                                                    "configuration_room": "A101",
                                                    "component_model": "BBU-01",
                                                    "mpn": None,
                                                    "slot": "RAID-BATTERY",
                                                    "port": "",
                                                    "parent_device_sn": "SN-SERVER-001",
                                                    "status": "pending",
                                                    "result": None,
                                                    "error_message": None
                                                }
                                            ],
                                            "items": []
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                404: {
                    "description": "工单不存在",
                    "content": {
                        "application/json": {
                            "example": {
                                "code": 404,
                                "message": "工单不存在: WO202512051234",
                                "data": None
                            }
                        }
                    }
                },
                500: {"description": "服务器内部错误"}
            })
async def get_assets_by_work_order_number(
    work_order_number: str = Path(..., description="外部工单号", example="WO202512051234"),
    db: Session = Depends(get_db)
):
    """
    通过外部工单号查询工单详情和设备列表
    
    ## 功能说明
    根据外部工单系统的工单号查询工单的完整信息，包括所有设备及其处理状态。
    每个设备会返回完整的位置信息（机房、房间、机柜、机位）和端口连接信息。
    电源管理工单会额外返回机柜详细信息（32个字段）。
    
    ## 路径参数
    - **work_order_number**: 外部工单号（必填）
    
    ## 返回字段说明
    
    ### 工单基本信息
    - **work_order_number**: 外部工单号
    - **batch_id**: 本地批次ID
    - **operation_type**: 操作类型（receiving/racking/power_management/manual_usb_install/generic_operation等）
    - **title**: 工单标题
    - **description**: 工单描述
    - **status**: 工单状态（pending/processing/completed/cancelled）
    - **work_order_status**: 外部工单状态
    - **creator**: 创建人
    - **assignee**: 指派人
    - **operator**: 操作人
    - **datacenter**: 机房
    - **room**: 房间
    - **remark**: 备注
    - **created_at**: 创建时间
    - **expected_completion_time**: 期望完成时间
    - **completed_time**: 完成时间
    - **device_count**: 设备数量
    - **items_count**: 设备明细数量
    
    ### 设备明细列表（items）
    每个设备包含以下字段：
    
    #### 基本信息
    - **id**: 明细ID
    - **asset_identifier**: 设备序列号
    - **asset_tag**: 资产标签
    - **asset_name**: 资产名称
    
    #### 位置信息（新增）
    - **datacenter**: 机房，设备所在的数据中心，如"DC01"
    - **room**: 房间，设备所在的房间，如"A101"
    - **cabinet**: 机柜，设备所在的机柜编号，如"CAB-001"、"TEST-CAB-001"
    - **rack_position**: 机位，设备在机柜中的U位，如"10-12U"
    - **location_detail**: 完整位置描述，原始的位置信息字符串，如"TEST-CAB-001 U10-U11"
    
    #### 端口信息（新增）
    - **port_info**: 端口连接信息列表，如果设备有网络连接则返回，否则为null
      - **source_port**: 源端口，本设备的端口名称，如"eth0"、"port1"
      - **target_port**: 目标端口，对端设备的端口名称
      - **target_asset_sn**: 对端设备序列号，连接的目标设备SN
      - **connection_type**: 连接类型，如"ethernet"（以太网）、"fiber"（光纤）、"console"（控制台）
      - **cable_type**: 线缆类型，如"Cat6"、"Cat6A"、"光纤"
    
    #### 状态和操作信息
    - **status**: 该设备的处理状态（pending/processing/completed/failed）
    - **operation_data**: 该设备的操作数据（JSON对象，根据工单类型不同内容不同）
    - **operation_summary**: 操作摘要，自动生成的可读描述
    - **result**: 该设备的处理结果
    - **error_message**: 错误信息
    
    ### 上架工单设备特有字段（operation_type=racking时，items中每个设备额外返回）
    
    #### 设备基本信息
    - **sn**: 设备序列号
    - **serial_number**: 设备序列号（同sn）
    - **asset_id**: 资产ID
    - **is_company_device**: 是否本公司设备（布尔值）
    
    #### 设备分类信息
    - **category_level1**: 一级分类，如"服务器"
    - **category_level2**: 二级分类，如"机架式服务器"
    - **category_level3**: 三级分类，如"2U机架式服务器"
    - **device_category_level1**: 设备一级分类（同category_level1）
    - **device_category_level2**: 设备二级分类（同category_level2）
    - **device_category_level3**: 设备三级分类（同category_level3）
    
    #### 厂商和型号
    - **vendor**: 厂商名称，如"Dell"、"HP"、"华为"
    - **vendor_name**: 厂商名称（同vendor）
    - **vendor_id**: 厂商ID
    - **model**: 设备型号，如"PowerEdge R740"
    - **vendor_standard_model**: 厂商标准机型
    - **order_number**: 入库编号，设备入库时的单号
    
    #### 目标位置信息
    - **target_datacenter**: 目标机房
    - **target_room**: 目标房间，上架的目标房间名称
    - **target_cabinet**: 目标机柜，上架的目标机柜编号
    - **target_rack_position**: 目标机架位，上架的目标U位，如"10-12"
    
    #### 上下联设备信息
    - **connected_devices**: 上下联设备列表（审核人添加）
      - **sn**: 设备序列号
      - **is_company_device**: 是否本公司设备（布尔值）
      - **device_type**: 设备属性（upstream-上联, downstream-下联）
    
    #### 关联工单号（查询该设备在其他工单中的记录）
    - **outbound_order_number**: 出库单号，该设备关联的出入库工单（出库）的工单号，没有则为null
    - **inbound_order_number**: 入库单号，该设备关联的到货工单的工单号，没有则为null
    - **network_racking_order_number**: 网络设备上架单号，该设备关联的其他上架工单的工单号，没有则为null
    - **power_order_number**: 插线通电单号，该设备关联的电源管理工单的工单号，没有则为null
    - **power_connection_order_number**: 插线通电单号（同power_order_number）
    
    ### 电源管理工单特定字段（operation_type=power_management时返回）
    - **power_action**: 电源操作（power_on上电/power_off下电）
    - **power_type**: 电源类型（AC交流电/DC直流电）
    - **power_reason**: 下电原因（仅下电时有值）
    - **cabinet_count**: 涉及的机柜数量
    - **attachments**: 附件列表（图片URL）
    - **room_cabinets_info**: 机房机柜完整信息（包含32个字段）
      - **room_name**: 机房名称
      - **total_cabinets**: 机房内机柜总数
      - **cabinets_in_work_order**: 本工单涉及的机柜数
      - **cabinets_not_in_work_order**: 本工单未涉及的机柜数
      - **cabinets**: 机柜列表（每个机柜包含以下32个字段）
        - **cabinet_number**: 机柜编号，机柜的唯一标识符，如"CAB-001"
        - **cabinet_name**: 机柜名称，机柜的显示名称，如"核心业务机柜A"
        - **datacenter**: 数据中心名称，机柜所在的数据中心，如"DC01"
        - **room**: 房间名称，机柜所在的房间，如"A101"
        - **room_number**: 房间编号，房间的编号标识，如"101"
        - **operator_cabinet_number**: 运营商机柜编号，运营商侧的机柜标识
        - **power_type**: 电源类型，机柜使用的电源类型，如"AC"（交流电）、"DC"（直流电）
        - **pdu_interface_standard**: PDU接口标准，电源分配单元的接口标准，如"C13"、"C19"
        - **cabinet_type**: 机柜类型，机柜的分类，如"标准机柜"、"网络机柜"
        - **cabinet_type_detail**: 机柜类型详情，机柜类型的详细说明，如"42U标准机柜"
        - **width**: 机柜宽度，机柜的宽度尺寸，如"600mm"
        - **size**: 机柜尺寸，机柜的高度规格，如"42U"、"47U"
        - **power_status**: 电源状态，机柜当前的电源状态，如"on"（已上电）、"off"（已下电）
        - **usage_status**: 使用状态，机柜的使用情况，如"in_use"（使用中）、"idle"（空闲）
        - **lifecycle_status**: 生命周期状态，机柜的生命周期阶段，如"active"（活跃）、"retired"（退役）
        - **module_construction_status**: 模块建设状态，机柜的建设完成情况，如"completed"（已完成）、"in_progress"（建设中）
        - **planning_category**: 规划类别，机柜的规划用途分类，如"生产"、"测试"、"开发"
        - **construction_density**: 建设密度，机柜的建设密度等级，如"高密度"、"中密度"、"低密度"
        - **last_power_operation**: 最后一次电源操作，最近一次执行的电源操作类型，如"power_on"、"power_off"
        - **last_power_operation_date**: 最后操作日期，最近一次电源操作的执行时间，ISO格式
        - **last_operation_result**: 最后操作结果，最近一次操作的执行结果，如"success"（成功）、"failed"（失败）
        - **last_operation_failure_reason**: 最后操作失败原因，如果操作失败，记录失败的具体原因
        - **total_devices**: 机柜内设备总数，该机柜中安装的所有设备数量
        - **devices_in_work_order**: 本工单涉及的设备数，本次工单中该机柜涉及的设备数量
        - **devices_not_in_work_order**: 不在本工单中的设备数，该机柜中不在本次工单范围内的设备数量
        - **is_in_work_order**: 是否在本工单中，布尔值，表示该机柜是否在本次工单的操作范围内
        - **work_order_devices**: 本工单涉及的设备列表，数组，包含该机柜中本次工单涉及的所有设备信息
          - **serial_number**: 设备序列号
          - **asset_tag**: 资产标签
          - **name**: 设备名称
          - **status**: 设备在工单中的状态
        - **total_u_count**: 总U位数，机柜的总U位容量，如42U机柜为42
        - **used_u_count**: 已使用U位数，机柜中已被设备占用的U位数量
        - **available_u_count**: 可用U位数，机柜中剩余可用的U位数量（total_u_count - used_u_count）
        - **responsible_person**: 负责人，该机柜的责任人或管理员
        - **notes**: 备注，关于该机柜的其他备注信息
    
    ### 资产出入门工单特定字段（operation_type=asset_accounting时返回）
    - **business_type**: 业务类型，可选值 fault_support(故障支持)、change_support(变更支持)、other(其他)
    - **service_content**: 服务内容，描述本次出入门的服务内容
    - **entry_exit_type**: 出入类型，move_in(搬入) 或 move_out(搬出)
    - **entry_exit_scope**: 出入范围，datacenter(出入机房)、campus(出入园区)、internal(机房园区内出入)
    - **entry_exit_reason**: 出入原因，说明设备出入的具体原因
    - **entry_exit_date**: 出入日期，格式 YYYY-MM-DD
    - **device_sns**: 设备SN列表，本次出入门涉及的所有设备序列号
    - **creator_name**: 创建人姓名，工单创建人的姓名
    - **campus_auth_order_number**: 园区授权单号，如需园区授权时的关联单号
    - **campus_auth_status**: 园区授权状态，园区授权的当前状态
    - **device_type**: 设备类型，出入门设备的类型分类
    
    ### 设备增配工单特定字段（operation_type=configuration时返回）
    - **parent_device_sn**: 父设备SN，要增配的目标设备序列号
    - **vendor_onsite**: 厂商是否上门，布尔值
    - **parent_device_can_shutdown**: 父设备能否关机，布尔值
    - **allowed_operation_start_time**: 允许操作开始时间，ISO 8601格式
    - **allowed_operation_end_time**: 允许操作结束时间，ISO 8601格式
    - **is_optical_module_upgrade**: 是否光模块增配，布尔值
    - **is_project_upgrade**: 是否项目增配，布尔值
    - **component_quantity**: 配件总数量
    - **sn_components_count**: 有SN配件数量
    - **no_sn_components_count**: 无SN配件数量
    - **sn_components**: 有SN配件列表，包含有序列号的配件信息
      - **id**: 明细ID
      - **sn**: 配件序列号
      - **asset_identifier**: 资产标识
      - **asset_tag**: 资产标签
      - **asset_name**: 资产名称
      - **quantity**: 配件数量
      - **device_category_level1**: 设备一级分类，如"配件"
      - **device_category_level2**: 设备二级分类，如"内存"
      - **device_category_level3**: 设备三级分类，如"DDR4内存"
      - **configuration_datacenter**: 增配机房
      - **configuration_room**: 增配房间
      - **component_model**: 配件型号，如"DDR4-3200-32GB"
      - **mpn**: 配件MPN编号
      - **slot**: 增配槽位，如"DIMM-A1"
      - **port**: 增配端口
      - **status**: 处理状态（pending/completed/failed）
      - **result**: 处理结果
      - **error_message**: 错误信息
    - **no_sn_components**: 无SN配件列表，包含无序列号的配件信息
      - **id**: 明细ID
      - **title**: 配件名称，如"散热风扇"、"RAID控制器电池"
      - **quantity**: 配件数量
      - **device_category_level1**: 设备一级分类，如"配件"
      - **device_category_level2**: 设备二级分类，如"散热设备"
      - **device_category_level3**: 设备三级分类，如"风扇"
      - **configuration_datacenter**: 增配机房
      - **configuration_room**: 增配房间
      - **component_model**: 配件型号，如"FAN-120MM"
      - **mpn**: 配件MPN编号
      - **slot**: 增配槽位，如"FAN-1"
      - **port**: 增配端口
      - **parent_device_sn**: 父设备SN
      - **status**: 处理状态（pending/completed/failed）
      - **result**: 处理结果
      - **error_message**: 错误信息
    
    ## 使用场景
    1. 查看某个工单包含哪些设备
    2. 检查工单中各设备的处理状态
    3. 追踪工单执行进度
    4. 排查工单执行失败的设备
    5. 电源管理工单审核时查看机柜详情
    6. 资产出入门工单查看设备搬入搬出详情
    7. 设备增配工单查看有SN配件和无SN配件列表
    
    ## 注意事项
    1. 如果工单不存在，返回404错误
    2. operation_summary是根据operation_type和operation_data自动生成的可读描述
    3. 设备列表按工单明细创建顺序排列
    4. 电源管理工单会额外返回room_cabinets_info字段，包含完整的32个机柜字段
    5. 资产出入门工单会额外返回entry_exit_type、entry_exit_scope等专用字段
    6. 设备增配工单会额外返回sn_components和no_sn_components字段，分别包含有SN和无SN的配件列表
    """
    
    # 1. 查询工单
    work_order = db.query(WorkOrder).filter(
        WorkOrder.work_order_number == work_order_number
    ).first()
    
    if not work_order:
        raise HTTPException(404, f"工单不存在: {work_order_number}")
    
    # 2. 查询工单明细
    items = db.query(WorkOrderItem).filter(
        WorkOrderItem.work_order_id == work_order.id
    ).all()


    if work_order.operation_type in [
                "generic_operation",
                "generic_non_operation",
                "generic_asset",
                "generic_request"  # 兼容旧数据
            ]:
        
        return {
        "code": 0,
        "message": "查询成功",
        "data": GenericWorkOrderService.get_generic_work_order_detail(work_order, items,db)
    }
    
    # 3. 构建基础响应数据（与batch_id接口保持一致）
    extra_data = work_order.extra or {}
    
    # 构建items_data（包含设备位置和端口信息）
    items_data = []
    for item in items:
        asset = item.asset
        if asset:
            # 获取房间信息
            room_info = None
            datacenter = None
            room_name = None
            if asset.room:
                room_info = asset.room
                datacenter = room_info.datacenter_abbreviation
                room_name = room_info.room_abbreviation
            
            # 解析机柜和机位信息（从location_detail中提取）
            cabinet = None
            rack_position = None
            if asset.location_detail:
                import re
                # 尝试匹配机柜信息，支持多种格式：
                # 1. "A-01机柜" 或 "机柜A-01"
                # 2. "TEST-CAB-001" (纯英文数字格式，空格或U位前的部分)
                cabinet_match = re.search(r'([A-Z0-9\-]+)(?:机柜|柜)', asset.location_detail)
                if cabinet_match:
                    cabinet = cabinet_match.group(1)
                else:
                    # 尝试匹配空格分隔的第一部分作为机柜号
                    parts = asset.location_detail.split()
                    if parts and re.match(r'^[A-Z0-9\-]+$', parts[0], re.IGNORECASE):
                        cabinet = parts[0]
                
                # 尝试匹配U位信息，如 "1-2U" 或 "U1-U2" 或 "U10-U11"
                u_match = re.search(r'(\d+)[-~](\d+)\s*[Uu]|[Uu](\d+)[-~][Uu]?(\d+)', asset.location_detail)
                if u_match:
                    if u_match.group(1) and u_match.group(2):
                        rack_position = f"{u_match.group(1)}-{u_match.group(2)}U"
                    elif u_match.group(3) and u_match.group(4):
                        rack_position = f"{u_match.group(3)}-{u_match.group(4)}U"
            
            # 获取端口信息（从NetworkConnection表查询）
            port_info = []
            connections = db.query(NetworkConnection).filter(
                NetworkConnection.source_asset_id == asset.id
            ).all()
            for conn in connections:
                port_info.append({
                    "source_port": conn.source_port,
                    "target_port": conn.target_port,
                    "target_asset_sn": conn.target_asset.serial_number if conn.target_asset else None,
                    "connection_type": conn.connection_type,
                    "cable_type": conn.cable_type
                })
            
            item_data = {
                "id": item.id,
                "asset_identifier": asset.serial_number,
                "asset_tag": asset.asset_tag,
                "asset_name": asset.name,
                # 位置信息
                "datacenter": datacenter,
                "room": room_name,
                "cabinet": cabinet,
                "rack_position": rack_position,
                "location_detail": asset.location_detail,
                # 端口信息
                "port_info": port_info if port_info else None,
                # 状态和操作信息
                "status": item.status,
                "operation_data": item.operation_data,
                "operation_summary": get_operation_summary(work_order.operation_type, item.operation_data),
                "result": item.result,
                "error_message": item.error_message
            }
            
            # 上架工单(racking)：添加设备详细信息
            if work_order.operation_type == "racking":
                op_data = item.operation_data or {}
                
                # 设备基本信息
                item_data["sn"] = asset.serial_number
                item_data["serial_number"] = asset.serial_number
                item_data["asset_id"] = asset.id
                item_data["is_company_device"] = asset.is_company_device
                
                # 三级分类
                item_data["device_category_level1"] = asset.category_item.item_label if asset.category_item else None
                item_data["device_category_level2"] = asset.secondary_category_item.item_label if asset.secondary_category_item else None
                item_data["device_category_level3"] = asset.tertiary_category_item.item_label if asset.tertiary_category_item else None
                item_data["category_level1"] = item_data["device_category_level1"]
                item_data["category_level2"] = item_data["device_category_level2"]
                item_data["category_level3"] = item_data["device_category_level3"]
                
                # 厂商
                item_data["vendor"] = asset.vendor.name if asset.vendor else None
                item_data["vendor_name"] = item_data["vendor"]
                item_data["vendor_id"] = asset.vendor_id
                
                # 型号
                item_data["model"] = asset.model
                item_data["vendor_standard_model"] = asset.vendor_standard_model
                
                # 入库编号
                item_data["order_number"] = asset.order_number
                
                # 目标机房、目标机柜、目标机架位（从operation_data中获取）
                item_data["target_datacenter"] = op_data.get("datacenter") or item.item_datacenter or work_order.datacenter
                item_data["target_room"] = op_data.get("room") or op_data.get("room_name") or op_data.get("target_room_name") or item.item_room or work_order.room
                item_data["target_cabinet"] = op_data.get("cabinet_number") or op_data.get("cabinet") or op_data.get("target_cabinet") or item.item_cabinet or work_order.cabinet
                item_data["target_rack_position"] = op_data.get("u_position") or op_data.get("rack_position") or op_data.get("target_rack_position") or item.item_rack_position or work_order.rack_position
                
                # 上下联设备信息
                item_data["connected_devices"] = op_data.get("connected_devices", [])
                
                # 查询该设备关联的其他工单号
                # 出库单号（出入库工单-出库）
                outbound_order = db.query(WorkOrder).join(WorkOrderItem).filter(
                    WorkOrderItem.asset_id == asset.id,
                    WorkOrder.operation_type.in_(["asset_accounting", "outbound"]),
                    WorkOrder.id != work_order.id
                ).order_by(WorkOrder.created_at.desc()).first()
                item_data["outbound_order_number"] = outbound_order.work_order_number if outbound_order else None
                
                # 入库单号（到货工单）
                inbound_order = db.query(WorkOrder).join(WorkOrderItem).filter(
                    WorkOrderItem.asset_id == asset.id,
                    WorkOrder.operation_type == "receiving",
                    WorkOrder.id != work_order.id
                ).order_by(WorkOrder.created_at.desc()).first()
                item_data["inbound_order_number"] = inbound_order.work_order_number if inbound_order else None
                
                # 网络设备上架单号（其他上架工单）
                network_racking_order = db.query(WorkOrder).join(WorkOrderItem).filter(
                    WorkOrderItem.asset_id == asset.id,
                    WorkOrder.operation_type == "racking",
                    WorkOrder.id != work_order.id
                ).order_by(WorkOrder.created_at.desc()).first()
                item_data["network_racking_order_number"] = network_racking_order.work_order_number if network_racking_order else None
                
                # 插线通电单号（电源管理工单）
                power_order = db.query(WorkOrder).join(WorkOrderItem).filter(
                    WorkOrderItem.asset_id == asset.id,
                    WorkOrder.operation_type == "power_management",
                    WorkOrder.id != work_order.id
                ).order_by(WorkOrder.created_at.desc()).first()
                item_data["power_order_number"] = power_order.work_order_number if power_order else None
                item_data["power_connection_order_number"] = item_data["power_order_number"]
            
            items_data.append(item_data)
    
    response_data = {
        # 核心标识
        "batch_id": work_order.batch_id,
        "work_order_number": work_order_number,
        "arrival_order_number": work_order.arrival_order_number,
        "source_order_number": work_order.source_order_number,
        
        # 业务信息
        "operation_type": work_order.operation_type,
        "title": work_order.title,
        "description": work_order.description,
        
        # 状态管理
        "status": work_order.status,
        "work_order_status": work_order.work_order_status,
        "is_timeout": work_order.is_timeout,
        "sla_countdown": work_order.sla_countdown,
        
        # 人员信息
        "creator": work_order.creator,
        "operator": work_order.operator,
        "assignee": work_order.assignee,
        "reviewer": work_order.reviewer,
        
        # 位置信息
        "datacenter": work_order.datacenter,
        "campus": work_order.campus,
        "room": work_order.room,
        "cabinet": work_order.cabinet,
        "rack_position": work_order.rack_position,
        
        # 项目信息
        "project_number": work_order.project_number,
        
        # 时间信息
        "start_time": work_order.start_time.isoformat() if work_order.start_time else None,
        "expected_completion_time": work_order.expected_completion_time.isoformat() if work_order.expected_completion_time else None,
        "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
        "close_time": work_order.close_time.isoformat() if work_order.close_time else None,
        "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
        "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None,
        
        # 统计信息
        "device_count": work_order.device_count or 0,
        "items_count": len(items_data),
        
        # 备注信息
        "remark": work_order.remark,
        
        # 扩展信息（从extra中提取常用字段）
        "priority": extra_data.get("priority"),
        "operation_type_detail": extra_data.get("operation_type_detail"),
        "is_business_online": extra_data.get("is_business_online"),
        "failure_reason": extra_data.get("failure_reason"),
        "attachments": extra_data.get("attachments"),
        
        # 设备明细
        "items": items_data
    }
    
    # 4. 如果是电源管理工单，添加电源管理特定字段
    if work_order.operation_type == "power_management":
        power_action = extra_data.get("power_action") or extra_data.get("operation_data", {}).get("power_action")
        power_type = extra_data.get("power_type") or extra_data.get("operation_data", {}).get("power_type")
        power_reason = extra_data.get("power_reason") or extra_data.get("operation_data", {}).get("reason")
        
        response_data.update({
            "power_action": power_action,
            "power_type": power_type,
            "power_reason": power_reason,
            "cabinet_count": work_order.cabinet_count or 0,
        })
        
        # 添加完整的机柜详细信息（包含32个字段）
        if work_order.room:
            try:
                import re
                
                work_order_cabinets = set()
                work_order_devices_by_cabinet = {}
                
                for item in items:
                    if item.asset:
                        cabinet = None
                        if item.asset.location_detail:
                            match = re.search(r'([A-Z0-9\-]+)(?:机柜|柜)', item.asset.location_detail)
                            if match:
                                cabinet = match.group(1)
                        
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
                
                room_obj = db.query(Room).filter(Room.room_abbreviation == work_order.room).first()
                all_cabinets_in_room = {}
                
                if room_obj:
                    assets_in_room = db.query(Asset).filter(Asset.room_id == room_obj.id).all()
                    
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
                
                cabinets_in_db = db.query(Cabinet).filter(Cabinet.room == work_order.room).all()
                cabinets_dict = {cab.cabinet_number: cab for cab in cabinets_in_db}
                
                cabinets_list = []
                for cabinet_name, stats in all_cabinets_in_room.items():
                    cabinet_info = cabinets_dict.get(cabinet_name)
                    
                    cabinet_data = {
                        'cabinet_number': cabinet_name,
                        'cabinet_name': cabinet_info.cabinet_name if cabinet_info else None,
                        'datacenter': cabinet_info.datacenter if cabinet_info else None,
                        'room': work_order.room,
                        'power_status': cabinet_info.power_status if cabinet_info else None,
                        'total_devices': stats['total_devices'],
                        'devices_in_work_order': stats['in_work_order'],
                        'devices_not_in_work_order': stats['not_in_work_order'],
                        'is_in_work_order': cabinet_name in work_order_cabinets,
                        'work_order_devices': work_order_devices_by_cabinet.get(cabinet_name, []),
                    }
                    
                    if cabinet_info:
                        cabinet_data.update({
                            'room_number': cabinet_info.room_number,
                            'operator_cabinet_number': cabinet_info.operator_cabinet_number,
                            'power_type': cabinet_info.power_type,
                            'pdu_interface_standard': cabinet_info.pdu_interface_standard,
                            'cabinet_type': cabinet_info.cabinet_type,
                            'cabinet_type_detail': cabinet_info.cabinet_type_detail,
                            'width': cabinet_info.width,
                            'size': cabinet_info.size,
                            'usage_status': cabinet_info.usage_status,
                            'lifecycle_status': cabinet_info.lifecycle_status,
                            'module_construction_status': cabinet_info.module_construction_status,
                            'planning_category': cabinet_info.planning_category,
                            'construction_density': cabinet_info.construction_density,
                            'last_power_operation': cabinet_info.last_power_operation,
                            'last_power_operation_date': cabinet_info.last_power_operation_date.isoformat() if cabinet_info.last_power_operation_date else None,
                            'last_operation_result': cabinet_info.last_operation_result,
                            'last_operation_failure_reason': cabinet_info.last_operation_failure_reason,
                            'total_u_count': cabinet_info.total_u_count,
                            'used_u_count': cabinet_info.used_u_count,
                            'available_u_count': cabinet_info.available_u_count,
                            'responsible_person': cabinet_info.responsible_person,
                            'notes': cabinet_info.notes,
                        })
                    
                    cabinets_list.append(cabinet_data)
                
                cabinets_list.sort(key=lambda x: x['cabinet_number'])
                
                response_data["room_cabinets_info"] = {
                    'room_name': work_order.room,
                    'total_cabinets': len(all_cabinets_in_room),
                    'cabinets_in_work_order': len(work_order_cabinets),
                    'cabinets_not_in_work_order': len(all_cabinets_in_room) - len(work_order_cabinets),
                    'cabinets': cabinets_list
                }
            except Exception as e:
                logger.error(f"获取机柜详细信息失败: {str(e)}")
                response_data["room_cabinets_info"] = None
    
    # 5. 如果是资产出入门工单，添加特定字段
    if work_order.operation_type == "asset_accounting":
        response_data.update({
            "business_type": extra_data.get("business_type"),
            "service_content": extra_data.get("service_content"),
            "entry_exit_type": extra_data.get("entry_exit_type"),
            "entry_exit_scope": extra_data.get("entry_exit_scope"),
            "entry_exit_reason": extra_data.get("entry_exit_reason"),
            "entry_exit_date": extra_data.get("entry_exit_date"),
            "device_sns": extra_data.get("device_sns", []),
            "creator_name": extra_data.get("creator_name"),
            "campus_auth_order_number": extra_data.get("campus_auth_order_number"),
            "campus_auth_status": extra_data.get("campus_auth_status"),
            "device_type": extra_data.get("device_type"),
        })
    
    # 6. 如果是设备增配工单，添加sn配件列表和无sn配件列表
    if work_order.operation_type == "configuration":
        # 添加增配工单特定字段
        response_data.update({
            "parent_device_sn": work_order.parent_device_sn,
            "vendor_onsite": work_order.vendor_onsite,
            "parent_device_can_shutdown": work_order.parent_device_can_shutdown,
            "allowed_operation_start_time": work_order.allowed_operation_start_time.isoformat() if work_order.allowed_operation_start_time else None,
            "allowed_operation_end_time": work_order.allowed_operation_end_time.isoformat() if work_order.allowed_operation_end_time else None,
            "is_optical_module_upgrade": work_order.is_optical_module_upgrade,
            "is_project_upgrade": work_order.is_project_upgrade,
            "component_quantity": work_order.component_quantity,
        })
        
        # 从工单明细中提取sn配件列表和无sn配件列表
        sn_components = []
        no_sn_components = []
        
        for item in items:
            op_data = item.operation_data or {}
            asset = item.asset  # 获取关联的资产对象
            
            # 判断是有SN配件还是无SN配件
            if 'sn' in op_data and op_data.get('sn'):
                # 有SN的配件 - 从资产表获取详细信息
                component_data = {
                    "id": item.id,
                    "sn": op_data.get('sn'),
                    "asset_identifier": item.asset_sn or op_data.get('serial_number'),
                    "asset_tag": item.asset_tag or op_data.get('asset_tag'),
                    "asset_name": op_data.get('asset_name'),
                    # 数量
                    "quantity": op_data.get('quantity', 1),
                    # 设备三级分类
                    "device_category_level1": None,
                    "device_category_level2": None,
                    "device_category_level3": None,
                    # 增配机房和房间
                    "configuration_datacenter": op_data.get('configuration_datacenter') or work_order.datacenter,
                    "configuration_room": op_data.get('configuration_room') or work_order.room,
                    # 配件型号和MPN
                    "component_model": op_data.get('component_model'),
                    "mpn": op_data.get('mpn'),
                    # 增配槽位和端口
                    "slot": op_data.get('slot', ''),
                    "port": op_data.get('port', ''),
                    # 状态信息
                    "status": item.status,
                    "result": item.result,
                    "error_message": item.error_message
                }
                
                # 从资产表获取更多信息
                if asset:
                    component_data["device_category_level1"] = asset.category_item.item_label if asset.category_item else None
                    component_data["device_category_level2"] = asset.secondary_category_item.item_label if asset.secondary_category_item else None
                    component_data["device_category_level3"] = asset.tertiary_category_item.item_label if asset.tertiary_category_item else None
                    # 如果operation_data中没有型号，从资产表获取
                    if not component_data["component_model"]:
                        component_data["component_model"] = asset.model
                
                sn_components.append(component_data)
            else:
                # 无SN的配件
                no_sn_components.append({
                    "id": item.id,
                    "title": op_data.get('title', ''),
                    # 数量
                    "quantity": op_data.get('quantity', 1),
                    # 设备三级分类（无SN配件通常没有分类信息，从operation_data获取）
                    "device_category_level1": op_data.get('device_category_level1'),
                    "device_category_level2": op_data.get('device_category_level2'),
                    "device_category_level3": op_data.get('device_category_level3'),
                    # 增配机房和房间
                    "configuration_datacenter": op_data.get('configuration_datacenter') or work_order.datacenter,
                    "configuration_room": op_data.get('configuration_room') or work_order.room,
                    # 配件型号和MPN
                    "component_model": op_data.get('component_model'),
                    "mpn": op_data.get('mpn'),
                    # 增配槽位和端口
                    "slot": op_data.get('slot', ''),
                    "port": op_data.get('port', ''),
                    # 父设备SN
                    "parent_device_sn": work_order.parent_device_sn,
                    # 状态信息
                    "status": item.status,
                    "result": item.result,
                    "error_message": item.error_message
                })
        
        response_data.update({
            "sn_components": sn_components,
            "no_sn_components": no_sn_components,
            "sn_components_count": len(sn_components),
            "no_sn_components_count": len(no_sn_components),
        })
    
    return {
        "code": 0,
        "message": "查询成功",
        "data": response_data
    }




@router.put("/{batch_id}/complete", summary="完成工单（通用）",
           response_model=ApiResponse,
           responses={
               200: {
                   "description": "工单完成成功",
                   "content": {
                       "application/json": {
                           "example": {
                               "code": 0,
                               "message": "工单完成成功",
                               "data": {
                                   "batch_id": "RACK_20251205120000",
                                   "operation_type": "racking",
                                   "status": "completed",
                                   "updated_count": 2,
                                   "failed_count": 0,
                                   "failed_items": [],
                                   "completed_time": "2025-12-05T14:00:00"
                               }
                           }
                       }
                   }
               },
               400: {
                   "description": "参数错误或工单已完成",
                   "content": {
                       "application/json": {
                           "example": {
                               "code": 400,
                               "message": "工单已完成，不能重复操作",
                               "data": None
                           }
                       }
                   }
               },
               404: {
                   "description": "工单不存在",
                   "content": {
                       "application/json": {
                           "example": {
                               "code": 404,
                               "message": "工单不存在: RACK_20251205120000",
                               "data": None
                           }
                       }
                   }
               },
               500: {"description": "服务器内部错误"}
           })
async def complete_work_order(
    batch_id: str = Path(..., description="批次ID", example="RACK_20251205120000"),
    operator: str = Form(..., description="操作人", example="张三"),
    comments: str = Form(None, description="备注", example="所有设备已完成上架"),
    db: Session = Depends(get_db)
):
    """
    完成工单（通用接口）
    
    ## 功能说明
    标记工单为完成状态，并根据工单类型自动执行相应的业务逻辑。
    
    ## 路径参数
    - **batch_id**: 批次ID（必填）
    
    ## 表单参数
    - **operator**: 操作人（必填）
    - **comments**: 备注（可选）
    
    ## 不同工单类型的业务逻辑
    
    ### receiving（设备到货）
    - 更新设备的room_id（房间）
    - 更新设备的lifecycle_status（生命周期状态）
    - 标记设备为已到货
    
    ### racking（设备上架）
    - 更新设备的位置信息（机柜、U位等）
    - 更新设备的room_id
    - 更新设备的lifecycle_status为"已上架"
    
    ### power_management（电源管理）
    - 更新设备的电源状态
    - 记录上电/下电时间
    - 更新设备的运行状态
    
    ### configuration（设备增配）
    - 创建或更新设备配置记录
    - 关联配件到父设备
    - 更新设备配置信息
    
    ### 其他类型
    - 标记工单明细为完成状态
    - 更新工单完成时间
    
    ## 返回字段说明
    - **batch_id**: 批次ID
    - **operation_type**: 操作类型
    - **status**: 工单状态（completed）
    - **updated_count**: 成功更新的设备数量
    - **failed_count**: 更新失败的设备数量
    - **failed_items**: 失败的设备列表（包含失败原因）
    - **completed_time**: 完成时间
    
    ## 使用场景
    1. 工单执行完毕后标记为完成
    2. 批量更新设备状态
    3. 触发后续业务流程
    
    ## 注意事项
    1. 工单必须处于pending或processing状态才能完成
    2. 已完成的工单不能重复完成
    3. 完成操作会自动更新相关设备的状态
    4. 如果部分设备更新失败，工单仍会标记为完成，但会返回失败列表
    5. 完成时间会自动记录为当前时间
    """
    
    # 1. 获取工单
    work_order = db.query(WorkOrder).filter(
        WorkOrder.batch_id == batch_id
    ).first()
    
    if not work_order:
        raise HTTPException(404, f"工单不存在: {batch_id}")
    
    if work_order.status == "completed":
        raise HTTPException(400, "工单已完成，不能重复操作")
    
    # 2. 获取所有WorkOrderItem
    items = db.query(WorkOrderItem).filter(
        WorkOrderItem.work_order_id == work_order.id
    ).all()
    
    # 机房级别的电源管理工单可以没有明细
    is_room_level_power = (
        work_order.operation_type == 'power_management' and 
        not items
    )
    
    if not items and not is_room_level_power:
        raise HTTPException(400, "工单没有明细")
    
    # 3. 记录"执行"状态日志（在实际执行操作之前）
    from app.constants.operation_types import OperationType, OperationResult
    
    if work_order.operation_type == 'power_management':
        extra_data = work_order.extra or {}
        power_action_desc = "上电" if extra_data.get("power_action") == "power_on" else "下电"
        logger.info(f"Work order executing", extra={
            "operationObject": batch_id,
            "operationType": OperationType.POWER_MANAGEMENT_EXECUTE,  # 执行
            "operator": operator,
            "result": OperationResult.SUCCESS,
            "operationDetail": f"开始执行电源管理工单（{power_action_desc}），房间: {work_order.room}",
            "remark": None
        })
    else:
        logger.info(f"Work order executing", extra={
            "operationObject": batch_id,
            "operationType": OperationType.WORK_ORDER_EXECUTE,
            "operator": operator,
            "result": OperationResult.SUCCESS,
            "operationDetail": f"开始执行{work_order.operation_type}工单",
            "remark": None
        })
    
    # 4. 根据operation_type执行不同的业务逻辑
    updated_count = 0
    failed_items = []
    
    try:
        if work_order.operation_type == "receiving":
            updated_count, failed_items = await complete_receiving_operation(items, operator, db)
        
        elif work_order.operation_type == "racking":
            updated_count, failed_items = await complete_racking_operation(items, operator, db)
        
        elif work_order.operation_type == "power_management":
            if items:
                updated_count, failed_items = await complete_power_management_operation(items, operator, db)
            else:
                # 机房级别的电源管理工单，没有设备明细，直接标记完成
                updated_count = 0
                failed_items = []
        
        elif work_order.operation_type == "configuration":
            updated_count, failed_items = await complete_configuration_operation(items, operator, db)
        
        else:
            # 其他类型的默认处理
            updated_count, failed_items = await complete_default_operation(items, operator, db)
        
        # 5. 更新工单状态
        work_order.status = "completed"
        work_order.completed_time = datetime.now()
        work_order.operator = operator
        if comments:
            work_order.remark = comments
        
        db.commit()
        
        # 6. 记录工单完成日志到ES（结单）
        # 电源管理工单使用专用的操作类型
        if work_order.operation_type == 'power_management':
            log_operation_type = OperationType.POWER_MANAGEMENT_COMPLETE  # 结单
            extra_data = work_order.extra or {}
            power_action_desc = "上电" if extra_data.get("power_action") == "power_on" else "下电"
            log_detail = f"电源管理工单结单（{power_action_desc}），房间: {work_order.room}"
        else:
            log_operation_type = OperationType.WORK_ORDER_COMPLETE
            log_detail = f"{work_order.operation_type}工单完成，成功{updated_count}项，失败{len(failed_items)}项"
        
        logger.info(f"Work order completed", extra={
            "operationObject": batch_id,
            "operationType": log_operation_type,
            "operator": operator,
            "result": OperationResult.SUCCESS,
            "operationDetail": log_detail,
            "remark": comments
        })
        
        return {
            "code": 0,
            "message": f"{work_order.operation_type}工单完成",
            "data": {
                "batch_id": batch_id,
                "operation_type": work_order.operation_type,
                "updated_count": updated_count,
                "failed_count": len(failed_items),
                "failed_items": failed_items if failed_items else None
            }
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Complete work order failed: {str(e)}")
        raise HTTPException(500, f"完成工单失败: {str(e)}")


async def complete_receiving_operation(items: List[WorkOrderItem], operator: str, db: Session):
    """完成设备到货操作"""
    updated_count = 0
    failed_items = []
    
    for item in items:
        try:
            asset = db.query(Asset).get(item.asset_id)
            if not asset:
                failed_items.append({
                    "serial_number": item.operation_data.get('serial_number'),
                    "reason": "资产不存在"
                })
                continue
            
            target_room_id = item.operation_data.get('target_room_id')
            old_room_id = asset.room_id
            
            # 更新位置和状态
            asset.room_id = target_room_id
            asset.lifecycle_status = "received"
            
            # 更新WorkOrderItem状态
            item.status = "completed"
            item.result = "success"
            
            updated_count += 1
            
            # 记录ES日志
            logger.info("Device received", extra={
                "operationObject": asset.serial_number,
                "operationType": "device.inbound",
                "operator": operator,
                "result": "success",
                "operationDetail": f"从房间{old_room_id}到货至房间{target_room_id}"
            })
            
        except Exception as e:
            failed_items.append({
                "serial_number": item.operation_data.get('serial_number'),
                "reason": str(e)
            })
    
    return updated_count, failed_items


async def complete_racking_operation(items: List[WorkOrderItem], operator: str, db: Session):
    """完成设备上架操作"""
    updated_count = 0
    failed_items = []
    
    for item in items:
        try:
            asset = db.query(Asset).get(item.asset_id)
            if not asset:
                failed_items.append({
                    "serial_number": item.operation_data.get('serial_number'),
                    "reason": "资产不存在"
                })
                continue
            
            # 更新位置信息
            cabinet = item.operation_data.get('cabinet_number')
            u_start = item.operation_data.get('u_position_start')
            u_end = item.operation_data.get('u_position_end')
            
            # 构建位置详情
            if u_start == u_end:
                location_detail = f"{cabinet} U{u_start}"
            else:
                location_detail = f"{cabinet} U{u_start}-U{u_end}"
            
            # 更新资产信息
            old_location = asset.location_detail
            asset.location_detail = location_detail
            asset.lifecycle_status = "racked"
            
            # 如果有机房信息，也更新机房
            if 'datacenter' in item.operation_data:
                # 这里可以根据机房名称查找并更新room_id
                pass
            
            # 更新WorkOrderItem状态
            item.status = "completed"
            item.result = "success"
            
            updated_count += 1
            
            # 记录变更日志到数据库
            from app.models.asset_models import AssetChangeLog
            change_log = AssetChangeLog(
                asset_id=asset.id,
                change_type="location_update",
                old_value=old_location or "",
                new_value=location_detail,
                operator=operator,
                change_reason="设备上架完成"
            )
            db.add(change_log)
            
            # 记录ES日志
            logger.info("Device racked", extra={
                "operationObject": asset.serial_number,
                "operationType": "device.rack_on",
                "operator": operator,
                "result": "success",
                "operationDetail": f"从 {old_location or '未知位置'} 上架至 {location_detail}"
            })
            
        except Exception as e:
            failed_items.append({
                "serial_number": item.operation_data.get('serial_number'),
                "reason": str(e)
            })
    
    return updated_count, failed_items


async def complete_power_management_operation(items: List[WorkOrderItem], operator: str, db: Session):
    """完成电源管理操作（上电/下电）"""
    updated_count = 0
    failed_items = []
    
    for item in items:
        try:
            asset = db.query(Asset).get(item.asset_id)
            if not asset:
                failed_items.append({
                    "serial_number": item.operation_data.get('serial_number'),
                    "reason": "资产不存在"
                })
                item.status = "failed"
                item.error_message = "资产不存在"
                continue
            
            # 获取电源动作类型
            power_action = item.operation_data.get('power_action')
            if not power_action:
                failed_items.append({
                    "serial_number": asset.serial_number,
                    "reason": "未指定power_action"
                })
                item.status = "failed"
                item.error_message = "未指定power_action"
                continue
            
            # 根据动作类型更新状态
            if power_action == 'power_on':
                # 上电操作
                asset.lifecycle_status = "powered_on"
                operation_type = "device.power_on"
                operation_detail = f"上电成功，电源类型: {item.operation_data.get('power_type', 'AC')}"
            elif power_action == 'power_off':
                # 下电操作
                asset.lifecycle_status = "powered_off"
                operation_type = "device.power_off"
                reason = item.operation_data.get('reason', '未知原因')
                operation_detail = f"下电成功，原因: {reason}"
            else:
                failed_items.append({
                    "serial_number": asset.serial_number,
                    "reason": f"无效的power_action: {power_action}"
                })
                item.status = "failed"
                item.error_message = f"无效的power_action: {power_action}"
                continue
            
            # 更新WorkOrderItem状态
            item.status = "completed"
            item.result = "success"
            item.executed_at = datetime.now()
            item.executed_by = operator
            
            updated_count += 1
            
            # 记录ES日志
            logger.info(f"Device {power_action}", extra={
                "operationObject": asset.serial_number,
                "operationType": operation_type,
                "operator": operator,
                "result": "success",
                "operationDetail": operation_detail
            })
            
        except Exception as e:
            failed_items.append({
                "serial_number": item.operation_data.get('serial_number'),
                "reason": str(e)
            })
            item.status = "failed"
            item.error_message = str(e)
    
    return updated_count, failed_items


async def complete_configuration_operation(items: List[WorkOrderItem], operator: str, db: Session):
    """完成设备增配操作：建立父设备与配件的拓扑关系"""
    updated_count = 0
    failed_items = []
    
    # 获取父设备（从第一个item的work_order中获取）
    if not items:
        return 0, []
    
    work_order = items[0].work_order
    parent_device_sn = work_order.parent_device_sn
    
    # 查找父设备
    parent_asset = db.query(Asset).filter(Asset.serial_number == parent_device_sn).first()
    if not parent_asset:
        for item in items:
            failed_items.append({
                "serial_number": item.operation_data.get('sn', item.operation_data.get('title')),
                "reason": f"父设备不存在: {parent_device_sn}"
            })
            item.status = "failed"
            item.error_message = f"父设备不存在: {parent_device_sn}"
        return 0, failed_items
    
    for item in items:
        try:
            operation_data = item.operation_data
            
            # 有SN的配件：建立与实际资产的拓扑关系
            if 'sn' in operation_data and operation_data['sn']:
                component_asset = db.query(Asset).filter(
                    Asset.serial_number == operation_data['sn']
                ).first()
                
                if not component_asset:
                    failed_items.append({
                        "serial_number": operation_data['sn'],
                        "reason": "配件资产不存在"
                    })
                    item.status = "failed"
                    item.error_message = "配件资产不存在"
                    continue
                
                # 建立拓扑关系
                configuration = AssetConfiguration(
                    asset_id=parent_asset.id,
                    related_asset_id=component_asset.id,
                    configuration_type="downstream",  # 下联（父→子）
                    connection_type="component",
                    configuration_info={
                        "slot": operation_data.get('slot', ''),
                        "port": operation_data.get('port', ''),
                        "quantity": operation_data.get('quantity', 1),
                        "installed_by": operator,
                        "installed_at": datetime.now().isoformat(),
                        "work_order_batch_id": work_order.batch_id
                    },
                    status=1
                )
                db.add(configuration)
                
                # 更新配件状态
                component_asset.lifecycle_status = "installed"
                
                logger.info("Component installed with SN", extra={
                    "operationObject": f"{parent_device_sn} -> {operation_data['sn']}",
                    "operationType": "component.install",
                    "operator": operator,
                    "result": "success",
                    "operationDetail": f"槽位: {operation_data.get('slot')}, 数量: {operation_data.get('quantity')}"
                })
            
            # 无SN的配件：只记录配置信息到父设备的extra字段
            else:
                title = operation_data.get('title', '未命名配件')
                
                # 也可以建立一个虚拟的拓扑关系
                configuration = AssetConfiguration(
                    asset_id=parent_asset.id,
                    related_asset_id=None,  # 无SN配件没有关联资产
                    configuration_type="downstream",
                    connection_type="component_virtual",
                    configuration_info={
                        "title": title,
                        "slot": operation_data.get('slot', ''),
                        "port": operation_data.get('port', ''),
                        "installed_by": operator,
                        "installed_at": datetime.now().isoformat(),
                        "work_order_batch_id": work_order.batch_id
                    },
                    status=1
                )
                db.add(configuration)
                
                logger.info("Component installed without SN", extra={
                    "operationObject": parent_device_sn,
                    "operationType": "component.install",
                    "operator": operator,
                    "result": "success",
                    "operationDetail": f"配件: {title}, 槽位: {operation_data.get('slot')}"
                })
            
            # 更新WorkOrderItem状态
            item.status = "completed"
            item.result = "success"
            updated_count += 1
            
        except Exception as e:
            failed_items.append({
                "serial_number": operation_data.get('sn', operation_data.get('title', '未知')),
                "reason": str(e)
            })
            item.status = "failed"
            item.error_message = str(e)
    
    # 更新父设备状态为已配置
    if updated_count > 0:
        parent_asset.lifecycle_status = "configured"
    
    return updated_count, failed_items


async def complete_default_operation(items: List[WorkOrderItem], operator: str, db: Session):
    """默认完成操作（其他类型）"""
    updated_count = 0
    failed_items = []
    
    for item in items:
        try:
            # 只更新WorkOrderItem状态，不修改Asset
            item.status = "completed"
            item.result = "success"
            updated_count += 1
            
        except Exception as e:
            failed_items.append({
                "serial_number": item.operation_data.get('serial_number'),
                "reason": str(e)
            })
    
    return updated_count, failed_items


def _apply_work_order_filters(query, db: Session, params: Dict[str, Any]):
    force_empty = False

    operation_type = params.get("operation_type")
    status = params.get("status")
    creator = params.get("creator")
    operator = params.get("operator")
    is_timeout = params.get("is_timeout")
    datacenter = params.get("datacenter")
    room = params.get("room")
    device_category_level1 = params.get("device_category_level1")
    device_category_level2 = params.get("device_category_level2")
    device_category_level3 = params.get("device_category_level3")
    work_order_number = params.get("work_order_number")
    work_order_status = params.get("work_order_status")
    arrival_order_number = params.get("arrival_order_number")
    source_order_number = params.get("source_order_number")
    batch_id = params.get("batch_id")
    title = params.get("title")
    serial_number = params.get("serial_number")
    created_at_start = params.get("created_at_start")
    created_at_end = params.get("created_at_end")
    cabinet_number = params.get("cabinet_number")
    u_position = params.get("u_position")
    device_model = params.get("device_model")
    start_time_start = params.get("start_time_start")
    start_time_end = params.get("start_time_end")
    completed_time_start = params.get("completed_time_start")
    completed_time_end = params.get("completed_time_end")
    power_action = params.get("power_action")
    parent_device_sn = params.get("parent_device_sn")
    parent_device_can_shutdown = params.get("parent_device_can_shutdown")
    component_model = params.get("component_model")
    component_mpn = params.get("component_mpn")
    component_quantity = params.get("component_quantity")
    component_sn = params.get("component_sn")
    inbound_order_number = params.get("inbound_order_number")
    outbound_order_number = params.get("outbound_order_number")
    close_time_start = params.get("close_time_start")
    close_time_end = params.get("close_time_end")

    if operation_type:
        query = query.filter(WorkOrder.operation_type == operation_type)
    if status:
        query = query.filter(WorkOrder.status == status)
    if creator:
        # 支持多个创建人查询，逗号分隔
        creators = [c.strip() for c in creator.split(',') if c.strip()]
        if len(creators) == 1:
            query = query.filter(WorkOrder.creator.like(f"%{creators[0]}%"))
        else:
            query = query.filter(WorkOrder.creator.in_(creators))
    if operator:
        query = query.filter(WorkOrder.operator.like(f"%{operator}%"))
    if is_timeout is not None:
        query = query.filter(WorkOrder.is_timeout == is_timeout)

    if datacenter:
        query = query.filter(WorkOrder.datacenter == datacenter)
    if room:
        query = query.filter(WorkOrder.room == room)

    if device_category_level1:
        query = query.filter(WorkOrder.device_category_level1.like(f"%{device_category_level1}%"))
    if device_category_level2:
        query = query.filter(WorkOrder.device_category_level2.like(f"%{device_category_level2}%"))
    if device_category_level3:
        query = query.filter(WorkOrder.device_category_level3.like(f"%{device_category_level3}%"))

    if work_order_number:
        # 支持多个工单号查询，逗号分隔
        work_order_numbers = [num.strip() for num in work_order_number.split(',') if num.strip()]
        if len(work_order_numbers) == 1:
            query = query.filter(WorkOrder.work_order_number == work_order_numbers[0])
        else:
            query = query.filter(WorkOrder.work_order_number.in_(work_order_numbers))
    if work_order_status:
        query = query.filter(WorkOrder.work_order_status == work_order_status)
    if arrival_order_number:
        query = query.filter(WorkOrder.arrival_order_number == arrival_order_number)
    if source_order_number:
        query = query.filter(WorkOrder.source_order_number.like(f"%{source_order_number}%"))
    if batch_id:
        query = query.filter(WorkOrder.batch_id.like(f"%{batch_id}%"))
    if title:
        query = query.filter(WorkOrder.title.like(f"%{title}%"))

    if parent_device_sn:
        query = query.filter(WorkOrder.parent_device_sn.like(f"%{parent_device_sn}%"))
    if parent_device_can_shutdown is not None:
        query = query.filter(WorkOrder.parent_device_can_shutdown == parent_device_can_shutdown)
    if component_model:
        query = query.filter(WorkOrder.component_model.like(f"%{component_model}%"))
    if component_mpn:
        query = query.filter(WorkOrder.component_mpn.like(f"%{component_mpn}%"))
    if component_quantity is not None:
        query = query.filter(WorkOrder.component_quantity == component_quantity)
    if inbound_order_number:
        query = query.filter(WorkOrder.inbound_order_number.like(f"%{inbound_order_number}%"))
    if outbound_order_number:
        query = query.filter(WorkOrder.outbound_order_number.like(f"%{outbound_order_number}%"))

    if created_at_start:
        try:
            start_dt = datetime.fromisoformat(created_at_start.replace('T', ' '))
            query = query.filter(WorkOrder.created_at >= start_dt)
        except ValueError:
            pass
    if created_at_end:
        try:
            end_dt = datetime.fromisoformat(created_at_end.replace('T', ' '))
            query = query.filter(WorkOrder.created_at <= end_dt)
        except ValueError:
            pass

    if start_time_start:
        try:
            start_dt = datetime.fromisoformat(start_time_start.replace('T', ' '))
            query = query.filter(WorkOrder.start_time >= start_dt)
        except ValueError:
            pass
    if start_time_end:
        try:
            end_dt = datetime.fromisoformat(start_time_end.replace('T', ' '))
            query = query.filter(WorkOrder.start_time <= end_dt)
        except ValueError:
            pass

    if completed_time_start:
        try:
            start_dt = datetime.fromisoformat(completed_time_start.replace('T', ' '))
            query = query.filter(WorkOrder.completed_time >= start_dt)
        except ValueError:
            pass
    if completed_time_end:
        try:
            end_dt = datetime.fromisoformat(completed_time_end.replace('T', ' '))
            query = query.filter(WorkOrder.completed_time <= end_dt)
        except ValueError:
            pass

    if close_time_start:
        try:
            start_dt = datetime.fromisoformat(close_time_start.replace('T', ' '))
            query = query.filter(WorkOrder.close_time >= start_dt)
        except ValueError:
            pass
    if close_time_end:
        try:
            end_dt = datetime.fromisoformat(close_time_end.replace('T', ' '))
            query = query.filter(WorkOrder.close_time <= end_dt)
        except ValueError:
            pass

    needs_item_join = cabinet_number or u_position or power_action or serial_number or device_model or component_sn

    if needs_item_join:
        from sqlalchemy import func
        subquery_conditions = []

        if cabinet_number:
            subquery_conditions.append(
                func.json_extract(WorkOrderItem.operation_data, '$.cabinet_number').like(f"%{cabinet_number}%")
            )
        if u_position:
            subquery_conditions.append(
                func.json_extract(WorkOrderItem.operation_data, '$.u_position').like(f"%{u_position}%")
            )
        if power_action:
            subquery_conditions.append(
                func.json_extract(WorkOrderItem.operation_data, '$.power_action') == power_action
            )
        if serial_number:
            # 支持多个序列号查询，逗号分隔
            serial_numbers = [sn.strip() for sn in serial_number.split(',') if sn.strip()]
            if len(serial_numbers) == 1:
                subquery_conditions.append(
                    WorkOrderItem.asset_sn.like(f"%{serial_numbers[0]}%")
                )
            else:
                subquery_conditions.append(
                    WorkOrderItem.asset_sn.in_(serial_numbers)
                )
        if device_model:
            asset_ids = db.query(Asset.id).filter(
                Asset.model.like(f"%{device_model}%")
            ).all()
            matched_asset_ids = [aid[0] for aid in asset_ids]
            if matched_asset_ids:
                subquery_conditions.append(
                    WorkOrderItem.asset_id.in_(matched_asset_ids)
                )
        if component_sn:
            subquery_conditions.append(
                func.json_extract(WorkOrderItem.operation_data, '$.sn').like(f"%{component_sn}%")
            )

        if subquery_conditions:
            from sqlalchemy import or_
            item_query = db.query(WorkOrderItem.work_order_id).filter(
                or_(*subquery_conditions)
            ).distinct()
            matched_work_order_ids = [row[0] for row in item_query.all()]
            if matched_work_order_ids:
                query = query.filter(WorkOrder.id.in_(matched_work_order_ids))
            else:
                force_empty = True

    return query, force_empty


@router.get("/", summary="查询工单列表（通用）",
            response_model=ApiResponse,
            responses={
                200: {
                    "description": "查询成功，返回工单列表及分页信息。\n\n**通用返回字段：**\n- id: 工单ID\n- batch_id: 批次ID\n- work_order_number: 外部工单号\n- work_order_status: 外部工单状态\n- operation_type: 操作类型（receiving/racking/power_management/configuration等）\n- title: 工单标题\n- status: 工单状态（pending/processing/completed/cancelled）\n- business_name: 业务名称\n- is_timeout: 是否超时（超时状态）\n- sla_countdown: SLA倒计时（秒），如果有expected_completion_time则使用该时间计算，否则使用created_at + 72小时\n- actual_duration: 实际用时（秒），completed_time - created_at，未完成时为null\n- priority: 优先级（从extra字段提取，有的工单有，没有则为null）\n- creator: 创建人\n- operator: 操作人\n- assignee: 指派人\n- datacenter: 机房\n- room: 房间\n- serial_numbers: 设备序列号列表（该工单关联的所有设备SN）\n- items_count: 工单项数量\n- device_count: 设备数量\n- created_at: 创建时间\n- expected_completion_time: 期望完成时间\n- completed_time: 完成时间\n- description: 描述\n- remark: 备注\n- source_order_number: 来源单号\n- reviewer: 审核人\n- start_time: 开始时间\n- updated_at: 更新时间\n\n**上架工单(racking)额外字段：**\n- project_number: 项目编号\n- campus: 园区\n- cabinet: 机柜\n- rack_position: 机位\n- device_category_level1: 设备一级分类\n- device_category_level2: 设备二级分类\n- device_category_level3: 设备三级分类\n\n**到货工单(receiving)额外字段：**\n- arrival_order_number: 到货单号\n- device_category_level1: 设备一级分类\n- device_category_level2: 设备二级分类\n- device_category_level3: 设备三级分类\n\n**电源管理工单(power_management)额外字段：**\n- completed_cabinet_count: 已完成机柜数\n\n**设备增配工单(configuration)额外字段：**\n- parent_device_sn: 父设备SN\n- parent_device_type: 父设备类型\n- parent_device_can_shutdown: 父设备能否关机\n- component_model: 配件型号\n- component_mpn: 配件MPN\n- component_quantity: 配件数量\n- inbound_order_number: 入库单号\n- outbound_order_number: 出库单号\n- close_time: 结束时间\n- device_category_level1: 设备一级分类\n- device_category_level2: 设备二级分类\n- device_category_level3: 设备三级分类\n- configuration_datacenter: 增配机房\n- configuration_room: 增配房间\n- work_order_status: 工单状态\n- failure_reason: 失败理由\n- upgrade_order_number: 增配单号",
                    "content": {
                        "application/json": {
                            "example": {
                                "code": 0,
                                "message": "查询成功",
                                "data": {
                                    "total": 1,
                                    "page": 1,
                                    "page_size": 20,
                                    "items": [
                                        {
                                            "id": 1,
                                            "batch_id": "RACK20251205120000",
                                            "work_order_number": "WO-2025-001",
                                            "work_order_status": "pending",
                                            "operation_type": "racking",
                                            "title": "服务器上架工单",
                                            "status": "pending",
                                            "business_name": "Asset",
                                            "is_timeout": False,
                                            "sla_countdown": 172800,
                                            "actual_duration": None,
                                            "priority": "urgent",
                                            "creator": "张三",
                                            "operator": "李四",
                                            "assignee": "王五",
                                            "datacenter": "DC01",
                                            "room": "A01",
                                            "serial_numbers": ["SN001", "SN002", "SN003"],
                                            "items_count": 5,
                                            "device_count": 3,
                                            "created_at": "2025-12-05T12:00:00",
                                            "expected_completion_time": "2025-12-08T12:00:00",
                                            "completed_time": None,
                                            "description": "批量上架服务器",
                                            "remark": "注意散热",
                                            "source_order_number": "SRC-2025-001",
                                            "reviewer": "赵六",
                                            "start_time": "2025-12-05T13:00:00",
                                            "updated_at": "2025-12-05T14:00:00",
                                            "project_number": "PRJ-2025-001",
                                            "campus": "北京园区",
                                            "cabinet": "A01-01",
                                            "rack_position": "U10-U12",
                                            "device_category_level1": "服务器",
                                            "device_category_level2": "机架式服务器",
                                            "device_category_level3": "2U服务器"
                                        }
                                    ]
                                }
                            }
                        }
                    }
                },
                500: {"description": "服务器内部错误"}
            })
async def list_work_orders(
    operation_type: Optional[str] = Query(None, description="操作类型"),
    status: Optional[str] = Query(None, description="工单状态"),
    creator: Optional[str] = Query(None, description="创建人（支持多个，逗号分隔，如：张三,李四）"),
    operator: Optional[str] = Query(None, description="操作人"),
    is_timeout: Optional[bool] = Query(None, description="是否超时"),
    datacenter: Optional[str] = Query(None, description="机房"),
    room: Optional[str] = Query(None, description="房间"),
    device_category_level1: Optional[str] = Query(None, description="设备一级类型"),
    device_category_level2: Optional[str] = Query(None, description="设备二级类型"),
    device_category_level3: Optional[str] = Query(None, description="设备三级类型"),
    work_order_number: Optional[str] = Query(None, description="外部工单号（支持多个，逗号分隔，如：WO-001,WO-002）"),
    work_order_status: Optional[str] = Query(None, description="外部工单状态"),
    arrival_order_number: Optional[str] = Query(None, description="到货单号"),
    source_order_number: Optional[str] = Query(None, description="来源单号"),
    batch_id: Optional[str] = Query(None, description="批次ID"),
    title: Optional[str] = Query(None, description="工单标题"),
    serial_number: Optional[str] = Query(None, description="设备序列号（支持多个，逗号分隔，如：SN001,SN002）"),
    created_at_start: Optional[str] = Query(None, description="创建时间起始"),
    created_at_end: Optional[str] = Query(None, description="创建时间结束"),
    cabinet_number: Optional[str] = Query(None, description="机柜编号"),
    u_position: Optional[str] = Query(None, description="U位"),
    device_model: Optional[str] = Query(None, description="设备型号"),
    start_time_start: Optional[str] = Query(None, description="开始时间起始"),
    start_time_end: Optional[str] = Query(None, description="开始时间结束"),
    completed_time_start: Optional[str] = Query(None, description="完成时间起始"),
    completed_time_end: Optional[str] = Query(None, description="完成时间结束"),
    power_action: Optional[str] = Query(None, description="电源操作"),
    parent_device_sn: Optional[str] = Query(None, description="父设备SN"),
    parent_device_can_shutdown: Optional[bool] = Query(None, description="父设备能否关机"),
    component_model: Optional[str] = Query(None, description="配件型号"),
    component_mpn: Optional[str] = Query(None, description="配件MPN"),
    component_quantity: Optional[int] = Query(None, description="配件数量"),
    component_sn: Optional[str] = Query(None, description="配件SN"),
    inbound_order_number: Optional[str] = Query(None, description="入库单号"),
    outbound_order_number: Optional[str] = Query(None, description="出库单号"),
    close_time_start: Optional[str] = Query(None, description="关闭时间起始"),
    close_time_end: Optional[str] = Query(None, description="关闭时间结束"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=10000, description="每页数量"),
    db: Session = Depends(get_db)
):
    """
    查询工单列表（支持所有类型）
    
    ## 功能说明
    统一的工单查询接口，支持所有类型工单的多条件组合查询。
    
    ## 通用筛选条件
    - **operation_type**: 操作类型（receiving/racking/power_management/configuration等）
    - **status**: 工单状态（pending/processing/completed/cancelled）
    - **creator**: 创建人（模糊搜索）
    - **operator**: 操作人（模糊搜索）
    - **datacenter**: 机房
    - **room**: 房间
    - **work_order_number**: 外部工单号
    - **work_order_status**: 外部工单状态
    - **batch_id**: 批次ID（模糊搜索）
    - **title**: 工单标题（模糊搜索）
    - **serial_number**: 设备序列号（查询包含该设备的工单）
    - **created_at_start/created_at_end**: 创建时间范围（格式：2025-11-21 或 2025-11-21 14:00:00）
    - created_at_end: 创建时间结束（格式：2025-11-21 或 2025-11-21 14:00:00）
    
    到货工单(receiving)特定查询：
    - device_category_level1: 设备一级分类（模糊搜索）
    - device_category_level2: 设备二级分类（模糊搜索）
    - device_category_level3: 设备三级分类（模糊搜索）
    - arrival_order_number: 到货单号
    - source_order_number: 来源业务单号（模糊搜索）
    
    上架工单(racking)特定查询：
    - cabinet_number: 机柜编号（模糊搜索）
    - u_position: U位（模糊搜索）
    - device_model: 设备型号（模糊搜索）
    - start_time_start: 开始时间起始（格式：2025-11-21 或 2025-11-21 14:00:00）
    - start_time_end: 开始时间结束（格式：2025-11-21 或 2025-11-21 14:00:00）
    - completed_time_start: 完成时间起始（格式：2025-11-21 或 2025-11-21 14:00:00）
    - completed_time_end: 完成时间结束（格式：2025-11-21 或 2025-11-21 14:00:00）
    
    电源管理工单(power_management)特定查询：
    - power_action: 电源动作（power_on/power_off）
    
    设备增配工单(configuration)特定查询：
    - parent_device_sn: 父设备SN（模糊搜索）
    - parent_device_can_shutdown: 父设备能否关机（true/false）
    - component_model: 配件型号（模糊搜索）
    - component_mpn: 配件MPN（模糊搜索）
    - component_quantity: 配件数量
    - component_sn: 设备SN/配件SN（模糊搜索）
    - inbound_order_number: 入库单号（模糊搜索）
    - outbound_order_number: 出库单号（模糊搜索）
    - close_time_start: 结束时间起始（格式：2025-11-21 或 2025-11-21 14:00:00）
    - close_time_end: 结束时间结束（格式：2025-11-21 或 2025-11-21 14:00:00）
    - device_category_level1: 设备一级分类（模糊搜索）
    - device_category_level2: 设备二级分类（模糊搜索）
    - device_category_level3: 设备三级分类（模糊搜索）
    
    分页：
    - page: 页码
    - page_size: 每页数量
    """
    
    params = {
        "operation_type": operation_type,
        "status": status,
        "creator": creator,
        "operator": operator,
        "is_timeout": is_timeout,
        "datacenter": datacenter,
        "room": room,
        "device_category_level1": device_category_level1,
        "device_category_level2": device_category_level2,
        "device_category_level3": device_category_level3,
        "work_order_number": work_order_number,
        "work_order_status": work_order_status,
        "arrival_order_number": arrival_order_number,
        "source_order_number": source_order_number,
        "batch_id": batch_id,
        "title": title,
        "serial_number": serial_number,
        "created_at_start": created_at_start,
        "created_at_end": created_at_end,
        "cabinet_number": cabinet_number,
        "u_position": u_position,
        "device_model": device_model,
        "start_time_start": start_time_start,
        "start_time_end": start_time_end,
        "completed_time_start": completed_time_start,
        "completed_time_end": completed_time_end,
        "power_action": power_action,
        "parent_device_sn": parent_device_sn,
        "parent_device_can_shutdown": parent_device_can_shutdown,
        "component_model": component_model,
        "component_mpn": component_mpn,
        "component_quantity": component_quantity,
        "component_sn": component_sn,
        "inbound_order_number": inbound_order_number,
        "outbound_order_number": outbound_order_number,
        "close_time_start": close_time_start,
        "close_time_end": close_time_end,
    }

    query, force_empty = _apply_work_order_filters(db.query(WorkOrder), db, params)

    if force_empty:
        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "total": 0,
                "page": page,
                "page_size": page_size,
                "items": []
            }
        }

    # 总数
    total = query.count()
    
    # 分页
    orders = query.order_by(
        WorkOrder.created_at.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    
    items = []
    for order in orders:
        items_count = db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order.id
        ).count()
        
        # 计算 SLA 倒计时
        sla_countdown = calculate_sla_countdown(order)
        
        # 计算实际用时（秒）
        actual_duration = None
        if order.completed_time and order.created_at:
            actual_duration = int((order.completed_time - order.created_at).total_seconds())
        
        # 获取工单关联的设备序列号列表
        item_sns = db.query(WorkOrderItem.asset_sn).filter(
            WorkOrderItem.work_order_id == order.id,
            WorkOrderItem.asset_sn.isnot(None)
        ).all()
        serial_numbers = [sn[0] for sn in item_sns if sn[0]]
        
        # 从extra字段提取扩展信息
        extra_data = order.extra if order.extra else {}
        priority = extra_data.get("priority")
        
        # 构建基础字段（所有工单类型通用）
        item_data = {
            "id": order.id,
            "batch_id": order.batch_id,
            "work_order_number": order.work_order_number,
            "work_order_status": order.work_order_status,
            "operation_type": order.operation_type,
            "title": order.title,
            "status": order.status,
            "business_name": "Asset",
            "is_timeout": order.is_timeout,
            "sla_countdown": sla_countdown,
            "actual_duration": actual_duration,
            "priority": priority,
            "creator": order.creator,
            "operator": order.operator,
            "assignee": order.assignee,
            "datacenter": order.datacenter,
            "room": order.room,
            "serial_numbers": serial_numbers,
            "items_count": items_count,
            "device_count": order.device_count,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "expected_completion_time": order.expected_completion_time.isoformat() if order.expected_completion_time else None,
            "completed_time": order.completed_time.isoformat() if order.completed_time else None,
            "description": order.description,
            "remark": order.remark,
            "source_order_number": order.source_order_number
        }
        
        # 根据operation_type添加特定业务字段
        if order.operation_type == "receiving":
            # 设备到货工单特有字段
            item_data.update({
                "arrival_order_number": order.arrival_order_number,
                "source_order_number": order.source_order_number,
                "project_number": order.project_number,
                "campus": order.campus,
                "room": order.room,
                "rack_position": order.rack_position,
                "reviewer": order.reviewer,
                "device_category_level1": order.device_category_level1,
                "device_category_level2": order.device_category_level2,
                "device_category_level3": order.device_category_level3
            })
        
        elif order.operation_type == "racking":
            # 设备上架工单特有字段
            item_data.update({
                "project_number": order.project_number,
                "source_order_number": order.source_order_number,
                "campus": order.campus,
                "cabinet": order.cabinet,
                "rack_position": order.rack_position,
                "device_category_level1": order.device_category_level1,
                "device_category_level2": order.device_category_level2,
                "device_category_level3": order.device_category_level3,
                "reviewer": order.reviewer,
                "start_time": order.start_time.isoformat() if order.start_time else None,
                "updated_at": order.updated_at.isoformat() if order.updated_at else None
            })
        
        elif order.operation_type == "power_management":
            # 电源管理工单特有字段
            # 统计完成机柜数（从WorkOrderItem的operation_data中提取cabinet去重）
            from sqlalchemy import func, distinct
            items_list = db.query(WorkOrderItem).filter(
                WorkOrderItem.work_order_id == order.id
            ).all()
            
            cabinet_set = set()
            for item in items_list:
                if item.operation_data and isinstance(item.operation_data, dict):
                    cabinet = item.operation_data.get('cabinet_number')
                    if cabinet:
                        cabinet_set.add(cabinet)
            
            completed_cabinet_count = len(cabinet_set)
            
            item_data.update({
                "start_time": order.start_time.isoformat() if order.start_time else None,
                "updated_at": order.updated_at.isoformat() if order.updated_at else None,
                "completed_cabinet_count": completed_cabinet_count
            })
        
        elif order.operation_type == "configuration":
            # 设备增配工单特有字段
            # 从extra字段提取失败理由
            failure_reason = extra_data.get("failure_reason")
            
            item_data.update({
                "parent_device_sn": order.parent_device_sn,
                "parent_device_type": order.device_category_level1,
                "parent_device_can_shutdown": order.parent_device_can_shutdown,
                "component_model": order.component_model,
                "component_mpn": order.component_mpn,
                "component_quantity": order.component_quantity,
                "inbound_order_number": order.inbound_order_number,
                "outbound_order_number": order.outbound_order_number,
                "close_time": order.close_time.isoformat() if order.close_time else None,
                "device_category_level1": order.device_category_level1,
                "device_category_level2": order.device_category_level2,
                "device_category_level3": order.device_category_level3,
                "configuration_datacenter": order.datacenter,
                "configuration_room": order.room,
                "work_order_status": order.work_order_status,
                "failure_reason": failure_reason,
                "upgrade_order_number": order.upgrade_order_number,
                "reviewer": order.reviewer,
                "updated_at": order.updated_at.isoformat() if order.updated_at else None
            })
        
        items.append(item_data)
    
    return {
        "code": 0,
        "message": "查询成功",
        "data": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items
        }
    }


@router.get("/export", summary="导出工单列表",
            responses={
                200: {
                    "description": "导出成功，返回Excel文件",
                    "content": {
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                            "schema": {
                                "type": "string",
                                "format": "binary"
                            }
                        }
                    }
                },
                404: {
                    "description": "没有找到符合条件的工单数据"
                },
                500: {"description": "服务器内部错误"}
            })
async def export_work_orders(
    operation_type: Optional[str] = Query(None, description="操作类型"),
    status: Optional[str] = Query(None, description="工单状态"),
    creator: Optional[str] = Query(None, description="创建人（支持多个，逗号分隔，如：张三,李四）"),
    operator: Optional[str] = Query(None, description="操作人"),
    is_timeout: Optional[bool] = Query(None, description="是否超时"),
    datacenter: Optional[str] = Query(None, description="机房"),
    room: Optional[str] = Query(None, description="房间"),
    device_category_level1: Optional[str] = Query(None, description="设备一级类型"),
    device_category_level2: Optional[str] = Query(None, description="设备二级类型"),
    device_category_level3: Optional[str] = Query(None, description="设备三级类型"),
    work_order_number: Optional[str] = Query(None, description="外部工单号（支持多个，逗号分隔，如：WO-001,WO-002）"),
    work_order_status: Optional[str] = Query(None, description="外部工单状态"),
    arrival_order_number: Optional[str] = Query(None, description="到货单号"),
    source_order_number: Optional[str] = Query(None, description="来源单号"),
    batch_id: Optional[str] = Query(None, description="批次ID"),
    title: Optional[str] = Query(None, description="工单标题"),
    serial_number: Optional[str] = Query(None, description="设备序列号（支持多个，逗号分隔，如：SN001,SN002）"),
    created_at_start: Optional[str] = Query(None, description="创建时间起始"),
    created_at_end: Optional[str] = Query(None, description="创建时间结束"),
    cabinet_number: Optional[str] = Query(None, description="机柜编号"),
    u_position: Optional[str] = Query(None, description="U位"),
    device_model: Optional[str] = Query(None, description="设备型号"),
    start_time_start: Optional[str] = Query(None, description="开始时间起始"),
    start_time_end: Optional[str] = Query(None, description="开始时间结束"),
    completed_time_start: Optional[str] = Query(None, description="完成时间起始"),
    completed_time_end: Optional[str] = Query(None, description="完成时间结束"),
    power_action: Optional[str] = Query(None, description="电源操作"),
    parent_device_sn: Optional[str] = Query(None, description="父设备SN"),
    parent_device_can_shutdown: Optional[bool] = Query(None, description="父设备能否关机"),
    component_model: Optional[str] = Query(None, description="配件型号"),
    component_mpn: Optional[str] = Query(None, description="配件MPN"),
    component_quantity: Optional[int] = Query(None, description="配件数量"),
    component_sn: Optional[str] = Query(None, description="配件SN"),
    inbound_order_number: Optional[str] = Query(None, description="入库单号"),
    outbound_order_number: Optional[str] = Query(None, description="出库单号"),
    close_time_start: Optional[str] = Query(None, description="关闭时间起始"),
    close_time_end: Optional[str] = Query(None, description="关闭时间结束"),
    export_all: bool = Query(False, description="是否导出全部（最多1000条）"),
    db: Session = Depends(get_db)
):
    """
    导出工单列表为Excel文件
    
    ## 功能说明
    根据查询条件导出工单列表到Excel文件，支持所有工单类型的导出。
    
    ## 查询参数
    支持与查询工单列表接口相同的所有筛选条件，包括：
    
    ### 通用筛选条件
    - **operation_type**: 操作类型
    - **status**: 工单状态
    - **creator**: 创建人
    - **operator**: 操作人
    - **datacenter**: 机房
    - **room**: 房间
    - **work_order_number**: 外部工单号
    - **batch_id**: 批次ID
    - **title**: 工单标题
    - **serial_number**: 设备序列号
    - **created_at_start/created_at_end**: 创建时间范围
    
    ### 到货工单特定条件
    - **device_category_level1/2/3**: 设备分类
    - **arrival_order_number**: 到货单号
    - **source_order_number**: 来源单号
    
    ### 上架工单特定条件
    - **cabinet_number**: 机柜编号
    - **u_position**: U位
    - **device_model**: 设备型号
    - **start_time_start/end**: 开始时间范围
    - **completed_time_start/end**: 完成时间范围
    
    ### 电源管理工单特定条件
    - **power_action**: 电源操作（power_on/power_off）
    
    ### 增配工单特定条件
    - **parent_device_sn**: 父设备SN
    - **parent_device_can_shutdown**: 父设备能否关机
    - **component_model**: 配件型号
    - **component_mpn**: 配件MPN
    - **component_quantity**: 配件数量
    - **component_sn**: 配件SN
    - **inbound_order_number**: 入库单号
    - **outbound_order_number**: 出库单号
    - **close_time_start/end**: 关闭时间范围
    
    ### 导出控制
    - **export_all**: 是否导出全部（默认false，最多导出1000条）
    
    ## 返回内容
    - **Content-Type**: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    - **文件名**: work_orders_YYYYMMDD_HHMMSS.xlsx
    - **Excel内容**: 包含所有工单字段的表格数据
    
    ## Excel列说明
    根据工单类型不同，Excel包含的列也不同：
    
    ### 通用列
    - 批次ID、工单号、操作类型、标题、状态
    - 创建人、操作人、指派人
    - 机房、房间
    - 设备数量
    - 创建时间、完成时间
    - 描述、备注
    
    ### 到货工单额外列
    - 到货单号、来源单号、项目编号
    - 设备分类（一级/二级/三级）
    - 园区、审核人
    
    ### 上架工单额外列
    - 机柜、机架位置
    - SLA倒计时、是否超时
    
    ### 电源管理工单额外列
    - 电源操作、电源类型
    
    ### 增配工单额外列
    - 父设备SN、厂商是否上门
    - 父设备能否关机、是否光模块增配
    - 允许操作时间范围
    - 配件信息
    
    ## 使用场景
    1. 批量导出工单数据进行分析
    2. 生成工单报表
    3. 数据备份
    4. 与其他系统集成
    
    ## 注意事项
    1. 如果没有符合条件的数据，返回404错误
    2. 默认最多导出1000条记录，设置export_all=true可导出全部
    3. 导出的Excel文件名包含时间戳
    4. 文件编码为UTF-8，支持中文
    5. 日期时间格式为ISO 8601
    """
    params = {
        "operation_type": operation_type,
        "status": status,
        "creator": creator,
        "operator": operator,
        "is_timeout": is_timeout,
        "datacenter": datacenter,
        "room": room,
        "device_category_level1": device_category_level1,
        "device_category_level2": device_category_level2,
        "device_category_level3": device_category_level3,
        "work_order_number": work_order_number,
        "work_order_status": work_order_status,
        "arrival_order_number": arrival_order_number,
        "source_order_number": source_order_number,
        "batch_id": batch_id,
        "title": title,
        "serial_number": serial_number,
        "created_at_start": created_at_start,
        "created_at_end": created_at_end,
        "cabinet_number": cabinet_number,
        "u_position": u_position,
        "device_model": device_model,
        "start_time_start": start_time_start,
        "start_time_end": start_time_end,
        "completed_time_start": completed_time_start,
        "completed_time_end": completed_time_end,
        "power_action": power_action,
        "parent_device_sn": parent_device_sn,
        "parent_device_can_shutdown": parent_device_can_shutdown,
        "component_model": component_model,
        "component_mpn": component_mpn,
        "component_quantity": component_quantity,
        "component_sn": component_sn,
        "inbound_order_number": inbound_order_number,
        "outbound_order_number": outbound_order_number,
        "close_time_start": close_time_start,
        "close_time_end": close_time_end,
    }

    query, force_empty = _apply_work_order_filters(db.query(WorkOrder), db, params)

    if force_empty:
        raise HTTPException(status_code=404, detail="没有找到符合条件的工单数据")

    export_limit = 1000 if export_all else 200
    orders = query.order_by(WorkOrder.created_at.desc()).limit(export_limit).all()

    if not orders:
        raise HTTPException(status_code=404, detail="没有找到符合条件的工单数据")

    rows = []
    for order in orders:
        items_count = db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order.id
        ).count()

        rows.append({
            "批次ID": order.batch_id,
            "外部工单号": order.work_order_number or "",
            "操作类型": order.operation_type,
            "标题": order.title or "",
            "内部状态": order.status,
            "外部状态": order.work_order_status or "",
            "是否超时": "是" if order.is_timeout else "否",
            "创建人": order.creator or "",
            "指派人": order.assignee or "",
            "操作人": order.operator or "",
            "审核人": order.reviewer or "",
            "机房": order.datacenter or "",
            "园区": order.campus or "",
            "房间": order.room or "",
            "机柜": order.cabinet or "",
            "机位": order.rack_position or "",
            "项目编号": order.project_number or "",
            "设备数量": order.device_count or 0,
            "到货单号": order.arrival_order_number or "",
            "来源单号": order.source_order_number or "",
            "入库单号": order.inbound_order_number or "",
            "出库单号": order.outbound_order_number or "",
            "期望完成时间": order.expected_completion_time.isoformat() if order.expected_completion_time else "",
            "开始时间": order.start_time.isoformat() if order.start_time else "",
            "完成时间": order.completed_time.isoformat() if order.completed_time else "",
            "结单时间": order.close_time.isoformat() if order.close_time else "",
            "创建时间": order.created_at.isoformat() if order.created_at else "",
            "更新时间": order.updated_at.isoformat() if order.updated_at else "",
            "备注": order.remark or "",
            "工单设备数量": items_count,
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="工单数据")
        worksheet = writer.sheets["工单数据"]
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    cell_length = len(str(cell.value))
                    if cell_length > max_length:
                        max_length = cell_length
                except Exception:
                    pass
            worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)

    output.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"工单导出_{timestamp}.xlsx"
    disposition = f"attachment; filename*=UTF-8''{quote(filename.encode('utf-8'))}"

    return StreamingResponse(
        io.BytesIO(output.read()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition}
    )


@router.get("/{batch_id}", summary="查询工单详情",
            response_model=ApiResponse,
            responses={
                200: {
                    "description": "查询成功",
                    "content": {
                        "application/json": {
                            "examples": {
                                "racking": {
                                    "summary": "上架工单详情（包含完整设备信息）",
                                    "value": {
                                        "code": 0,
                                        "message": "查询成功",
                                        "data": {
                                            "batch_id": "RACK_20251205120000",
                                            "work_order_number": "WO202512051234",
                                            "operation_type": "racking",
                                            "title": "服务器上架",
                                            "status": "completed",
                                            "work_order_status": "已完成",
                                            "creator": "张三",
                                            "assignee": "李四",
                                            "operator": "李四",
                                            "datacenter": "DC01",
                                            "room": "Room-A",
                                            "device_count": 2,
                                            "created_at": "2025-12-05T12:00:00",
                                            "completed_time": "2025-12-05T14:00:00",
                                            "description": "批量上架服务器",
                                            "remark": "按照标准流程上架",
                                            "items": [
                                                {
                                                    "id": 1,
                                                    "asset_identifier": "SN123456",
                                                    "asset_tag": "AT001",
                                                    "asset_name": "Dell服务器R740",
                                                    "asset_id": 100,
                                                    "sn": "SN123456",
                                                    "serial_number": "SN123456",
                                                    "model": "PowerEdge R740",
                                                    "vendor_standard_model": "Dell R740",
                                                    "vendor_id": 1,
                                                    "vendor_name": "Dell",
                                                    "category_level1": "服务器",
                                                    "category_level2": "机架式服务器",
                                                    "category_level3": "2U服务器",
                                                    "target_datacenter": "DC01",
                                                    "target_room": "Room-A",
                                                    "target_cabinet": "CAB-001",
                                                    "target_rack_position": "10-12U",
                                                    "location_detail": "CAB-001机柜 10-12U",
                                                    "room_id": 1,
                                                    "ip_address": "192.168.1.100",
                                                    "mac_address": "00:11:22:33:44:55",
                                                    "asset_status": "active",
                                                    "lifecycle_status": "racked",
                                                    "outbound_order_number": "OUT202512051000",
                                                    "inbound_order_number": "RECV202512041000",
                                                    "network_racking_order_number": None,
                                                    "power_connection_order_number": "PWR202512051500",
                                                    "connected_devices": [
                                                        {"sn": "SW-CORE-001", "is_company_device": True, "device_type": "upstream"},
                                                        {"sn": "STORAGE-001", "is_company_device": False, "device_type": "downstream"}
                                                    ],
                                                    "status": "completed",
                                                    "result": "上架成功",
                                                    "operation_data": {
                                                        "cabinet_number": "CAB-001",
                                                        "u_position": "10-12"
                                                    },
                                                    "operation_summary": "机柜: CAB-001, 机位: 10-12U",
                                                    "error_message": None
                                                }
                                            ]
                                        }
                                    }
                                },
                                "power_management": {
                                    "summary": "电源管理工单详情（完整40字段）",
                                    "value": {
                                        "code": 0,
                                        "message": "查询成功",
                                        "data": {
                                            # 核心标识 (4个)
                                            "batch_id": "POWER_20251205120000",
                                            "work_order_number": "WO202512051234",
                                            "arrival_order_number": "ARR202512051234",
                                            "source_order_number": "SRC202512051234",
                                            
                                            # 业务信息 (3个)
                                            "operation_type": "power_management",
                                            "title": "A101房间设备上电",
                                            "description": "批量上电操作",
                                            
                                            # 状态管理 (4个)
                                            "status": "processing",
                                            "work_order_status": "处理中",
                                            "is_timeout": False,
                                            "sla_countdown": 3600,
                                            
                                            # 人员信息 (4个)
                                            "creator": "张三",
                                            "operator": "李四",
                                            "assignee": "李四",
                                            "reviewer": "王五",
                                            
                                            # 位置信息 (5个)
                                            "datacenter": "DC01",
                                            "campus": "北京园区",
                                            "room": "A101",
                                            "cabinet": "CAB-001",
                                            "rack_position": "10-12U",
                                            
                                            # 项目信息 (1个)
                                            "project_number": "PROJ-2025-001",
                                            
                                            # 时间信息 (6个)
                                            "start_time": "2025-12-05T12:00:00",
                                            "expected_completion_time": "2025-12-06T12:00:00",
                                            "completed_time": "2025-12-06T10:30:00",
                                            "close_time": "2025-12-06T11:00:00",
                                            "created_at": "2025-12-05T12:00:00",
                                            "updated_at": "2025-12-05T12:30:00",
                                            
                                            # 统计信息 (2个)
                                            "device_count": 5,
                                            "items_count": 5,
                                            
                                            # 备注信息 (1个)
                                            "remark": "按照标准流程操作",
                                            
                                            # 扩展信息 (4个)
                                            "priority": "high",
                                            "operation_type_detail": "紧急上电",
                                            "is_business_online": True,
                                            "failure_reason": None,
                                            
                                            # 电源管理特定字段 (5个)
                                            "power_action": "power_on",
                                            "power_type": "AC",
                                            "power_reason": None,
                                            "cabinet_count": 3,
                                            "cabinet_summary": {
                                                "total_cabinets": 3,
                                                "cabinet_list": ["A-01", "A-02", "A-03"],
                                                "note": "如需查看完整的机柜详细信息（32个字段），请调用 GET /api/v1/work-orders/{work_order_id}/room-cabinets"
                                            },
                                            
                                            # 设备明细 (1个)
                                            "items": [
                                                {
                                                    "id": 1,
                                                    "asset_identifier": "SN123456",
                                                    "asset_tag": "DEV001",
                                                    "asset_name": "Dell服务器R740",
                                                    "status": "completed",
                                                    "operation_data": {"location_detail": "机柜A-01"},
                                                    "operation_summary": "位置: 机柜A-01",
                                                    "result": "上电成功",
                                                    "error_message": None
                                                }
                                            ]
                                        }
                                    }
                                },
                                "configuration": {
                                    "summary": "增配工单详情",
                                    "value": {
                                        "code": 0,
                                        "message": "查询成功",
                                        "data": {
                                            "batch_id": "CONF_20251205120000",
                                            "work_order_number": "WO202512051234",
                                            "operation_type": "configuration",
                                            "title": "服务器内存增配",
                                            "status": "completed",
                                            "parent_device_sn": "SN-PARENT-001",
                                            "vendor_onsite": True,
                                            "parent_device_can_shutdown": False,
                                            "allowed_operation_start_time": "2025-12-05T20:00:00",
                                            "allowed_operation_end_time": "2025-12-06T06:00:00",
                                            "is_optical_module_upgrade": False,
                                            "is_project_upgrade": True,
                                            "project_number": "PROJ-2025-001",
                                            "items": [
                                                {
                                                    "serial_number": "SN-MEM-001",
                                                    "asset_tag": "AT-MEM-001",
                                                    "asset_name": "内存条32GB",
                                                    "status": "completed",
                                                    "result": "增配成功",
                                                    "operation_data": {
                                                        "sn": "SN-MEM-001",
                                                        "slot": "DIMM-A1",
                                                        "quantity": 1
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                404: {
                    "description": "工单不存在",
                    "content": {
                        "application/json": {
                            "example": {
                                "code": 404,
                                "message": "工单不存在: RACK_20251205120000",
                                "data": None
                            }
                        }
                    }
                },
                500: {"description": "服务器内部错误"}
            })
async def get_work_order_detail(
    batch_id: str = Path(..., description="批次ID", example="RACK_20251205120000"),
    db: Session = Depends(get_db)
):
    """
    查询工单详情（通用）
    
    ## 功能说明
    根据批次ID查询工单的完整信息，包括所有设备明细和操作数据。
    
    ## 路径参数
    - **batch_id**: 批次ID（必填）
    
    ## 返回字段说明
    
    ### 通用字段
    - **batch_id**: 批次ID
    - **work_order_number**: 外部工单号
    - **operation_type**: 操作类型
    - **title**: 工单标题
    - **status**: 工单状态
      - pending: 待处理
      - processing: 处理中
      - completed: 已完成
      - cancelled: 已取消
    - **work_order_status**: 外部工单状态描述
    - **creator**: 创建人
    - **assignee**: 指派人
    - **operator**: 操作人
    - **datacenter**: 机房
    - **room**: 房间
    - **device_count**: 设备数量
    - **created_at**: 创建时间
    - **expected_completion_time**: 期望完成时间
    - **completed_time**: 完成时间
    - **description**: 工单描述
    - **remark**: 备注
    - **items**: 设备明细列表
      - **serial_number**: 设备序列号
      - **asset_tag**: 资产标签
      - **asset_name**: 资产名称
      - **status**: 明细状态
      - **result**: 处理结果
      - **operation_data**: 操作数据
      - **error_message**: 错误信息
      - **executed_at**: 执行时间
      - **executed_by**: 执行人
    
    ### 到货工单特定字段
    - **arrival_order_number**: 到货单号
    - **source_order_number**: 来源单号
    - **project_number**: 项目编号
    - **campus**: 园区
    - **reviewer**: 审核人
    - **device_category_level1/2/3**: 设备分类
    
    ### 上架工单特定字段
    - **cabinet**: 机柜
    - **rack_position**: 机架位置
    - **sla_countdown**: SLA倒计时（秒）
    - **is_timeout**: 是否超时
    - **start_time**: 开始时间
    - **items**: 设备明细列表（上架工单包含完整设备信息）
      - **id**: 明细ID
      - **asset_identifier**: 设备序列号
      - **asset_tag**: 资产标签
      - **asset_name**: 资产名称
      - **asset_id**: 资产ID
      - **sn**: 设备序列号
      - **serial_number**: 序列号
      - **model**: 设备型号
      - **vendor_standard_model**: 厂商标准机型
      - **vendor_id**: 厂商ID
      - **vendor_name**: 厂商名称
      - **category_level1**: 一级分类
      - **category_level2**: 二级分类
      - **category_level3**: 三级分类
      - **target_datacenter**: 目标机房
      - **target_room**: 目标房间
      - **target_cabinet**: 目标机柜
      - **target_rack_position**: 目标机位
      - **location_detail**: 当前位置详情
      - **room_id**: 房间ID
      - **ip_address**: IP地址
      - **mac_address**: MAC地址
      - **asset_status**: 资产状态
      - **lifecycle_status**: 生命周期状态
      - **outbound_order_number**: 出库单号
      - **inbound_order_number**: 入库单号
      - **network_racking_order_number**: 网络设备上架单号
      - **power_connection_order_number**: 插线通电单号
      - **connected_devices**: 上下联设备列表（审核人添加）
        - **sn**: 设备序列号
        - **is_company_device**: 是否本公司设备（布尔值）
        - **device_type**: 设备属性（upstream-上联, downstream-下联）
      - **status**: 明细状态
      - **operation_data**: 操作数据
      - **operation_summary**: 操作摘要
      - **result**: 处理结果
      - **error_message**: 错误信息
    
    ### 电源管理工单特定字段
    - **power_action**: 电源操作（power_on上电/power_off下电）
    - **power_type**: 电源类型（AC交流电/DC直流电）
    - **power_reason**: 下电原因（仅下电时有值）
    - **cabinet_count**: 涉及的机柜数量
    - **expected_completion_time**: 期望完成时间
    - **room_cabinets_info**: 机房机柜完整信息（包含32个字段）
      - **room_name**: 机房名称
      - **total_cabinets**: 机房内机柜总数
      - **cabinets_in_work_order**: 本工单涉及的机柜数
      - **cabinets_not_in_work_order**: 本工单未涉及的机柜数
      - **cabinets**: 机柜列表（每个机柜包含以下32个字段）
        - **cabinet_number**: 机柜编号，机柜的唯一标识符，如"CAB-001"
        - **cabinet_name**: 机柜名称，机柜的显示名称，如"核心业务机柜A"
        - **datacenter**: 数据中心名称，机柜所在的数据中心，如"DC01"
        - **room**: 房间名称，机柜所在的房间，如"A101"
        - **room_number**: 房间编号，房间的编号标识，如"101"
        - **operator_cabinet_number**: 运营商机柜编号，运营商侧的机柜标识
        - **power_type**: 电源类型，机柜使用的电源类型，如"AC"（交流电）、"DC"（直流电）
        - **pdu_interface_standard**: PDU接口标准，电源分配单元的接口标准，如"C13"、"C19"
        - **cabinet_type**: 机柜类型，机柜的分类，如"标准机柜"、"网络机柜"
        - **cabinet_type_detail**: 机柜类型详情，机柜类型的详细说明，如"42U标准机柜"
        - **width**: 机柜宽度，机柜的宽度尺寸，如"600mm"
        - **size**: 机柜尺寸，机柜的高度规格，如"42U"、"47U"
        - **power_status**: 电源状态，机柜当前的电源状态，如"on"（已上电）、"off"（已下电）
        - **usage_status**: 使用状态，机柜的使用情况，如"in_use"（使用中）、"idle"（空闲）
        - **lifecycle_status**: 生命周期状态，机柜的生命周期阶段，如"active"（活跃）、"retired"（退役）
        - **module_construction_status**: 模块建设状态，机柜的建设完成情况，如"completed"（已完成）、"in_progress"（建设中）
        - **planning_category**: 规划类别，机柜的规划用途分类，如"生产"、"测试"、"开发"
        - **construction_density**: 建设密度，机柜的建设密度等级，如"高密度"、"中密度"、"低密度"
        - **last_power_operation**: 最后一次电源操作，最近一次执行的电源操作类型，如"power_on"、"power_off"
        - **last_power_operation_date**: 最后操作日期，最近一次电源操作的执行时间，ISO格式
        - **last_operation_result**: 最后操作结果，最近一次操作的执行结果，如"success"（成功）、"failed"（失败）
        - **last_operation_failure_reason**: 最后操作失败原因，如果操作失败，记录失败的具体原因
        - **total_devices**: 机柜内设备总数，该机柜中安装的所有设备数量
        - **devices_in_work_order**: 本工单涉及的设备数，本次工单中该机柜涉及的设备数量
        - **devices_not_in_work_order**: 不在本工单中的设备数，该机柜中不在本次工单范围内的设备数量
        - **is_in_work_order**: 是否在本工单中，布尔值，表示该机柜是否在本次工单的操作范围内
        - **work_order_devices**: 本工单涉及的设备列表，数组，包含该机柜中本次工单涉及的所有设备信息
          - **serial_number**: 设备序列号
          - **asset_tag**: 资产标签
          - **name**: 设备名称
          - **status**: 设备在工单中的状态
        - **total_u_count**: 总U位数，机柜的总U位容量，如42U机柜为42
        - **used_u_count**: 已使用U位数，机柜中已被设备占用的U位数量
        - **available_u_count**: 可用U位数，机柜中剩余可用的U位数量（total_u_count - used_u_count）
        - **responsible_person**: 负责人，该机柜的责任人或管理员
        - **notes**: 备注，关于该机柜的其他备注信息
    
    ### 增配工单特定字段
    - **parent_device_sn**: 父设备SN
    - **vendor_onsite**: 厂商是否上门
    - **parent_device_can_shutdown**: 父设备能否关机
    - **allowed_operation_start_time**: 允许操作开始时间
    - **allowed_operation_end_time**: 允许操作结束时间
    - **is_optical_module_upgrade**: 是否光模块增配
    - **is_project_upgrade**: 是否项目增配
    - **project_number**: 项目编号
    - **inbound_order_number**: 入库单号
    - **outbound_order_number**: 出库单号
    - **upgrade_order_number**: 增配单号
    - **close_time**: 关闭时间
    
    ### 网络故障/变更配合工单特定字段
    - **priority**: 优先级（normal-一般, urgent-紧急）
    - **business_type**: 业务类型（fault_support-故障支持, change_support-变更支持, other-其他）
    - **operation_type_detail**: 操作类型详情
    - **is_business_online**: 业务是否在线
    - **service_content**: 服务内容
    - **processing_result**: 处理结果
    - **accept_remark**: 接单备注
    - **close_remark**: 结单备注
    - **devices**: 设备列表（替代items字段）
    
    ## 使用场景
    1. 查看工单的完整信息
    2. 检查工单执行进度
    3. 查看设备处理详情
    4. 审计工单操作记录
    
    ## 注意事项
    1. 如果工单不存在，返回404错误
    2. items列表包含该工单的所有设备明细
    3. operation_data的结构根据operation_type不同而不同
    4. 不同工单类型返回的字段会有所不同
    """
    
    work_order = db.query(WorkOrder).filter(
        WorkOrder.batch_id == batch_id
    ).first()
    
    if not work_order:
        return ApiResponse(
            code=1002,
            message=f"工单不存在: {batch_id}",
            data=None
        )
    
    extra_data = work_order.extra or {}
    # 获取所有明细
    items = db.query(WorkOrderItem).filter(
        WorkOrderItem.work_order_id == work_order.id
    ).all()
    
    items_data = []
    for item in items:
        asset = item.asset
        item_data = {
            "id": item.id,
            "asset_identifier": asset.serial_number if asset else None,
            "asset_tag": asset.asset_tag if asset else None,
            "asset_name": asset.name if asset else None,
            "status": item.status,
            "operation_data": item.operation_data,
            "operation_summary": get_operation_summary(work_order.operation_type, item.operation_data),
            "result": item.result,
            "error_message": item.error_message
        }
        
        # 对于上架工单，添加更完整的设备信息
        if work_order.operation_type == "racking" and asset:
            # 获取操作数据中的位置信息
            op_data = item.operation_data or {}
            
            # 获取三级分类名称
            category_level1 = None
            category_level2 = None
            category_level3 = None
            if asset.category_item:
                category_level1 = asset.category_item.item_label
            if asset.secondary_category_item:
                category_level2 = asset.secondary_category_item.item_label
            if asset.tertiary_category_item:
                category_level3 = asset.tertiary_category_item.item_label
            
            # 获取厂商名称
            vendor_name = None
            if asset.vendor:
                vendor_name = asset.vendor.name
            
            item_data.update({
                # 设备基本信息
                "asset_id": asset.id,
                "sn": asset.serial_number,
                "serial_number": asset.serial_number,
                "model": asset.model,
                "vendor_standard_model": asset.vendor_standard_model,
                
                # 厂商信息
                "vendor_id": asset.vendor_id,
                "vendor_name": vendor_name,
                
                # 三级分类
                "category_level1": category_level1,
                "category_level2": category_level2,
                "category_level3": category_level3,
                
                # 目标位置信息（从operation_data或item字段获取）
                "target_datacenter": op_data.get("datacenter") or item.item_datacenter or work_order.datacenter,
                "target_room": op_data.get("room") or op_data.get("target_room") or item.item_room or work_order.room,
                "target_cabinet": op_data.get("cabinet_number") or op_data.get("cabinet") or item.item_cabinet or work_order.cabinet,
                "target_rack_position": op_data.get("u_position") or op_data.get("rack_position") or item.item_rack_position or work_order.rack_position,
                
                # 当前位置信息
                "location_detail": asset.location_detail,
                "room_id": asset.room_id,
                
                # 网络信息
                "ip_address": asset.ip_address,
                "mac_address": asset.mac_address,
                
                # 状态信息
                "asset_status": asset.asset_status,
                "lifecycle_status": asset.lifecycle_status,
            })
            
            # 查询关联的各类单号
            # 出库单号（出库工单）
            outbound_order = db.query(WorkOrder).join(WorkOrderItem).filter(
                WorkOrderItem.asset_id == asset.id,
                WorkOrder.operation_type == "outbound",
                WorkOrder.id != work_order.id
            ).order_by(WorkOrder.created_at.desc()).first()
            item_data["outbound_order_number"] = outbound_order.work_order_number if outbound_order else None
            
            # 入库单号（到货工单）
            inbound_order = db.query(WorkOrder).join(WorkOrderItem).filter(
                WorkOrderItem.asset_id == asset.id,
                WorkOrder.operation_type == "receiving",
                WorkOrder.id != work_order.id
            ).order_by(WorkOrder.created_at.desc()).first()
            item_data["inbound_order_number"] = inbound_order.work_order_number if inbound_order else None
            
            # 网络设备上架单号（其他上架工单）
            network_racking_order = db.query(WorkOrder).join(WorkOrderItem).filter(
                WorkOrderItem.asset_id == asset.id,
                WorkOrder.operation_type == "racking",
                WorkOrder.id != work_order.id
            ).order_by(WorkOrder.created_at.desc()).first()
            item_data["network_racking_order_number"] = network_racking_order.work_order_number if network_racking_order else None
            
            # 插线通电单号（电源管理工单）
            power_order = db.query(WorkOrder).join(WorkOrderItem).filter(
                WorkOrderItem.asset_id == asset.id,
                WorkOrder.operation_type == "power_management",
                WorkOrder.id != work_order.id
            ).order_by(WorkOrder.created_at.desc()).first()
            item_data["power_connection_order_number"] = power_order.work_order_number if power_order else None
            
            # 上下联设备信息（审核人添加）
            # 格式: [{"sn": "xxx", "is_company_device": true, "device_type": "upstream/downstream"}, ...]
            item_data["connected_devices"] = op_data.get("connected_devices", [])
        
        items_data.append(item_data)
    
    # 构建基础响应数据（所有工单类型的通用字段）
    response_data = {
        # 核心标识
        "batch_id": work_order.batch_id,
        "work_order_number": work_order.work_order_number,
        "arrival_order_number": work_order.arrival_order_number,
        "source_order_number": work_order.source_order_number,
        
        # 业务信息
        "operation_type": work_order.operation_type,
        "title": work_order.title,
        "description": work_order.description,
        
        # 状态管理
        "status": work_order.status,
        "work_order_status": work_order.work_order_status,
        "is_timeout": work_order.is_timeout,
        "sla_countdown": work_order.sla_countdown,
        
        # 人员信息
        "creator": work_order.creator,
        "operator": work_order.operator,
        "assignee": work_order.assignee,
        "reviewer": work_order.reviewer,
        
        # 位置信息
        "datacenter": work_order.datacenter,
        "campus": work_order.campus,
        "room": work_order.room,
        "cabinet": work_order.cabinet,
        "rack_position": work_order.rack_position,
        
        # 项目信息
        "project_number": work_order.project_number,
        
        # 时间信息
        "start_time": work_order.start_time.isoformat() if work_order.start_time else None,
        "expected_completion_time": work_order.expected_completion_time.isoformat() if work_order.expected_completion_time else None,
        "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
        "close_time": work_order.close_time.isoformat() if work_order.close_time else None,
        "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
        "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None,
        
        # 统计信息
        "device_count": work_order.device_count or 0,
        "items_count": len(items_data),
        
        # 备注信息
        "remark": work_order.remark,
        
        # 扩展信息（从extra中提取常用字段）
        "priority": extra_data.get("priority"),
        "operation_type_detail": extra_data.get("operation_type_detail"),
        "is_business_online": extra_data.get("is_business_online"),
        "failure_reason": extra_data.get("failure_reason"),
        "attachments": extra_data.get("attachments"),  # 附件列表
        
        # 设备明细
        "items": items_data
    }
    
    # 如果是电源管理工单，添加电源管理特定字段
    if work_order.operation_type == "power_management":
        # 从 extra 中提取电源管理信息（优先从extra直接获取，兼容旧的operation_data结构）
        power_action = extra_data.get("power_action") or extra_data.get("operation_data", {}).get("power_action")
        power_type = extra_data.get("power_type") or extra_data.get("operation_data", {}).get("power_type")
        power_reason = extra_data.get("power_reason") or extra_data.get("operation_data", {}).get("reason")
        
        response_data.update({
            "power_action": power_action,
            "power_type": power_type,
            "power_reason": power_reason,
            "cabinet_count": work_order.cabinet_count or 0,
        })
        
        # 添加完整的机柜详细信息（包含32个字段）
        if work_order.room:
            try:
                # 导入必要的模块
                import re
                
                # 获取工单涉及的设备和机柜
                work_order_cabinets = set()
                work_order_devices_by_cabinet = {}
                
                for item in items:
                    if item.asset:
                        cabinet = None
                        if item.asset.location_detail:
                            match = re.search(r'([A-Z0-9\-]+)(?:机柜|柜)', item.asset.location_detail)
                            if match:
                                cabinet = match.group(1)
                        
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
                
                # 获取房间的所有设备（按机柜分组）
                room_obj = db.query(Room).filter(Room.room_abbreviation == work_order.room).first()
                all_cabinets_in_room = {}
                
                if room_obj:
                    assets_in_room = db.query(Asset).filter(Asset.room_id == room_obj.id).all()
                    
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
                
                # 从机柜表获取详细信息
                cabinets_in_db = db.query(Cabinet).filter(Cabinet.room == work_order.room).all()
                cabinets_dict = {cab.cabinet_number: cab for cab in cabinets_in_db}
                
                # 构建机柜列表
                cabinets_list = []
                for cabinet_name, stats in all_cabinets_in_room.items():
                    cabinet_info = cabinets_dict.get(cabinet_name)
                    
                    cabinet_data = {
                        'cabinet_number': cabinet_name,
                        'cabinet_name': cabinet_info.cabinet_name if cabinet_info else None,
                        'datacenter': cabinet_info.datacenter if cabinet_info else None,
                        'room': work_order.room,
                        'power_status': cabinet_info.power_status if cabinet_info else None,
                        'total_devices': stats['total_devices'],
                        'devices_in_work_order': stats['in_work_order'],
                        'devices_not_in_work_order': stats['not_in_work_order'],
                        'is_in_work_order': cabinet_name in work_order_cabinets,
                        'work_order_devices': work_order_devices_by_cabinet.get(cabinet_name, []),
                    }
                    
                    # 添加完整的32个字段（如果机柜信息存在）
                    if cabinet_info:
                        cabinet_data.update({
                            'room_number': cabinet_info.room_number,
                            'operator_cabinet_number': cabinet_info.operator_cabinet_number,
                            'power_type': cabinet_info.power_type,
                            'pdu_interface_standard': cabinet_info.pdu_interface_standard,
                            'cabinet_type': cabinet_info.cabinet_type,
                            'cabinet_type_detail': cabinet_info.cabinet_type_detail,
                            'width': cabinet_info.width,
                            'size': cabinet_info.size,
                            'usage_status': cabinet_info.usage_status,
                            'lifecycle_status': cabinet_info.lifecycle_status,
                            'module_construction_status': cabinet_info.module_construction_status,
                            'planning_category': cabinet_info.planning_category,
                            'construction_density': cabinet_info.construction_density,
                            'last_power_operation': cabinet_info.last_power_operation,
                            'last_power_operation_date': cabinet_info.last_power_operation_date.isoformat() if cabinet_info.last_power_operation_date else None,
                            'last_operation_result': cabinet_info.last_operation_result,
                            'last_operation_failure_reason': cabinet_info.last_operation_failure_reason,
                            'total_u_count': cabinet_info.total_u_count,
                            'used_u_count': cabinet_info.used_u_count,
                            'available_u_count': cabinet_info.available_u_count,
                            'responsible_person': cabinet_info.responsible_person,
                            'notes': cabinet_info.notes,
                        })
                    
                    cabinets_list.append(cabinet_data)
                
                cabinets_list.sort(key=lambda x: x['cabinet_number'])
                
                response_data["room_cabinets_info"] = {
                    'room_name': work_order.room,
                    'total_cabinets': len(all_cabinets_in_room),
                    'cabinets_in_work_order': len(work_order_cabinets),
                    'cabinets_not_in_work_order': len(all_cabinets_in_room) - len(work_order_cabinets),
                    'cabinets': cabinets_list
                }
            except Exception as e:
                logger.error(f"获取机柜详细信息失败: {str(e)}")
                # 失败时返回简化版本
                cabinets_set = set()
                for item in items:
                    location = item.operation_data.get("location_detail") if item.operation_data else None
                    if not location and item.asset:
                        location = item.asset.location_detail
                    
                    if location:
                        cabinet_match = location.replace("机柜", "").strip()
                        if cabinet_match:
                            cabinets_set.add(cabinet_match)
                
                response_data["cabinet_summary"] = {
                    "total_cabinets": len(cabinets_set),
                    "cabinet_list": sorted(list(cabinets_set)),
                    "note": "机柜详细信息获取失败"
                }
    
    # 如果是增配工单，添加增配特定字段
    if work_order.operation_type == "configuration":
        response_data.update({
            "parent_device_sn": work_order.parent_device_sn,
            "vendor_onsite": work_order.vendor_onsite,
            "parent_device_can_shutdown": work_order.parent_device_can_shutdown,
            "allowed_operation_start_time": work_order.allowed_operation_start_time.isoformat() if work_order.allowed_operation_start_time else None,
            "allowed_operation_end_time": work_order.allowed_operation_end_time.isoformat() if work_order.allowed_operation_end_time else None,
            "is_optical_module_upgrade": work_order.is_optical_module_upgrade,
            "is_project_upgrade": work_order.is_project_upgrade,
            "inbound_order_number": work_order.inbound_order_number,
            "outbound_order_number": work_order.outbound_order_number,
            "upgrade_order_number": work_order.upgrade_order_number,
        })
    
    # 如果是网络故障/变更配合工单，添加特定字段
    if work_order.operation_type == "network_issue_coordination":
        response_data.update({
            "priority": extra_data.get("priority"),
            "business_type": extra_data.get("business_type"),
            "operation_type_detail": extra_data.get("operation_type_detail"),
            "is_business_online": extra_data.get("is_business_online"),
            "service_content": extra_data.get("service_content"),
            "processing_result": extra_data.get("processing_result"),
            "accept_remark": extra_data.get("accept_remark"),
            "close_remark": work_order.description if work_order.status == 'completed' else None,
        })
        # 重命名devices字段以保持一致性
        response_data["devices"] = response_data.pop("items")
    
    # 如果是资产出入门工单，添加特定字段
    if work_order.operation_type == "asset_accounting":
        response_data.update({
            "priority": extra_data.get("priority"),
            "business_type": extra_data.get("business_type"),
            "device_sns": extra_data.get("device_sns", []),
            "service_content": extra_data.get("service_content"),
            "entry_exit_type": extra_data.get("entry_exit_type"),
            "entry_exit_scope": extra_data.get("entry_exit_scope"),
            "entry_exit_reason": extra_data.get("entry_exit_reason"),
            "entry_exit_date": extra_data.get("entry_exit_date"),
            "attachments": extra_data.get("attachments", []),
            "creator_name": extra_data.get("creator_name"),
            "updated_assets_count": extra_data.get("updated_assets_count"),
            "callback_remark": extra_data.get("callback_remark"),
        })
    
    return ApiResponse(
        code=0,
        message="查询成功",
        data=response_data
    )


# ==================== 上下电管理工单 ====================

class PowerManagementCreateRequest(BaseModel):
    """上下电管理工单创建请求"""
    # 核心标识
    work_order_number: str = Field(..., description="外部工单系统工单号")
    arrival_order_number: Optional[str] = Field(None, description="到货单号")
    source_order_number: Optional[str] = Field(None, description="来源单号/来源业务单号")
    
    # 业务信息
    title: str = Field(..., description="工单标题")
    description: Optional[str] = Field(None, description="工单描述/备注")
    
    # 状态管理
    status: str = Field("pending", description="内部状态: pending/processing/completed/cancelled")
    work_order_status: Optional[str] = Field("processing", description="外部工单系统状态: processing/completed/failed")
    
    # 人员信息
    creator: str = Field(..., description="创建人")
    operator: Optional[str] = Field(None, description="当前操作人/结束人")
    assignee: Optional[str] = Field(None, description="指派人")
    reviewer: Optional[str] = Field(None, description="审核人")
    
    # 位置信息
    datacenter: Optional[str] = Field(None, description="机房")
    campus: Optional[str] = Field(None, description="园区")
    room: Optional[str] = Field(None, description="房间")
    cabinet: Optional[str] = Field(None, description="机柜")
    rack_position: Optional[str] = Field(None, description="机位")
    
    # 项目信息
    project_number: Optional[str] = Field(None, description="项目编号")
    
    # 时间信息
    start_time: Optional[datetime] = Field(None, description="开始时间")
    expected_completion_time: Optional[datetime] = Field(None, description="期望完成时间")
    
    # 备注信息
    remark: Optional[str] = Field(None, description="备注")
    
    # 扩展信息
    priority: str = Field("normal", description="优先级: high/medium/low")
    operation_type_detail: Optional[str] = Field(None, description="操作类型明细")
    is_business_online: Optional[bool] = Field(None, description="业务是否在线")
    
    # 电源管理特定字段
    power_action: str = Field(..., description="电源操作: power_on/power_off")
    power_type: Optional[str] = Field(None, description="电源类型: AC/DC")
    power_reason: Optional[str] = Field(None, description="下电原因（仅下电时有值）")
    cabinet_count: Optional[int] = Field(None, description="涉及的机柜数量")


class CabinetSummary(BaseModel):
    """机柜统计信息"""
    total_cabinets: int = Field(..., description="机柜总数")
    cabinet_list: List[str] = Field(..., description="机柜编号列表")
    note: str = Field(..., description="提示信息")


class WorkOrderItemDetail(BaseModel):
    """工单设备明细"""
    id: int = Field(..., description="明细ID")
    asset_identifier: Optional[str] = Field(None, description="资产标识（序列号）")
    asset_tag: Optional[str] = Field(None, description="资产标签")
    asset_name: Optional[str] = Field(None, description="资产名称")
    status: Optional[str] = Field(None, description="处理状态")
    operation_data: Optional[dict] = Field(None, description="操作数据")
    operation_summary: Optional[str] = Field(None, description="操作摘要")
    result: Optional[str] = Field(None, description="处理结果")
    error_message: Optional[str] = Field(None, description="错误信息")


class PowerManagementDetailResponse(BaseModel):
    """上下电管理工单详情响应 - 包含40个字段"""
    
    # ===== 核心标识 (4个) =====
    batch_id: str = Field(..., description="内部批次号", example="POWER_20251205120000")
    work_order_number: str = Field(..., description="外部工单系统工单号", example="WO202512051234")
    arrival_order_number: Optional[str] = Field(None, description="到货单号", example="ARR202512051234")
    source_order_number: Optional[str] = Field(None, description="来源单号/来源业务单号", example="SRC202512051234")
    
    # ===== 业务信息 (3个) =====
    operation_type: str = Field(..., description="操作类型", example="power_management")
    title: str = Field(..., description="工单标题", example="A101房间设备上电")
    description: Optional[str] = Field(None, description="工单描述/备注", example="批量上电操作")
    
    # ===== 状态管理 (4个) =====
    status: str = Field(..., description="内部状态: pending/processing/completed/cancelled", example="processing")
    work_order_status: Optional[str] = Field(None, description="外部工单系统状态", example="处理中")
    is_timeout: bool = Field(..., description="是否超时", example=False)
    sla_countdown: Optional[int] = Field(None, description="SLA倒计时（秒）", example=3600)
    
    # ===== 人员信息 (4个) =====
    creator: str = Field(..., description="创建人", example="张三")
    operator: Optional[str] = Field(None, description="当前操作人/结束人", example="李四")
    assignee: Optional[str] = Field(None, description="指派人", example="李四")
    reviewer: Optional[str] = Field(None, description="审核人", example="王五")
    
    # ===== 位置信息 (5个) =====
    datacenter: Optional[str] = Field(None, description="机房", example="DC01")
    campus: Optional[str] = Field(None, description="园区", example="北京园区")
    room: Optional[str] = Field(None, description="房间", example="A101")
    cabinet: Optional[str] = Field(None, description="机柜", example="CAB-001")
    rack_position: Optional[str] = Field(None, description="机位", example="10-12U")
    
    # ===== 项目信息 (1个) =====
    project_number: Optional[str] = Field(None, description="项目编号", example="PROJ-2025-001")
    
    # ===== 时间信息 (6个) =====
    start_time: Optional[str] = Field(None, description="开始时间", example="2025-12-05T12:00:00")
    expected_completion_time: Optional[str] = Field(None, description="期望完成时间", example="2025-12-06T12:00:00")
    completed_time: Optional[str] = Field(None, description="实际完成时间", example="2025-12-06T10:30:00")
    close_time: Optional[str] = Field(None, description="结单时间/结束时间", example="2025-12-06T11:00:00")
    created_at: str = Field(..., description="创建时间", example="2025-12-05T12:00:00")
    updated_at: Optional[str] = Field(None, description="更新时间", example="2025-12-06T10:30:00")
    
    # ===== 统计信息 (2个) =====
    device_count: int = Field(..., description="设备数量", example=5)
    items_count: int = Field(..., description="明细数量", example=5)
    
    # ===== 备注信息 (1个) =====
    remark: Optional[str] = Field(None, description="备注", example="按照标准流程操作")
    
    # ===== 扩展信息 (4个) =====
    priority: Optional[str] = Field(None, description="优先级: high/medium/low", example="high")
    operation_type_detail: Optional[str] = Field(None, description="操作类型明细", example="紧急上电")
    is_business_online: Optional[bool] = Field(None, description="业务是否在线", example=True)
    failure_reason: Optional[str] = Field(None, description="失败原因", example=None)
    
    # ===== 电源管理特定字段 (5个) =====
    power_action: Optional[str] = Field(None, description="电源操作: power_on/power_off", example="power_on")
    power_type: Optional[str] = Field(None, description="电源类型: AC/DC", example="AC")
    power_reason: Optional[str] = Field(None, description="下电原因（仅下电时有值）", example="设备维护")
    cabinet_count: int = Field(..., description="涉及的机柜数量", example=3)
    cabinet_summary: Optional[CabinetSummary] = Field(None, description="机柜统计信息（轻量级）")
    
    # ===== 设备明细 (1个) =====
    items: List[WorkOrderItemDetail] = Field(..., description="设备明细列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "POWER_20251205120000",
                "work_order_number": "WO202512051234",
                "arrival_order_number": None,
                "source_order_number": "SRC202512051234",
                "operation_type": "power_management",
                "title": "A101房间设备上电",
                "description": "批量上电操作",
                "status": "processing",
                "work_order_status": "处理中",
                "is_timeout": False,
                "sla_countdown": 3600,
                "creator": "张三",
                "operator": "李四",
                "assignee": "李四",
                "reviewer": None,
                "datacenter": "DC01",
                "campus": "北京园区",
                "room": "A101",
                "cabinet": None,
                "rack_position": None,
                "project_number": None,
                "start_time": "2025-12-05T12:00:00",
                "expected_completion_time": "2025-12-06T12:00:00",
                "completed_time": None,
                "close_time": None,
                "created_at": "2025-12-05T12:00:00",
                "updated_at": "2025-12-05T12:30:00",
                "device_count": 5,
                "items_count": 5,
                "remark": "按照标准流程操作",
                "priority": "high",
                "operation_type_detail": "紧急上电",
                "is_business_online": True,
                "failure_reason": None,
                "power_action": "power_on",
                "power_type": "AC",
                "power_reason": None,
                "cabinet_count": 3,
                "cabinet_summary": {
                    "total_cabinets": 3,
                    "cabinet_list": ["A-01", "A-02", "A-03"],
                    "note": "如需查看完整的机柜详细信息（32个字段），请调用 GET /api/v1/work-orders/{work_order_id}/room-cabinets"
                },
                "items": []
            }
        }


@router.post(
    "/unified/power-management", 
    summary="创建上下电管理工单",
    responses={
        200: {
            "description": "工单创建成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "工单创建成功",
                        "data": {
                            "work_order_id": 123,
                            "work_order_number": "PM-TEST-20251209120000",
                            "batch_id": "POWER_20251209120000",
                            "status": "pending"
                        },
                        "timestamp": "2025-12-09T12:00:00"
                    }
                }
            }
        }
    }
)
async def create_power_management_work_order(
    request: PowerManagementCreateRequest,
    db: Session = Depends(get_db)
):
    """
    创建上下电管理工单
    
    ## 功能说明
    用于创建设备上电或下电的工单，支持批量设备的电源管理操作。
    
    ## 请求参数（完整40字段支持）
    ### 核心标识
    - **work_order_number**: 外部工单系统工单号（必填）
    - **arrival_order_number**: 到货单号
    - **source_order_number**: 来源单号/来源业务单号
    
    ### 业务信息
    - **title**: 工单标题（必填）
    - **description**: 工单描述/备注
    
    ### 人员信息
    - **creator**: 创建人（必填）
    - **operator**: 当前操作人/结束人
    - **assignee**: 指派人
    - **reviewer**: 审核人
    
    ### 位置信息
    - **datacenter**: 机房
    - **campus**: 园区
    - **room**: 房间
    - **cabinet**: 机柜
    - **rack_position**: 机位
    
    ### 电源管理特定字段
    - **power_action**: 电源操作 power_on/power_off（必填）
    - **power_type**: 电源类型 AC/DC
    - **power_reason**: 下电原因（仅下电时有值）
    - **cabinet_count**: 涉及的机柜数量
    
    ## 返回数据
    返回创建的工单ID和基本信息
    """
    try:
        # 验证必填字段
        if request.power_action not in ["power_on", "power_off"]:
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message="power_action 必须是 power_on 或 power_off",
                data=None
            )
        
        # 生成batch_id
        batch_id = f"POWER_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 创建工单基础记录
        work_order = WorkOrder(
            batch_id=batch_id,
            work_order_number=request.work_order_number,
            arrival_order_number=request.arrival_order_number,
            source_order_number=request.source_order_number,
            operation_type="power_management",
            title=request.title,
            description=request.description,
            status=request.status,
            work_order_status=request.work_order_status,
            creator=request.creator,
            operator=request.operator,
            assignee=request.assignee,
            reviewer=request.reviewer,
            datacenter=request.datacenter,
            campus=request.campus,
            room=request.room,
            cabinet=request.cabinet,
            rack_position=request.rack_position,
            project_number=request.project_number,
            start_time=request.start_time,
            expected_completion_time=request.expected_completion_time,
            remark=request.remark,
            device_count=0,  # 初始为0，后续添加设备时更新
            cabinet_count=request.cabinet_count or 0,
            extra={
                "priority": request.priority,
                "operation_type_detail": request.operation_type_detail,
                "is_business_online": request.is_business_online,
                "power_action": request.power_action,
                "power_type": request.power_type,
                "power_reason": request.power_reason,
            }
        )
        
        db.add(work_order)
        db.commit()
        db.refresh(work_order)
        
        logger.info(f"上下电管理工单创建成功: {work_order.id}, 工单号: {request.work_order_number}, batch_id: {batch_id}")
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="工单创建成功",
            data={
                "work_order_id": work_order.id,
                "work_order_number": work_order.work_order_number,
                "batch_id": work_order.batch_id,
                "status": work_order.status
            }
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"创建上下电管理工单失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"创建工单失败: {str(e)}",
            data=None
        )


@router.get(
    "/unified/power-management/{work_order_id}", 
    summary="获取上下电管理工单详情",
    responses={
        200: {
            "description": "查询成功，返回完整的40个字段",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "查询成功",
                        "data": {
                            # ===== 核心标识 (4个) =====
                            "batch_id": "POWER_20251205120000",
                            "work_order_number": "WO202512051234",
                            "arrival_order_number": "ARR202512051234",
                            "source_order_number": "SRC202512051234",
                            
                            # ===== 业务信息 (3个) =====
                            "operation_type": "power_management",
                            "title": "A101房间设备上电",
                            "description": "批量上电操作",
                            
                            # ===== 状态管理 (4个) =====
                            "status": "processing",
                            "work_order_status": "处理中",
                            "is_timeout": False,
                            "sla_countdown": 3600,
                            
                            # ===== 人员信息 (4个) =====
                            "creator": "张三",
                            "operator": "李四",
                            "assignee": "李四",
                            "reviewer": "王五",
                            
                            # ===== 位置信息 (5个) =====
                            "datacenter": "DC01",
                            "campus": "北京园区",
                            "room": "A101",
                            "cabinet": "CAB-001",
                            "rack_position": "10-12U",
                            
                            # ===== 项目信息 (1个) =====
                            "project_number": "PROJ-2025-001",
                            
                            # ===== 时间信息 (6个) =====
                            "start_time": "2025-12-05T12:00:00",
                            "expected_completion_time": "2025-12-06T12:00:00",
                            "completed_time": "2025-12-06T10:30:00",
                            "close_time": "2025-12-06T11:00:00",
                            "created_at": "2025-12-05T12:00:00",
                            "updated_at": "2025-12-05T12:30:00",
                            
                            # ===== 统计信息 (2个) =====
                            "device_count": 5,
                            "items_count": 5,
                            
                            # ===== 备注信息 (1个) =====
                            "remark": "按照标准流程操作",
                            
                            # ===== 扩展信息 (4个) =====
                            "priority": "high",
                            "operation_type_detail": "紧急上电",
                            "is_business_online": True,
                            "failure_reason": None,
                            
                            # ===== 电源管理特定字段 (5个) =====
                            "power_action": "power_on",
                            "power_type": "AC",
                            "power_reason": None,
                            "cabinet_count": 3,
                            "cabinet_summary": {
                                "total_cabinets": 3,
                                "cabinet_list": ["A-01", "A-02", "A-03"],
                                "note": "如需查看完整的机柜详细信息（32个字段），请调用 GET /api/v1/work-orders/{work_order_id}/room-cabinets"
                            },
                            
                            # ===== 设备明细 (1个) =====
                            "items": [
                                {
                                    "id": 1,
                                    "asset_identifier": "SN123456",
                                    "asset_tag": "DEV001",
                                    "asset_name": "Dell服务器R740",
                                    "status": "completed",
                                    "operation_data": {"location_detail": "机柜A-01"},
                                    "operation_summary": "位置: 机柜A-01",
                                    "result": "上电成功",
                                    "error_message": None
                                }
                            ]
                        },
                        "timestamp": "2025-12-05T12:30:00"
                    }
                }
            }
        }
    }
)
async def get_power_management_work_order(
    work_order_id: int = Path(..., description="工单ID"),
    db: Session = Depends(get_db)
):
    """
    获取上下电管理工单详情（完整40字段）
    
    ## 功能说明
    根据工单ID查询上下电管理工单的完整信息，返回所有40个字段。
    
    ## 路径参数
    - **work_order_id**: 工单ID
    
    ## 返回数据（40个字段）
    ### 通用字段（35个）
    - 核心标识：batch_id, work_order_number, arrival_order_number, source_order_number
    - 业务信息：operation_type, title, description
    - 状态管理：status, work_order_status, is_timeout, sla_countdown
    - 人员信息：creator, operator, assignee, reviewer
    - 位置信息：datacenter, campus, room, cabinet, rack_position
    - 项目信息：project_number
    - 时间信息：start_time, expected_completion_time, completed_time, close_time, created_at, updated_at
    - 统计信息：device_count, items_count
    - 备注信息：remark
    - 扩展信息：priority, operation_type_detail, is_business_online, failure_reason
    - 设备明细：items
    
    ### 电源管理特定字段（5个）
    - power_action：电源操作
    - power_type：电源类型
    - power_reason：下电原因
    - cabinet_count：涉及的机柜数量
    - cabinet_summary：机柜统计信息
    """
    try:
        # 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.id == work_order_id,
            WorkOrder.operation_type == "power_management"
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"工单不存在: {work_order_id}",
                data=None
            )
        
        # 查询工单明细
        items = db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == work_order.id
        ).all()
        
        items_data = []
        cabinets_set = set()
        for item in items:
            asset = item.asset
            items_data.append({
                "id": item.id,
                "asset_identifier": asset.serial_number if asset else None,
                "asset_tag": asset.asset_tag if asset else None,
                "asset_name": asset.name if asset else None,
                "status": item.status,
                "operation_data": item.operation_data,
                "operation_summary": get_operation_summary(work_order.operation_type, item.operation_data),
                "result": item.result,
                "error_message": item.error_message
            })
            
            # 提取机柜信息
            if item.operation_data:
                location = item.operation_data.get("location_detail")
                if location:
                    cabinet_match = location.replace("机柜", "").strip()
                    if cabinet_match:
                        cabinets_set.add(cabinet_match)
        
        # 从 extra 中提取扩展字段
        extra = work_order.extra or {}
        
        # 计算SLA倒计时
        sla_countdown = calculate_sla_countdown(work_order)
        
        # 构建完整的40字段响应数据
        response_data = {
            # ===== 核心标识 (4个) =====
            "batch_id": work_order.batch_id,
            "work_order_number": work_order.work_order_number,
            "arrival_order_number": work_order.arrival_order_number,
            "source_order_number": work_order.source_order_number,
            
            # ===== 业务信息 (3个) =====
            "operation_type": work_order.operation_type,
            "title": work_order.title,
            "description": work_order.description,
            
            # ===== 状态管理 (4个) =====
            "status": work_order.status,
            "work_order_status": work_order.work_order_status,
            "is_timeout": work_order.is_timeout or False,
            "sla_countdown": sla_countdown,
            
            # ===== 人员信息 (4个) =====
            "creator": work_order.creator,
            "operator": work_order.operator,
            "assignee": work_order.assignee,
            "reviewer": work_order.reviewer,
            
            # ===== 位置信息 (5个) =====
            "datacenter": work_order.datacenter,
            "campus": work_order.campus,
            "room": work_order.room,
            "cabinet": work_order.cabinet,
            "rack_position": work_order.rack_position,
            
            # ===== 项目信息 (1个) =====
            "project_number": work_order.project_number,
            
            # ===== 时间信息 (6个) =====
            "start_time": work_order.start_time.isoformat() if work_order.start_time else None,
            "expected_completion_time": work_order.expected_completion_time.isoformat() if work_order.expected_completion_time else None,
            "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
            "close_time": work_order.close_time.isoformat() if work_order.close_time else None,
            "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
            "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None,
            
            # ===== 统计信息 (2个) =====
            "device_count": work_order.device_count or 0,
            "items_count": len(items_data),
            
            # ===== 备注信息 (1个) =====
            "remark": work_order.remark,
            
            # ===== 扩展信息 (4个) =====
            "priority": extra.get("priority"),
            "operation_type_detail": extra.get("operation_type_detail"),
            "is_business_online": extra.get("is_business_online"),
            "failure_reason": extra.get("failure_reason"),
            
            # ===== 电源管理特定字段 (5个) =====
            "power_action": extra.get("power_action"),
            "power_type": extra.get("power_type"),
            "power_reason": extra.get("power_reason"),
            "cabinet_count": work_order.cabinet_count or 0,
            "cabinet_summary": {
                "total_cabinets": len(cabinets_set),
                "cabinet_list": sorted(list(cabinets_set)),
                "note": "如需查看完整的机柜详细信息（32个字段），请调用 GET /api/v1/work-orders/{work_order_id}/room-cabinets"
            } if cabinets_set else None,
            
            # ===== 设备明细 (1个) =====
            "items": items_data
        }
        
        logger.info(f"查询上下电管理工单成功: {work_order_id}, 返回40个字段")
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="查询成功",
            data=response_data
        )
        
    except Exception as e:
        logger.error(f"查询上下电管理工单失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询工单失败: {str(e)}",
            data=None
        )


@router.patch("/{batch_id}", summary="更新工单信息",
              response_model=ApiResponse,
              responses={
                  200: {"description": "更新成功"},
                  404: {"description": "工单不存在"},
                  500: {"description": "服务器内部错误"}
              })
async def update_work_order(
    batch_id: str = Path(..., description="批次ID"),
    attachments: Optional[List[str]] = Body(None, description="附件URL列表（图片链接）"),
    remark: Optional[str] = Body(None, description="备注"),
    description: Optional[str] = Body(None, description="描述"),
    db: Session = Depends(get_db)
):
    """
    更新工单信息
    
    ## 功能说明
    更新工单的附件、备注、描述等信息。主要用于上传附件（图片）。
    
    ## 路径参数
    - **batch_id**: 批次ID
    
    ## 请求体参数（可选）
    - **attachments**: 附件URL列表，存储图片链接
    - **remark**: 备注
    - **description**: 描述
    
    ## 使用场景
    1. 上传工单附件（图片）
    2. 更新工单备注
    3. 补充工单描述
    
    ## 请求示例
    ```json
    {
      "attachments": [
        "https://example.com/image1.jpg",
        "https://example.com/image2.jpg"
      ],
      "remark": "已上传现场照片"
    }
    ```
    
    ## 返回示例
    ```json
    {
      "code": 0,
      "message": "更新成功",
      "data": {
        "batch_id": "PWR20251209120000",
        "attachments": ["https://example.com/image1.jpg"],
        "updated_at": "2025-12-09T15:30:00"
      }
    }
    ```
    """
    try:
        # 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.batch_id == batch_id
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"工单不存在: {batch_id}",
                data=None
            )
        
        # 更新字段
        updated = False
        
        if attachments is not None:
            # 将附件保存到extra字段
            if work_order.extra is None:
                work_order.extra = {}
            work_order.extra['attachments'] = attachments
            updated = True
        
        if remark is not None:
            work_order.remark = remark
            updated = True
        
        if description is not None:
            work_order.description = description
            updated = True
        
        if updated:
            work_order.updated_at = datetime.now()
            db.commit()
            db.refresh(work_order)
        
        return ApiResponse(
            code=0,
            message="更新成功",
            data={
                "batch_id": work_order.batch_id,
                "attachments": work_order.extra.get('attachments') if work_order.extra else None,
                "remark": work_order.remark,
                "description": work_order.description,
                "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None
            }
        )
        
    except Exception as e:
        logger.error(f"更新工单失败: {str(e)}")
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"更新工单失败: {str(e)}",
            data=None
        )



@router.get("/room/{room_name}/cabinets", summary="查询机房的机柜信息",
            response_model=ApiResponse,
            responses={
                200: {"description": "查询成功"},
                404: {"description": "机房不存在"},
                500: {"description": "服务器内部错误"}
            })
async def get_room_cabinets(
    room_name: str = Path(..., description="机房名称"),
    db: Session = Depends(get_db)
):
    """
    查询指定机房包含的所有机柜信息
    
    ## 功能说明
    根据机房名称查询该机房内所有机柜的详细信息，包括机柜编号、位置、容量等。
    
    ## 路径参数
    - **room_name**: 机房名称（如：A101, B201等）
    
    ## 返回字段
    - **room**: 机房名称
    - **datacenter**: 数据中心
    - **cabinet_count**: 机柜总数
    - **cabinets**: 机柜列表
      - **cabinet_number**: 机柜编号
      - **cabinet_name**: 机柜名称
      - **location**: 位置描述
      - **total_u**: 总U位数
      - **used_u**: 已使用U位数
      - **available_u**: 可用U位数
      - **device_count**: 设备数量
      - **power_status**: 电源状态
    
    ## 使用场景
    1. 上下电工单创建时，查看机房包含哪些机柜
    2. 机房容量规划
    3. 设备上架前查看可用机柜
    
    ## 请求示例
    ```
    GET /api/v1/work-orders/room/A101/cabinets
    ```
    
    ## 返回示例
    ```json
    {
      "code": 0,
      "message": "查询成功",
      "data": {
        "room": "A101",
        "datacenter": "DC01",
        "cabinet_count": 3,
        "cabinets": [
          {
            "cabinet_number": "CAB-001",
            "cabinet_name": "机柜A-01",
            "location": "A区第1排",
            "total_u": 42,
            "used_u": 20,
            "available_u": 22,
            "device_count": 5,
            "power_status": "on"
          }
        ]
      }
    }
    ```
    """
    try:
        # 查询机房信息
        room = db.query(Room).filter(
            Room.room_abbreviation == room_name
        ).first()
        
        if not room:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"机房不存在: {room_name}",
                data=None
            )
        
        # 查询该机房的所有设备，提取机柜信息
        assets = db.query(Asset).filter(
            Asset.room_id == room.id,
            Asset.location_detail.isnot(None)
        ).all()
        
        # 统计机柜信息
        cabinets_dict = {}
        
        for asset in assets:
            if not asset.location_detail:
                continue
            
            # 从location_detail中提取机柜编号
            # 支持格式：CAB-001 U10-U12, 机柜A-01 U5-U7
            import re
            cabinet_match = re.search(r'([A-Z0-9\-]+(?:机柜)?[A-Z0-9\-]*)\s*U?(\d+)', asset.location_detail)
            
            if cabinet_match:
                cabinet_number = cabinet_match.group(1).replace('机柜', '').strip()
                
                if cabinet_number not in cabinets_dict:
                    cabinets_dict[cabinet_number] = {
                        'cabinet_number': cabinet_number,
                        'cabinet_name': f"机柜{cabinet_number}",
                        'location': f"{room_name}",
                        'total_u': 42,  # 默认42U
                        'used_u': 0,
                        'available_u': 42,
                        'device_count': 0,
                        'devices': [],
                        'power_status': 'unknown'
                    }
                
                cabinets_dict[cabinet_number]['device_count'] += 1
                cabinets_dict[cabinet_number]['devices'].append({
                    'serial_number': asset.serial_number,
                    'name': asset.name,
                    'u_position': cabinet_match.group(2) if len(cabinet_match.groups()) > 1 else None
                })
        
        # 转换为列表
        cabinets_list = list(cabinets_dict.values())
        
        # 按机柜编号排序
        cabinets_list.sort(key=lambda x: x['cabinet_number'])
        
        return ApiResponse(
            code=0,
            message="查询成功",
            data={
                "room": room_name,
                "room_full_name": room.room_full_name,
                "datacenter": room.datacenter if hasattr(room, 'datacenter') else None,
                "cabinet_count": len(cabinets_list),
                "cabinets": cabinets_list
            }
        )
        
    except Exception as e:
        logger.error(f"查询机房机柜信息失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )



# =====================================================
# 上架工单设备位置修改接口
# =====================================================

class RackingLocationUpdate(BaseModel):
    """上架工单设备位置更新请求"""
    target_room: Optional[str] = Field(None, description="目标机房名称")
    target_cabinet: Optional[str] = Field(None, description="目标机柜编号")
    target_rack_position: Optional[str] = Field(None, description="目标机位（U位），如'10-12'")


@router.put(
    "/racking/{work_order_number}/items/{item_id}/location",
    summary="修改上架工单设备的目标位置",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "修改成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "位置信息更新成功",
                        "data": {
                            "item_id": 68,
                            "serial_number": "SN123456",
                            "updated_fields": ["target_room", "target_cabinet", "target_rack_position"],
                            "target_room": "A102",
                            "target_cabinet": "CAB-002",
                            "target_rack_position": "15-17"
                        }
                    }
                }
            }
        },
        400: {
            "description": "参数错误或工单类型不正确",
            "content": {
                "application/json": {
                    "example": {
                        "code": 400,
                        "message": "此接口仅支持上架工单(racking)",
                        "data": None
                    }
                }
            }
        },
        404: {
            "description": "工单或设备明细不存在",
            "content": {
                "application/json": {
                    "example": {
                        "code": 404,
                        "message": "未找到工单号为 WO123456 的工单",
                        "data": None
                    }
                }
            }
        },
        500: {"description": "服务器内部错误"}
    }
)
async def update_racking_item_location(
    work_order_number: str = Path(..., description="工单号", example="deviceLaunch1765351230060"),
    item_id: int = Path(..., description="工单明细ID", example=68),
    location_data: RackingLocationUpdate = Body(..., description="位置更新数据"),
    db: Session = Depends(get_db)
):
    """
    修改上架工单设备的目标位置信息
    
    ## 功能说明
    允许人工修改上架工单中某个设备的目标机房、目标机柜、目标机位信息。
    仅支持上架工单(operation_type=racking)，其他类型工单不允许使用此接口。
    
    ## 路径参数
    - **work_order_number**: 工单号（必填）
    - **item_id**: 工单明细ID（必填）
    
    ## 请求体参数
    - **target_room**: 目标机房名称（可选），如"A101"、"301"
    - **target_cabinet**: 目标机柜编号（可选），如"CAB-001"、"A-01"
    - **target_rack_position**: 目标机位/U位（可选），如"10-12"、"1-3"
    
    ## 注意事项
    1. 仅支持上架工单(racking)，其他类型工单会返回400错误
    2. 只能修改目标机房、目标机柜、目标机位，其他字段不允许修改
    3. 可以只修改部分字段，未传的字段保持原值
    4. 修改会同时更新工单明细的operation_data字段
    5. 工单已完成(completed)或已取消(cancelled)后不允许修改
    
    ## 使用场景
    1. 上架前发现原定位置不合适，需要调整
    2. 机柜空间不足，需要更换目标机柜
    3. 现场实际情况与计划不符，需要修正
    """
    try:
        # 1. 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.work_order_number == work_order_number
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到工单号为 {work_order_number} 的工单",
                data=None
            )
        
        # 2. 验证工单类型
        if work_order.operation_type != "racking":
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message=f"此接口仅支持上架工单(racking)，当前工单类型为: {work_order.operation_type}",
                data=None
            )
        
        # 3. 验证工单状态
        if work_order.status in ["completed", "cancelled"]:
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message=f"工单已{work_order.status}，不允许修改",
                data=None
            )
        
        # 4. 查询工单明细
        work_order_item = db.query(WorkOrderItem).filter(
            WorkOrderItem.id == item_id,
            WorkOrderItem.work_order_id == work_order.id
        ).first()
        
        if not work_order_item:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到ID为 {item_id} 的工单明细",
                data=None
            )
        
        # 5. 更新位置信息
        operation_data = work_order_item.operation_data or {}
        updated_fields = []
        
        if location_data.target_room is not None:
            operation_data["room_name"] = location_data.target_room
            operation_data["target_room_name"] = location_data.target_room
            work_order_item.item_room = location_data.target_room
            updated_fields.append("target_room")
        
        if location_data.target_cabinet is not None:
            operation_data["cabinet_number"] = location_data.target_cabinet
            operation_data["target_cabinet"] = location_data.target_cabinet
            work_order_item.item_cabinet = location_data.target_cabinet
            updated_fields.append("target_cabinet")
        
        if location_data.target_rack_position is not None:
            operation_data["u_position"] = location_data.target_rack_position
            operation_data["rack_position"] = location_data.target_rack_position
            operation_data["target_rack_position"] = location_data.target_rack_position
            # 解析U位起止
            import re
            u_match = re.match(r'(\d+)[-~](\d+)', location_data.target_rack_position)
            if u_match:
                operation_data["u_position_start"] = int(u_match.group(1))
                operation_data["u_position_end"] = int(u_match.group(2))
                operation_data["u_count"] = int(u_match.group(2)) - int(u_match.group(1)) + 1
            work_order_item.item_rack_position = location_data.target_rack_position
            updated_fields.append("target_rack_position")
        
        if not updated_fields:
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message="未提供任何需要更新的字段",
                data=None
            )
        
        # 6. 保存更新
        work_order_item.operation_data = operation_data
        # 标记JSON字段已修改，确保SQLAlchemy能检测到变化
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(work_order_item, "operation_data")
        db.commit()
        db.refresh(work_order_item)
        
        # 7. 记录日志
        logger.info(f"上架工单设备位置更新", extra={
            "operationObject": work_order_number,
            "operationType": "racking.location_update",
            "operator": "system",
            "result": "success",
            "operationDetail": f"设备 {work_order_item.asset_sn} 位置更新: {', '.join(updated_fields)}"
        })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="位置信息更新成功",
            data={
                "item_id": item_id,
                "serial_number": work_order_item.asset_sn,
                "updated_fields": updated_fields,
                "target_room": operation_data.get("room_name") or operation_data.get("target_room_name"),
                "target_cabinet": operation_data.get("cabinet_number") or operation_data.get("target_cabinet"),
                "target_rack_position": operation_data.get("u_position") or operation_data.get("rack_position")
            }
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"更新上架工单设备位置失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"更新失败: {str(e)}",
            data=None
        )


# =====================================================
# 上架工单设备上下联设备管理接口
# =====================================================

class ConnectedDevice(BaseModel):
    """上下联设备信息"""
    sn: str = Field(..., description="设备序列号")
    is_company_device: bool = Field(..., description="是否本公司设备")
    device_type: str = Field(..., description="设备属性：upstream-上联, downstream-下联")


class ConnectedDevicesUpdate(BaseModel):
    """上下联设备更新请求"""
    connected_devices: List[ConnectedDevice] = Field(..., description="上下联设备列表")


@router.put(
    "/racking/{work_order_number}/connected-devices",
    summary="更新上架工单的上下联设备信息",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "更新成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "上下联设备信息更新成功",
                        "data": {
                            "work_order_number": "RACK20251211153644",
                            "connected_devices": [
                                {"sn": "SW-001", "is_company_device": True, "device_type": "upstream"},
                                {"sn": "SRV-002", "is_company_device": False, "device_type": "downstream"}
                            ]
                        }
                    }
                }
            }
        },
        400: {"description": "参数错误或工单类型不支持"},
        404: {"description": "工单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def update_racking_connected_devices(
    work_order_number: str = Path(..., description="工单号"),
    update_data: ConnectedDevicesUpdate = Body(..., description="上下联设备信息"),
    db: Session = Depends(get_db)
):
    """
    更新上架工单的上下联设备信息
    
    允许审核人在上架工单审核时添加或修改上下联设备信息。
    上下联设备信息绑定到整个工单，不绑定到具体设备。
    仅支持上架工单(operation_type=racking)，其他类型工单不允许使用此接口。
    
    ## 路径参数
    - **work_order_number**: 工单号（必填）
    
    ## 请求体参数
    - **connected_devices**: 上下联设备列表（必填）
      - **sn**: 设备序列号（必填）
      - **is_company_device**: 是否本公司设备（必填，布尔值）
      - **device_type**: 设备属性（必填），upstream-上联, downstream-下联
    
    ## 注意事项
    1. 仅支持上架工单(racking)，其他类型工单会返回400错误
    2. device_type为upstream表示上联设备（如交换机、路由器）
    3. device_type为downstream表示下联设备（如服务器、存储）
    4. 传空数组[]表示清空所有上下联设备
    
    ## 使用场景
    1. 审核人在审核上架工单时添加上下联信息
    2. 记录设备的物理连接拓扑
    """
    try:
        # 1. 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.work_order_number == work_order_number
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到工单号为 {work_order_number} 的工单",
                data=None
            )
        
        # 2. 验证工单类型
        if work_order.operation_type != "racking":
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message=f"此接口仅支持上架工单，当前工单类型为: {work_order.operation_type}",
                data=None
            )
        
        # 3. 更新工单extra字段中的上下联设备信息
        extra_data = work_order.extra or {}
        
        # 直接存储为列表
        connected_devices = [device.model_dump() for device in update_data.connected_devices]
        
        extra_data["connected_devices"] = connected_devices
        work_order.extra = extra_data
        
        db.commit()
        db.refresh(work_order)
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="上下联设备信息更新成功",
            data={
                "work_order_number": work_order_number,
                "connected_devices": connected_devices
            }
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"更新上架工单上下联信息失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"更新失败: {str(e)}",
            data=None
        )


@router.get(
    "/racking/{work_order_number}/connected-devices",
    summary="查询上架工单的上下联设备信息",
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
                            "work_order_number": "RACK20251211153644",
                            "connected_devices": [
                                {"sn": "SW-001", "is_company_device": True, "device_type": "upstream"},
                                {"sn": "SRV-002", "is_company_device": False, "device_type": "downstream"}
                            ]
                        }
                    }
                }
            }
        },
        404: {"description": "工单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_racking_connected_devices(
    work_order_number: str = Path(..., description="工单号"),
    db: Session = Depends(get_db)
):
    """
    查询上架工单的上下联设备信息
    
    ## 路径参数
    - **work_order_number**: 工单号（必填）
    
    ## 返回字段
    - **work_order_number**: 工单号
    - **connected_devices**: 上下联设备列表
      - **sn**: 设备序列号
      - **is_company_device**: 是否本公司设备
      - **device_type**: 设备属性（upstream-上联, downstream-下联）
    """
    try:
        # 1. 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.work_order_number == work_order_number
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到工单号为 {work_order_number} 的工单",
                data=None
            )
        
        # 2. 获取上下联设备信息
        extra_data = work_order.extra or {}
        connected_devices = extra_data.get("connected_devices", [])
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="查询成功",
            data={
                "work_order_number": work_order_number,
                "connected_devices": connected_devices
            }
        )
        
    except Exception as e:
        logger.error(f"查询上架工单上下联信息失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.delete(
    "/racking/{work_order_number}/connected-devices",
    summary="删除上架工单的上下联设备信息",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "删除成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "上下联设备信息已清空",
                        "data": {
                            "work_order_number": "RACK20251211153644"
                        }
                    }
                }
            }
        },
        400: {"description": "参数错误或工单类型不支持"},
        404: {"description": "工单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def delete_racking_connected_devices(
    work_order_number: str = Path(..., description="工单号"),
    db: Session = Depends(get_db)
):
    """
    删除上架工单的上下联设备信息
    
    清空该工单的所有上下联设备信息。
    仅支持上架工单(operation_type=racking)。
    
    ## 路径参数
    - **work_order_number**: 工单号（必填）
    """
    try:
        # 1. 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.work_order_number == work_order_number
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到工单号为 {work_order_number} 的工单",
                data=None
            )
        
        # 2. 验证工单类型
        if work_order.operation_type != "racking":
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message=f"此接口仅支持上架工单，当前工单类型为: {work_order.operation_type}",
                data=None
            )
        
        # 3. 清空上下联设备信息
        extra_data = work_order.extra or {}
        extra_data["connected_devices"] = []
        work_order.extra = extra_data
        
        db.commit()
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="上下联设备信息已清空",
            data={
                "work_order_number": work_order_number
            }
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"删除上架工单上下联信息失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"删除失败: {str(e)}",
            data=None
        )


@router.delete(
    "/racking/{work_order_number}/connected-devices/{device_sn}",
    summary="删除上架工单的单个上下联设备",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "删除成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "上下联设备删除成功",
                        "data": {
                            "work_order_number": "RACK20251211153644",
                            "deleted_sn": "SW-001",
                            "remaining_devices": [
                                {"sn": "SRV-002", "is_company_device": False, "device_type": "downstream"}
                            ]
                        }
                    }
                }
            }
        },
        400: {"description": "参数错误或工单类型不支持"},
        404: {"description": "工单不存在或设备不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def delete_racking_single_connected_device(
    work_order_number: str = Path(..., description="工单号"),
    device_sn: str = Path(..., description="要删除的设备序列号"),
    db: Session = Depends(get_db)
):
    """
    删除上架工单的单个上下联设备
    
    根据设备SN删除指定的上下联设备。
    仅支持上架工单(operation_type=racking)。
    
    ## 路径参数
    - **work_order_number**: 工单号（必填）
    - **device_sn**: 要删除的设备序列号（必填）
    """
    try:
        # 1. 查询工单
        work_order = db.query(WorkOrder).filter(
            WorkOrder.work_order_number == work_order_number
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到工单号为 {work_order_number} 的工单",
                data=None
            )
        
        # 2. 验证工单类型
        if work_order.operation_type != "racking":
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message=f"此接口仅支持上架工单，当前工单类型为: {work_order.operation_type}",
                data=None
            )
        
        # 3. 获取当前上下联设备列表
        extra_data = work_order.extra or {}
        connected_devices = extra_data.get("connected_devices", [])
        
        # 4. 查找并删除指定设备
        device_found = False
        new_devices = []
        for device in connected_devices:
            if device.get("sn") == device_sn:
                device_found = True
            else:
                new_devices.append(device)
        
        if not device_found:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到序列号为 {device_sn} 的上下联设备",
                data=None
            )
        
        # 5. 更新工单
        extra_data["connected_devices"] = new_devices
        work_order.extra = extra_data
        
        db.commit()
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="上下联设备删除成功",
            data={
                "work_order_number": work_order_number,
                "deleted_sn": device_sn,
                "remaining_devices": new_devices
            }
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"删除单个上下联设备失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"删除失败: {str(e)}",
            data=None
        )
