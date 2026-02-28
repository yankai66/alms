"""
万能类操作工单 - Pydantic Schemas
"""

from pydantic import BaseModel, Field, model_validator, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class GenericPriority(str, Enum):
    """优先级"""
    NORMAL = "normal"  # 一般
    URGENT = "urgent"  # 紧急


class GenericBusinessType(str, Enum):
    """业务类型"""
    FAULT_SUPPORT = "fault_support"  # 故障支持
    CHANGE_SUPPORT = "change_support"  # 变更支持
    OTHER = "other"  # 其他


class GenericOperationType(str, Enum):
    """操作类型"""
    PRODUCTION_NETWORK = "production_network"  # 生产网线
    OOB_NETWORK = "oob_network"  # 带外网线


class GenericWorkOrderType(str, Enum):
    """工单类型"""
    OPERATION = "operation"  # 操作类工单
    NON_OPERATION = "non_operation"  # 非操作类工单
    ASSET = "asset"  # 资产类工单


class OperationSubType(str, Enum):
    """操作子类型"""
    PROJECT_FOLLOW = "project_follow"  # 项目随工（施工队等操作-现场随工）
    INSPECTION = "inspection"  # 巡检（变更/项目类巡检）
    ONSITE_COLLABORATION = "onsite_collaboration"  # 现场协同（基础设施侧/安全侧）
    NON_STANDARD_PROJECT = "non_standard_project"  # 无功单覆盖项目（现场操作-特殊类专项/非标准流程）
    EQUIPMENT_RELOCATION = "equipment_relocation"  # 设备搬运（同园区内现场搬迁设备/随工物流下架搬迁）
    ASSET_PROCESSING = "asset_processing"  # 资产类工单处理（入籍单/举证单/拔盘单）
    ASSET_COLLABORATION = "asset_collaboration"  # 资产类工作协同（资产盘点等）


class GenericWorkOrderCreate(BaseModel):
    """创建万能类操作工单请求"""
    
    # 基础信息
    title: str = Field(..., max_length=200, description="工单标题")
    datacenter: Optional[str] = Field(None, max_length=50, description="机房")
    priority: Optional[GenericPriority] = Field(None, description="优先级：normal-一般, urgent-紧急")
    remark: Optional[str] = Field(None, description="备注")
    
    # 工单类型和编号
    work_order_type: GenericWorkOrderType = Field(..., description="工单类型：operation-操作类工单, non_operation-非操作类工单, asset-资产类工单")
    business_type: Optional[GenericBusinessType] = Field(None, description="业务类型：fault_support-故障支持, change_support-变更支持, other-其他")
    source_order_number: Optional[str] = Field(None, max_length=100, description="来源单号")
    
    # 操作信息
    operation_type: Optional[GenericOperationType] = Field(None, description="操作类型：production_network-生产网线, oob_network-带外网线")
    operation_type_detail: Optional[str] = Field(None, max_length=100, description="操作类型详情")
    is_business_online: Optional[bool] = Field(None, description="业务是否在线")
    
    # 操作类工单专用字段
    operation_sub_type: Optional[OperationSubType] = Field(None, description="操作子类型/操作类型：project_follow-项目随工, inspection-巡检, onsite_collaboration-现场协同, non_standard_project-无功单覆盖项目, equipment_relocation-设备搬运, asset_processing-资产类工单处理, asset_collaboration-资产类工作协同")
    estimated_operation_time: Optional[str] = Field(None, description="预计操作时间（YYYY-MM-DD HH:MM）")
    sop: Optional[str] = Field(None, description="SOP（标准操作流程）")
    
    # 非操作类工单专用字段
    execution_location: Optional[str] = Field(None, description="执行包间（包括机房、园区、包间）")
    precautions: Optional[str] = Field(None, description="注意事项")
    
    # 处理信息
    processing_result: Optional[str] = Field(None, description="处理结果")
    failure_reason: Optional[str] = Field(None, description="失败原因")
    accept_remark: Optional[str] = Field(None, description="接单备注")
    
    # 设备信息
    device_sns: Optional[List[str]] = Field(default=[], description="设备SN列表（可选）")
    service_content: Optional[str] = Field(None, description="服务内容")
    
    # 人员信息
    assignee: str = Field(..., max_length=100, description="指派人")
    creator_name: Optional[str] = Field("system", max_length=100, description="创建人姓名")
    
    @model_validator(mode='after')
    def validate_required_fields(self):
        """根据工单类型验证必填字段"""
        if self.work_order_type == 'operation':
            # 操作类工单必填字段
            if not self.operation_sub_type:
                raise ValueError('操作类工单必须填写操作子类型(operation_sub_type)')
            if not self.estimated_operation_time:
                raise ValueError('操作类工单必须填写预计操作时间(estimated_operation_time)')
            if not self.sop:
                raise ValueError('操作类工单必须填写SOP(sop)')
            if not self.remark:
                raise ValueError('操作类工单必须填写备注(remark)')
        else:
            # 非操作类工单和资产类工单必填字段（完全一样）
            if not self.operation_sub_type:
                raise ValueError('非操作类/资产类工单必须填写操作类型(operation_sub_type)')
            if not self.estimated_operation_time:
                raise ValueError('非操作类/资产类工单必须填写预计操作时间(estimated_operation_time)')
            if not self.execution_location:
                raise ValueError('非操作类/资产类工单必须填写执行包间(execution_location)')
            if not self.remark:
                raise ValueError('非操作类/资产类工单必须填写备注(remark)')
            if not self.precautions:
                raise ValueError('非操作类/资产类工单必须填写注意事项(precautions)')
        
        return self
    
    class Config:
        use_enum_values = True


class GenericWorkOrderResponse(BaseModel):
    """万能类操作工单响应"""
    
    work_order_number: Optional[str] = Field(None, description="工单号")
    batch_id: str = Field(..., description="批次ID")
    title: str = Field(..., description="工单标题")
    datacenter: Optional[str] = Field(None, description="机房")
    priority: Optional[str] = Field(None, description="优先级")
    work_order_type: str = Field(..., description="工单类型")
    business_type: Optional[str] = Field(None, description="业务类型")
    source_order_number: Optional[str] = Field(None, description="来源单号")
    operation_type: Optional[str] = Field(None, description="操作类型")
    operation_type_detail: Optional[str] = Field(None, description="操作类型详情")
    is_business_online: Optional[bool] = Field(None, description="业务是否在线")
    operation_sub_type: Optional[str] = Field(None, description="操作子类型/操作类型")
    estimated_operation_time: Optional[str] = Field(None, description="预计操作时间")
    sop: Optional[str] = Field(None, description="SOP")
    execution_location: Optional[str] = Field(None, description="执行包间")
    precautions: Optional[str] = Field(None, description="注意事项")
    device_sns: Optional[List[str]] = Field(default=[], description="设备SN列表（可选）")
    service_content: Optional[str] = Field(None, description="服务内容")
    assignee: str = Field(..., description="指派人")
    status: str = Field(..., description="工单状态")
    remark: Optional[str] = Field(None, description="备注")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    
    class Config:
        from_attributes = True


class GenericWorkOrderQuery(BaseModel):
    """查询万能类操作工单参数"""
    
    work_order_number: Optional[str] = Field(None, description="工单号")
    batch_id: Optional[str] = Field(None, description="批次ID")
    datacenter: Optional[str] = Field(None, description="机房")
    priority: Optional[str] = Field(None, description="优先级")
    work_order_type: Optional[str] = Field(None, description="工单类型")
    business_type: Optional[str] = Field(None, description="业务类型")
    operation_type: Optional[str] = Field(None, description="操作类型")
    operation_sub_type: Optional[str] = Field(None, description="操作子类型")
    status: Optional[str] = Field(None, description="状态")
    assignee: Optional[str] = Field(None, description="指派人")
    device_sn: Optional[str] = Field(None, description="设备SN")
    created_from: Optional[datetime] = Field(None, description="创建时间起始")
    created_to: Optional[datetime] = Field(None, description="创建时间结束")
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(10, ge=1, le=100, description="每页数量")


class GenericWorkOrderProcess(BaseModel):
    """处理万能类操作工单请求"""
    
    batch_id: str = Field(..., description="批次ID")
    operator: str = Field(..., max_length=100, description="操作人")
    processing_result: str = Field(..., description="处理结果")
    failure_reason: Optional[str] = Field(None, description="失败原因（处理失败时必填）")
    accept_remark: Optional[str] = Field(None, description="接单备注")
    is_complete: bool = Field(False, description="是否完成工单")
    
    @model_validator(mode='after')
    def validate_failure_reason(self):
        """如果处理结果为失败，必须提供失败原因"""
        if self.processing_result and self.processing_result.lower() in ['failed', 'failure', '失败']:
            if not self.failure_reason:
                raise ValueError('处理失败时必须提供失败原因')
        return self
