"""
IT资产管理系统 - Pydantic Schemas
用于API请求和响应的数据验证和序列化
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from decimal import Decimal
from enum import Enum

# =====================================================
# 枚举定义
# =====================================================
# 注意：资产状态、生命周期状态等枚举已迁移到数据字典管理
# Schema中使用str类型，通过数据字典验证

class LifecycleStatusEnum(str, Enum):
    """生命周期阶段状态（内部流程状态，保留）"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


# =====================================================
# 基础Schema类
# =====================================================

class BaseSchema(BaseModel):
    """基础Schema类"""
    class Config:
        from_attributes = True
        use_enum_values = True

# =====================================================
# 房间类型 Schemas
# =====================================================

class RoomTypeBase(BaseSchema):
    type_code: str = Field(..., max_length=50, description="类型编码")
    type_name: str = Field(..., max_length=100, description="类型名称（中文）")
    description: Optional[str] = Field(None, description="类型描述")
    sequence_order: Optional[int] = Field(None, description="显示顺序")
    is_active: Optional[int] = Field(1, description="是否启用：1-启用，0-禁用")

class RoomTypeCreate(RoomTypeBase):
    pass

class RoomTypeUpdate(BaseSchema):
    type_code: Optional[str] = Field(None, max_length=50)
    type_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    sequence_order: Optional[int] = None
    is_active: Optional[int] = None

class RoomTypeResponse(RoomTypeBase):
    id: int
    created_at: datetime
    updated_at: datetime

# =====================================================
# 房间管理 Schemas（简化版）
# =====================================================

class RoomBase(BaseSchema):
    room_abbreviation: str = Field(..., max_length=20, description="房间缩写")
    room_full_name: str = Field(..., max_length=200, description="房间全称（中文）")
    room_number: str = Field(..., max_length=50, description="房间号")
    room_type_id: int = Field(..., description="房间类型ID")
    datacenter_abbreviation: Optional[str] = Field(None, max_length=20, description="机房缩写")
    building_number: Optional[str] = Field(None, max_length=20, description="楼号")
    floor_number: Optional[str] = Field(None, max_length=10, description="楼层")
    status: Optional[int] = Field(1, description="状态：1-启用，0-禁用")
    notes: Optional[str] = Field(None, description="备注")

class RoomCreate(RoomBase):
    created_by: str = Field(..., max_length=100, description="创建人")

class RoomUpdate(BaseSchema):
    room_abbreviation: Optional[str] = Field(None, max_length=20)
    room_full_name: Optional[str] = Field(None, max_length=200)
    room_number: Optional[str] = Field(None, max_length=50)
    room_type_id: Optional[int] = None
    datacenter_abbreviation: Optional[str] = Field(None, max_length=20)
    building_number: Optional[str] = Field(None, max_length=20)
    floor_number: Optional[str] = Field(None, max_length=10)
    status: Optional[int] = None
    notes: Optional[str] = None

class RoomResponse(RoomBase):
    id: int
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    room_type_rel: Optional[RoomTypeResponse] = Field(None, description="房间类型详情")

# =====================================================
# 资产管理 Schemas
# =====================================================

class AssetCategoryBase(BaseSchema):
    name: str = Field(..., max_length=100, description="分类名称")
    code: str = Field(..., max_length=20, description="分类编码")
    parent_id: Optional[int] = Field(None, description="父分类ID")
    description: Optional[str] = Field(None, description="分类描述")
    status: Optional[int] = Field(1, description="状态：1-启用，0-禁用")

class AssetCategoryCreate(AssetCategoryBase):
    pass

class AssetCategoryUpdate(BaseSchema):
    name: Optional[str] = Field(None, max_length=100)
    code: Optional[str] = Field(None, max_length=20)
    parent_id: Optional[int] = None
    description: Optional[str] = None
    status: Optional[int] = None

class AssetCategoryResponse(AssetCategoryBase):
    id: int
    created_at: datetime
    updated_at: datetime

class VendorBase(BaseSchema):
    name: str = Field(..., max_length=200, description="供应商名称")
    code: str = Field(..., max_length=50, description="供应商编码")
    contact_person: Optional[str] = Field(None, max_length=100, description="联系人")
    phone: Optional[str] = Field(None, max_length=50, description="联系电话")
    email: Optional[str] = Field(None, max_length=200, description="邮箱")
    address: Optional[str] = Field(None, description="地址")
    website: Optional[str] = Field(None, max_length=200, description="网站")
    status: Optional[int] = Field(1, description="状态：1-启用，0-禁用")

class VendorCreate(VendorBase):
    pass

class VendorUpdate(BaseSchema):
    name: Optional[str] = Field(None, max_length=200)
    code: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    website: Optional[str] = Field(None, max_length=200)
    status: Optional[int] = None

class VendorResponse(VendorBase):
    id: int
    created_at: datetime
    updated_at: datetime

class AssetBase(BaseSchema):
    asset_tag: str = Field(..., max_length=100, description="资产标签/编号")
    name: Optional[str] = Field(None, max_length=200, description="资产名称")
    serial_number: Optional[str] = Field(None, max_length=200, description="序列号")
    room_id: Optional[int] = Field(None, description="房间ID")
    order_number: Optional[str] = Field(None, max_length=100, description="出入库单号")
    category_item_id: Optional[int] = Field(None, description="一级分类字典项ID")
    secondary_category_item_id: Optional[int] = Field(None, description="二级分类字典项ID")
    tertiary_category_item_id: Optional[int] = Field(None, description="三级分类字典项ID")
    quantity: Optional[int] = Field(1, ge=1, description="数量")
    is_available: Optional[bool] = Field(True, description="是否可用")
    unavailable_reason: Optional[str] = Field(None, description="不可用原因")
    vendor_name: Optional[str] = Field(None, max_length=200, description="厂商")
    model_name: Optional[str] = Field(None, max_length=200, description="型号")
    mpn: Optional[str] = Field(None, max_length=200, description="MPN")
    machine_model: Optional[str] = Field(None, max_length=200, description="机型")
    three_stage_model: Optional[str] = Field(None, max_length=200, description="三段机型")
    vendor_standard_model: Optional[str] = Field(None, max_length=200, description="厂商标准机型")
    location_detail: Optional[str] = Field(None, max_length=200, description="具体位置描述（如机柜、机位等）")
    asset_status: Optional[str] = Field("active", max_length=50, description="资产管理状态（对应字典: asset_status）")
    lifecycle_status: Optional[str] = Field("registered", max_length=50, description="生命周期状态（对应字典: asset_lifecycle_status）")
    device_direction: Optional[str] = Field("inbound", max_length=20, description="设备去向：inbound-入库, outbound-出库")
    notes: Optional[str] = Field(None, description="备注")
    created_by: Optional[str] = Field(None, max_length=100, description="创建人")
    extra_json: Optional[dict] = Field(None, description="扩展JSON字段，存储额外信息")

class AssetCreate(AssetBase):
    pass

class AssetUpdate(BaseSchema):
    asset_tag: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=200)
    serial_number: Optional[str] = Field(None, max_length=200)
    room_id: Optional[int] = None
    location_detail: Optional[str] = Field(None, max_length=200)
    asset_status: Optional[str] = Field(None, max_length=50)
    lifecycle_status: Optional[str] = Field(None, max_length=50)
    device_direction: Optional[str] = Field(None, max_length=20)
    is_available: Optional[bool] = None
    unavailable_reason: Optional[str] = None
    notes: Optional[str] = None

class AssetResponse(BaseSchema):
    id: int
    asset_tag: str = Field(..., max_length=100, description="资产标签/编号")
    name: Optional[str] = Field(None, max_length=200, description="资产名称")
    serial_number: Optional[str] = Field(None, max_length=200, description="序列号")
    room_id: Optional[int] = Field(None, description="房间ID")
    order_number: Optional[str] = Field(None, description="出入库单号")
    room_name: Optional[str] = Field(None, description="房间名称")
    room_abbreviation: Optional[str] = Field(None, description="房间缩写")
    room_number: Optional[str] = Field(None, description="房间号")
    datacenter_abbreviation: Optional[str] = Field(None, description="机房/园区缩写")
    building_number: Optional[str] = Field(None, description="楼号")
    floor_number: Optional[str] = Field(None, description="楼层")
    # 响应中只显示文字标签，不显示ID
    category: Optional[str] = Field(None, description="一级分类")
    secondary_category: Optional[str] = Field(None, description="二级分类")
    tertiary_category: Optional[str] = Field(None, description="三级分类")
    quantity: Optional[int] = Field(1, ge=1, description="数量")
    is_available: Optional[bool] = Field(True, description="是否可用")
    unavailable_reason: Optional[str] = Field(None, description="不可用原因")
    vendor_name: Optional[str] = Field(None, max_length=200, description="厂商")
    model_name: Optional[str] = Field(None, max_length=200, description="型号")
    mpn: Optional[str] = Field(None, max_length=200, description="MPN")
    machine_model: Optional[str] = Field(None, max_length=200, description="机型")
    three_stage_model: Optional[str] = Field(None, max_length=200, description="三段机型")
    vendor_standard_model: Optional[str] = Field(None, max_length=200, description="厂商标准机型")
    location_detail: Optional[str] = Field(None, max_length=200, description="具体位置描述（如机柜、机位等）")
    asset_status: Optional[str] = Field("active", max_length=50, description="资产管理状态")
    lifecycle_status: Optional[str] = Field("registered", max_length=50, description="生命周期状态")
    device_direction: Optional[str] = Field("inbound", max_length=20, description="设备去向")
    device_direction: Optional[str] = Field("inbound", max_length=20, description="设备去向")
    notes: Optional[str] = Field(None, description="备注")
    created_by: Optional[str] = Field(None, max_length=100, description="创建人")
    extra_json: Optional[dict] = Field(None, description="扩展JSON字段，存储额外信息")
    created_at: datetime
    updated_at: datetime

# =====================================================
# 生命周期管理 Schemas
# =====================================================

class LifecycleStageBase(BaseSchema):
    stage_code: str = Field(..., max_length=20, description="阶段编码")
    stage_name: str = Field(..., max_length=100, description="阶段名称")
    description: Optional[str] = Field(None, description="阶段描述")
    sequence_order: int = Field(..., description="阶段顺序")
    is_active: Optional[int] = Field(1, description="是否启用")

class LifecycleStageCreate(LifecycleStageBase):
    pass

class LifecycleStageUpdate(BaseSchema):
    stage_code: Optional[str] = Field(None, max_length=20)
    stage_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    sequence_order: Optional[int] = None
    is_active: Optional[int] = None

class LifecycleStageResponse(LifecycleStageBase):
    id: int
    created_at: datetime

class AssetLifecycleStatusBase(BaseSchema):
    asset_id: int = Field(..., description="资产ID")
    stage_id: int = Field(..., description="生命周期阶段ID")
    status: Optional[LifecycleStatusEnum] = Field(LifecycleStatusEnum.NOT_STARTED, description="阶段状态")
    start_date: Optional[datetime] = Field(None, description="开始时间")
    end_date: Optional[datetime] = Field(None, description="结束时间")
    responsible_person: Optional[str] = Field(None, max_length=100, description="负责人")
    notes: Optional[str] = Field(None, description="备注")

class AssetLifecycleStatusCreate(AssetLifecycleStatusBase):
    pass

class AssetLifecycleStatusUpdate(BaseSchema):
    asset_id: Optional[int] = None
    stage_id: Optional[int] = None
    status: Optional[LifecycleStatusEnum] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    responsible_person: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None

class AssetLifecycleStatusResponse(AssetLifecycleStatusBase):
    id: int
    created_at: datetime
    updated_at: datetime


# =====================================================
# 注意：暂存审核管理 Schemas 已废弃，功能合并到WorkOrder
# =====================================================

# =====================================================
# 标准API响应 Schemas
# =====================================================

class ResponseCode:
    """标准响应状态码"""
    SUCCESS = 0                    # 成功
    PARAM_ERROR = 1001            # 参数错误
    NOT_FOUND = 1002              # 资源不存在
    ALREADY_EXISTS = 1003         # 资源已存在
    PERMISSION_DENIED = 1004      # 权限不足
    BAD_REQUEST = 4000            # 请求格式错误
    INTERNAL_ERROR = 5000         # 内部错误
    DATABASE_ERROR = 5001         # 数据库错误
    EXTERNAL_API_ERROR = 5002     # 外部API错误

class ApiResponse(BaseSchema):
    """标准API响应格式"""
    code: int = Field(..., description="业务状态码：0-成功，非0-失败")
    message: str = Field(..., description="响应消息（英文）")
    data: Optional[Any] = Field(None, description="响应数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间")

class ApiListResponse(BaseSchema):
    """标准列表响应格式"""
    code: int = Field(..., description="业务状态码：0-成功，非0-失败")
    message: str = Field(..., description="响应消息（英文）")
    data: List[Any] = Field(default_factory=list, description="响应数据列表")
    total: int = Field(0, description="总记录数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(10, description="每页大小")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间")

# =====================================================
# 复合查询 Schemas
# =====================================================

class AssetLocationInfo(BaseSchema):
    """资产位置信息（简化版）"""
    room_abbreviation: Optional[str] = None
    room_full_name: Optional[str] = None
    datacenter_abbreviation: Optional[str] = None
    building_number: Optional[str] = None
    floor_number: Optional[str] = None
    location_detail: Optional[str] = None
    full_location: Optional[str] = None

class WorkOrderSummary(BaseSchema):
    """资产关联工单摘要"""
    work_order_id: int
    batch_id: Optional[str] = None
    work_order_number: Optional[str] = None
    operation_type: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    work_order_status: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_time: Optional[datetime] = None
    item_status: Optional[str] = None
    item_result: Optional[str] = None


class AssetDetailResponse(AssetResponse):
    """资产详细信息响应"""
    category_name: Optional[str] = None
    vendor_name: Optional[str] = None
    location_info: Optional[AssetLocationInfo] = None
    lifecycle_stages: Optional[List[AssetLifecycleStatusResponse]] = None
    latest_work_order: Optional[WorkOrderSummary] = None

class AssetSearchParams(BaseSchema):
    """资产搜索参数"""
    asset_tag: Optional[str] = None
    name: Optional[str] = None
    serial_number: Optional[str] = None
    asset_status: Optional[str] = None
    lifecycle_status: Optional[str] = None
    device_direction: Optional[str] = None
    is_available: Optional[bool] = None
    room_id: Optional[int] = None
    # 分类查询参数（文字形式）
    category: Optional[str] = Field(None, description="一级分类（文字）")
    secondary_category: Optional[str] = Field(None, description="二级分类（文字）")
    tertiary_category: Optional[str] = Field(None, description="三级分类（文字）")
    # 创建时间范围查询
    created_from: Optional[datetime] = Field(None, description="创建时间起始（包含）")
    created_to: Optional[datetime] = Field(None, description="创建时间结束（包含）")
    
class PaginationParams(BaseSchema):
    """分页参数"""
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(10, ge=1, le=100, description="每页数量")

class PaginatedResponse(BaseSchema):
    """分页响应"""
    items: List[Any]
    total: int
    page: int
    size: int
    pages: int

# =====================================================
# 统计分析 Schemas
# =====================================================

class AssetStatistics(BaseSchema):
    """资产统计信息"""
    total_assets: int = 0
    active_assets: int = 0
    inactive_assets: int = 0
    maintenance_assets: int = 0
    retired_assets: int = 0
    disposed_assets: int = 0
    total_value: Optional[Decimal] = None
    
class DepartmentStatistics(BaseSchema):
    """部门资产统计"""
    department: str
    asset_count: int
    total_value: Optional[Decimal] = None
    
class CategoryStatistics(BaseSchema):
    """分类资产统计"""
    category_name: str
    asset_count: int
    total_value: Optional[Decimal] = None

class LocationStatistics(BaseSchema):
    """位置资产统计"""
    region_name: str
    building_name: str
    room_count: int
    cabinet_count: int
    asset_count: int
    utilization_rate: Optional[float] = None
