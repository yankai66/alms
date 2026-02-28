"""
资产出入门工单 - Pydantic Schemas
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class EntryExitPriority(str, Enum):
    """优先级"""
    NORMAL = "normal"  # 一般
    URGENT = "urgent"  # 紧急


class EntryExitBusinessType(str, Enum):
    """业务类型"""
    FAULT_SUPPORT = "fault_support"  # 故障支持
    CHANGE_SUPPORT = "change_support"  # 变更支持
    OTHER = "other"  # 其他


class EntryExitType(str, Enum):
    """出入类型"""
    MOVE_IN = "move_in"  # 搬入
    MOVE_OUT = "move_out"  # 搬出


class EntryExitScope(str, Enum):
    """出入范围"""
    DATACENTER = "datacenter"  # 出入机房
    CAMPUS = "campus"  # 出入园区
    INTERNAL = "internal"  # 机房园区内出入


class AssetEntryExitWorkOrderCreate(BaseModel):
    """创建资产出入门工单请求"""
    
    # 基础信息
    title: str = Field(..., max_length=200, description="工单标题")
    datacenter: Optional[str] = Field(None, max_length=50, description="机房")
    priority: Optional[EntryExitPriority] = Field(None, description="优先级：normal-一般, urgent-紧急")
    business_type: Optional[EntryExitBusinessType] = Field(None, description="业务类型：fault_support-故障支持, change_support-变更支持, other-其他")
    
    # 设备信息
    device_sns: List[str] = Field(..., min_items=1, description="设备SN列表")
    service_content: Optional[str] = Field(None, description="服务内容")
    
    # 资产出入门专用字段
    entry_exit_type: EntryExitType = Field(..., description="出入类型：move_in-搬入, move_out-搬出")
    entry_exit_scope: EntryExitScope = Field(..., description="出入范围：datacenter-出入机房, campus-出入园区, internal-机房园区内出入")
    entry_exit_reason: str = Field(..., max_length=500, description="出入原因")
    entry_exit_date: Optional[str] = Field(None, description="出入日期（YYYY-MM-DD格式）")
    
    # 人员信息
    assignee: str = Field(..., max_length=100, description="指派人")
    creator_name: str = Field(..., max_length=100, description="创建人姓名")
    
    # 可选字段
    remark: Optional[str] = Field(None, max_length=1000, description="备注")
    attachments: Optional[List[str]] = Field(None, description="附件URL列表（支持多附件）")
    source_order_number: Optional[str] = Field(None, max_length=100, description="来源单号")
    campus_auth_order_number: Optional[str] = Field(None, max_length=100, description="园区授权单号")
    campus_auth_status: Optional[str] = Field(None, max_length=50, description="园区授权状态")
    device_type: Optional[str] = Field(None, max_length=100, description="设备类型")
    sign_date: Optional[str] = Field(None, description="签字日期（YYYY-MM-DD格式）")
    
    @validator('entry_exit_date', 'sign_date')
    def validate_date_format(cls, v):
        """验证日期格式"""
        if v:
            try:
                datetime.strptime(v, '%Y-%m-%d')
            except ValueError:
                raise ValueError('日期格式必须为 YYYY-MM-DD')
        return v
    
    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "title": "服务器设备搬入",
                "device_sns": ["SN123456", "SN789012"],
                "entry_exit_type": "move_in",
                "entry_exit_scope": "datacenter",
                "entry_exit_reason": "新设备采购到货，需搬入机房进行上架部署",
                "assignee": "张三",
                "creator_name": "李四",
                "datacenter": "DC01",
                "priority": "normal",
                "business_type": "other",
                "service_content": "新采购服务器搬入机房上架",
                "entry_exit_date": "2025-12-10",
                "sign_date": "2025-12-10",
                "remark": "请提前准备好机柜空间",
                "attachments": ["https://example.com/attachment1.pdf", "https://example.com/attachment2.jpg"]
            }
        }


class AssetEntryExitWorkOrderResponse(BaseModel):
    """资产出入门工单响应"""
    
    work_order_number: Optional[str] = Field(None, description="工单号")
    batch_id: str = Field(..., description="批次ID")
    title: str = Field(..., description="工单标题")
    datacenter: Optional[str] = Field(None, description="机房")
    priority: Optional[str] = Field(None, description="优先级")
    business_type: Optional[str] = Field(None, description="业务类型")
    device_sns: List[str] = Field(..., description="设备SN列表")
    device_count: int = Field(..., description="设备数量")
    service_content: Optional[str] = Field(None, description="服务内容")
    entry_exit_type: str = Field(..., description="出入类型")
    entry_exit_scope: str = Field(..., description="出入范围")
    entry_exit_reason: str = Field(..., description="出入原因")
    entry_exit_date: Optional[str] = Field(None, description="出入日期")
    assignee: str = Field(..., description="指派人")
    creator_name: str = Field(..., description="创建人")
    status: str = Field(..., description="内部状态")
    work_order_status: str = Field("processing", description="外部工单状态：processing-进行中, completed-已完成, failed-失败")
    remark: Optional[str] = Field(None, description="备注")
    attachments: Optional[List[str]] = Field(None, description="附件URL列表")
    source_order_number: Optional[str] = Field(None, description="来源单号")
    campus_auth_order_number: Optional[str] = Field(None, description="园区授权单号")
    campus_auth_status: Optional[str] = Field(None, description="园区授权状态")
    device_type: Optional[str] = Field(None, description="设备类型")
    sign_date: Optional[str] = Field(None, description="签字日期")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    
    class Config:
        from_attributes = True


class AssetEntryExitWorkOrderQuery(BaseModel):
    """查询资产出入门工单参数"""
    
    work_order_number: Optional[str] = Field(None, description="工单号")
    batch_id: Optional[str] = Field(None, description="批次ID")
    datacenter: Optional[str] = Field(None, description="机房")
    priority: Optional[str] = Field(None, description="优先级")
    business_type: Optional[str] = Field(None, description="业务类型")
    status: Optional[str] = Field(None, description="状态")
    assignee: Optional[str] = Field(None, description="指派人")
    device_sn: Optional[str] = Field(None, description="设备SN")
    entry_exit_type: Optional[str] = Field(None, description="出入类型")
    entry_exit_scope: Optional[str] = Field(None, description="出入范围")
    creator_name: Optional[str] = Field(None, description="创建人")
    created_from: Optional[datetime] = Field(None, description="创建时间起始")
    created_to: Optional[datetime] = Field(None, description="创建时间结束")
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(10, ge=1, le=100, description="每页数量")


class AssetEntryExitWorkOrderProcess(BaseModel):
    """处理资产出入门工单请求"""
    
    batch_id: str = Field(..., description="批次ID")
    operator: str = Field(..., max_length=100, description="操作人")
    processing_result: str = Field(..., description="处理结果")
    failure_reason: Optional[str] = Field(None, description="失败原因（处理失败时必填）")
    remark: Optional[str] = Field(None, description="处理备注")
    is_complete: bool = Field(False, description="是否完成工单")
    
    @validator('failure_reason')
    def validate_failure_reason(cls, v, values):
        """如果处理结果为失败，必须提供失败原因"""
        if 'processing_result' in values and values['processing_result'].lower() in ['failed', 'failure', '失败']:
            if not v:
                raise ValueError('处理失败时必须提供失败原因')
        return v
