"""
IT资产管理系统 - 位置管理API路由（简化版 - 只管理房间）
提供房间管理的RESTful API接口
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.services.asset_service import LocationService
from app.schemas.asset_schemas import (
    RoomResponse, RoomCreate, RoomUpdate, 
    RoomTypeResponse, RoomTypeCreate, RoomTypeUpdate,
    ApiResponse, ApiListResponse, ResponseCode
)
from app.models.asset_models import RoomType, Room

router = APIRouter()

# =====================================================
# 房间类型管理接口
# =====================================================

@router.get("/room-types", response_model=ApiListResponse, summary="获取房间类型列表")
async def get_room_types(
    is_active: Optional[int] = Query(None, description="是否启用：1-启用，0-禁用"),
    db: Session = Depends(get_db)
):
    """
    获取房间类型列表（枚举值）
    
    返回所有可用的房间类型，前端可用于下拉选择
    """
    try:
        query = db.query(RoomType)
        
        # 筛选启用状态
        if is_active is not None:
            query = query.filter(RoomType.is_active == is_active)
        
        # 按顺序排序
        room_types = query.order_by(RoomType.sequence_order).all()
        
        # 转换为响应格式（转为字典）
        room_types_data = [
            RoomTypeResponse.model_validate(rt).model_dump() 
            for rt in room_types
        ]
        
        return ApiListResponse(
            code=ResponseCode.SUCCESS,
            message="查询成功",
            data=room_types_data,
            total=len(room_types_data),
            page=1,
            page_size=len(room_types_data)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询房间类型失败: {str(e)}")


@router.get("/room-types/{type_id}", response_model=ApiResponse, summary="获取房间类型详情")
async def get_room_type(
    type_id: int,
    db: Session = Depends(get_db)
):
    """获取指定房间类型的详细信息"""
    room_type = db.query(RoomType).filter(RoomType.id == type_id).first()
    
    if not room_type:
        return ApiResponse(
            code=ResponseCode.NOT_FOUND,
            message="房间类型不存在"
        )
    
    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="查询成功",
        data=RoomTypeResponse.model_validate(room_type)
    )


@router.post("/room-types", response_model=ApiResponse, summary="创建房间类型")
async def create_room_type(
    room_type_data: RoomTypeCreate,
    db: Session = Depends(get_db)
):
    """创建新的房间类型（管理员功能）"""
    # 检查编码是否已存在
    existing = db.query(RoomType).filter(RoomType.type_code == room_type_data.type_code).first()
    if existing:
        return ApiResponse(
            code=ResponseCode.ALREADY_EXISTS,
            message=f"房间类型编码 '{room_type_data.type_code}' 已存在"
        )
    
    try:
        new_room_type = RoomType(**room_type_data.model_dump())
        db.add(new_room_type)
        db.commit()
        db.refresh(new_room_type)
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="房间类型创建成功",
            data=RoomTypeResponse.model_validate(new_room_type)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建房间类型失败: {str(e)}")


@router.put("/room-types/{type_id}", response_model=ApiResponse, summary="更新房间类型")
async def update_room_type(
    type_id: int,
    room_type_data: RoomTypeUpdate,
    db: Session = Depends(get_db)
):
    """更新房间类型信息（管理员功能）"""
    room_type = db.query(RoomType).filter(RoomType.id == type_id).first()
    
    if not room_type:
        return ApiResponse(
            code=ResponseCode.NOT_FOUND,
            message="房间类型不存在"
        )
    
    try:
        # 更新字段
        update_data = room_type_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(room_type, field, value)
        
        db.commit()
        db.refresh(room_type)
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="房间类型更新成功",
            data=RoomTypeResponse.model_validate(room_type)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新房间类型失败: {str(e)}")


@router.delete("/room-types/{type_id}", response_model=ApiResponse, summary="删除房间类型")
async def delete_room_type(
    type_id: int,
    db: Session = Depends(get_db)
):
    """
    删除房间类型（管理员功能）
    
    注意：如果有房间使用该类型，将无法删除
    """
    room_type = db.query(RoomType).filter(RoomType.id == type_id).first()
    
    if not room_type:
        return ApiResponse(
            code=ResponseCode.NOT_FOUND,
            message="房间类型不存在"
        )
    
    # 检查是否有房间使用该类型
    from app.models.asset_models import Room
    room_count = db.query(Room).filter(Room.room_type_id == type_id).count()
    if room_count > 0:
        return ApiResponse(
            code=ResponseCode.PARAM_ERROR,
            message=f"无法删除，当前有 {room_count} 个房间正在使用该类型"
        )
    
    try:
        db.delete(room_type)
        db.commit()
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="房间类型删除成功"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除房间类型失败: {str(e)}")


# =====================================================
# 房间管理接口
# =====================================================

@router.get("/rooms", response_model=ApiListResponse, summary="获取房间列表")
async def get_rooms(
    datacenter_abbreviation: Optional[str] = Query(None, description="机房缩写"),
    building_number: Optional[str] = Query(None, description="楼号"),
    floor_number: Optional[str] = Query(None, description="楼层"),
    room_number: Optional[str] = Query(None, description="房间号"),
    room_type_id: Optional[int] = Query(None, description="房间类型ID"),
    notes_keyword: Optional[str] = Query(None, description="备注模糊搜索关键字"),
    created_from: Optional[str] = Query(None, description="创建时间起始（格式：YYYY-MM-DD）"),
    created_to: Optional[str] = Query(None, description="创建时间结束（格式：YYYY-MM-DD）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=10000, description="每页大小"),
    db: Session = Depends(get_db)
):
    """
    获取房间列表（支持多条件筛选）
    
    筛选条件：
    - datacenter_abbreviation: 机房缩写
    - building_number: 楼号
    - floor_number: 楼层
    - room_number: 房间号
    - room_type_id: 房间类型ID
    - notes_keyword: 备注模糊搜索关键字
    - created_from: 创建时间起始
    - created_to: 创建时间结束
    """
    service = LocationService(db)
    
    # 解析时间参数
    from datetime import datetime
    created_from_dt = None
    created_to_dt = None
    
    try:
        if created_from:
            created_from_dt = datetime.strptime(created_from, "%Y-%m-%d")
        if created_to:
            created_to_dt = datetime.strptime(created_to, "%Y-%m-%d")
            # 包含当天结束时间
            created_to_dt = created_to_dt.replace(hour=23, minute=59, second=59)
    except ValueError:
        return ApiListResponse(
            code=ResponseCode.PARAM_ERROR,
            message="invalid date format, use YYYY-MM-DD",
            data=[],
            total=0,
            page=page,
            page_size=page_size
        )
    
    # 使用多条件搜索
    rooms = service.search_rooms(
        datacenter_abbreviation=datacenter_abbreviation,
        building_number=building_number,
        floor_number=floor_number,
        room_number=room_number,
        room_type_id=room_type_id,
        created_from=created_from_dt,
        created_to=created_to_dt,
        notes_keyword=notes_keyword
    )
    
    # 应用分页
    total = len(rooms)
    skip = (page - 1) * page_size
    rooms_page = rooms[skip:skip + page_size]
    
    # 手动构建房间数据列表
    rooms_data = []
    for room in rooms_page:
        room_dict = {
            "id": room.id,
            "room_abbreviation": room.room_abbreviation,
            "room_full_name": room.room_full_name,
            "room_number": room.room_number,
            "room_type_id": room.room_type_id,
            "room_type": room.room_type_rel.type_name if room.room_type_rel else None,
            "room_type_code": room.room_type_rel.type_code if room.room_type_rel else None,
            "datacenter_abbreviation": room.datacenter_abbreviation,
            "building_number": room.building_number,
            "floor_number": room.floor_number,
            "status": room.status,
            "notes": room.notes,
            "created_by": room.created_by,
            "created_at": room.created_at.isoformat() if room.created_at else None,
            "updated_at": room.updated_at.isoformat() if room.updated_at else None
        }
        rooms_data.append(room_dict)
    
    return ApiListResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data=rooms_data,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get(
    "/rooms/location-options",
    response_model=ApiResponse,
    summary="获取现有房间的楼号/楼层选项"
)
async def get_room_location_options(
    datacenter_abbreviation: Optional[str] = Query(None, description="机房缩写，可选"),
    building_number: Optional[str] = Query(None, description="楼号，可选；不传则返回所有楼号"),
    db: Session = Depends(get_db)
):
    """根据传入参数返回现有房间的楼号列表或指定楼号下的楼层列表"""
    service = LocationService(db)

    if building_number:
        floors = service.get_floors_by_building(
            building_number=building_number,
            datacenter_abbreviation=datacenter_abbreviation
        )
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={
                "type": "floors",
                "building_number": building_number,
                "options": floors
            }
        )

    buildings = service.get_distinct_buildings(datacenter_abbreviation=datacenter_abbreviation)
    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data={
            "type": "buildings",
            "options": buildings
        }
    )


@router.get(
    "/rooms/location-options/all",
    response_model=ApiResponse,
    summary="获取全部楼号与楼层列表"
)
async def get_all_room_locations(
    datacenter_abbreviation: Optional[str] = Query(None, description="机房缩写，可选"),
    db: Session = Depends(get_db)
):
    """一次性返回所有已启用房间的楼号及楼层列表"""
    service = LocationService(db)
    buildings = service.get_distinct_buildings(datacenter_abbreviation=datacenter_abbreviation)
    floors = service.get_distinct_floors(datacenter_abbreviation=datacenter_abbreviation)

    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data={
            "buildings": buildings,
            "floors": floors
        }
    )


@router.get(
    "/rooms/datacenters",
    response_model=ApiResponse,
    summary="获取现有房间涉及的园区/机房缩写"
)
async def get_distinct_datacenters(db: Session = Depends(get_db)):
    """返回所有已启用房间的机房/园区缩写列表"""
    service = LocationService(db)
    datacenters = service.get_distinct_datacenters()

    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data={"datacenters": datacenters}
    )


@router.get(
    "/rooms/numbers",
    response_model=ApiResponse,
    summary="获取现有房间号列表"
)
async def get_distinct_room_numbers(
    datacenter_abbreviation: Optional[str] = Query(None, description="机房缩写，可选"),
    db: Session = Depends(get_db)
):
    """返回所有已启用房间的房间号列表，可按机房过滤"""
    service = LocationService(db)
    room_numbers = service.get_distinct_room_numbers(datacenter_abbreviation=datacenter_abbreviation)

    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data={"room_numbers": room_numbers}
    )


@router.post("/rooms", response_model=ApiResponse, summary="创建房间")
async def create_room(
    room_data: RoomCreate,
    db: Session = Depends(get_db)
):
    """创建房间"""
    service = LocationService(db)
    
    # 检查房间缩写是否已存在
    existing = service.get_all_rooms()
    for room in existing:
        if room.room_abbreviation == room_data.room_abbreviation:
            return ApiResponse(
                code=ResponseCode.ALREADY_EXISTS,
                message="room abbreviation already exists",
                data=None
            )
    
    try:
        room = service.create_room(room_data.dict())
        # 手动构建响应数据，避免SQLAlchemy对象序列化问题
        room_data_dict = {
            "id": room.id,
            "room_abbreviation": room.room_abbreviation,
            "room_full_name": room.room_full_name,
            "room_number": room.room_number,
            "room_type_id": room.room_type_id,
            "room_type": room.room_type_rel.type_name if room.room_type_rel else None,
            "room_type_code": room.room_type_rel.type_code if room.room_type_rel else None,
            "datacenter_abbreviation": room.datacenter_abbreviation,
            "building_number": room.building_number,
            "floor_number": room.floor_number,
            "status": room.status,
            "notes": room.notes,
            "created_by": room.created_by,
            "created_at": room.created_at.isoformat() if room.created_at else None,
            "updated_at": room.updated_at.isoformat() if room.updated_at else None
        }
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data=room_data_dict
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message="internal server error",
            data={"error": str(e)}
        )

@router.get("/rooms/{room_id}", response_model=ApiResponse, summary="获取房间详情")
async def get_room(room_id: int, db: Session = Depends(get_db)):
    """获取房间详情"""
    service = LocationService(db)
    room = service.get_room_by_id(room_id)
    if not room:
        return ApiResponse(
            code=ResponseCode.NOT_FOUND,
            message="room not found",
            data=None
        )
    
    room_data_dict = {
        "id": room.id,
        "room_abbreviation": room.room_abbreviation,
        "room_full_name": room.room_full_name,
        "room_number": room.room_number,
        "room_type_id": room.room_type_id,
        "room_type": room.room_type_rel.type_name if room.room_type_rel else None,
        "room_type_code": room.room_type_rel.type_code if room.room_type_rel else None,
        "datacenter_abbreviation": room.datacenter_abbreviation,
        "building_number": room.building_number,
        "floor_number": room.floor_number,
        "status": room.status,
        "notes": room.notes,
        "created_by": room.created_by,
        "created_at": room.created_at.isoformat() if room.created_at else None,
        "updated_at": room.updated_at.isoformat() if room.updated_at else None
    }
    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data=room_data_dict
    )

@router.put("/rooms/{room_id}", response_model=ApiResponse, summary="更新房间")
async def update_room(
    room_id: int,
    room_data: RoomUpdate,
    db: Session = Depends(get_db)
):
    """更新房间"""
    service = LocationService(db)
    
    # 如果更新房间缩写，检查是否已存在
    if room_data.room_abbreviation:
        existing = service.get_all_rooms()
        for room in existing:
            if room.id != room_id and room.room_abbreviation == room_data.room_abbreviation:
                return ApiResponse(
                    code=ResponseCode.ALREADY_EXISTS,
                    message="room abbreviation already exists",
                    data=None
                )
    
    try:
        room = service.update_room(room_id, room_data.dict(exclude_unset=True))
        if not room:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message="room not found",
                data=None
            )
        
        room_data_dict = {
            "id": room.id,
            "room_abbreviation": room.room_abbreviation,
            "room_full_name": room.room_full_name,
            "room_number": room.room_number,
            "room_type_id": room.room_type_id,
            "room_type": room.room_type_rel.type_name if room.room_type_rel else None,
            "room_type_code": room.room_type_rel.type_code if room.room_type_rel else None,
            "datacenter_abbreviation": room.datacenter_abbreviation,
            "building_number": room.building_number,
            "floor_number": room.floor_number,
            "status": room.status,
            "notes": room.notes,
            "created_by": room.created_by,
            "created_at": room.created_at.isoformat() if room.created_at else None,
            "updated_at": room.updated_at.isoformat() if room.updated_at else None
        }
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data=room_data_dict
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message="internal server error",
            data={"error": str(e)}
        )

@router.delete("/rooms/{room_id}", response_model=ApiResponse, summary="删除房间")
async def delete_room(room_id: int, db: Session = Depends(get_db)):
    """删除房间（软删除）"""
    service = LocationService(db)
    
    try:
        success = service.delete_room(room_id)
        if not success:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message="room not found",
                data=None
            )
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="success",
            data={"room_id": room_id}
        )
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message="internal server error",
            data={"error": str(e)}
        )

# =====================================================
# 房间统计接口
# =====================================================

@router.get("/rooms/statistics/datacenter", response_model=ApiResponse, summary="机房统计")
async def get_datacenter_statistics(db: Session = Depends(get_db)):
    """获取按机房统计的房间数量"""
    service = LocationService(db)
    rooms = service.get_all_rooms()
    
    stats = {}
    for room in rooms:
        datacenter = room.datacenter_abbreviation or "未分类"
        if datacenter not in stats:
            stats[datacenter] = 0
        stats[datacenter] += 1
    
    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data=[{"datacenter": k, "room_count": v} for k, v in stats.items()]
    )

@router.get("/rooms/statistics/building-floor", response_model=ApiResponse, summary="楼层统计")
async def get_building_floor_statistics(db: Session = Depends(get_db)):
    """获取按楼层统计的房间数量"""
    service = LocationService(db)
    rooms = service.get_all_rooms()
    
    stats = {}
    for room in rooms:
        if room.building_number and room.floor_number:
            key = f"{room.building_number}楼{room.floor_number}层"
            if key not in stats:
                stats[key] = 0
            stats[key] += 1
    
    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data=[{"location": k, "room_count": v} for k, v in stats.items()]
    )

@router.get("/rooms/statistics/type", response_model=ApiResponse, summary="房间类型统计")
async def get_room_type_statistics(db: Session = Depends(get_db)):
    """获取按房间类型统计的数量"""
    service = LocationService(db)
    rooms = service.get_all_rooms()
    
    stats = {}
    for room in rooms:
        room_type = room.room_type_rel.type_name if room.room_type_rel else "未分类"
        if room_type not in stats:
            stats[room_type] = 0
        stats[room_type] += 1
    
    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="success",
        data=[{"room_type": k, "room_count": v} for k, v in stats.items()]
    )

# =====================================================
# 房间导入（Excel）
# =====================================================

@router.post("/rooms/import", response_model=ApiResponse, summary="通过Excel导入房间")
async def import_rooms(
    file: UploadFile = File(..., description="包含房间信息的Excel文件（.xlsx）"),
    operator: Optional[str] = Form(None, description="导入操作者名称，用作创建人"),
    db: Session = Depends(get_db)
):
    """
    通过Excel批量导入房间。
    
    - 自动识别表头（首行），支持常见字段别名：
      - 房间简称：['*房间简称','房间简称','*房间','房间']
      - 房间全名：['房间全名','房间全称']
      - 房间编号：['房间编号','编号','房号']
      - 数据中心简称：['机房简称','数据中心简称','机房','数据中心','DC']
      - 楼号：['楼号','楼栋']
      - 楼层：['楼层','层数']
      - 房间类型：['房间类型','房间类型编码','房间类型名称']
      - 状态：['状态']
      - 备注：['备注','说明']
      - 创建人：['创建人','操作人','导入人']
    - 房间类型可用“编码”或“名称”匹配现有 RoomType
    - 去重规则：按房间简称 `room_abbreviation` 唯一
    - 失败行会生成Excel错误报告，保存在 `alms/temp/`
    """
    import os
    from datetime import datetime
    import pandas as pd
    
    # 校验文件类型
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        return ApiResponse(code=ResponseCode.PARAM_ERROR, message="仅支持 .xlsx 文件", data=None)

    # 读取Excel到DataFrame
    try:
        content = await file.read()
        from io import BytesIO
        df = pd.read_excel(BytesIO(content), sheet_name=0, dtype=str)
    except Exception as e:
        return ApiResponse(code=ResponseCode.PARAM_ERROR, message=f"读取Excel失败: {str(e)}", data=None)

    if df.empty:
        return ApiResponse(code=ResponseCode.PARAM_ERROR, message="Excel内容为空", data=None)

    # 规范化列名（去除首尾空格）
    df.columns = [str(c).strip() for c in df.columns]

    # 单元格规范化：将任意值安全转为字符串；空/NaN -> ""
    import math
    def cell_to_str(value) -> str:
        try:
            # pandas 的缺失值判断
            import pandas as _pd
            if value is None or (isinstance(value, float) and (_pd.isna(value) or math.isnan(value))):
                return ""
        except Exception:
            # 非 float 或无法判断 NaN 的情形
            if value is None:
                return ""
        # 数字类：避免 "1.0" 这类显示
        if isinstance(value, (int,)):
            return str(value)
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return str(value)
        # 其它直接转字符串并 strip
        return str(value).strip()

    # 严格按模板列名匹配
    # 模板列顺序与名称（中文）：房间缩写 | 房间全称 | 房间类型 | 机房缩写 | 楼号 | 楼层 | 房间号 | 备注
    expected_cols = [
        "房间缩写", "房间全称", "房间类型", "机房缩写", "楼号", "楼层", "房间号", "备注"
    ]
    missing_cols = [c for c in ["房间缩写", "房间类型"] if c not in df.columns]
    # 必填：房间缩写、房间类型
    missing_required = []
    if "房间缩写" not in df.columns:
        missing_required.append("房间缩写")
    if "房间类型" not in df.columns:
        missing_required.append("房间类型")
    if missing_required or missing_cols:
        return ApiResponse(
            code=ResponseCode.PARAM_ERROR,
            message=f"缺少必填列: {', '.join(missing_required)}",
            data={"detected_headers": list(df.columns)}
        )

    # 列变量（不存在则视为可选）
    col_room_abbr = "房间缩写"
    col_room_type_any = "房间类型"
    col_room_full = "房间全称" if "房间全称" in df.columns else None
    col_room_num = "房间号" if "房间号" in df.columns else None
    col_dc = "机房缩写" if "机房缩写" in df.columns else None
    col_building = "楼号" if "楼号" in df.columns else None
    col_floor = "楼层" if "楼层" in df.columns else None
    col_notes = "备注" if "备注" in df.columns else None
    col_created_by = "创建人" if "创建人" in df.columns else None

    # 预取现有房间简称集合做去重
    existing_abbrs = set(
        r[0] for r in db.query(Room.room_abbreviation).all()
    )

    success_count = 0
    failure_count = 0
    error_rows = []

    # 逐行处理
    for idx, row in df.iterrows():
        row_num = idx + 2  # Excel显示行号（含表头）
        try:
            room_abbr = cell_to_str(row.get(col_room_abbr)) if col_room_abbr else ""
            if not room_abbr:
                raise ValueError("房间简称为空")
            if room_abbr in existing_abbrs:
                raise ValueError(f"房间简称已存在: {room_abbr}")

            room_full = cell_to_str(row.get(col_room_full)) if col_room_full else None
            room_num = cell_to_str(row.get(col_room_num)) if col_room_num else None
            dc = cell_to_str(row.get(col_dc)) if col_dc else None
            building = cell_to_str(row.get(col_building)) if col_building else None
            floor = cell_to_str(row.get(col_floor)) if col_floor else None
            # 状态列不在模板中，默认启用
            status_val = None
            notes = cell_to_str(row.get(col_notes)) if col_notes else None
            creator = cell_to_str(row.get(col_created_by)) if col_created_by else None
            if not creator and operator:
                creator = operator

            # 房间类型匹配（编码或名称）
            room_type_raw = cell_to_str(row.get(col_room_type_any))
            if not room_type_raw:
                raise ValueError("房间类型为空")
            # 支持按 ID、编码 或 名称 匹配
            rt = None
            if room_type_raw.isdigit():
                rt = db.query(RoomType).filter(RoomType.id == int(room_type_raw)).first()
            if not rt:
                rt = db.query(RoomType).filter(
                    (RoomType.type_code == room_type_raw) | (RoomType.type_name == room_type_raw)
                ).first()
            if not rt:
                raise ValueError(f"未找到匹配的房间类型: {room_type_raw}")

            # 状态解析：允许 1/0 或 文本
            status_int = 1
            if status_val:
                if status_val in ("1", "启用", "在用", "active", "启"):
                    status_int = 1
                elif status_val in ("0", "禁用", "停用", "inactive", "禁"):
                    status_int = 0
                else:
                    # 非法值则默认启用，但记录警告
                    pass

            new_room = Room(
                room_abbreviation=room_abbr,
                room_full_name=room_full,
                room_number=room_num,
                room_type_id=rt.id,
                datacenter_abbreviation=dc,
                building_number=building,
                floor_number=floor,
                status=status_int,
                notes=notes,
                created_by=creator or "system"
            )
            db.add(new_room)
            db.flush()

            existing_abbrs.add(room_abbr)
            success_count += 1
        except Exception as e:
            failure_count += 1
            error_msg = str(e)
            error_row = row.copy()
            error_row["错误信息"] = error_msg
            error_row["行号"] = row_num
            error_rows.append(error_row)

    # 若全部失败则回滚
    if success_count == 0:
        db.rollback()
    else:
        db.commit()

    # 输出失败报告
    error_report_path = None
    error_report_url = None
    if error_rows:
        try:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            temp_dir = os.path.abspath(os.path.join(base_dir, "temp"))
            os.makedirs(temp_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            error_report_path = os.path.join(temp_dir, f"房间导入失败记录_{ts}.xlsx")
            err_df = pd.DataFrame(error_rows)
            err_df.to_excel(error_report_path, index=False)
            # 生成可下载URL（通过下方 error-report 接口提供下载）
            error_report_url = f"/api/v1/locations/rooms/import/error-report/{os.path.basename(error_report_path)}"
        except Exception:
            # 报告生成失败不影响主流程
            error_report_path = None
            error_report_url = None

    return ApiResponse(
        code=ResponseCode.SUCCESS if success_count > 0 else ResponseCode.PARAM_ERROR,
        message="导入完成" if success_count > 0 else "导入失败",
        data={
            "success_count": success_count,
            "failure_count": failure_count,
            "error_report": error_report_url
        }
    )


@router.get("/rooms/import/template", summary="下载房间导入模板（Excel）")
async def download_rooms_import_template():
    """
    下载房间导入Excel模板。
    表头字段（严格顺序）：
    - 房间缩写（必填，唯一）
    - 房间全称（可选）
    - 房间类型（必填，支持ID/编码/名称）
    - 机房缩写（可选）
    - 楼号（可选）
    - 楼层（可选）
    - 房间号（可选）
    - 备注（可选）
    """
    import pandas as pd
    from io import BytesIO
    headers = ["房间缩写", "房间全称", "房间类型", "机房缩写", "楼号", "楼层", "房间号", "备注"]
    df = pd.DataFrame(columns=headers)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="房间导入模板")
    output.seek(0)

    # 避免非ASCII字符导致 header 编码错误：提供 ASCII 回退 + RFC5987 filename*
    from urllib.parse import quote
    utf8_name = "房间导入模板.xlsx"
    ascii_fallback = "rooms_template.xlsx"
    disposition = f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(utf8_name)}'

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )


@router.get("/rooms/import/error-report/{filename}", summary="下载房间导入失败报告")
async def download_rooms_error_report(filename: str):
    """
    下载房间导入失败的Excel报告。
    仅允许访问 `alms/temp/` 目录下由系统生成的文件。
    """
    import os
    from fastapi.responses import FileResponse
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    temp_dir = os.path.abspath(os.path.join(base_dir, "temp"))
    # 防目录穿越
    safe_name = os.path.basename(filename)
    file_path = os.path.join(temp_dir, safe_name)
    if not os.path.exists(file_path):
        return ApiResponse(code=ResponseCode.NOT_FOUND, message="文件不存在", data=None)

    from urllib.parse import quote
    ascii_fallback = "rooms_error_report.xlsx"
    # 如果文件名可编码成 latin-1，就直接使用原名；否则提供 ASCII 回退并通过 filename*
    try:
        safe_name.encode("latin-1")
        disposition = f'attachment; filename="{safe_name}"'
    except UnicodeEncodeError:
        disposition = f'attachment; filename="{ascii_fallback}"; filename*=UTF-8''{quote(safe_name)}'
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )