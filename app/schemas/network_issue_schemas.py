"""
网络故障/变更配合工单 - Pydantic Schemas
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum


class NetworkIssuePriority(str, Enum):
    """优先级"""
    NORMAL = "normal"  # 一般
    URGENT = "urgent"  # 紧急


class NetworkBusinessType(str, Enum):
    """业务类型"""
    FAULT_SUPPORT = "fault_support"  # 故障支持
    CHANGE_SUPPORT = "change_support"  # 变更支持
    OTHER = "other"  # 其他


class NetworkOperationType(str, Enum):
    """操作类型"""
    PRODUCTION_NETWORK = "production_network"  # 生产网线
    OOB_NETWORK = "oob_network"  # 带外网线


class NetworkIssueWorkOrderCreate(BaseModel):
    """创建网络故障/变更配合工单请求"""
    
    # 基础信息
    title: str = Field(..., max_length=200, description="工单标题")
    datacenter: Optional[Any] = Field(None, description="机房（支持字符串或数字ID）")
    priority: Optional[NetworkIssuePriority] = Field(None, description="优先级：normal-一般, urgent-紧急")
    remark: Optional[str] = Field(None, description="备注")
    
    # 工单类型和编号（工单类型使用系统的operation_type，这里不需要单独字段）
    business_type: Optional[NetworkBusinessType] = Field(None, description="业务类型：fault_support-故障支持, change_support-变更支持, other-其他")
    source_order_number: Optional[str] = Field(None, max_length=100, description="来源单号")
    
    # 操作信息
    operation_type: Optional[NetworkOperationType] = Field(None, description="操作类型：production_network-生产网线, oob_network-带外网线")
    operation_type_detail: Optional[str] = Field(None, max_length=100, description="操作类型详情")
    is_business_online: Optional[bool] = Field(None, description="业务是否在线")
    
    # 处理信息（创建时可选，处理时必填）
    processing_result: Optional[str] = Field(None, description="处理结果")
    failure_reason: Optional[str] = Field(None, description="失败原因")
    accept_remark: Optional[str] = Field(None, description="接单备注")
    
    # 设备信息
    device_sns: Any = Field(..., description="设备SN列表（支持数组或逗号分隔的字符串）")
    service_content: Optional[str] = Field(None, description="服务内容")
    
    @validator('datacenter', pre=True)
    def convert_datacenter(cls, v):
        """将数字ID转换为字符串"""
        if v is not None:
            return str(v)
        return v
    
    @validator('device_sns', pre=True)
    def convert_device_sns(cls, v):
        """将字符串转换为列表"""
        if isinstance(v, str):
            # 支持逗号分隔的字符串
            return [s.strip() for s in v.split(',') if s.strip()]
        return v
    
    # 人员信息
    assignee: str = Field(..., max_length=100, description="指派人")
    creator_name: Optional[str] = Field("system", max_length=100, description="创建人姓名")
    
    class Config:
        use_enum_values = True


class NetworkIssueWorkOrderResponse(BaseModel):
    """网络故障/变更配合工单响应"""
    
    work_order_number: Optional[str] = Field(None, description="工单号")
    batch_id: str = Field(..., description="批次ID")
    title: str = Field(..., description="工单标题")
    datacenter: Optional[str] = Field(None, description="机房")
    priority: Optional[str] = Field(None, description="优先级")
    business_type: Optional[str] = Field(None, description="业务类型")
    source_order_number: Optional[str] = Field(None, description="来源单号")
    operation_type: Optional[str] = Field(None, description="操作类型")
    operation_type_detail: Optional[str] = Field(None, description="操作类型详情")
    is_business_online: Optional[bool] = Field(None, description="业务是否在线")
    device_sns: List[str] = Field(..., description="设备SN列表")
    service_content: Optional[str] = Field(None, description="服务内容")
    assignee: str = Field(..., description="指派人")
    status: str = Field(..., description="工单状态")
    remark: Optional[str] = Field(None, description="备注")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    
    class Config:
        from_attributes = True


class NetworkIssueWorkOrderQuery(BaseModel):
    """查询网络故障/变更配合工单参数"""
    
    work_order_number: Optional[str] = Field(None, description="工单号")
    batch_id: Optional[str] = Field(None, description="批次ID")
    datacenter: Optional[str] = Field(None, description="机房")
    priority: Optional[str] = Field(None, description="优先级")
    business_type: Optional[str] = Field(None, description="业务类型")
    operation_type: Optional[str] = Field(None, description="操作类型")
    status: Optional[str] = Field(None, description="状态")
    assignee: Optional[str] = Field(None, description="指派人")
    device_sn: Optional[str] = Field(None, description="设备SN")
    created_from: Optional[datetime] = Field(None, description="创建时间起始")
    created_to: Optional[datetime] = Field(None, description="创建时间结束")
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(10, ge=1, le=100, description="每页数量")


class NetworkIssueWorkOrderProcess(BaseModel):
    """处理网络故障/变更配合工单请求"""
    
    batch_id: str = Field(..., description="批次ID")
    operator: str = Field(..., max_length=100, description="操作人")
    processing_result: str = Field(..., description="处理结果")
    failure_reason: Optional[str] = Field(None, description="失败原因（处理失败时必填）")
    accept_remark: Optional[str] = Field(None, description="接单备注")
    is_complete: bool = Field(False, description="是否完成工单")
    
    @validator('failure_reason')
    def validate_failure_reason(cls, v, values):
        """如果处理结果为失败，必须提供失败原因"""
        if 'processing_result' in values and values['processing_result'].lower() in ['failed', 'failure', '失败']:
            if not v:
                raise ValueError('处理失败时必须提供失败原因')
        return v
