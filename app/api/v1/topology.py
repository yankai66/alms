"""
设备拓扑管理API
提供设备之间的拓扑关系管理（上联/下联）
基于 AssetConfiguration 表实现
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

from app.db.session import get_db
from app.schemas.asset_schemas import ApiResponse, ResponseCode
from app.models.asset_models import (
    Asset,
    AssetConfiguration,
    WorkOrder
)
# from app.models.asset_models import RackingBatch  # 已废弃，使用WorkOrder替代

router = APIRouter()


# =====================================================
# 请求/响应模型
# =====================================================

class TopologyConnectionCreate(BaseModel):
    """创建拓扑连接请求"""
    source_sn: str = Field(..., description="源设备SN（上联设备）*")
    target_sn: str = Field(..., description="目标设备SN（下联设备）*")
    connection_type: Optional[str] = Field(None, description="连接类型：ethernet-以太网, fiber-光纤, console-控制台, power-电源, other-其他")


class TopologyConnectionUpdate(BaseModel):
    """更新拓扑连接请求"""
    connection_type: Optional[str] = Field(None, description="连接类型")


def _resolve_racking_binding(
    db: Session,
    work_order_number: Optional[str],
    racking_batch_id: Optional[int]
):
    """根据传入的工单号或批次ID定位上架批次"""
    batch = None
    resolved_work_order = work_order_number
    
    if racking_batch_id is not None:
        # 使用WorkOrder替代RackingBatch
        batch = db.query(WorkOrder).filter(WorkOrder.id == racking_batch_id).first()
        if not batch:
            return None, None, ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"工单不存在: {racking_batch_id}",
                data=None,
                timestamp=datetime.now().isoformat()
            )
        resolved_work_order = resolved_work_order or batch.batch_id
    elif work_order_number:
        batch = db.query(WorkOrder).filter(WorkOrder.batch_id == work_order_number).first()
        if not batch:
            return None, None, ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"工单不存在: {work_order_number}",
                data=None,
                timestamp=datetime.now().isoformat()
            )
    
    return batch, resolved_work_order, None

# =====================================================
# 设备拓扑管理接口
# =====================================================

@router.get("/device/{sn}", summary="查询设备的完整拓扑")
async def get_device_topology(
    sn: str,
    db: Session = Depends(get_db)
):
    """查询指定设备的完整拓扑关系（包括所有上联和下联）"""
    try:
        # 检查设备是否存在
        asset = db.query(Asset).filter(Asset.serial_number == sn).first()
        if not asset:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到SN为 {sn} 的设备",
                data=None
            )
        
        asset_id = asset.id
        
        # 查询该设备作为主设备的所有连接（下联）
        downstream_configs = db.query(AssetConfiguration).options(
            joinedload(AssetConfiguration.related_asset)
        ).filter(
            and_(
                AssetConfiguration.asset_id == asset_id,
                AssetConfiguration.configuration_type == "downstream",
                AssetConfiguration.status == 1
            )
        ).all()
        
        # 查询该设备作为关联设备的所有连接（上联）
        # 如果其他设备的下联指向该设备，那么那些设备就是该设备的上联
        upstream_configs = db.query(AssetConfiguration).options(
            joinedload(AssetConfiguration.asset)
        ).filter(
            and_(
                AssetConfiguration.related_asset_id == asset_id,
                AssetConfiguration.configuration_type == "downstream",
                AssetConfiguration.status == 1
            )
        ).all()
        
        # 构建上联列表
        upstream_list = []
        for config in upstream_configs:
            upstream_list.append({
                "sn": config.asset.serial_number if config.asset else None,
                "is_company_device": config.asset.is_company_device if config.asset else True,
                "connection_type": config.connection_type,
                "work_order_number": config.work_order_number
            })
        
        # 构建下联列表
        downstream_list = []
        for config in downstream_configs:
            downstream_list.append({
                "sn": config.related_asset.serial_number if config.related_asset else None,
                "is_company_device": config.related_asset.is_company_device if config.related_asset else True,
                "connection_type": config.connection_type,
                "work_order_number": config.work_order_number
            })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "sn": asset.serial_number,
                "is_company_device": asset.is_company_device,
                "upstream": upstream_list,  # 上联设备列表
                "downstream": downstream_list,  # 下联设备列表
                "upstream_count": len(upstream_list),
                "downstream_count": len(downstream_list)
            }
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.get("/device/{sn}/upstream", summary="查询设备的上联列表")
async def get_device_upstream(
    sn: str,
    db: Session = Depends(get_db)
):
    """查询指定设备的所有上联设备"""
    try:
        asset = db.query(Asset).filter(Asset.serial_number == sn).first()
        if not asset:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到SN为 {sn} 的设备",
                data=None
            )
        
        asset_id = asset.id
        
        # 查询上联（该设备作为关联设备）
        # 如果其他设备的下联指向该设备，那么那些设备就是该设备的上联
        upstream_configs = db.query(AssetConfiguration).options(
            joinedload(AssetConfiguration.asset)
        ).filter(
            and_(
                AssetConfiguration.related_asset_id == asset_id,
                AssetConfiguration.configuration_type == "downstream",
                AssetConfiguration.status == 1
            )
        ).all()
        
        upstream_list = []
        for config in upstream_configs:
            upstream_list.append({
                "sn": config.asset.serial_number if config.asset else None,
                "is_company_device": config.asset.is_company_device if config.asset else True,
                "connection_type": config.connection_type,
                "work_order_number": config.work_order_number
            })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "sn": sn,
                "total": len(upstream_list),
                "upstream": upstream_list
            }
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.get("/device/{sn}/downstream", summary="查询设备的下联列表")
async def get_device_downstream(
    sn: str,
    db: Session = Depends(get_db)
):
    """查询指定设备的所有下联设备"""
    try:
        asset = db.query(Asset).filter(Asset.serial_number == sn).first()
        if not asset:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到SN为 {sn} 的设备",
                data=None
            )
        
        asset_id = asset.id
        
        # 查询下联（该设备作为主设备）
        downstream_configs = db.query(AssetConfiguration).options(
            joinedload(AssetConfiguration.related_asset)
        ).filter(
            and_(
                AssetConfiguration.asset_id == asset_id,
                AssetConfiguration.configuration_type == "downstream",
                AssetConfiguration.status == 1
            )
        ).all()
        
        downstream_list = []
        for config in downstream_configs:
            downstream_list.append({
                "sn": config.related_asset.serial_number if config.related_asset else None,
                "is_company_device": config.related_asset.is_company_device if config.related_asset else True,
                "connection_type": config.connection_type,
                "work_order_number": config.work_order_number
            })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "sn": sn,
                "total": len(downstream_list),
                "downstream": downstream_list
            }
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.post("/connection", summary="创建拓扑连接")
async def create_topology_connection(
    connection_data: TopologyConnectionCreate,
    work_order_number: Optional[str] = Query(None, description="关联上架工单号"),
    racking_batch_id: Optional[int] = Query(None, ge=1, description="关联上架批次ID"),
    db: Session = Depends(get_db)
):
    """创建设备之间的拓扑连接（上联/下联关系）"""
    try:
        batch, resolved_work_order, error_response = _resolve_racking_binding(db, work_order_number, racking_batch_id)
        if error_response:
            return error_response
        
        # 检查源设备是否存在
        source_asset = db.query(Asset).filter(Asset.serial_number == connection_data.source_sn).first()
        if not source_asset:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到SN为 {connection_data.source_sn} 的源设备",
                data=None
            )
        
        # 检查目标设备是否存在
        target_asset = db.query(Asset).filter(Asset.serial_number == connection_data.target_sn).first()
        if not target_asset:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到SN为 {connection_data.target_sn} 的目标设备",
                data=None
            )
        
        # 检查是否已存在相同的连接
        existing = db.query(AssetConfiguration).filter(
            and_(
                AssetConfiguration.asset_id == source_asset.id,
                AssetConfiguration.related_asset_id == target_asset.id,
                AssetConfiguration.configuration_type == "downstream"
            )
        ).first()
        
        if existing:
            return ApiResponse(
                code=ResponseCode.ALREADY_EXISTS,
                message="该设备之间的连接关系已存在",
                data={"connection_id": existing.id}
            )
        
        # 创建连接关系（源设备 -> 目标设备，源设备的下联 = 目标设备的上联）
        # 在源设备上创建下联记录
        downstream_config = AssetConfiguration(
            asset_id=source_asset.id,
            configuration_type="downstream",
            related_asset_id=target_asset.id,
            connection_type=connection_data.connection_type,
            racking_batch_id=batch.id if batch else None,
            work_order_number=resolved_work_order or (batch.work_order_number if batch else None)
        )
        
        db.add(downstream_config)
        
        # 在目标设备上创建上联记录（可选，如果希望双向记录）
        # 这里我们只创建单向记录，查询时通过逻辑处理
        
        db.commit()
        db.refresh(downstream_config)
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="拓扑连接创建成功",
            data={
                "connection_id": downstream_config.id,
                "source_sn": connection_data.source_sn,
                "source_asset_id": source_asset.id,
                "target_sn": connection_data.target_sn,
                "target_asset_id": target_asset.id,
                "work_order_number": downstream_config.work_order_number
            }
        )
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"创建失败: {str(e)}",
            data=None
        )


@router.put("/connection/{connection_id}", summary="更新拓扑连接")
async def update_topology_connection(
    connection_id: int,
    connection_data: TopologyConnectionUpdate,
    work_order_number: Optional[str] = Query(None, description="关联上架工单号"),
    racking_batch_id: Optional[int] = Query(None, ge=1, description="关联上架批次ID"),
    clear_work_order_binding: bool = Query(False, description="是否清除工单绑定"),
    db: Session = Depends(get_db)
):
    """更新拓扑连接信息"""
    try:
        config = db.query(AssetConfiguration).filter(
            AssetConfiguration.id == connection_id
        ).first()
        
        if not config:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到ID为 {connection_id} 的连接记录",
                data=None
            )
        
        # 更新字段
        if connection_data.connection_type is not None:
            config.connection_type = connection_data.connection_type
        
        if clear_work_order_binding:
            config.racking_batch_id = None
            config.work_order_number = None
        elif work_order_number is not None or racking_batch_id is not None:
            batch, resolved_work_order, error_response = _resolve_racking_binding(db, work_order_number, racking_batch_id)
            if error_response:
                return error_response
            config.racking_batch_id = batch.id if batch else None
            config.work_order_number = resolved_work_order or (batch.work_order_number if batch else None)
        
        config.updated_at = datetime.now()
        db.commit()
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="拓扑连接更新成功",
            data={"connection_id": connection_id}
        )
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"更新失败: {str(e)}",
            data=None
        )


@router.delete("/connection/{connection_id}", summary="删除拓扑连接")
async def delete_topology_connection(
    connection_id: int,
    db: Session = Depends(get_db)
):
    """删除拓扑连接"""
    try:
        config = db.query(AssetConfiguration).filter(
            AssetConfiguration.id == connection_id
        ).first()
        
        if not config:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到ID为 {connection_id} 的连接记录",
                data=None
            )
        
        db.delete(config)
        db.commit()
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="拓扑连接删除成功",
            data={"connection_id": connection_id}
        )
    except Exception as e:
        db.rollback()
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"删除失败: {str(e)}",
            data=None
        )


@router.get("/work-order/{work_order_number}", summary="根据上架工单查询拓扑连接")
async def get_connections_by_work_order(
    work_order_number: str,
    db: Session = Depends(get_db)
):
    """根据上架工单号查询在该工单中建立的拓扑关系"""
    try:
        # 注意：AssetConfiguration表中没有work_order_number字段
        # 需要通过configuration_info JSON字段中的work_order_number来过滤
        # 或者通过其他关联方式
        
        # 方案1：通过JSON字段过滤（如果configuration_info中存储了work_order_number）
        # 使用MySQL的JSON函数
        from sqlalchemy import text
        connections_query = db.query(AssetConfiguration).options(
            joinedload(AssetConfiguration.asset),
            joinedload(AssetConfiguration.related_asset)
        ).filter(
            text("JSON_EXTRACT(configuration_info, '$.work_order_number') = :work_order_number")
        ).params(work_order_number=work_order_number).order_by(AssetConfiguration.created_at.asc())
        
        connections = connections_query.all()
        batch = db.query(WorkOrder).filter(WorkOrder.batch_id == work_order_number).first()
        
        if not batch and not connections:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到工单号为 {work_order_number} 的上架记录",
                data=None
            )
        
        connection_data = []
        for config in connections:
            connection_data.append({
                "connection_id": config.id,
                "source_sn": config.asset.serial_number if config.asset else None,
                "source_is_company_device": config.asset.is_company_device if config.asset else True,
                "target_sn": config.related_asset.serial_number if config.related_asset else None,
                "target_is_company_device": config.related_asset.is_company_device if config.related_asset else True,
                "connection_type": config.connection_type,
                "created_at": config.created_at.isoformat() if config.created_at else None
            })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "work_order_number": work_order_number,
                "racking_batch_id": batch.id if batch else None,
                "racking_batch_number": batch.batch_id if batch else None,
                "total": len(connection_data),
                "connections": connection_data
            }
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )


@router.get("/path/{source_sn}/{target_sn}", summary="查询设备间的拓扑路径")
async def get_topology_path(
    source_sn: str,
    target_sn: str,
    max_depth: int = Query(5, ge=1, le=10, description="最大搜索深度"),
    db: Session = Depends(get_db)
):
    """查询两个设备之间的拓扑连接路径（简单实现，返回直接连接）"""
    try:
        # 检查设备是否存在
        source_asset = db.query(Asset).filter(Asset.serial_number == source_sn).first()
        target_asset = db.query(Asset).filter(Asset.serial_number == target_sn).first()
        
        if not source_asset:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到SN为 {source_sn} 的源设备",
                data=None
            )
        
        if not target_asset:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到SN为 {target_sn} 的目标设备",
                data=None
            )
        
        # 查找直接连接（source -> target 或 target -> source）
        direct_connection = db.query(AssetConfiguration).options(
            joinedload(AssetConfiguration.asset),
            joinedload(AssetConfiguration.related_asset)
        ).filter(
            or_(
                and_(
                    AssetConfiguration.asset_id == source_asset.id,
                    AssetConfiguration.related_asset_id == target_asset.id,
                    AssetConfiguration.configuration_type == "downstream",
                    AssetConfiguration.status == 1
                ),
                and_(
                    AssetConfiguration.asset_id == target_asset.id,
                    AssetConfiguration.related_asset_id == source_asset.id,
                    AssetConfiguration.configuration_type == "downstream",
                    AssetConfiguration.status == 1
                )
            )
        ).first()
        
        if direct_connection:
            return ApiResponse(
                code=ResponseCode.SUCCESS,
                message="找到直接连接",
                data={
                    "path_found": True,
                    "path_type": "direct",
                    "path": [
                        {
                            "sn": source_sn,
                            "is_company_device": source_asset.is_company_device
                        },
                        {
                            "sn": target_sn,
                            "is_company_device": target_asset.is_company_device
                        }
                    ],
                    "connection_type": direct_connection.connection_type,
                    "work_order_number": direct_connection.work_order_number
                }
            )
        else:
            return ApiResponse(
                code=ResponseCode.SUCCESS,
                message="未找到直接连接路径",
                data={
                    "path_found": False,
                    "path_type": None,
                    "path": None
                }
            )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )

