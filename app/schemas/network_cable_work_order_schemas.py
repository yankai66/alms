"""
服务器网线/光纤更换工单 - Pydantic Schemas
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum

from app.schemas.asset_schemas import BaseSchema, ApiResponse, ResponseCode


# =====================================================
# 枚举定义
# =====================================================

class OperationTypeEnum(str, Enum):
    """操作类型枚举"""
    PRODUCTION_NETWORK = "生产网线"
    OUT_OF_BAND_NETWORK = "带外网线"
    # 支持英文值
    PRODUCTION = "production_network"
    OUT_OF_BAND = "out_of_band_network"


class UrgencyLevelEnum(str, Enum):
    """紧急程度枚举"""
    GENERAL = "一般"
    URGENT = "紧急"
    # 支持英文值
    NORMAL = "normal"
    URGENT_EN = "urgent"


class PriorityLevelEnum(str, Enum):
    """优先级枚举"""
    GENERAL = "normal"
    URGENT = "urgent"


# =====================================================
# 工单创建 Schemas
# =====================================================

class NetworkCableWorkOrderCreate(BaseSchema):
    """创建服务器网线/光纤更换工单请求"""
    operation_type: OperationTypeEnum = Field(..., description="操作类型：生产网线/带外网线")
    title: str = Field(..., max_length=200, description="工单标题")
    allowed_start_time: datetime = Field(..., description="允许操作开始时间（年月日）")
    allowed_end_time: datetime = Field(..., description="允许操作结束时间（年月日）")
    urgency_level: UrgencyLevelEnum = Field(..., description="紧急程度：一般/紧急")
    remarks: Optional[str] = Field(None, max_length=140, description="备注（可选，最多140字）")
    assignee: str = Field(..., max_length=100, description="指派人（必填）")
    device_info: Optional[Any] = Field(None, description="设备信息（可选，支持字典或数组格式）")
    creator_name: Optional[str] = Field(None, max_length=100, description="创建人姓名（可选，默认使用系统用户）")
    
    @validator('remarks')
    def validate_remarks_length(cls, v):
        """验证备注长度"""
        if v is not None and len(v) > 140:
            raise ValueError('备注最多可输入140字')
        return v
    
    @validator('allowed_end_time')
    def validate_time_range(cls, v, values):
        """验证时间范围"""
        if 'allowed_start_time' in values:
            start_time = values['allowed_start_time']
            if v < start_time:
                raise ValueError('结束时间必须晚于开始时间')
        return v


class NetworkCableWorkOrderResponse(BaseSchema):
    """服务器网线/光纤更换工单响应"""
    work_order_number: Optional[str] = Field(None, description="工单号")
    operation_type: str = Field(..., description="操作类型")
    title: str = Field(..., description="工单标题")
    allowed_start_time: datetime = Field(..., description="允许操作开始时间")
    allowed_end_time: datetime = Field(..., description="允许操作结束时间")
    urgency_level: str = Field(..., description="紧急程度")
    remarks: Optional[str] = Field(None, description="备注")


class DeviceInfoQueryParams(BaseSchema):
    """设备信息查询参数"""
    asset_tag: Optional[str] = Field(None, description="资产标签")
    serial_number: Optional[str] = Field(None, description="序列号")
    name: Optional[str] = Field(None, description="设备名称")
    room_id: Optional[int] = Field(None, description="房间ID")
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(10, ge=1, le=100, description="每页数量")


class DevicePortUpdate(BaseSchema):
    """更新设备端口信息请求"""
    serial_number: str = Field(..., description="设备序列号（必填）")
    network_port: str = Field(..., max_length=100, description="端口信息（必填）")


# =====================================================
# 手工U盘装机 Schemas
# =====================================================

class ManualUsbInstallCreate(BaseSchema):
    """手工U盘装机单创建请求"""
    title: str = Field(..., max_length=200, description="标题（必填）")
    project_requirement: str = Field(..., max_length=500, description="项目需求（必填）")
    device_sn_text: str = Field(..., description="设备SN，支持批量输入，空格/换行分隔")
    datacenter: Optional[str] = Field(None, max_length=50, description="机房（可选）")
    room: Optional[str] = Field(None, max_length=50, description="房间（可选）")
    os_template: Optional[str] = Field(None, max_length=200, description="OS模板（可选）")
    priority: PriorityLevelEnum = Field(..., description="优先级：normal(一般)/urgent(紧急)")
    source_order_number: Optional[str] = Field(None, max_length=100, description="来源单号（可选）")
    operation_type_detail: Optional[str] = Field(None, max_length=100, description="操作类型（可选）")
    is_business_online: Optional[bool] = Field(None, description="业务是否在线（可选）")
    remarks: Optional[str] = Field(None, max_length=200, description="备注（可选）")
    assignee: str = Field(..., max_length=100, description="指派人（必填）")
    creator_name: Optional[str] = Field(None, max_length=100, description="创建人姓名（可选，默认system）")

    @validator('device_sn_text')
    def validate_device_sn_text(cls, v: str):
        if not v or not v.strip():
            raise ValueError("设备SN不能为空")
        sn_list = [sn.strip() for sn in v.replace("\n", " ").split(" ") if sn.strip()]
        if not sn_list:
            raise ValueError("请输入至少一个有效的设备SN")
        return " ".join(sn_list)

    @validator('remarks')
    def validate_manual_remarks_length(cls, v):
        if v is not None and len(v) > 200:
            raise ValueError("备注最多可输入200字")
        return v


class ManualUsbInstallResponse(BaseSchema):
    """手工U盘装机单响应"""
    work_order_number: Optional[str] = Field(None, description="工单号")
    title: str = Field(..., description="标题")
    project_requirement: str = Field(..., description="项目需求")
    device_sns: List[str] = Field(..., description="设备SN列表")
    datacenter: Optional[str] = Field(None, description="机房")
    room: Optional[str] = Field(None, description="房间")
    os_template: Optional[str] = Field(None, description="OS模板")
    priority: str = Field(..., description="优先级")
    source_order_number: Optional[str] = Field(None, description="来源单号")
    operation_type_detail: Optional[str] = Field(None, description="操作类型")
    is_business_online: Optional[bool] = Field(None, description="业务是否在线")
    remarks: Optional[str] = Field(None, description="备注")


# =====================================================
# 设备信息详情 Schemas
# =====================================================

class DeviceBasicInfo(BaseSchema):
    serial_number: str = Field(..., description="设备SN")
    datacenter: Optional[str] = Field(None, description="机房缩写")
    room: Optional[str] = Field(None, description="房间全称")
    cabinet_number: Optional[str] = Field(None, description="机柜")
    rack_position: Optional[str] = Field(None, description="机位")
    network_port: Optional[str] = Field(None, description="端口信息")
    is_company_device: Optional[bool] = Field(None, description="是否本公司设备")


class LinkedDeviceInfo(BaseSchema):
    serial_number: Optional[str] = Field(None, description="关联设备SN")
    name: Optional[str] = Field(None, description="设备名称")
    link_type: str = Field(..., description="关联类型：upstream/downstream")
    port: Optional[str] = Field(None, description="连接端口")
    is_company_device: Optional[bool] = Field(None, description="是否本公司设备")


class DeviceDetailResponse(BaseSchema):
    device: DeviceBasicInfo
    linked_devices: List[LinkedDeviceInfo] = Field(default_factory=list)


class BatchDeviceQuery(BaseSchema):
    """批量设备查询请求"""
    device_sns: List[str] = Field(..., description="设备SN列表", min_items=1, max_items=100)


class BatchDeviceDetailResponse(BaseSchema):
    """批量设备详情响应"""
    devices: List[DeviceDetailResponse] = Field(default_factory=list, description="设备详情列表")


# =====================================================
# 统一工单流程处理 Schemas
# =====================================================

class WorkOrderProcessRequest(BaseSchema):
    """工单流程处理请求"""
    order_number: str = Field(..., description="工单号")
    description: str = Field(..., description="处理描述")
    is_passed: int = Field(..., description="是否通过：1-通过，0-失败")
    is_complete: int = Field(..., description="是否完成：1-完成，0-未完成")
    is_transfer: int = Field(0, description="是否转移：1-转移，0-不转移")
    attachment_urls: List[str] = Field(default_factory=list, description="附件URL列表")
    process_variables: Dict[str, Any] = Field(default_factory=dict, description="流程变量")
    feedback_person: str = Field(..., description="反馈人员")
    feedback_person_name: str = Field(..., description="反馈人员姓名")
    failure_reason: Optional[str] = Field(None, description="失败原因（可选）")
    close_remark: Optional[str] = Field(None, description="结单备注（可选）")


class WorkOrderProcessResponse(BaseSchema):
    """工单流程处理响应"""
    success: bool = Field(..., description="处理是否成功")
    message: str = Field(..., description="处理结果消息")
    work_order_number: str = Field(..., description="工单号")
    work_order_status: Optional[str] = Field(None, description="工单状态")
    is_closed: bool = Field(False, description="是否结单")
    failure_reason: Optional[str] = Field(None, description="失败理由（如果处理失败）")
    close_remark: Optional[str] = Field(None, description="结单备注")

