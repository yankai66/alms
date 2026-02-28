"""
IT资产管理系统 - SQLAlchemy模型定义
包含：位置层级、资产管理、生命周期管理等所有数据模型
"""

from sqlalchemy import (
    Column, Integer, String, Text, DECIMAL, Date, DateTime, 
    Boolean, Enum, ForeignKey, UniqueConstraint, Index, func, JSON
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.mysql import TINYINT, TIMESTAMP
from app.db.session import Base
import enum
from datetime import datetime
from typing import Optional

# =====================================================
# 枚举定义
# =====================================================
# 注意：大部分枚举已迁移到数据字典管理（dict_types + dict_items）
# 以下枚举仅用于内部流程状态

class LifecycleStatusEnum(str, enum.Enum):
    """生命周期阶段状态（用于asset_lifecycle_status表的status字段）"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


# =====================================================
# 位置管理模型（简化版 - 只保留房间）
# =====================================================

class RoomType(Base):
    """房间类型表（枚举表）"""
    __tablename__ = "room_types"
    
    id = Column(Integer, primary_key=True, index=True)
    type_code = Column(String(50), unique=True, nullable=False, comment="类型编码")
    type_name = Column(String(100), nullable=False, comment="类型名称（中文）")
    description = Column(Text, comment="类型描述")
    sequence_order = Column(Integer, comment="显示顺序")
    is_active = Column(TINYINT, default=1, comment="是否启用：1-启用，0-禁用")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    rooms = relationship("Room", back_populates="room_type_rel")
    
    __table_args__ = (
        Index('idx_type_code', 'type_code'),
        Index('idx_sequence_order', 'sequence_order'),
        Index('idx_is_active', 'is_active'),
    )

class Room(Base):
    """房间表（简化版）"""
    __tablename__ = "rooms"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # 基础标识信息
    room_abbreviation = Column(String(20), unique=True, nullable=False, comment="房间缩写")
    room_full_name = Column(String(200), nullable=False, comment="房间全称（中文）")
    room_number = Column(String(50), nullable=False, comment="房间号")
    
    # 分类和位置信息
    room_type_id = Column(Integer, ForeignKey("room_types.id"), nullable=False, comment="房间类型ID")
    datacenter_abbreviation = Column(String(20), comment="机房缩写")
    building_number = Column(String(20), comment="楼号")
    floor_number = Column(String(10), comment="楼层")
    
    # 管理信息
    status = Column(TINYINT, default=1, comment="状态：1-启用，0-禁用")
    notes = Column(Text, comment="备注")
    created_by = Column(String(100), comment="创建人")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    room_type_rel = relationship("RoomType", back_populates="rooms")
    assets = relationship("Asset", back_populates="room")
    
    __table_args__ = (
        Index('idx_room_type_id', 'room_type_id'),
        Index('idx_datacenter_abbreviation', 'datacenter_abbreviation'),
        Index('idx_building_floor', 'building_number', 'floor_number'),
        Index('idx_status', 'status'),
    )

# =====================================================
# 资产管理模型
# =====================================================

class AssetCategory(Base):
    """资产分类表"""
    __tablename__ = "asset_categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, comment="分类名称")
    code = Column(String(64), unique=True, nullable=False, comment="分类编码")
    parent_id = Column(Integer, ForeignKey("asset_categories.id"), comment="父分类ID")
    description = Column(Text, comment="分类描述")
    status = Column(TINYINT, default=1, comment="状态：1-启用，0-禁用")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    parent = relationship("AssetCategory", remote_side=[id])
    assets = relationship("Asset", back_populates="category")
    
    __table_args__ = (
        Index('idx_parent_id', 'parent_id'),
        Index('idx_code', 'code'),
        Index('idx_status', 'status'),
    )

class Vendor(Base):
    """供应商表"""
    __tablename__ = "vendors"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, comment="供应商名称")
    code = Column(String(50), unique=True, nullable=False, comment="供应商编码")
    contact_person = Column(String(100), comment="联系人")
    phone = Column(String(50), comment="联系电话")
    email = Column(String(200), comment="邮箱")
    address = Column(Text, comment="地址")
    website = Column(String(200), comment="网站")
    status = Column(TINYINT, default=1, comment="状态：1-启用，0-禁用")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    assets = relationship("Asset", back_populates="vendor")
    
    __table_args__ = (
        Index('idx_code', 'code'),
        Index('idx_status', 'status'),
    )

class Asset(Base):
    """资产主表"""
    __tablename__ = "assets"
    
    id = Column(Integer, primary_key=True, index=True)
    asset_tag = Column(String(100), unique=True, nullable=False, comment="资产标签/编号")
    name = Column(String(200), nullable=False, comment="资产名称")
    category_id = Column(Integer, ForeignKey("asset_categories.id"), nullable=False)
    category_item_id = Column(Integer, ForeignKey("dict_items.id", ondelete="SET NULL"))
    secondary_category_item_id = Column(Integer, ForeignKey("dict_items.id", ondelete="SET NULL"))
    tertiary_category_item_id = Column(Integer, ForeignKey("dict_items.id", ondelete="SET NULL"))
    vendor_id = Column(Integer, ForeignKey("vendors.id"))
    model = Column(String(200), comment="型号")
    vendor_standard_model = Column(String(200), comment="厂商标准机型")
    quantity = Column(Integer, nullable=False, default=1, comment="数量")
    serial_number = Column(String(200), comment="序列号")
    purchase_date = Column(Date, comment="采购日期")
    warranty_date = Column(Date, comment="保修到期日期")
    purchase_price = Column(DECIMAL(15, 2), comment="采购价格")
    current_value = Column(DECIMAL(15, 2), comment="当前价值")
    room_id = Column(Integer, ForeignKey("rooms.id"), comment="房间ID")
    datacenter_abbreviation = Column(String(20), comment="机房缩写")
    location_detail = Column(String(200), comment="具体位置描述（如机柜、机位等）")
    order_number = Column(String(100), comment="出入库单号")
    ip_address = Column(String(45), comment="IP地址")
    mac_address = Column(String(17), comment="MAC地址")
    operating_system = Column(String(200), comment="操作系统")
    cpu_info = Column(Text, comment="CPU信息")
    memory_gb = Column(Integer, comment="内存大小（GB）")
    storage_info = Column(Text, comment="存储信息")
    network_info = Column(Text, comment="网络配置信息")
    power_consumption = Column(DECIMAL(8, 2), comment="功耗（W）")
    
    # 资产管理状态（对应字典类型: asset_status）
    asset_status = Column(String(50), default="active", comment="资产管理状态：active/inactive/maintenance/retired/disposed")
    
    # 生命周期状态（对应字典类型: asset_lifecycle_status）
    lifecycle_status = Column(String(50), default="registered", comment="生命周期状态：registered/received/racked/powered_on/running等")
    device_direction = Column(String(20), default="inbound", nullable=False, comment="设备去向：inbound-入库, outbound-出库")
    
    # 可用性状态
    is_available = Column(Boolean, default=True, comment="是否可用")
    unavailable_reason = Column(Text, comment="不可用原因")
    
    is_company_device = Column(Boolean, default=True, comment="是否本公司设备：True-是, False-否")
    owner = Column(String(100), comment="责任人")
    department = Column(String(100), comment="所属部门")
    notes = Column(Text, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    category = relationship("AssetCategory", back_populates="assets")
    vendor = relationship("Vendor", back_populates="assets")
    room = relationship("Room", back_populates="assets")
    category_item = relationship("DictItem", foreign_keys=[category_item_id])
    secondary_category_item = relationship("DictItem", foreign_keys=[secondary_category_item_id])
    tertiary_category_item = relationship("DictItem", foreign_keys=[tertiary_category_item_id])
    lifecycle_status_records = relationship("AssetLifecycleStatus", back_populates="asset", cascade="all, delete-orphan")
    change_logs = relationship("AssetChangeLog", back_populates="asset", cascade="all, delete-orphan")
    maintenance_records = relationship("MaintenanceRecord", back_populates="asset", cascade="all, delete-orphan")
# racking_items = relationship("RackingBatchItem", back_populates="asset", cascade="all, delete-orphan")  # 已迁移到WorkOrder
    configurations = relationship("AssetConfiguration", foreign_keys="[AssetConfiguration.asset_id]", back_populates="asset", cascade="all, delete-orphan")
    related_configurations = relationship("AssetConfiguration", foreign_keys="[AssetConfiguration.related_asset_id]", back_populates="related_asset")
    work_order_items = relationship("WorkOrderItem", back_populates="asset")
    source_connections = relationship("NetworkConnection", foreign_keys="[NetworkConnection.source_asset_id]", back_populates="source_asset")
    target_connections = relationship("NetworkConnection", foreign_keys="[NetworkConnection.target_asset_id]", back_populates="target_asset")
    source_relationships = relationship("AssetRelationship", foreign_keys="[AssetRelationship.source_asset_id]", back_populates="source_asset")
    target_relationships = relationship("AssetRelationship", foreign_keys="[AssetRelationship.target_asset_id]", back_populates="target_asset")
    
    __table_args__ = (
        Index('idx_asset_tag', 'asset_tag'),
        Index('idx_category_id', 'category_id'),
        Index('idx_category_item_id', 'category_item_id'),
        Index('idx_secondary_category_item_id', 'secondary_category_item_id'),
        Index('idx_tertiary_category_item_id', 'tertiary_category_item_id'),
        Index('idx_vendor_id', 'vendor_id'),
        Index('idx_quantity', 'quantity'),
        Index('idx_room_id', 'room_id'),
        Index('idx_asset_status', 'asset_status'),
        Index('idx_lifecycle_status', 'lifecycle_status'),
        Index('idx_device_direction', 'device_direction'),
        Index('idx_is_available', 'is_available'),
        Index('idx_owner', 'owner'),
        Index('idx_department', 'department'),
        Index('idx_ip_address', 'ip_address'),
        Index('idx_serial_number', 'serial_number'),
    )

# =====================================================
# 设备到货批次管理模型 - 已废弃，合并到WorkOrder
# =====================================================
# 原receiving_batches和receiving_batch_items已删除
# 功能合并到统一的work_orders和work_order_items

# =====================================================
# 生命周期管理模型
# =====================================================

class LifecycleStage(Base):
    """生命周期阶段定义表"""
    __tablename__ = "lifecycle_stages"
    
    id = Column(Integer, primary_key=True, index=True)
    stage_code = Column(String(20), unique=True, nullable=False, comment="阶段编码")
    stage_name = Column(String(100), nullable=False, comment="阶段名称")
    description = Column(Text, comment="阶段描述")
    sequence_order = Column(Integer, nullable=False, comment="阶段顺序")
    is_active = Column(TINYINT, default=1, comment="是否启用")
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    # 关系
    asset_statuses = relationship("AssetLifecycleStatus", back_populates="stage")
    
    __table_args__ = (
        Index('idx_sequence_order', 'sequence_order'),
        Index('idx_stage_code', 'stage_code'),
    )

class AssetLifecycleStatus(Base):
    """资产生命周期状态表"""
    __tablename__ = "asset_lifecycle_status"
    
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    stage_id = Column(Integer, ForeignKey("lifecycle_stages.id"), nullable=False)
    status = Column(Enum(LifecycleStatusEnum), default=LifecycleStatusEnum.NOT_STARTED, comment="阶段状态")
    start_date = Column(TIMESTAMP, comment="开始时间")
    end_date = Column(TIMESTAMP, comment="结束时间")
    responsible_person = Column(String(100), comment="负责人")
    notes = Column(Text, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    asset = relationship("Asset", back_populates="lifecycle_status_records")
    stage = relationship("LifecycleStage", back_populates="asset_statuses")
    
    __table_args__ = (
        UniqueConstraint('asset_id', 'stage_id', name='uk_asset_stage'),
        Index('idx_asset_id', 'asset_id'),
        Index('idx_stage_id', 'stage_id'),
        Index('idx_status', 'status'),
    )


# =====================================================
# 暂存审核管理模型 - 已废弃，合并到WorkOrder
# =====================================================
# 原staging_import_batches、staging_assets、staging_audit_logs已删除
# 审核功能集成到统一的work_orders系统

# =====================================================
# 辅助管理模型
# =====================================================

class AssetChangeLog(Base):
    """资产变更记录表"""
    __tablename__ = "asset_change_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    change_type = Column(String(50), nullable=False, comment="变更类型（对应字典: asset_change_type）：create/update/move/status_change/delete")
    field_name = Column(String(100), comment="变更字段")
    old_value = Column(Text, comment="原值")
    new_value = Column(Text, comment="新值")
    change_reason = Column(Text, comment="变更原因")
    operator = Column(String(100), nullable=False, comment="操作人")
    change_date = Column(TIMESTAMP, server_default=func.now(), comment="变更时间")
    
    # 关系
    asset = relationship("Asset", back_populates="change_logs")
    
    __table_args__ = (
        Index('idx_asset_id', 'asset_id'),
        Index('idx_change_type', 'change_type'),
        Index('idx_change_date', 'change_date'),
        Index('idx_operator', 'operator'),
    )

class MaintenanceRecord(Base):
    """维护记录表"""
    __tablename__ = "maintenance_records"
    
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    maintenance_type = Column(String(50), nullable=False, comment="维护类型（对应字典: maintenance_type）：preventive/corrective/upgrade/inspection")
    title = Column(String(200), nullable=False, comment="维护标题")
    description = Column(Text, comment="维护描述")
    maintenance_date = Column(Date, nullable=False, comment="维护日期")
    technician = Column(String(100), comment="技术员")
    downtime_hours = Column(DECIMAL(5, 2), comment="停机时间（小时）")
    status = Column(String(50), default='scheduled', comment="维护状态（对应字典: maintenance_status）：scheduled/in_progress/completed/cancelled")
    notes = Column(Text, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    asset = relationship("Asset", back_populates="maintenance_records")
    
    __table_args__ = (
        Index('idx_asset_id', 'asset_id'),
        Index('idx_maintenance_type', 'maintenance_type'),
        Index('idx_maintenance_date', 'maintenance_date'),
        Index('idx_status', 'status'),
        Index('idx_technician', 'technician'),
    )

class NetworkConnection(Base):
    """网络连接表"""
    __tablename__ = "network_connections"
    
    id = Column(Integer, primary_key=True, index=True)
    source_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    source_port = Column(String(100), comment="源端口")
    target_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    target_port = Column(String(100), comment="目标端口")
    connection_type = Column(String(50), default='ethernet', comment="连接类型（对应字典: connection_type）：ethernet/fiber/console/power/other")
    cable_type = Column(String(100), comment="线缆类型")
    cable_length = Column(DECIMAL(8, 2), comment="线缆长度（米）")
    bandwidth = Column(String(50), comment="带宽")
    status = Column(TINYINT, default=1, comment="状态：1-正常，0-异常")
    notes = Column(Text, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    source_asset = relationship("Asset", foreign_keys=[source_asset_id], back_populates="source_connections")
    target_asset = relationship("Asset", foreign_keys=[target_asset_id], back_populates="target_connections")
    
    __table_args__ = (
        Index('idx_source_asset', 'source_asset_id'),
        Index('idx_target_asset', 'target_asset_id'),
        Index('idx_connection_type', 'connection_type'),
        Index('idx_status', 'status'),
    )

# =====================================================
# 通用数据字典（字典类型 + 字典项）
# =====================================================

class DictType(Base):
    """数据字典类型"""
    __tablename__ = "dict_types"

    id = Column(Integer, primary_key=True, index=True)
    type_code = Column(String(100), unique=True, nullable=False, comment="字典类型编码，系统内唯一")
    type_name = Column(String(200), nullable=False, comment="字典类型名称")
    description = Column(Text, comment="说明")
    status = Column(TINYINT, default=1, comment="状态：1启用，0禁用")
    sequence_order = Column(Integer, default=0, comment="显示排序")
    built_in = Column(TINYINT, default=0, comment="是否内置：1内置，0用户创建")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    items = relationship("DictItem", back_populates="dict_type", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_dict_type_code', 'type_code'),
        Index('idx_dict_type_status', 'status'),
    )


class DictItem(Base):
    """数据字典项"""
    __tablename__ = "dict_items"

    id = Column(Integer, primary_key=True, index=True)
    type_id = Column(Integer, ForeignKey("dict_types.id", ondelete="CASCADE"), nullable=False)
    item_code = Column(String(100), nullable=False, comment="字典项编码（在同一类型下唯一）")
    item_label = Column(String(200), nullable=False, comment="显示名称")
    item_value = Column(String(500), nullable=True, comment="值（字符串存储，可被业务解析）")
    color = Column(String(20), comment="颜色（可选）")
    icon = Column(String(100), comment="图标（可选）")
    status = Column(TINYINT, default=1, comment="状态：1启用，0禁用")
    sequence_order = Column(Integer, default=0, comment="显示排序")
    remark = Column(Text, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    dict_type = relationship("DictType", back_populates="items")

    __table_args__ = (
        UniqueConstraint('type_id', 'item_code', name='uk_dict_item_type_code'),
        Index('idx_dict_item_type_id', 'type_id'),
        Index('idx_dict_item_status', 'status'),
        Index('idx_dict_item_order', 'sequence_order'),
    )


# =====================================================
# 设备上架管理模型 - 已迁移到WorkOrder统一工单系统
# =====================================================

# class RackingBatch(Base):
#     """设备上架批次表 - 已废弃，使用WorkOrder替代"""
#     __tablename__ = "racking_batches"
#     
#     id = Column(Integer, primary_key=True, index=True)
#     batch_id = Column(String(50), unique=True, nullable=False, comment="系统批次ID（格式：RACKYYYYMMDDNNN）")
#     excel_batch_number = Column(String(100), comment="Excel上架单号")
#     work_order_number = Column(String(100), comment="工单号")
#     status = Column(String(50), default="pending", comment="批次状态：pending-待上架, racking-上架中, completed-已完成, cancelled-已取消")
#     operator = Column(String(100), comment="操作人")
#     reviewer = Column(String(100), comment="审核人")
#     inspector = Column(String(100), comment="验收人")
#     racking_time = Column(TIMESTAMP, comment="上架完成时间")
#     import_file_name = Column(String(200), comment="导入文件名")
#     remark = Column(Text, comment="备注信息")
#     project_number = Column(String(100), comment="项目编号")
#     source_order_number = Column(String(100), comment="来源单号")
#     close_time = Column(TIMESTAMP, comment="结单时间")
#     sla_deadline = Column(TIMESTAMP, comment="SLA截止时间")
#     network_racking_order_number = Column(String(100), comment="网络设备上架单号")
#     power_connection_order_number = Column(String(100), comment="插线通电单号")
#     inbound_order_number = Column(String(100), comment="入库单号")
#     outbound_order_number = Column(String(100), comment="出库单号")
#     created_at = Column(TIMESTAMP, server_default=func.now())
#     updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
#     
#     # 关系
#     items = relationship(
#         "RackingBatchItem",
#         back_populates="batch",
#         cascade="all, delete-orphan"
#     )
#     
#     __table_args__ = (
#         Index('idx_racking_batch_id', 'batch_id'),
#         Index('idx_excel_batch_number', 'excel_batch_number'),
#         Index('idx_work_order_number', 'work_order_number'),
#         Index('idx_status', 'status'),
#         Index('idx_racking_time', 'racking_time'),
#     )


# class RackingBatchItem(Base):
#     """设备上架明细表 - 已废弃，使用WorkOrderItem替代"""
#     __tablename__ = "racking_batch_items"
#     
#     id = Column(Integer, primary_key=True, index=True)
#     batch_id = Column(Integer, ForeignKey("racking_batches.id", ondelete="CASCADE"), nullable=False, comment="关联批次ID")
#     asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, comment="资产ID")
#     cabinet_id = Column(Integer, nullable=True, comment="机柜ID（可选）")
#     cabinet_number = Column(String(100), comment="机柜编号（文本记录）")
#     datacenter = Column(String(50), comment="机房缩写")
#     room_number = Column(String(50), comment="房间号")
#     u_position_start = Column(Integer, nullable=False, comment="起始U位")
#     u_position_end = Column(Integer, nullable=False, comment="结束U位")
#     u_count = Column(Integer, nullable=False, comment="占用U数")
#     rack_position = Column(String(50), comment="机位信息（原始文本）")
#     front_or_back = Column(String(10), default="front", comment="前/后：front-前, back-后, both-前后")
#     power_supply = Column(String(50), comment="电源信息")
#     network_port = Column(String(100), comment="网络端口信息")
#     status = Column(String(50), default="pending", comment="状态：pending-待上架, racking-上架中, completed-已完成, cancelled-已取消")
#     error = Column(Text, comment="备注信息")
#     created_at = Column(TIMESTAMP, server_default=func.now())
#     updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
#     
#     # 关系
#     batch = relationship("RackingBatch", back_populates="items")
#     asset = relationship("Asset")
#     
#     __table_args__ = (
#         Index('idx_racking_batch_id_item', 'batch_id'),
#         Index('idx_asset_id_item', 'asset_id'),
#         Index('idx_cabinet_number_item', 'cabinet_number'),
#         Index('idx_status_item', 'status'),
#     )


# =====================================================
# 设备增配管理模型
# =====================================================

class AssetConfiguration(Base):
    """设备增配表（支持上联/下联）"""
    __tablename__ = "asset_configurations"
    
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, comment="资产ID（主设备）")
    configuration_type = Column(String(20), nullable=False, comment="增配类型：upstream-上联, downstream-下联")
    related_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=True, comment="关联资产ID（上联或下联设备，可为空）")
    connection_type = Column(String(50), comment="连接类型：ethernet-以太网, fiber-光纤, console-控制台, power-电源, other-其他")
    configuration_info = Column(JSON, comment="增配详细信息（JSON格式，便于扩展）")
    status = Column(TINYINT, default=1, comment="状态：1-启用，0-禁用")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    asset = relationship("Asset", foreign_keys=[asset_id])
    related_asset = relationship("Asset", foreign_keys=[related_asset_id])
    
    __table_args__ = (
        Index('idx_asset_id_config', 'asset_id'),
        Index('idx_related_asset_id_config', 'related_asset_id'),
        Index('idx_configuration_type', 'configuration_type'),
        Index('idx_status_config', 'status'),
    )


# =====================================================
# 统一工单管理模型
# =====================================================

class WorkOrder(Base):
    """统一工单表 - 支持设备到货、设备上架、设备增配等多种类型"""
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    
    # ===== 核心标识 =====
    batch_id = Column(String(50), unique=True, nullable=False, index=True, comment="内部批次号（格式：RECV/RACK/CONF+时间戳）")
    work_order_number = Column(String(100), unique=True, nullable=True, index=True, comment="外部工单系统工单号（通过回调接口更新）")
    arrival_order_number = Column(String(100), index=True, comment="到货单号（通过回调接口更新）")
    source_order_number = Column(String(100), index=True, comment="来源单号/来源业务单号")
    
    # ===== 业务信息 =====
    operation_type = Column(String(50), nullable=False, index=True, comment="操作类型：receiving/racking/configuration等")
    title = Column(String(200), comment="工单标题")
    description = Column(Text, comment="工单描述/备注")
    
    # ===== 状态管理 =====
    status = Column(String(50), default="pending", index=True, comment="内部状态：pending/processing/completed/cancelled")
    work_order_status = Column(String(50), index=True, comment="外部工单系统状态（由外部系统更新）")
    is_timeout = Column(Boolean, default=False, comment="是否超时")
    sla_countdown = Column(Integer, comment="SLA倒计时（秒）")
    
    # ===== 人员信息 =====
    creator = Column(String(100), index=True, comment="创建人")
    operator = Column(String(100), comment="当前操作人/结束人")
    assignee = Column(String(100), comment="指派人")
    reviewer = Column(String(100), comment="审核人")
    
    # ===== 位置信息（公共） =====
    datacenter = Column(String(50), index=True, comment="机房")
    campus = Column(String(50), comment="园区")
    room = Column(String(50), comment="房间")
    cabinet = Column(String(50), comment="机柜")
    rack_position = Column(String(50), comment="机位（如1-2U）")
    
    # ===== 项目信息 =====
    project_number = Column(String(100), comment="项目编号")
    
    # ===== 分类信息（设备到货和增配用） =====
    device_category_level1 = Column(String(100), comment="设备一级类型/父设备一级类型")
    device_category_level2 = Column(String(100), comment="设备二级分类/配件二级分类")
    device_category_level3 = Column(String(100), comment="设备三级分类/配件三级分类")
    
    # ===== 时间信息 =====
    start_time = Column(TIMESTAMP, comment="开始时间")
    expected_completion_time = Column(TIMESTAMP, comment="期望完成时间")
    completed_time = Column(TIMESTAMP, comment="实际完成时间")
    close_time = Column(TIMESTAMP, comment="结单时间/结束时间")
    allowed_operation_start_time = Column(TIMESTAMP, comment="允许操作开始时间（增配用）")
    allowed_operation_end_time = Column(TIMESTAMP, comment="允许操作结束时间（增配用）")
    
    # ===== 统计信息 =====
    device_count = Column(Integer, default=0, comment="设备数量（统计items中的设备数）")
    cabinet_count = Column(Integer, default=0, comment="机柜数量（统计涉及的机柜数，电源管理工单使用）")
    
    # ===== 设备增配专用字段 =====
    parent_device_sn = Column(String(200), comment="父设备SN（增配用）")
    parent_device_can_shutdown = Column(Boolean, comment="父设备能否关机（增配用）")
    component_model = Column(String(200), comment="配件型号（增配用）")
    component_mpn = Column(String(200), comment="配件MPN（增配用）")
    component_quantity = Column(Integer, comment="配件数量（增配用）")
    inbound_order_number = Column(String(100), comment="入库单号（增配用）")
    outbound_order_number = Column(String(100), comment="出库单号（增配用）")
    upgrade_order_number = Column(String(100), comment="增配单号（增配用）")
    vendor_onsite = Column(Boolean, comment="厂商是否上门（增配用）")
    is_optical_module_upgrade = Column(Boolean, comment="是否光模块增配（增配用）")
    is_project_upgrade = Column(Boolean, comment="是否项目增配（增配用）")
    
    # ===== 扩展信息 =====
    # 用于存储各类型特有的、不常查询的字段
    extra = Column(JSON, comment="""扩展信息（JSON）：
    - 设备到货：文件名、批次信息等
    - 设备上架：详细位置信息等
    - 设备增配：其他配置参数等
    """)
    remark = Column(Text, comment="备注")
    
    # ===== 时间戳 =====
    created_at = Column(TIMESTAMP, server_default=func.now(), index=True, comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # ===== 关系 =====
    items = relationship("WorkOrderItem", back_populates="work_order", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_batch_id", "batch_id"),
        Index("idx_operation_type", "operation_type"),
        Index("idx_status", "status"),
        Index("idx_work_order_status", "work_order_status"),
        Index("idx_work_order_number", "work_order_number"),
        Index("idx_arrival_order_number", "arrival_order_number"),
        Index("idx_source_order_number", "source_order_number"),
        Index("idx_creator", "creator"),
        Index("idx_datacenter", "datacenter"),
        Index("idx_project_number", "project_number"),
        Index("idx_created_at", "created_at"),
        Index("idx_parent_device_sn", "parent_device_sn"),
    )


class WorkOrderItem(Base):
    """工单明细表 - 存储每个设备的具体操作信息"""
    __tablename__ = "work_order_items"
    
    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True, comment="工单ID")
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True, comment="资产ID")
    
    # ===== 设备标识 =====
    asset_sn = Column(String(200), index=True, comment="设备序列号（冗余字段，便于查询）")
    asset_tag = Column(String(100), comment="资产标签（冗余字段）")
    
    # ===== 操作数据 =====
    # 根据operation_type存储不同的操作数据
    operation_data = Column(JSON, comment="""操作数据（JSON）：
    - 设备到货：{target_room_id, target_room_name, ...}
    - 设备上架：{cabinet_number, u_position_start, u_position_end, datacenter, room, ...}
    - 设备增配：{parent_device_sn, component_type, component_model, quantity, ...}
    - 其他：根据具体操作类型存储
    """)
    
    # ===== 位置信息（明细级别） =====
    # 某些操作类型可能每个设备的位置不同
    item_datacenter = Column(String(50), comment="该设备的机房")
    item_room = Column(String(50), comment="该设备的房间")
    item_cabinet = Column(String(50), comment="该设备的机柜")
    item_rack_position = Column(String(50), comment="该设备的机位")
    
    # ===== 状态和结果 =====
    status = Column(String(50), default="pending", index=True, comment="该项状态：pending/processing/completed/failed")
    result = Column(Text, comment="执行结果或错误信息")
    error_message = Column(Text, comment="错误详情")
    
    # ===== 执行信息 =====
    executed_at = Column(TIMESTAMP, comment="实际执行时间")
    executed_by = Column(String(100), comment="实际执行人")
    
    # ===== 时间戳 =====
    created_at = Column(TIMESTAMP, server_default=func.now(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # ===== 关系 =====
    work_order = relationship("WorkOrder", back_populates="items")
    asset = relationship("Asset", back_populates="work_order_items")
    
    __table_args__ = (
        Index("idx_work_order_id", "work_order_id"),
        Index("idx_asset_id", "asset_id"),
        Index("idx_asset_sn", "asset_sn"),
        Index("idx_status", "status"),
        Index("idx_executed_at", "executed_at"),
    )


