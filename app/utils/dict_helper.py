"""
数据字典辅助工具
提供统一的字典查询和验证功能
"""

from sqlalchemy.orm import Session
from app.models.asset_models import DictType, DictItem
from typing import List, Dict, Optional
from functools import lru_cache


def get_dict_items(db: Session, type_code: str, status_filter: bool = True) -> List[Dict]:
    """
    获取指定字典类型的所有字典项
    
    Args:
        db: 数据库会话
        type_code: 字典类型编码
        status_filter: 是否只返回启用的项（默认True）
    
    Returns:
        字典项列表，每项包含：code, label, value, color, icon
    
    Example:
        >>> items = get_dict_items(db, "asset_lifecycle_status")
        >>> # [{"code": "registered", "label": "已登记", ...}, ...]
    """
    dict_type = db.query(DictType).filter(
        DictType.type_code == type_code
    ).first()
    
    if not dict_type:
        return []
    
    query = db.query(DictItem).filter(DictItem.type_id == dict_type.id)
    
    if status_filter and dict_type.status == 1:
        query = query.filter(DictItem.status == 1)
    
    items = query.order_by(DictItem.sequence_order).all()
    
    return [
        {
            "code": item.item_code,
            "label": item.item_label,
            "value": item.item_value,
            "color": item.color,
            "icon": item.icon,
            "remark": item.remark
        }
        for item in items
    ]


def get_dict_label(db: Session, type_code: str, item_code: str) -> Optional[str]:
    """
    获取字典项的显示名称
    
    Args:
        db: 数据库会话
        type_code: 字典类型编码
        item_code: 字典项编码
    
    Returns:
        字典项的label，如果不存在返回None
    
    Example:
        >>> label = get_dict_label(db, "asset_lifecycle_status", "registered")
        >>> # "已登记"
    """
    dict_type = db.query(DictType).filter(DictType.type_code == type_code).first()
    if not dict_type:
        return None
    
    item = db.query(DictItem).filter(
        DictItem.type_id == dict_type.id,
        DictItem.item_code == item_code,
        DictItem.status == 1
    ).first()
    
    return item.item_label if item else None


def validate_dict_value(db: Session, type_code: str, item_code: str) -> bool:
    """
    验证字典值是否有效
    
    Args:
        db: 数据库会话
        type_code: 字典类型编码
        item_code: 字典项编码
    
    Returns:
        True表示有效，False表示无效
    
    Example:
        >>> is_valid = validate_dict_value(db, "asset_lifecycle_status", "registered")
        >>> # True
    """
    dict_type = db.query(DictType).filter(
        DictType.type_code == type_code,
        DictType.status == 1
    ).first()
    
    if not dict_type:
        return False
    
    item = db.query(DictItem).filter(
        DictItem.type_id == dict_type.id,
        DictItem.item_code == item_code,
        DictItem.status == 1
    ).first()
    
    return item is not None


def get_dict_map(db: Session, type_code: str) -> Dict[str, str]:
    """
    获取字典类型的code->label映射
    
    Args:
        db: 数据库会话
        type_code: 字典类型编码
    
    Returns:
        {code: label}字典
    
    Example:
        >>> mapping = get_dict_map(db, "asset_lifecycle_status")
        >>> # {"registered": "已登记", "received": "已到货", ...}
    """
    items = get_dict_items(db, type_code)
    return {item["code"]: item["label"] for item in items}


def get_all_dict_types(db: Session) -> List[Dict]:
    """
    获取所有字典类型
    
    Args:
        db: 数据库会话
    
    Returns:
        字典类型列表
    """
    dict_types = db.query(DictType).filter(
        DictType.status == 1
    ).order_by(DictType.sequence_order).all()
    
    return [
        {
            "type_code": dt.type_code,
            "type_name": dt.type_name,
            "description": dt.description,
            "built_in": dt.built_in
        }
        for dt in dict_types
    ]


# 常用字典类型常量
class DictTypeCode:
    """字典类型编码常量"""
    # 资产相关
    ASSET_STATUS = "asset_status"  # 资产管理状态
    ASSET_LIFECYCLE_STATUS = "asset_lifecycle_status"  # 资产生命周期状态
    ASSET_CHANGE_TYPE = "asset_change_type"  # 资产变更类型
    
    # 工单相关
    WORK_ORDER_OPERATION_TYPE = "work_order_operation_type"  # 工单操作类型
    WORK_ORDER_STATUS = "work_order_status"  # 工单状态
    
    # 维护相关
    MAINTENANCE_TYPE = "maintenance_type"  # 维护类型
    MAINTENANCE_STATUS = "maintenance_status"  # 维护状态
    
    # 连接相关
    CONNECTION_TYPE = "connection_type"  # 连接类型
    
    # 生命周期相关
    LIFECYCLE_STAGE_STATUS = "lifecycle_stage_status"  # 生命周期阶段状态
