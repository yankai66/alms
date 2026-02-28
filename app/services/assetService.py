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

class assetService:
    
    @staticmethod
    def get_device_topology(
    sn: str,
    db: Session = Depends(get_db)):

        try:
            # 检查设备是否存在
            asset = db.query(Asset).filter(Asset.serial_number == sn).first()
            if not asset:
                return None
            
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
            
            return {
                    "sn": asset.serial_number,
                    "is_company_device": asset.is_company_device,
                    "upstream": upstream_list,  # 上联设备列表
                    "downstream": downstream_list,  # 下联设备列表
                    "upstream_count": len(upstream_list),
                    "downstream_count": len(downstream_list)
                }
            
        except Exception as e:
            return None