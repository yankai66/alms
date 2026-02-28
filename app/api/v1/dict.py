import json

from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List

from app.db.session import get_db
from app.schemas.asset_schemas import ApiResponse, ResponseCode
from app.models.asset_models import DictType, DictItem

router = APIRouter()


@router.get("/types", summary="字典类型列表")
async def list_dict_types(
    keyword: Optional[str] = Query(None, description="按编码/名称模糊查询"),
    status: Optional[int] = Query(None, description="状态：1启用，0禁用"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=10000),
    db: Session = Depends(get_db)
):
    query = db.query(DictType)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((DictType.type_code.like(like)) | (DictType.type_name.like(like)))
    if status is not None:
        query = query.filter(DictType.status == status)

    query = query.order_by(DictType.sequence_order.asc(), DictType.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    data = [
        {
            "id": t.id,
            "type_code": t.type_code,
            "type_name": t.type_name,
            "description": t.description,
            "status": t.status,
            "sequence_order": t.sequence_order,
            "built_in": t.built_in,
            "created_at": t.created_at,
            "updated_at": t.updated_at
        } for t in items
    ]

    return ApiResponse(code=ResponseCode.SUCCESS, message="success", data={
        "total": total, "page": page, "page_size": page_size, "items": data
    })


@router.post("/types", summary="新增字典类型（支持批量创建字典项）")
async def create_dict_type(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    创建字典类型，支持同时创建字典项
    
    简单创建（只创建类型）:
    {
        "type_code": "device_status",
        "type_name": "设备状态"
    }
    
    批量创建（类型+字典项）:
    {
        "type_code": "device_status",
        "type_name": "设备状态",
        "items": [
            {"item_code": "running", "item_label": "运行中"},
            {"item_code": "stopped", "item_label": "停机"}
        ]
    }
    """
    type_code = (payload.get("type_code") or "").strip()
    type_name = (payload.get("type_name") or "").strip()
    if not type_code or not type_name:
        return ApiResponse(code=ResponseCode.PARAM_ERROR, message="type_code/type_name 为必填", data=None)

    exists = db.query(DictType).filter(DictType.type_code == type_code).first()
    if exists:
        return ApiResponse(code=ResponseCode.ALREADY_EXISTS, message="type_code 已存在", data=None)

    # 检查是否需要批量创建字典项
    items = payload.get("items", [])
    
    # 如果有字典项，验证字典项参数
    if items:
        item_codes = set()
        for i, item in enumerate(items):
            item_code = (item.get("item_code") or "").strip()
            item_label = (item.get("item_label") or "").strip()
            if not item_code or not item_label:
                return ApiResponse(code=ResponseCode.PARAM_ERROR, 
                                 message=f"第{i+1}个字典项的item_code/item_label为必填", data=None)
            if item_code in item_codes:
                return ApiResponse(code=ResponseCode.PARAM_ERROR, 
                                 message=f"字典项编码 '{item_code}' 重复", data=None)
            item_codes.add(item_code)

    try:
        # 创建字典类型
        dict_type = DictType(
            type_code=type_code,
            type_name=type_name,
            description=payload.get("description"),
            status=payload.get("status", 1),
            sequence_order=payload.get("sequence_order", 0),
            built_in=payload.get("built_in", 0)
        )
        db.add(dict_type)
        db.flush()  # 获取ID但不提交
        
        # 如果有字典项，批量创建
        created_items = []
        if items:
            for item in items:
                dict_item = DictItem(
                    type_id=dict_type.id,
                    item_code=item.get("item_code").strip(),
                    item_label=item.get("item_label").strip(),
                    item_value=item.get("item_value"),
                    color=item.get("color"),
                    icon=item.get("icon"),
                    status=item.get("status", 1),
                    sequence_order=item.get("sequence_order", 0),
                    remark=item.get("remark")
                )
                db.add(dict_item)
                created_items.append({
                    "item_code": dict_item.item_code,
                    "item_label": dict_item.item_label
                })
        
        # 提交事务
        db.commit()
        db.refresh(dict_type)
        
        # 返回结果
        result_data = {"id": dict_type.id, "type_code": dict_type.type_code}
        if created_items:
            result_data.update({
                "items_count": len(created_items),
                "items": created_items
            })
            message = f"创建字典类型和{len(created_items)}个字典项成功"
        else:
            message = "创建字典类型成功"
        
        return ApiResponse(code=ResponseCode.SUCCESS, message=message, data=result_data)
        
    except Exception as e:
        db.rollback()
        return ApiResponse(code=ResponseCode.SERVER_ERROR, message=f"创建失败: {str(e)}", data=None)



@router.put("/types/{type_id}", summary="更新字典类型")
async def update_dict_type(
    type_id: int,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    t = db.query(DictType).filter(DictType.id == type_id).first()
    if not t:
        return ApiResponse(code=ResponseCode.NOT_FOUND, message="字典类型不存在", data=None)
    if t.built_in:
        # 内置类型限制修改范围：不允许改编码与 built_in
        payload.pop("type_code", None)
        payload.pop("built_in", None)

    for field in ["type_name", "description", "status", "sequence_order"]:
        if field in payload:
            setattr(t, field, payload[field])
    db.commit()
    return ApiResponse(code=ResponseCode.SUCCESS, message="updated", data=None)


@router.delete("/types/{type_id}", summary="删除字典类型")
async def delete_dict_type(
    type_id: int,
    db: Session = Depends(get_db)
):
    t = db.query(DictType).filter(DictType.id == type_id).first()
    if not t:
        return ApiResponse(code=ResponseCode.NOT_FOUND, message="字典类型不存在", data=None)
    if t.built_in:
        return ApiResponse(code=ResponseCode.PARAM_ERROR, message="内置类型禁止删除", data=None)

    db.delete(t)
    db.commit()
    return ApiResponse(code=ResponseCode.SUCCESS, message="deleted", data=None)


@router.get("/types/{type_code}/items", summary="查询字典项")
async def list_dict_items(
    type_code: str,
    keyword: Optional[str] = Query(None),
    status: Optional[int] = Query(None),
    level: Optional[int] = Query(None, ge=1, le=5, description="按层级筛选，配合资产分类字典使用"),
    db: Session = Depends(get_db)
):
    t = db.query(DictType).filter(DictType.type_code == type_code).first()
    if not t:
        return ApiResponse(code=ResponseCode.NOT_FOUND, message="字典类型不存在", data=None)
    query = db.query(DictItem).filter(DictItem.type_id == t.id)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (DictItem.item_code.like(like)) |
            (DictItem.item_label.like(like)) |
            (DictItem.item_value.like(like))
        )
    if status is not None:
        query = query.filter(DictItem.status == status)
    query = query.order_by(DictItem.sequence_order.asc(), DictItem.created_at.desc())
    items = query.all()

    def _match_level(item: DictItem) -> bool:
        if level is None:
            return True
        if not item.item_value:
            return False
        try:
            value_data = json.loads(item.item_value)
        except (json.JSONDecodeError, TypeError):
            return False
        return value_data.get("level") == level

    filtered_items = [i for i in items if _match_level(i)]

    data = [{
        "id": i.id,
        "item_code": i.item_code,
        "item_label": i.item_label,
        "item_value": i.item_value,
        "color": i.color,
        "icon": i.icon,
        "status": i.status,
        "sequence_order": i.sequence_order,
        "remark": i.remark,
        "created_at": i.created_at,
        "updated_at": i.updated_at
    } for i in filtered_items]
    return ApiResponse(code=ResponseCode.SUCCESS, message="success", data=data)


@router.post("/types/{type_code}/items", summary="新增字典项")
async def create_dict_item(
    type_code: str,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    t = db.query(DictType).filter(DictType.type_code == type_code).first()
    if not t:
        return ApiResponse(code=ResponseCode.NOT_FOUND, message="字典类型不存在", data=None)

    item_code = (payload.get("item_code") or "").strip()
    item_label = (payload.get("item_label") or "").strip()
    if not item_code or not item_label:
        return ApiResponse(code=ResponseCode.PARAM_ERROR, message="item_code/item_label 为必填", data=None)

    exists = db.query(DictItem).filter(DictItem.type_id == t.id, DictItem.item_code == item_code).first()
    if exists:
        return ApiResponse(code=ResponseCode.ALREADY_EXISTS, message="item_code 已存在", data=None)

    i = DictItem(
        type_id=t.id,
        item_code=item_code,
        item_label=item_label,
        item_value=payload.get("item_value"),
        color=payload.get("color"),
        icon=payload.get("icon"),
        status=payload.get("status", 1),
        sequence_order=payload.get("sequence_order", 0),
        remark=payload.get("remark")
    )
    db.add(i)
    db.commit()
    db.refresh(i)
    return ApiResponse(code=ResponseCode.SUCCESS, message="created", data={"id": i.id})


@router.put("/items/{item_id}", summary="更新字典项")
async def update_dict_item(
    item_id: int,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    i = db.query(DictItem).filter(DictItem.id == item_id).first()
    if not i:
        return ApiResponse(code=ResponseCode.NOT_FOUND, message="字典项不存在", data=None)

    for field in ["item_label", "item_value", "color", "icon", "status", "sequence_order", "remark"]:
        if field in payload:
            setattr(i, field, payload[field])
    db.commit()
    return ApiResponse(code=ResponseCode.SUCCESS, message="updated", data=None)


@router.delete("/items/{item_id}", summary="删除字典项")
async def delete_dict_item(
    item_id: int,
    db: Session = Depends(get_db)
):
    i = db.query(DictItem).filter(DictItem.id == item_id).first()
    if not i:
        return ApiResponse(code=ResponseCode.NOT_FOUND, message="字典项不存在", data=None)
    db.delete(i)
    db.commit()
    return ApiResponse(code=ResponseCode.SUCCESS, message="deleted", data=None)


