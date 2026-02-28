"""
统一资产关联关系表设计
用于统一管理所有资产之间的关联关系，便于扩展
"""

from sqlalchemy import (
    Column, Integer, String, Text, DECIMAL, DateTime, 
    Boolean, Enum, ForeignKey, UniqueConstraint, Index, func, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mysql import TINYINT, TIMESTAMP
from app.db.session import Base


class AssetRelationshipType(Base):
    """资产关联类型定义表（字典表）"""
    __tablename__ = "asset_relationship_types"
    
    id = Column(Integer, primary_key=True, index=True)
    type_code = Column(String(50), unique=True, nullable=False, comment="关联类型编码（如：upstream, downstream, network, power, etc.）")
    type_name = Column(String(100), nullable=False, comment="关联类型名称（中文）")
    description = Column(Text, comment="类型描述")
    direction_type = Column(String(20), default="bidirectional", comment="方向类型：unidirectional-单向, bidirectional-双向")
    is_active = Column(TINYINT, default=1, comment="是否启用：1-启用，0-禁用")
    sequence_order = Column(Integer, default=0, comment="显示顺序")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    relationships = relationship("AssetRelationship", back_populates="relationship_type")
    
    __table_args__ = (
        Index('idx_type_code', 'type_code'),
        Index('idx_is_active', 'is_active'),
    )


class AssetRelationship(Base):
    """统一资产关联关系表（核心表）"""
    __tablename__ = "asset_relationships"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # 关联的两个资产
    source_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, comment="源资产ID")
    target_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, comment="目标资产ID")
    
    # 关联类型（通过字典表管理，便于扩展）
    relationship_type_id = Column(Integer, ForeignKey("asset_relationship_types.id"), nullable=False, comment="关联类型ID")
    
    # 关联属性（通用字段，JSON存储扩展信息）
    source_port = Column(String(100), comment="源端口/接口")
    target_port = Column(String(100), comment="目标端口/接口")
    connection_type = Column(String(50), comment="连接类型：ethernet-以太网, fiber-光纤, console-控制台, power-电源, other-其他")
    cable_type = Column(String(100), comment="线缆类型")
    cable_length = Column(DECIMAL(8, 2), comment="线缆长度（米）")
    bandwidth = Column(String(50), comment="带宽")
    
    # 扩展信息（JSON格式，便于存储不同类型的特定属性）
    relationship_attrs = Column(JSON, comment="关联扩展属性（JSON格式）")
    
    # 状态管理
    status = Column(TINYINT, default=1, comment="状态：1-正常，0-禁用")
    notes = Column(Text, comment="备注")
    
    # 审计字段
    created_by = Column(String(100), comment="创建人")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关系
    source_asset = relationship("Asset", foreign_keys=[source_asset_id], back_populates="source_relationships")
    target_asset = relationship("Asset", foreign_keys=[target_asset_id], back_populates="target_relationships")
    relationship_type = relationship("AssetRelationshipType", back_populates="relationships")
    
    __table_args__ = (
        # 同一对资产、同一类型只能有一条关联（单向关联）
        UniqueConstraint('source_asset_id', 'target_asset_id', 'relationship_type_id', name='uk_asset_relationship'),
        # 索引
        Index('idx_source_asset', 'source_asset_id'),
        Index('idx_target_asset', 'target_asset_id'),
        Index('idx_relationship_type', 'relationship_type_id'),
        Index('idx_status', 'status'),
        Index('idx_created_at', 'created_at'),
        # 复合索引用于常见查询
        Index('idx_source_type_status', 'source_asset_id', 'relationship_type_id', 'status'),
        Index('idx_target_type_status', 'target_asset_id', 'relationship_type_id', 'status'),
    )

