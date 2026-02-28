"""
IT资产管理系统 - 业务逻辑服务
包含资产管理的核心业务逻辑
"""

from sqlalchemy.orm import Session, joinedload, aliased
from sqlalchemy import and_, or_, func, desc, asc
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, date
from decimal import Decimal
import math
import json
import re

from app.models.asset_models import (
    Asset,
    AssetCategory,
    Vendor,
    Room,
    LifecycleStage,
    AssetLifecycleStatus,
    AssetChangeLog,
    MaintenanceRecord,
    NetworkConnection,
    DictItem,
    DictType,
    WorkOrder,
    WorkOrderItem,
)
from app.schemas.asset_schemas import (
    AssetCreate, AssetUpdate, AssetSearchParams, PaginationParams,
    AssetDetailResponse, AssetStatistics, DepartmentStatistics,
    CategoryStatistics, LocationStatistics
)
from app.core.logging_config import get_logger

logger = get_logger(__name__)

class AssetService:
    """资产管理服务"""
    
    CATEGORY_DICT_TYPE = "asset_category"
    CATEGORY_LEVEL_MAPPING = {
        1: 1,
        2: 2,
        3: 3,
    }
    
    def __init__(self, db: Session):
        self.db = db
        self._asset_columns = {column.name for column in Asset.__table__.columns}
        self._dict_type_cache: Dict[str, int] = {}
    
    # =====================================================
    # 资产基础CRUD操作
    # =====================================================
    
    def create_asset(
        self, 
        asset_data: AssetCreate, 
        operator: str = "system",
        extra_fields: Optional[Dict[str, Any]] = None
    ) -> Asset:
        """创建资产"""
        # 检查资产标签是否已存在
        existing_asset = self.db.query(Asset).filter(Asset.asset_tag == asset_data.asset_tag).first()
        if existing_asset:
            raise ValueError(f"资产标签 {asset_data.asset_tag} 已存在")
        
        payload = asset_data.dict(exclude_none=True)
        if extra_fields:
            for key, value in extra_fields.items():
                if value is not None:
                    payload[key] = value
        
        payload = {key: value for key, value in payload.items() if key in self._asset_columns}
        
        if "category_id" not in payload or payload["category_id"] is None:
            default_category = self._get_default_category()
            if not default_category:
                raise ValueError("系统未配置任何资产分类，请先创建分类")
            payload["category_id"] = default_category.id
        
        # 设置创建人（使用owner字段）
        if "owner" not in payload or payload["owner"] is None:
            payload["owner"] = operator
        
        # 创建资产
        asset = Asset(**payload)
        self.db.add(asset)
        self.db.flush()  # 获取ID
        
        # 记录变更日志
        self._log_asset_change(
            asset_id=asset.id,
            change_type="create",
            new_value=f"创建资产: {asset.name}",
            operator=operator
        )
        
        # 注意：设备导入时只创建资产记录，不创建生命周期状态
        # 生命周期状态应该在真正的业务操作（如设备到货、设备上架）时才创建
        
        self.db.commit()
        return asset
    
    def get_asset(self, asset_id: int) -> Optional[Asset]:
        """获取单个资产"""
        return self.db.query(Asset).filter(Asset.id == asset_id).first()
    
    def get_asset_by_tag(self, asset_tag: str) -> Optional[Asset]:
        """根据资产标签获取资产"""
        return self.db.query(Asset).filter(Asset.asset_tag == asset_tag).first()
    
    def get_asset_by_serial_number(self, serial_number: str) -> Optional[Asset]:
        """根据序列号获取资产"""
        return self.db.query(Asset).filter(Asset.serial_number == serial_number).first()
    
    def update_asset(self, asset_id: int, asset_data: AssetUpdate, operator: str = "system") -> Optional[Asset]:
        """更新资产"""
        asset = self.get_asset(asset_id)
        if not asset:
            return None
        
        # 记录变更前的值
        old_values = {}
        update_data = asset_data.dict(exclude_unset=True)
        
        for field, new_value in update_data.items():
            old_value = getattr(asset, field)
            if old_value != new_value:
                old_values[field] = old_value
                setattr(asset, field, new_value)
        
        # 记录变更日志
        for field, old_value in old_values.items():
            self._log_asset_change(
                asset_id=asset_id,
                change_type="update",
                field_name=field,
                old_value=str(old_value),
                new_value=str(getattr(asset, field)),
                operator=operator
            )
        
        self.db.commit()
        return asset
    
    def delete_asset(self, asset_id: int, operator: str = "system") -> bool:
        """删除资产"""
        asset = self.get_asset(asset_id)
        if not asset:
            return False
        
        # 记录删除日志
        self._log_asset_change(
            asset_id=asset_id,
            change_type="delete",
            old_value=f"删除资产: {asset.name}",
            operator=operator
        )
        
        # 删除资产（关联的生命周期状态、变更日志等会通过cascade自动删除）
        self.db.delete(asset)
        self.db.commit()
        return True
    
    # =====================================================
    # 资产导入
    # =====================================================
    
    def import_assets_from_records(self, records: List[Dict[str, Any]], operator: str = "system") -> Dict[str, Any]:
        """根据Excel解析后的数据批量导入资产"""
        if not records:
            return {"success_count": 0, "failure_count": 0, "errors": []}
        
        success_count = 0
        errors: List[Dict[str, Any]] = []
        created_asset_ids: List[int] = []
        
        for row_index, raw_row in enumerate(records, start=2):  # Excel数据从第2行开始（第1行为标题）
            if self._is_row_empty(raw_row):
                continue
            
            try:
                payload = self._build_asset_payload_from_row(raw_row, row_index)
                asset = self.create_asset(
                    AssetCreate(**payload["schema"]),
                    operator=operator,
                    extra_fields=payload["extra"]
                )
                created_asset_ids.append(asset.id)
                success_count += 1
            except ValueError as exc:
                self.db.rollback()
                errors.append({
                    "row": row_index,
                    "serial_number": self._clean_str(raw_row.get("SN")),
                    "error": str(exc)
                })
            except Exception as exc:
                self.db.rollback()
                logger.exception("Asset import unexpected error", extra={"row": row_index, "sn": raw_row.get("SN")})
                errors.append({
                    "row": row_index,
                    "serial_number": self._clean_str(raw_row.get("SN")),
                    "error": "系统内部错误，请稍后重试"
                })
        
        return {
            "success_count": success_count,
            "failure_count": len(errors),
            "errors": errors,
            "created_asset_ids": created_asset_ids
        }
    
    # =====================================================
    # 资产查询和搜索
    # =====================================================
    
    def search_assets(
        self, 
        search_params: AssetSearchParams, 
        pagination: PaginationParams,
        datacenter: Optional[str] = None
    ) -> Tuple[List[Asset], int]:
        """搜索资产"""
        query = self.db.query(Asset)
        
        # 应用搜索条件
        if search_params.asset_tag:
            query = query.filter(Asset.asset_tag.like(f"%{search_params.asset_tag}%"))
        
        if search_params.name:
            query = query.filter(Asset.name.like(f"%{search_params.name}%"))
        
        if search_params.serial_number:
            query = query.filter(Asset.serial_number.like(f"%{search_params.serial_number}%"))
        
        if search_params.asset_status:
            query = query.filter(Asset.asset_status == search_params.asset_status)

        if search_params.lifecycle_status:
            query = query.filter(Asset.lifecycle_status == search_params.lifecycle_status)

        if search_params.device_direction:
            query = query.filter(Asset.device_direction == search_params.device_direction)

        if search_params.is_available is not None:
            query = query.filter(Asset.is_available == search_params.is_available)
        
        if search_params.room_id:
            query = query.filter(Asset.room_id == search_params.room_id)
        if datacenter:
            query = query.join(Room, Asset.room_id == Room.id).filter(Room.datacenter_abbreviation == datacenter)
        
        if search_params.category:
            level1_alias = aliased(DictItem)
            query = query.join(level1_alias, Asset.category_item).filter(
                level1_alias.item_label.like(f"%{search_params.category}%")
            )
        
        if search_params.secondary_category:
            level2_alias = aliased(DictItem)
            query = query.join(level2_alias, Asset.secondary_category_item).filter(
                level2_alias.item_label.like(f"%{search_params.secondary_category}%")
            )
        
        if search_params.tertiary_category:
            level3_alias = aliased(DictItem)
            query = query.join(level3_alias, Asset.tertiary_category_item).filter(
                level3_alias.item_label.like(f"%{search_params.tertiary_category}%")
            )
        
        # 创建时间范围查询
        if search_params.created_from:
            query = query.filter(Asset.created_at >= search_params.created_from)
        
        if search_params.created_to:
            query = query.filter(Asset.created_at <= search_params.created_to)
        
        # 获取总数
        total = query.count()
        
        # 按创建时间倒序排列
        query = query.order_by(Asset.created_at.desc())
        
        # 应用分页
        offset = (pagination.page - 1) * pagination.size
        assets = query.offset(offset).limit(pagination.size).all()
        
        return assets, total
    
    def update_asset_availability(self, asset_id: int, is_available: bool, unavailable_reason: Optional[str] = None) -> Asset:
        """更新资产可用状态"""
        asset = self.db.query(Asset).filter(Asset.id == asset_id).first()
        if not asset:
            raise ValueError("资产不存在")
        
        # 更新可用状态
        asset.is_available = is_available
        
        # 更新不可用原因
        if is_available:
            # 设置为可用时，清空不可用原因
            asset.unavailable_reason = None
        else:
            # 设置为不可用时，更新不可用原因
            asset.unavailable_reason = unavailable_reason or "未指定原因"
        
        # 保存更改
        self.db.commit()
        self.db.refresh(asset)
        
        return asset
    
    def get_asset_detail(self, asset_id: int) -> Optional[Dict[str, Any]]:
        """获取资产详细信息"""
        asset = self.db.query(Asset).options(
            joinedload(Asset.room)
        ).filter(Asset.id == asset_id).first()
        
        if not asset:
            return None
        
        # 构建位置信息
        location_info = None
        if asset.room:
            room = asset.room
            location_info = {
                "room_abbreviation": room.room_abbreviation,
                "room_full_name": room.room_full_name,
                "datacenter_abbreviation": room.datacenter_abbreviation,
                "building_number": room.building_number,
                "floor_number": room.floor_number,
                "location_detail": asset.location_detail,
                "full_location": self._build_full_location(asset)
            }
        
        # 获取生命周期状态
        lifecycle_stages = self.db.query(AssetLifecycleStatus).options(
            joinedload(AssetLifecycleStatus.stage)
        ).filter(AssetLifecycleStatus.asset_id == asset_id).all()

        # 最新工单
        latest_work_order = (
            self.db.query(WorkOrder, WorkOrderItem)
            .join(WorkOrderItem, WorkOrderItem.work_order_id == WorkOrder.id)
            .filter(WorkOrderItem.asset_id == asset_id)
            .order_by(WorkOrder.created_at.desc())
            .first()
        )
        work_order_summary = None
        vendor_standard_model = None
        if latest_work_order:
            order, item = latest_work_order
            work_order_summary = {
                "work_order_id": order.id,
                "batch_id": order.batch_id,
                "work_order_number": order.work_order_number,
                "operation_type": order.operation_type,
                "title": order.title,
                "status": order.status,
                "work_order_status": order.work_order_status,
                "created_at": order.created_at,
                "completed_time": order.completed_time,
                "item_status": item.status,
                "item_result": item.result,
            }
            if order.operation_type == "receiving":
                vendor_standard_model = (
                    (item.operation_data or {}).get("vendor_standard_model")
                    if hasattr(item, "operation_data") and item.operation_data
                    else None
                )

        # 如果资产本身没有厂商标准机型，则尝试使用最近到货工单的信息
        if not getattr(asset, "vendor_standard_model", None) and vendor_standard_model:
            setattr(asset, "vendor_standard_model", vendor_standard_model)

        return {
            "asset": asset,
            "location_info": location_info,
            "lifecycle_stages": lifecycle_stages,
            "latest_work_order": work_order_summary,
        }
    
    # =====================================================
    # 生命周期管理
    # =====================================================
    
    def update_lifecycle_status(
        self, 
        asset_id: int, 
        stage_id: int, 
        status: str, 
        responsible_person: str = None,
        notes: str = None,
        operator: str = "system"
    ) -> bool:
        """更新资产生命周期状态"""
        lifecycle_status = self.db.query(AssetLifecycleStatus).filter(
            and_(
                AssetLifecycleStatus.asset_id == asset_id,
                AssetLifecycleStatus.stage_id == stage_id
            )
        ).first()
        
        if not lifecycle_status:
            # 创建新的生命周期状态
            lifecycle_status = AssetLifecycleStatus(
                asset_id=asset_id,
                stage_id=stage_id,
                status=status,
                start_date=datetime.now() if status == "in_progress" else None,
                responsible_person=responsible_person,
                notes=notes
            )
            self.db.add(lifecycle_status)
        else:
            # 更新现有状态
            old_status = lifecycle_status.status
            lifecycle_status.status = status
            
            if status == "in_progress" and old_status != "in_progress":
                lifecycle_status.start_date = datetime.now()
            elif status == "completed" and old_status != "completed":
                lifecycle_status.end_date = datetime.now()
            
            if responsible_person:
                lifecycle_status.responsible_person = responsible_person
            if notes:
                lifecycle_status.notes = notes
        
        # 记录变更日志
        stage = self.db.query(LifecycleStage).filter(LifecycleStage.id == stage_id).first()
        stage_name = stage.stage_name if stage else f"阶段{stage_id}"
        
        self._log_asset_change(
            asset_id=asset_id,
            change_type="status_change",
            field_name="lifecycle_status",
            new_value=f"{stage_name}: {status}",
            operator=operator
        )
        
        self.db.commit()
        return True
    
    def get_assets_by_lifecycle_stage(self, stage_id: int, status: str = None) -> List[Asset]:
        """获取处于特定生命周期阶段的资产"""
        query = self.db.query(Asset).join(AssetLifecycleStatus).filter(
            AssetLifecycleStatus.stage_id == stage_id
        )
        
        if status:
            query = query.filter(AssetLifecycleStatus.status == status)
        
        return query.all()
    
    # =====================================================
    # 位置管理（简化版 - 只管理房间）
    # =====================================================
    
    def assign_room(self, asset_id: int, room_id: int, location_detail: str = None, operator: str = "system") -> bool:
        """分配房间"""
        asset = self.get_asset(asset_id)
        if not asset:
            return False
        
        # 检查房间是否存在
        room = self.db.query(Room).filter(Room.id == room_id).first()
        if not room:
            return False
        
        old_room_id = asset.room_id
        old_location_detail = asset.location_detail
        
        # 分配新房间
        asset.room_id = room_id
        if location_detail:
            asset.location_detail = location_detail
        
        # 记录变更日志
        self._log_asset_change(
            asset_id=asset_id,
            change_type="move",
            field_name="room_id",
            old_value=str(old_room_id) if old_room_id else None,
            new_value=str(room_id),
            change_reason="房间分配",
            operator=operator
        )
        
        if location_detail and old_location_detail != location_detail:
            self._log_asset_change(
                asset_id=asset_id,
                change_type="update",
                field_name="location_detail",
                old_value=old_location_detail,
                new_value=location_detail,
                operator=operator
            )
        
        self.db.commit()
        return True
    
    def release_room(self, asset_id: int, operator: str = "system") -> bool:
        """释放房间"""
        asset = self.get_asset(asset_id)
        if not asset or not asset.room_id:
            return False
        
        old_room_id = asset.room_id
        old_location_detail = asset.location_detail
        
        asset.room_id = None
        asset.location_detail = None
        
        # 记录变更日志
        self._log_asset_change(
            asset_id=asset_id,
            change_type="move",
            field_name="room_id",
            old_value=str(old_room_id),
            new_value=None,
            change_reason="释放房间",
            operator=operator
        )
        
        self.db.commit()
        return True
    
    # =====================================================
    # 统计分析
    # =====================================================
    
    def get_asset_statistics(self) -> AssetStatistics:
        """获取资产统计信息"""
        total_assets = self.db.query(Asset).count()
        
        status_counts = self.db.query(
            Asset.asset_status,
            func.count(Asset.id)
        ).group_by(Asset.asset_status).all()
        
        status_dict = {status: count for status, count in status_counts}
        
        return AssetStatistics(
            total_assets=total_assets,
            active_assets=status_dict.get('active', 0),
            inactive_assets=status_dict.get('inactive', 0),
            maintenance_assets=status_dict.get('maintenance', 0),
            retired_assets=status_dict.get('retired', 0),
            disposed_assets=status_dict.get('disposed', 0),
            total_value=Decimal('0')  # 已移除采购价格字段，总价值设为0
        )
    
    def get_department_statistics(self) -> List[DepartmentStatistics]:
        """获取部门资产统计（已移除部门字段，返回空列表）"""
        # 部门字段已移除，返回空列表
        return []
    
    def get_category_statistics(self) -> List[CategoryStatistics]:
        """获取分类资产统计（已移除分类字段，返回空列表）"""
        # 分类字段已移除，返回空列表
        return []
    
    # =====================================================
    # 私有辅助方法
    # =====================================================
    
    def _log_asset_change(
        self, 
        asset_id: int, 
        change_type: str, 
        operator: str,
        field_name: str = None,
        old_value: str = None,
        new_value: str = None,
        change_reason: str = None
    ):
        """记录资产变更日志"""
        change_log = AssetChangeLog(
            asset_id=asset_id,
            change_type=change_type,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            change_reason=change_reason,
            operator=operator
        )
        self.db.add(change_log)
    
    def _initialize_lifecycle_status(self, asset_id: int, operator: str):
        """初始化资产生命周期状态"""
        # 获取所有生命周期阶段
        stages = self.db.query(LifecycleStage).order_by(LifecycleStage.sequence_order).all()
        
        for stage in stages:
            status = AssetLifecycleStatus(
                asset_id=asset_id,
                stage_id=stage.id,
                status="not_started",
                responsible_person=operator
            )
            self.db.add(status)
    
    def _build_full_location(self, asset: Asset) -> str:
        """构建完整位置信息（简化版）"""
        if not asset or not asset.room:
            return ""
        
        room = asset.room
        parts = []
        
        # 添加机房信息
        if room.datacenter_abbreviation:
            parts.append(room.datacenter_abbreviation)
        
        # 添加楼层信息
        if room.building_number and room.floor_number:
            parts.append(f"{room.building_number}楼{room.floor_number}层")
        
        # 添加房间信息
        parts.append(room.room_full_name)
        
        # 添加具体位置
        if asset.location_detail:
            parts.append(asset.location_detail)
        
        return " → ".join(parts)

    def _build_asset_payload_from_row(self, row: Dict[str, Any], row_number: int) -> Dict[str, Dict[str, Any]]:
        sn = self._clean_str(row.get("SN"))
        if not sn:
            raise ValueError(f"第{row_number}行缺少SN，无法导入")
        
        model_name = self._clean_str(row.get("型号"))
        asset_name = model_name or sn
        quantity = self._parse_quantity(row.get("数量"))
        is_available = self._parse_bool(row.get("是否可用"))
        unavailable_reason_raw = self._clean_str(row.get("不可用原因"))
        unavailable_reason = unavailable_reason_raw if not is_available else None
        if not is_available and not unavailable_reason:
            unavailable_reason = "导入标记为不可用"
        
        device_direction = self._clean_str(row.get("设备去向"))
        order_number = self._clean_str(row.get("出入库单号"))
        mpn = self._clean_str(row.get("MPN"))
        machine_model = self._clean_str(row.get("机型"))
        three_stage_model = self._clean_str(row.get("三段机型"))
        vendor_standard_model = self._clean_str(row.get("厂商标准机型"))
        vendor_name = self._clean_str(row.get("厂商"))
        datacenter = self._clean_str(row.get("机房"))
        room_value = self._clean_str(row.get("房间"))
        
        # 如果只有机房列有值且包含分隔符，尝试解析为"机房-房间"格式
        # if datacenter and not room_value and "-" in datacenter:
        #     parts = datacenter.split("-", 1)
        #     if len(parts) == 2:
        #         datacenter, room_value = parts[0].strip(), parts[1].strip()
        category_level1 = self._clean_str(row.get("一级分类"))
        category_level2 = self._clean_str(row.get("二级分类"))
        category_level3 = self._clean_str(row.get("三级分类"))
        primary_category_item = self._get_category_dict_item(1, category_level1)
        secondary_category_item = self._get_category_dict_item(2, category_level2, parent=primary_category_item) if category_level2 else None
        tertiary_category_item = self._get_category_dict_item(3, category_level3, parent=secondary_category_item) if category_level3 else None
        category_id = self._sync_category_hierarchy(primary_category_item, secondary_category_item, tertiary_category_item)
        vendor = self._get_or_create_vendor(vendor_name) if vendor_name else None
        room_id = self._resolve_room_id(datacenter, room_value) if room_value else None
        
        notes_payload = {}
        if order_number:
            notes_payload["order_number"] = order_number
        if mpn:
            notes_payload["mpn"] = mpn
        if machine_model:
            notes_payload["machine_model"] = machine_model
        if three_stage_model:
            notes_payload["three_stage_model"] = three_stage_model
        notes = json.dumps(notes_payload, ensure_ascii=False) if notes_payload else None
        location_detail = room_value
        
        schema_payload = {
            "asset_tag": sn,
            "name": asset_name,
            "serial_number": sn,
            "room_id": room_id,
            "datacenter_abbreviation": datacenter,
            "quantity": quantity,
            "is_available": is_available,
            "unavailable_reason": unavailable_reason,
            "location_detail": location_detail,
            "asset_status": "active",
            "lifecycle_status": "registered",
            "device_direction": device_direction or "inbound",
            "notes": notes,
            "owner": None  # owner将在create_asset中设置为operator
        }
        
        extra_payload = {
            "category_id": category_id,
            "category_item_id": primary_category_item.id,
            "secondary_category_item_id": secondary_category_item.id if secondary_category_item else None,
            "tertiary_category_item_id": tertiary_category_item.id if tertiary_category_item else None,
            "vendor_id": vendor.id if vendor else None,
        }
        if model_name:
            extra_payload["model"] = model_name
        if vendor_standard_model:
            extra_payload["vendor_standard_model"] = vendor_standard_model
        
        return {"schema": schema_payload, "extra": extra_payload}
    
    def _is_row_empty(self, row: Dict[str, Any]) -> bool:
        return all(self._clean_str(value) is None for value in row.values())
    
    def _clean_str(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, float):
            if math.isnan(value):
                return None
        text = str(value).strip()
        return text if text else None
    
    def _parse_quantity(self, value: Any) -> int:
        if value is None:
            return 1
        try:
            if isinstance(value, str):
                value = value.strip()
            quantity = int(float(value))
        except (TypeError, ValueError):
            return 1
        return quantity if quantity > 0 else 1
    
    def _parse_bool(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value).strip().lower()
        if not text:
            return True
        if text in {"0", "false", "no", "n", "否", "不可用"}:
            return False
        if text in {"1", "true", "yes", "y", "是", "可用"}:
            return True
        return True
    
    def _parse_device_direction(self, value: Optional[str]) -> str:
        if value is None:
            return "inbound"
        if isinstance(value, bool):
            return "inbound" if value else "outbound"
        text = str(value).strip().lower()
        if not text:
            return "inbound"
        outbound_values = {"outbound", "出库", "false", "0", "no", "n"}
        return "outbound" if text in outbound_values else "inbound"
    
    def _sync_category_hierarchy(
        self,
        level1_item: DictItem,
        level2_item: Optional[DictItem] = None,
        level3_item: Optional[DictItem] = None,
    ) -> int:
        if not level1_item:
            raise ValueError("一级分类不能为空")
        
        current_category = self._get_or_create_category_from_dict_item(level1_item, None)
        latest_category = current_category
        
        if level2_item:
            latest_category = self._get_or_create_category_from_dict_item(level2_item, latest_category)
        if level3_item:
            latest_category = self._get_or_create_category_from_dict_item(level3_item, latest_category)
        
        return latest_category.id
    
    def _get_or_create_category_from_dict_item(
        self,
        dict_item: DictItem,
        parent_category: Optional[AssetCategory]
    ) -> AssetCategory:
        query = self.db.query(AssetCategory).filter(
            AssetCategory.code == dict_item.item_code
        )
        if parent_category:
            query = query.filter(AssetCategory.parent_id == parent_category.id)
        else:
            query = query.filter(AssetCategory.parent_id.is_(None))
        
        category = query.first()
        if category:
            return category
        
        category = AssetCategory(
            name=dict_item.item_label,
            code=dict_item.item_code,
            parent_id=parent_category.id if parent_category else None,
            description=dict_item.item_value,
        )
        self.db.add(category)
        self.db.flush()
        return category
    
    def _generate_category_code(self, name: str) -> str:
        base = self._slugify(name) or "CAT"
        code = base
        counter = 1
        while self.db.query(AssetCategory).filter(AssetCategory.code == code).first():
            counter += 1
            code = f"{base}_{counter}"
        return code
    
    def _get_or_create_vendor(self, name: str) -> Optional[Vendor]:
        if not name:
            return None
        vendor = self.db.query(Vendor).filter(func.lower(Vendor.name) == name.lower()).first()
        if vendor:
            return vendor
        
        code = self._generate_vendor_code(name)
        vendor = Vendor(name=name, code=code)
        self.db.add(vendor)
        self.db.flush()
        return vendor
    
    def _generate_vendor_code(self, name: str) -> str:
        base = self._slugify(name) or "VENDOR"
        code = base
        counter = 1
        while self.db.query(Vendor).filter(Vendor.code == code).first():
            counter += 1
            code = f"{base}_{counter}"
        return code
    
    def _slugify(self, value: str) -> str:
        return re.sub(r'[^0-9A-Za-z]+', '_', value).strip('_').upper()
    
    def _resolve_room_id(self, datacenter: Optional[str], room_value: Optional[str]) -> Optional[int]:
        if not room_value:
            return None
        
        query = self.db.query(Room)
        room_value_lower = room_value.lower()
        
        def _match_clause():
            return or_(
                func.lower(Room.room_full_name) == room_value_lower,
                func.lower(Room.room_abbreviation) == room_value_lower,
                func.lower(Room.room_number) == room_value_lower
            )
        
        if datacenter:
            query = query.filter(func.lower(Room.datacenter_abbreviation) == datacenter.lower())
        
        room = query.filter(_match_clause()).first()
        if not room:
            # 如果在指定机房下没找到，尝试在所有房间中查找
            room = self.db.query(Room).filter(_match_clause()).first()
        
        if not room:
            logger.warning(
                "Room not found during asset import",
                extra={"datacenter": datacenter, "room_value": room_value}
            )
        
        return room.id if room else None
    
    def _get_default_category(self) -> Optional[AssetCategory]:
        return self.db.query(AssetCategory).order_by(AssetCategory.id).first()

    def _get_category_dict_item(
        self,
        level: int,
        label: Optional[str],
        parent: Optional[DictItem] = None
    ) -> DictItem:
        if not label:
            raise ValueError(f"{level}级分类不能为空")
        
        dict_type = self.db.query(DictType).filter(DictType.type_code == self.CATEGORY_DICT_TYPE).first()
        if not dict_type:
            raise ValueError(f"未找到分类数据字典类型 {self.CATEGORY_DICT_TYPE}")
        
        query = self.db.query(DictItem).filter(
            DictItem.type_id == dict_type.id,
            func.lower(DictItem.item_label) == label.lower()
        )
        if parent:
            query = query.filter(
                DictItem.item_value.contains(f"\"parent_code\": \"{parent.item_code}\"")
            )
        else:
            query = query.filter(
                DictItem.item_value.contains("\"parent_code\": null")
            )
        
        item = query.first()
        if not item:
            raise ValueError(f"{level}级分类 '{label}' 不在数据字典 {self.CATEGORY_DICT_TYPE} 中")
        return item


class LocationService:
    """位置管理服务（简化版 - 只管理房间）"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_all_rooms(self) -> List[Room]:
        """获取所有房间"""
        return self.db.query(Room).options(joinedload(Room.room_type_rel)).filter(Room.status == 1).all()
    
    def get_room_by_id(self, room_id: int) -> Optional[Room]:
        """根据ID获取房间"""
        return self.db.query(Room).options(joinedload(Room.room_type_rel)).filter(Room.id == room_id).first()
    
    def get_rooms_by_datacenter(self, datacenter_abbreviation: str) -> List[Room]:
        """根据机房缩写获取房间"""
        return self.db.query(Room).filter(
            Room.datacenter_abbreviation == datacenter_abbreviation,
            Room.status == 1
        ).all()

    def get_distinct_datacenters(self) -> List[str]:
        """获取已有房间涉及的机房/园区缩写列表"""
        rows = (
            self.db.query(Room.datacenter_abbreviation)
            .filter(Room.status == 1, Room.datacenter_abbreviation.isnot(None))
            .distinct()
            .order_by(Room.datacenter_abbreviation)
            .all()
        )
        return [row[0] for row in rows]

    def get_rooms_by_building_floor(self, building_number: str, floor_number: str) -> List[Room]:
        """根据楼号和楼层获取房间"""
        return self.db.query(Room).filter(
            Room.building_number == building_number,
            Room.floor_number == floor_number,
            Room.status == 1
        ).all()

    def get_distinct_buildings(self, datacenter_abbreviation: Optional[str] = None) -> List[str]:
        """获取现有房间的楼号列表"""
        query = self.db.query(Room.building_number).filter(Room.status == 1, Room.building_number.isnot(None))
        if datacenter_abbreviation:
            query = query.filter(Room.datacenter_abbreviation == datacenter_abbreviation)
        rows = query.distinct().order_by(Room.building_number).all()
        return [row[0] for row in rows]

    def get_floors_by_building(
        self,
        building_number: str,
        datacenter_abbreviation: Optional[str] = None
    ) -> List[str]:
        """获取指定楼号下的楼层列表"""
        query = self.db.query(Room.floor_number).filter(
            Room.status == 1,
            Room.building_number == building_number,
            Room.floor_number.isnot(None)
        )
        if datacenter_abbreviation:
            query = query.filter(Room.datacenter_abbreviation == datacenter_abbreviation)
        rows = query.distinct().order_by(Room.floor_number).all()
        return [row[0] for row in rows]

    def get_distinct_floors(self, datacenter_abbreviation: Optional[str] = None) -> List[str]:
        """获取所有房间涉及的楼层列表"""
        query = self.db.query(Room.floor_number).filter(Room.status == 1, Room.floor_number.isnot(None))
        if datacenter_abbreviation:
            query = query.filter(Room.datacenter_abbreviation == datacenter_abbreviation)
        rows = query.distinct().order_by(Room.floor_number).all()
        return [row[0] for row in rows]

    def get_distinct_room_numbers(self, datacenter_abbreviation: Optional[str] = None) -> List[str]:
        """获取所有房间号列表，可按机房过滤"""
        query = self.db.query(Room.room_number).filter(Room.status == 1, Room.room_number.isnot(None))
        if datacenter_abbreviation:
            query = query.filter(Room.datacenter_abbreviation == datacenter_abbreviation)
        rows = query.distinct().order_by(Room.room_number).all()
        return [row[0] for row in rows]

    def search_rooms(
        self, 
        datacenter_abbreviation: Optional[str] = None,
        building_number: Optional[str] = None,
        floor_number: Optional[str] = None,
        room_number: Optional[str] = None,
        room_type_id: Optional[int] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        notes_keyword: Optional[str] = None,
    ) -> List[Room]:
        """多条件搜索房间"""
        # 使用 joinedload 加载 room_type_rel 关系，避免 N+1 查询
        query = self.db.query(Room).options(joinedload(Room.room_type_rel)).filter(Room.status == 1)
        
        # 按机房缩写筛选
        if datacenter_abbreviation:
            query = query.filter(Room.datacenter_abbreviation == datacenter_abbreviation)
        
        # 按楼号筛选
        if building_number:
            query = query.filter(Room.building_number == building_number)
        
        # 按楼层筛选
        if floor_number:
            query = query.filter(Room.floor_number == floor_number)
        # 按房间号筛选
        if room_number:
            query = query.filter(Room.room_number == room_number)
        
        # 按房间类型筛选
        if room_type_id:
            query = query.filter(Room.room_type_id == room_type_id)
        
        # 按创建时间范围筛选
        if created_from:
            query = query.filter(Room.created_at >= created_from)
        if created_to:
            query = query.filter(Room.created_at <= created_to)
        if notes_keyword:
            query = query.filter(Room.notes.isnot(None), Room.notes.ilike(f"%{notes_keyword}%"))
        
        return query.order_by(Room.created_at.desc()).all()
    
    def create_room(self, room_data: dict) -> Room:
        """创建房间"""
        room = Room(**room_data)
        self.db.add(room)
        self.db.commit()
        self.db.refresh(room)
        return room
    
    def update_room(self, room_id: int, room_data: dict) -> Optional[Room]:
        """更新房间"""
        room = self.get_room_by_id(room_id)
        if not room:
            return None
        
        for key, value in room_data.items():
            if hasattr(room, key):
                setattr(room, key, value)
        
        self.db.commit()
        self.db.refresh(room)
        return room
    
    def delete_room(self, room_id: int) -> bool:
        """删除房间（软删除）"""
        room = self.get_room_by_id(room_id)
        if not room:
            return False
        
        room.status = 0
        self.db.commit()
        return True


# =====================================================
# 注意：暂存审核管理服务已废弃，功能已迁移到WorkOrder统一工单系统
# =====================================================


