# models package
from app.models.models import User
from app.models.asset_models import *
from app.models.asset_relationships import AssetRelationship, AssetRelationshipType

__all__ = [
    "User",
    # 位置管理
    "RoomType",
    "Room",
    # 资产管理
    "AssetCategory",
    "Vendor",
    "Asset",
    # 生命周期
    "LifecycleStage",
    "AssetLifecycleStatus",
    # 工单管理（统一）
    "WorkOrder",
    "WorkOrderItem",
    # 上架批次（已迁移到WorkOrder）
    # "RackingBatch",
    # "RackingBatchItem",
    # 增配
    "AssetConfiguration",
    # 辅助管理
    "AssetChangeLog",
    "MaintenanceRecord",
    "NetworkConnection",
    # 数据字典
    "DictType",
    "DictItem",
    # 统一关联关系
    "AssetRelationship",
    "AssetRelationshipType",
]
