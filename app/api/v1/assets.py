"""
IT资产管理系统 - 资产管理API路由
提供资产相关的RESTful API接口
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Path, UploadFile, File, Form, Body
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from datetime import date, datetime
import os
import pandas as pd
import io
import re
from urllib.parse import quote

from pydantic import BaseModel, Field

from app.db.session import get_db
from app.services.asset_service import AssetService, LocationService
from app.schemas.asset_schemas import (
    AssetCreate, AssetUpdate, AssetResponse, AssetDetailResponse,
    AssetSearchParams, PaginationParams, PaginatedResponse,
    AssetStatistics, DepartmentStatistics, CategoryStatistics,
    ApiResponse, ResponseCode,
)
from app.models.asset_models import Asset, Room, DictType, DictItem, WorkOrder, WorkOrderItem
from app.core.logging_config import get_logger
from app.constants.operation_types import OperationType, OperationResult

router = APIRouter()
logger = get_logger(__name__)


class SerialNumberBatchRequest(BaseModel):
    serial_numbers: List[str] = Field(..., min_items=1, max_items=500, description="需要校验的SN列表")


def _parse_serial_numbers(serial_number_raw: Optional[str]) -> List[str]:
    if not serial_number_raw:
        return []
    parts = re.split(r"[,\s]+", serial_number_raw.strip())
    return [part for part in (p.strip() for p in parts) if part]


def _build_asset_response(asset: Asset) -> AssetResponse:
    # 构建响应数据，只包含AssetResponse schema中定义的字段
    
    # 从notes字段中解析mpn、machine_model、three_stage_model等字段
    mpn = None
    machine_model = None
    three_stage_model = None
    order_number = getattr(asset, "order_number", None)
    notes_text = asset.notes
    
    if asset.notes:
        try:
            import json
            notes_data = json.loads(asset.notes)
            if isinstance(notes_data, dict):
                mpn = notes_data.get("mpn")
                machine_model = notes_data.get("machine_model")
                three_stage_model = notes_data.get("three_stage_model")
                # order_number也可能在notes中
                if not order_number:
                    order_number = notes_data.get("order_number")
        except (json.JSONDecodeError, TypeError):
            # 如果notes不是JSON格式，保持原样
            pass
    
    response_data = {
        "id": asset.id,
        "asset_tag": asset.asset_tag,
        "name": asset.name,
        "serial_number": asset.serial_number,
        "room_id": asset.room_id,
        "order_number": order_number,
        "room_name": asset.room.room_full_name if asset.room else None,
        "room_abbreviation": asset.room.room_abbreviation if asset.room else None,
        "room_number": asset.room.room_number if asset.room else None,
        "datacenter_abbreviation": asset.room.datacenter_abbreviation if asset.room else None,
        "building_number": asset.room.building_number if asset.room else None,
        "floor_number": asset.room.floor_number if asset.room else None,
        "quantity": getattr(asset, "quantity", None) or 1,
        "is_available": asset.is_available,
        "unavailable_reason": asset.unavailable_reason,
        "vendor_name": asset.vendor.name if hasattr(asset, "vendor") and asset.vendor else None,
        "model_name": asset.model,
        "mpn": mpn,
        "machine_model": machine_model,
        "three_stage_model": three_stage_model,
        "vendor_standard_model": getattr(asset, "vendor_standard_model", None),
        "location_detail": asset.location_detail,
        "asset_status": asset.asset_status,
        "lifecycle_status": asset.lifecycle_status,
        "device_direction": getattr(asset, "device_direction", None),
        "notes": notes_text,
        "created_by": getattr(asset, "owner", None),  # 使用owner字段作为创建人
        "extra_json": None,  # Asset模型中没有此字段
        "created_at": asset.created_at,
        "updated_at": asset.updated_at
    }
    
    # 分类信息（使用实际存在的关系）
    if hasattr(asset, "category_item") and asset.category_item:
        response_data["category"] = asset.category_item.item_label
    elif hasattr(asset, "category") and asset.category:
        response_data["category"] = asset.category.name
    else:
        response_data["category"] = None
    
    response_data["secondary_category"] = (
        asset.secondary_category_item.item_label
        if hasattr(asset, "secondary_category_item") and asset.secondary_category_item
        else None
    )
    response_data["tertiary_category"] = (
        asset.tertiary_category_item.item_label
        if hasattr(asset, "tertiary_category_item") and asset.tertiary_category_item
        else None
    )
    
    return AssetResponse(**response_data)


def get_asset_service(db: Session = Depends(get_db)) -> AssetService:
    return AssetService(db)

def get_location_service(db: Session = Depends(get_db)) -> LocationService:
    return LocationService(db)


# =====================================================
# 资产导入模版
# =====================================================

@router.get(
    "/import/template",
    summary="下载资产导入模板（Excel）",
    responses={
        200: {"description": "模板文件下载成功"}
    }
)
async def download_asset_import_template():
    """
    下载资产导入模板（Excel）
    
    功能说明：
    - 提供标准的资产导入Excel模板
    - 模板包含所有必要的列和格式
    
    返回说明：
    - 返回Excel文件流
    - 文件名：资产导入模板.xlsx
    - Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    
    模板包含列：
    - SN: 序列号（必填）
    - 出入库单号: 出入库单号（可选）
    - 一级分类: 设备一级分类（可选）
    - 二级分类: 设备二级分类（可选）
    - 三级分类: 设备三级分类（可选）
    - 厂商: 厂商名称（可选）
    - 型号: 设备型号（可选）
    - 厂商标准机型: 厂商标准机型（可选）
    - MPN: MPN编号（可选）
    - 机型: 机型（可选）
    - 三段机型: 三段机型（可选）
    - 机房: 机房名称（可选，用于匹配房间）
    - 房间: 房间名称（可选，需与数据库中的房间记录匹配）
    - 数量: 数量（可选，默认1）
    - 是否可用: 是否可用（可选，默认是）
    - 不可用原因: 不可用原因（可选）
    - 设备去向: 设备去向（可选，inbound/outbound）
    
    使用场景：
    - 批量导入资产前下载模板
    - 了解导入格式要求
    
    注意事项：
    - SN列为必填列
    - 模板格式固定，不要修改列名
    - 机房和房间字段需要与系统中已有的房间记录匹配才能关联
    """
    headers = [
        "SN",
        "出入库单号",
        "一级分类",
        "二级分类",
        "三级分类",
        "厂商",
        "型号",
        "厂商标准机型",
        "MPN",
        "机型",
        "三段机型",
        "机房",
        "房间",
        "数量",
        "是否可用",
        "不可用原因",
        "设备去向",
    ]

    df = pd.DataFrame(columns=headers)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="资产导入模板")
    output.seek(0)

    utf8_name = "资产导入模板.xlsx"
    ascii_fallback = "asset_import_template.xlsx"
    disposition = f'attachment; filename="{ascii_fallback}"; filename*=UTF-8''{quote(utf8_name)}'

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )


@router.post(
    "/import",
    response_model=ApiResponse,
    summary="批量导入资产（Excel）",
    responses={
        200: {"description": "导入成功"},
        400: {"description": "文件格式错误或数据验证失败"},
        500: {"description": "服务器内部错误"}
    }
)
async def import_assets(
    file: UploadFile = File(..., description="资产导入Excel文件（.xlsx或.xls格式，使用提供的模板）"),
    operator: str = Form(..., description="操作人姓名（必填）"),
    service: AssetService = Depends(get_asset_service)
):
    """
    批量导入资产（Excel）
    
    功能说明：
    - 根据模板批量导入资产数据
    - 自动验证数据格式和必填字段
    - 支持部分失败，生成错误报告
    
    请求参数说明：
    - file: Excel文件（必填，.xlsx或.xls格式）
    - operator: 操作人姓名（必填，表单参数）
    
    Excel必填列：
    - SN: 序列号（必填）
    - 一级分类: 设备一级分类（必填）
    
    Excel可选列：
    - 出入库单号、二级分类、三级分类
    - 厂商、型号、厂商标准机型、MPN、机型、三段机型
    - 机房、房间、数量
    - 是否可用、不可用原因、设备去向
    
    机房和房间说明：
    - 机房和房间字段用于关联系统中已有的房间记录
    - 系统会根据机房+房间名称匹配数据库中的房间
    - 如果匹配不到，room_id会为空，但不会导致导入失败
    - 房间匹配支持：房间全称、房间缩写、房间号
    
    返回字段说明：
    - code (integer): 响应码，0表示成功，非0表示失败
    - message (string): 响应消息，描述操作结果
    - data (object): 导入结果对象，包含以下字段：
      - success_count (integer): 成功导入的资产数量
      - failure_count (integer): 导入失败的资产数量
      - created_asset_ids (array[integer]): 成功创建的资产ID列表
      - errors (array[object]): 错误列表，每个错误对象包含：
        - row (integer): Excel中的行号（从2开始，第1行为标题）
        - serial_number (string): 该行的序列号
        - error (string): 错误原因描述
      - error_report (string|null): 错误报告下载链接，格式为 /api/v1/assets/import/error-report/{filename}，如无失败记录则为null
    - timestamp (string): 响应时间戳，ISO 8601格式
    
    响应示例：
    ```json
    {
      "code": 0,
      "message": "导入成功10条，导入失败2条，请下载错误报告查看",
      "data": {
        "success_count": 10,
        "failure_count": 2,
        "created_asset_ids": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
        "errors": [
          {"row": 5, "serial_number": "SN12345", "error": "序列号已存在"},
          {"row": 8, "serial_number": "SN67890", "error": "一级分类不存在"}
        ],
        "error_report": "/api/v1/assets/import/error-report/资产导入失败记录_20251212095000.xlsx"
      },
      "timestamp": "2025-12-12T09:50:00.000000"
    }
    ```
    
    使用场景：
    - 批量导入资产数据
    - 资产初始化
    - 资产数据迁移
    
    注意事项：
    - 必须使用提供的模板格式
    - Excel文件不能为空
    - SN和一级分类为必填列
    - 支持部分失败，失败记录会生成错误报告
    - 错误报告可通过返回的链接下载
    """
    if not file.filename:
        return ApiResponse(
            code=ResponseCode.PARAM_ERROR,
            message="请上传有效的Excel文件",
            data={"success_count": 0, "failure_count": 0, "error_report": None}
        )
    
    filename = file.filename.lower()
    if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
        return ApiResponse(
            code=ResponseCode.PARAM_ERROR,
            message="仅支持.xlsx或.xls格式的Excel文件",
            data={"success_count": 0, "failure_count": 0, "error_report": None}
        )
    
    try:
        file_bytes = await file.read()
        df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as exc:
        logger.error("Failed to parse asset import file", extra={"error": str(exc)})
        return ApiResponse(
            code=ResponseCode.PARAM_ERROR,
            message="无法读取Excel文件，请确认文件格式是否与模板一致",
            data={"success_count": 0, "failure_count": 0, "error_report": None}
        )
    
    df = df.dropna(how="all")
    if df.empty:
        return ApiResponse(
            code=ResponseCode.PARAM_ERROR,
            message="导入文件中没有有效数据",
            data={"success_count": 0, "failure_count": 0, "error_report": None}
        )
    
    df.columns = [str(col).strip() for col in df.columns]
    required_columns = {"SN", "一级分类"}
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        return ApiResponse(
            code=ResponseCode.PARAM_ERROR,
            message=f"导入模板缺少必要列: {', '.join(missing_columns)}",
            data={"success_count": 0, "failure_count": 0, "error_report": None}
        )
    
    records = df.to_dict(orient="records")
    result = service.import_assets_from_records(records, operator)

    error_report_url = None
    errors = result.get("errors") or []
    if errors:
        try:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            temp_dir = os.path.abspath(os.path.join(base_dir, "temp"))
            os.makedirs(temp_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"资产导入失败记录_{timestamp}.xlsx"
            report_path = os.path.join(temp_dir, filename)
            error_rows = []
            for err in errors:
                error_rows.append({
                    "行号": err.get("row"),
                    "序列号": err.get("serial_number"),
                    "错误信息": err.get("error"),
                })
            pd.DataFrame(error_rows).to_excel(report_path, index=False)
            error_report_url = f"/api/v1/assets/import/error-report/{quote(filename)}"
        except Exception as exc:
            logger.error("Failed to generate asset import error report", extra={"error": str(exc)})
            error_report_url = None
    result["error_report"] = error_report_url
    
    success_count = result.get("success_count", 0)
    failure_count = result.get("failure_count", 0)
    message = f"导入成功{success_count}条，导入失败{failure_count}条"
    if failure_count > 0 and error_report_url:
        message += "，请下载错误报告查看"
    
    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message=message,
        data=result
    )


@router.get(
    "/import/error-report/{filename}",
    summary="下载资产导入失败报告",
    responses={
        200: {"description": "文件下载成功"},
        404: {"description": "文件不存在"}
    }
)
async def download_asset_error_report(
    filename: str = Path(..., description="错误报告文件名")
):
    """
    下载资产导入失败报告
    
    功能说明：
    - 下载资产导入失败的Excel错误报告
    - 包含失败原因和行号信息
    
    路径参数说明：
    - filename: 错误报告文件名（从导入接口返回的error_report链接中获取）
    
    返回说明：
    - 返回Excel文件流
    - Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    - 文件包含行号、序列号和错误信息列
    
    使用场景：
    - 导入失败后下载错误报告
    - 查看失败原因
    - 修正数据后重新导入
    
    注意事项：
    - 文件存储在temp目录
    - 文件名格式：资产导入失败记录_{timestamp}.xlsx
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    temp_dir = os.path.abspath(os.path.join(base_dir, "temp"))
    safe_name = os.path.basename(filename)
    file_path = os.path.join(temp_dir, safe_name)

    if not os.path.exists(file_path):
        return ApiResponse(code=ResponseCode.NOT_FOUND, message="文件不存在", data=None)

    try:
        safe_name.encode("latin-1")
        disposition = f'attachment; filename="{safe_name}"'
    except UnicodeEncodeError:
        ascii_name = "asset_error_report.xlsx"
        disposition = f'attachment; filename="{ascii_name}"; filename*=UTF-8''{quote(safe_name)}'

    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )


# =====================================================
# 资产基础CRUD接口
# =====================================================

@router.post(
    "/",
    response_model=ApiResponse,
    summary="创建资产",
    responses={
        200: {"description": "创建成功"},
        400: {"description": "参数错误或资产标签已存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def create_asset(
    asset_data: AssetCreate = Body(
        ...,
        examples=[
            {
                "asset_tag": "ASSET-2025-001",
                "name": "服务器-Dell R740",
                "serial_number": "SN123456789",
                "room_id": 1,
                "category_item_id": 10,
                "secondary_category_item_id": 20,
                "tertiary_category_item_id": 30,
                "model": "Dell PowerEdge R740",
                "vendor_standard_model": "R740",
                "location_detail": "A01机柜-U10",
                "asset_status": "active",
                "lifecycle_status": "registered",
                "is_available": True,
                "quantity": 1,
                "notes": "新采购服务器"
            }
        ]
    ),
    operator: str = Query("system", description="操作人姓名"),
    service: AssetService = Depends(get_asset_service)
):
    """
    创建新资产
    
    功能说明：
    - 创建新的资产记录
    - 自动记录创建日志到ES
    - 支持设置资产的基本信息、分类、位置等
    
    请求参数说明：
    - asset_tag: 资产标签（必填，必须唯一）
    - name: 资产名称（必填）
    - serial_number: 序列号（可选，建议填写）
    - room_id: 房间ID（可选）
    - category_item_id: 一级分类ID（可选）
    - secondary_category_item_id: 二级分类ID（可选）
    - tertiary_category_item_id: 三级分类ID（可选）
    - model: 型号（可选）
    - vendor_standard_model: 厂商标准机型（可选）
    - location_detail: 具体位置描述（可选，如机柜号、U位等）
    - asset_status: 资产管理状态（可选，默认active）
    - lifecycle_status: 生命周期状态（可选，默认registered）
    - is_available: 是否可用（可选，默认true）
    - quantity: 数量（可选，默认1）
    - notes: 备注（可选）
    - operator: 操作人（查询参数，默认system）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 创建的资产对象（包含所有资产字段）
    
    使用场景：
    - 手动创建单个资产
    - 资产登记
    - 资产初始化
    
    注意事项：
    - asset_tag必须唯一，重复会返回400错误
    - serial_number建议填写，便于后续管理
    - room_id必须是已存在的房间ID
    - category_item_id等分类ID必须是已存在的字典项ID
    - 创建成功后会自动记录操作日志
    """
    try:
        asset = service.create_asset(asset_data, operator)
        
        # 记录资产创建日志
        logger.info("Asset created successfully", extra={
            "operationObject": asset.serial_number or asset.asset_tag,
            "operationType": OperationType.ASSET_CREATE,
            "operator": operator,
            "result": OperationResult.SUCCESS
        })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="创建成功",
            data=_build_asset_response(asset).model_dump()
        )
    except ValueError as e:
        logger.error("Asset creation failed", extra={
            "operationObject": asset_data.serial_number or asset_data.asset_tag,
            "operationType": OperationType.ASSET_CREATE,
            "operator": operator,
            "result": OperationResult.FAILED
        })
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Asset creation error", extra={
            "operationObject": asset_data.serial_number or asset_data.asset_tag,
            "operationType": OperationType.ASSET_CREATE,
            "operator": operator,
            "result": OperationResult.FAILED
        })
        raise HTTPException(status_code=500, detail=f"创建资产失败: {str(e)}")


@router.put(
    "/{asset_id}/availability",
    response_model=ApiResponse,
    summary="更新资产可用状态",
    responses={
        200: {"description": "更新成功"},
        400: {"description": "参数错误"},
        404: {"description": "资产不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def update_asset_availability(
    asset_id: int = Path(..., description="资产ID", example=1),
    is_available: bool = Query(..., description="是否可用：true（可用）/false（不可用）"),
    unavailable_reason: Optional[str] = Query(None, description="不可用原因（当is_available为false时建议填写）"),
    service: AssetService = Depends(get_asset_service)
):
    """
    更新资产可用状态
    
    功能说明：
    - 单独更新资产的可用状态
    - 自动记录状态变更日志到ES
    - 支持设置不可用原因
    
    路径参数说明：
    - asset_id: 资产ID（必填）
    
    查询参数说明：
    - is_available: 是否可用（必填，true/false）
    - unavailable_reason: 不可用原因（可选，当设置为不可用时建议填写）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 更新后的资产对象（包含所有资产字段）
    
    使用场景：
    - 设备故障时标记为不可用
    - 设备维修完成后恢复可用
    - 设备状态管理
    
    注意事项：
    - 资产ID必须存在
    - 设置为不可用时建议填写原因
    - 设置为可用时会自动清空不可用原因
    - 状态变更会记录到ES日志
    """
    try:
        # 验证资产是否存在
        asset = service.get_asset(asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="资产不存在")
        
        # 验证参数
        if not is_available and not unavailable_reason:
            raise HTTPException(
                status_code=400, 
                detail="设置为不可用时，建议提供不可用原因"
            )
        
        # 更新可用状态
        updated_asset = service.update_asset_availability(
            asset_id=asset_id,
            is_available=is_available,
            unavailable_reason=unavailable_reason if not is_available else None
        )
        
        # 记录资产状态更新日志
        operation_type = OperationType.ASSET_SET_AVAILABLE if is_available else OperationType.ASSET_SET_UNAVAILABLE
        logger.info("Asset availability updated successfully", extra={
            "operationObject": updated_asset.serial_number or updated_asset.asset_tag,
            "operationType": operation_type,
            "operator": "system",
            "result": OperationResult.SUCCESS
        })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="更新成功",
            data=_build_asset_response(updated_asset).model_dump()
        )
        
    except ValueError as e:
        logger.error("Asset availability update failed", extra={
            "operationObject": f"asset_id:{asset_id}",
            "operationType": OperationType.ASSET_SET_AVAILABLE if is_available else OperationType.ASSET_SET_UNAVAILABLE,
            "operator": "system",
            "result": OperationResult.FAILED
        })
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Asset availability update error", extra={
            "operationObject": f"asset_id:{asset_id}",
            "operationType": OperationType.ASSET_SET_AVAILABLE if is_available else OperationType.ASSET_SET_UNAVAILABLE,
            "operator": "system",
            "result": OperationResult.FAILED
        })
        raise HTTPException(status_code=500, detail=f"更新资产可用状态失败: {str(e)}")

@router.get(
    "/export",
    summary="批量导出资产",
    responses={
        200: {"description": "导出成功，返回Excel文件"},
        404: {"description": "没有找到符合条件的资产数据"},
        500: {"description": "服务器内部错误"}
    }
)
async def export_assets(
    # 搜索参数（与查询接口相同）
    asset_tag: Optional[str] = Query(None, description="资产标签（模糊搜索）"),
    name: Optional[str] = Query(None, description="资产名称（模糊搜索）"),
    serial_number: Optional[str] = Query(None, description="序列号（精确匹配，多个序列号用逗号分隔）"),
    asset_status: Optional[str] = Query(None, description="资产状态：active/inactive/maintenance/retired/disposed"),
    lifecycle_status: Optional[str] = Query(None, description="生命周期状态"),
    room_id: Optional[int] = Query(None, description="房间ID（精确匹配）"),
    datacenter: Optional[str] = Query(None, description="机房缩写（精确匹配）"),
    is_available: Optional[bool] = Query(None, description="是否可用：true/false"),
    
    # 分类查询参数（文字形式）
    category: Optional[str] = Query(None, description="一级分类（文字，模糊搜索）"),
    secondary_category: Optional[str] = Query(None, description="二级分类（文字，模糊搜索）"),
    tertiary_category: Optional[str] = Query(None, description="三级分类（文字，模糊搜索）"),
    
    # 创建时间范围查询
    created_from: Optional[datetime] = Query(None, description="创建时间起始，格式：YYYY-MM-DD HH:MM:SS"),
    created_to: Optional[datetime] = Query(None, description="创建时间结束，格式：YYYY-MM-DD HH:MM:SS"),
    
    # 导出参数
    export_all: bool = Query(False, description="是否导出所有数据（忽略分页限制，最多导出100条）"),
    
    service: AssetService = Depends(get_asset_service)
):
    """
    批量导出资产数据为Excel文件
    
    功能说明：
    - 根据筛选条件导出资产数据为Excel文件
    - 支持与查询接口相同的所有筛选条件
    - 自动设置Excel列宽
    - 文件名包含时间戳
    
    查询参数说明：
    - asset_tag: 资产标签（模糊搜索）
    - name: 资产名称（模糊搜索）
    - serial_number: 序列号（精确匹配，多个序列号用逗号分隔）
    - asset_status: 资产管理状态
    - lifecycle_status: 生命周期状态
    - room_id: 房间ID（精确匹配）
    - datacenter: 机房缩写（精确匹配）
    - is_available: 是否可用
    - category: 一级分类（文字，模糊搜索）
    - secondary_category: 二级分类（文字，模糊搜索）
    - tertiary_category: 三级分类（文字，模糊搜索）
    - created_from/created_to: 创建时间范围
    - export_all: 是否导出所有数据（默认false，最多导出100条）
    
    返回说明：
    - 返回Excel文件流
    - 文件名格式：资产导出_{YYYYMMdd_HHmmss}.xlsx
    - Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    
    Excel包含列：
    - SN: 序列号
    - 出入库单号: 出入库单号
    - 一级分类: 设备一级分类
    - 二级分类: 设备二级分类
    - 三级分类: 设备三级分类
    - 厂商: 厂商名称
    - 型号: 设备型号
    - MPN: MPN编号
    - 机型: 机型
    - 三段机型: 三段机型
    - 机房: 机房缩写
    - 房间: 房间名称
    - 是否可用: 是/否
    - 设备去向: 设备去向（入库/出库）
    - 创建人: 资产创建人
    - 创建时间: 资产创建时间
    
    使用场景：
    - 批量导出资产数据
    - 生成资产报表
    - 资产数据备份
    - 资产数据分析
    
    注意事项：
    - 所有查询参数都是可选的
    - 不传参数时导出所有资产（最多100条）
    - serial_number支持多个序列号，用逗号分隔
    - 导出数量限制为100条，避免文件过大
    - Excel列宽自动调整，最大宽度50
    - 文件名使用UTF-8编码
    """
    try:
        # 构建搜索参数
        search_params = AssetSearchParams(
            asset_tag=asset_tag,
            name=name,
            serial_number=serial_number,
            asset_status=asset_status,
            lifecycle_status=lifecycle_status,
            is_available=is_available,
            room_id=room_id,
            category=category,
            secondary_category=secondary_category,
            tertiary_category=tertiary_category,
            created_from=created_from,
            created_to=created_to
        )
        
        # 设置分页参数 - 如果导出所有数据，设置最大允许的页面大小
        if export_all:
            pagination_params = PaginationParams(page=1, size=100)  # 导出最多100条
        else:
            pagination_params = PaginationParams(page=1, size=100)   # 默认导出100条
        
        # 对于导出功能，如果有序列号查询，使用精确匹配
        if serial_number:
            # 直接查询数据库，使用精确匹配
            query = service.db.query(Asset)
            
            # 应用其他搜索条件
            if asset_tag:
                query = query.filter(Asset.asset_tag.like(f"%{asset_tag}%"))
            if name:
                query = query.filter(Asset.name.like(f"%{name}%"))
            if serial_number:
                serial_numbers = _parse_serial_numbers(serial_number)
                if len(serial_numbers) == 1:
                    query = query.filter(Asset.serial_number == serial_numbers[0])
                else:
                    query = query.filter(Asset.serial_number.in_(serial_numbers))
            if asset_status:
                query = query.filter(Asset.asset_status == asset_status)
            if lifecycle_status:
                query = query.filter(Asset.lifecycle_status == lifecycle_status)
            if room_id:
                query = query.filter(Asset.room_id == room_id)
            if datacenter:
                query = query.join(Room, Asset.room_id == Room.id).filter(Room.datacenter_abbreviation == datacenter)
            
            # 分类查询
            if category:
                from app.models.asset_models import DictItem
                category_items = service.db.query(DictItem).filter(
                    DictItem.item_label.like(f"%{category}%")
                ).all()
                if category_items:
                    category_ids = [item.id for item in category_items]
                    query = query.filter(Asset.category_item_id.in_(category_ids))
                else:
                    query = query.filter(Asset.id.is_(None))
            
            if secondary_category:
                from app.models.asset_models import DictItem
                secondary_items = service.db.query(DictItem).filter(
                    DictItem.item_label.like(f"%{secondary_category}%")
                ).all()
                if secondary_items:
                    secondary_ids = [item.id for item in secondary_items]
                    query = query.filter(Asset.secondary_category_item_id.in_(secondary_ids))
                else:
                    query = query.filter(Asset.id.is_(None))
            
            if tertiary_category:
                from app.models.asset_models import DictItem
                tertiary_items = service.db.query(DictItem).filter(
                    DictItem.item_label.like(f"%{tertiary_category}%")
                ).all()
                if tertiary_items:
                    tertiary_ids = [item.id for item in tertiary_items]
                    query = query.filter(Asset.tertiary_category_item_id.in_(tertiary_ids))
                else:
                    query = query.filter(Asset.id.is_(None))
            
            # 时间范围查询
            if created_from:
                query = query.filter(Asset.created_at >= created_from)
            if created_to:
                query = query.filter(Asset.created_at <= created_to)
            
            # 获取结果
            assets = query.limit(100).all()
            total = len(assets)
        else:
            # 没有序列号查询时，使用原有的搜索服务（支持模糊匹配）
            assets, total = service.search_assets(search_params, pagination_params, datacenter=datacenter)
        
        if not assets:
            raise HTTPException(status_code=404, detail="没有找到符合条件的资产数据")
        
        # 构建导出数据
        export_data = []
        for asset in assets:
            asset_response = _build_asset_response(asset)
            
            # 转换为字典格式
            asset_dict = {
                "SN": asset_response.serial_number or "",
                "出入库单号": asset_response.order_number or "",
                "一级分类": asset_response.category or "",
                "二级分类": asset_response.secondary_category or "",
                "三级分类": asset_response.tertiary_category or "",
                "厂商": asset_response.vendor_name or "",
                "型号": asset_response.model_name or "",
                "MPN": asset_response.mpn or "",
                "机型": asset_response.machine_model or "",
                "三段机型": asset_response.three_stage_model or "",
                "机房": asset_response.datacenter_abbreviation or "",
                "房间": asset_response.room_name or "",
                "是否可用": "是" if asset_response.is_available else "否",
                "设备去向": {"inbound": "入库", "outbound": "出库"}.get(asset_response.device_direction, "") if asset_response.device_direction else "",
                "创建人": asset_response.created_by or "",
                "创建时间": asset_response.created_at.strftime("%Y-%m-%d %H:%M:%S") if asset_response.created_at else "",
            }
            export_data.append(asset_dict)
        
        # 创建DataFrame
        df = pd.DataFrame(export_data)
        
        # 创建Excel文件
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='资产数据', index=False)
            
            # 获取工作表并设置列宽
            worksheet = writer.sheets['资产数据']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)  # 最大宽度50
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"资产导出_{timestamp}.xlsx"
        encoded_filename = quote(filename.encode('utf-8'))
        
        # 返回文件
        return StreamingResponse(
            io.BytesIO(output.read()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.get(
    "/serial-number/validate",
    summary="查询SN是否有效",
    response_model=ApiResponse,
    responses={
        200: {"description": "查询成功"},
        500: {"description": "服务器内部错误"}
    }
)
async def validate_serial_number(
    serial_number: str = Query(..., description="要校验的设备序列号SN", example="SN123456789"),
    db: Session = Depends(get_db)
):
    """
    查询SN是否有效
    
    功能说明：
    - 根据序列号判断资产是否存在于系统中
    - 返回资产的基本信息
    
    查询参数说明：
    - serial_number: 设备序列号（必填，精确匹配）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息（"SN有效"或"SN不存在"）
    - data: 校验结果对象
      - serial_number: 序列号
      - is_valid: 是否有效（true/false）
      - asset_id: 资产ID（如果存在）
      - asset_tag: 资产标签（如果存在）
      - name: 资产名称（如果存在）
      - asset_status: 资产状态（如果存在）
      - room_id: 房间ID（如果存在）
      - category: 分类名称（如果存在）
    
    使用场景：
    - 创建工单前验证设备是否存在
    - 导入数据前验证SN
    - 设备查询
    
    注意事项：
    - SN必须精确匹配
    - 不存在的SN返回is_valid=false
    - 存在的SN返回基本信息
    """
    try:
        asset = db.query(Asset).filter(Asset.serial_number == serial_number).first()
        data = {
            "serial_number": serial_number,
            "is_valid": asset is not None,
            "asset_id": asset.id if asset else None,
            "asset_tag": asset.asset_tag if asset else None,
            "name": asset.name if asset else None,
            "asset_status": asset.asset_status if asset else None,
            "room_id": asset.room_id if asset else None,
            "category": asset.category.name if asset and hasattr(asset, "category") and asset.category else None,
        }
        message = "SN有效" if asset else "SN不存在"
        return ApiResponse(code=ResponseCode.SUCCESS, message=message, data=data)
    except Exception as e:
        logger.error("SN校验失败", extra={
            "operationObject": serial_number,
            "operationType": getattr(OperationType, "ASSET_SEARCH", OperationType.ASSET_CREATE),
            "result": OperationResult.FAILED,
            "operationDetail": str(e)
        })
        raise HTTPException(status_code=500, detail=f"SN校验失败: {str(e)}")


@router.get(
    "/serial-number/location",
    summary="根据SN查询机房/位置信息",
    response_model=ApiResponse,
    responses={
        200: {"description": "查询成功"},
        404: {"description": "资产不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_location_by_serial_number(
    serial_number: str = Query(..., description="设备序列号SN", example="SN123456789"),
    db: Session = Depends(get_db)
):
    """
    根据SN查询机房/位置信息
    
    功能说明：
    - 通过序列号快速定位设备所在机房/房间
    - 返回房间、机房、位置描述等信息
    
    查询参数说明：
    - serial_number: 设备序列号（必填，精确匹配）
    
    返回字段说明：
    - code: 响应码（0表示成功，404表示未找到）
    - message: 响应消息
    - data: 位置信息对象
      - serial_number: 序列号
      - asset_tag: 资产标签
      - name: 资产名称
      - datacenter: 机房缩写
      - room_id: 房间ID
      - room_name: 房间全称
      - room_abbreviation: 房间简称
      - room_number: 房间编号
      - location_detail: 位置描述（如机柜+U位）
      - cabinet: 机柜编号（从location_detail解析）
      - rack_position: 机位/U位（从location_detail解析，如"U10-U12"）
      - lifecycle_status: 生命周期状态
    
    使用场景：
    - 工单创建或处理前快速确认设备所在机房
    - 现场定位设备
    - 前端搜索框按SN定位
    
    注意事项：
    - 必须提供准确SN
    - 如果资产未关联房间，相关字段返回null
    """
    try:
        asset = db.query(Asset).filter(Asset.serial_number == serial_number).first()
        if not asset:
            return ApiResponse(
                code=1002,
                message="资产不存在",
                data=None
            )

        room = asset.room
        
        # 解析location_detail获取机柜和机位信息
        cabinet = None
        rack_position = None
        if asset.location_detail:
            # location_detail格式示例: "机柜A-01 U10-U12" 或 "TEST-CAB-001 U10-U11"
            location_parts = asset.location_detail.split()
            if len(location_parts) >= 1:
                cabinet = location_parts[0].replace("机柜", "").strip()
            if len(location_parts) >= 2 and location_parts[1].startswith("U"):
                rack_position = location_parts[1]
        
        data = {
            "serial_number": asset.serial_number,
            "asset_tag": asset.asset_tag,
            "name": asset.name,
            "datacenter": room.datacenter_abbreviation if room else None,
            "room_id": asset.room_id,
            "room_name": room.room_full_name if room else None,
            "room_abbreviation": room.room_abbreviation if room else None,
            "room_number": room.room_number if room else None,
            "location_detail": asset.location_detail,
            "cabinet": cabinet,  # 新增：机柜编号
            "rack_position": rack_position,  # 新增：机位（U位）
            "lifecycle_status": asset.lifecycle_status,
        }

        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="SN位置查询成功",
            data=data
        )
    except Exception as e:
        logger.exception("Get asset location by SN failed", extra={"serial_number": serial_number})
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询SN位置失败: {str(e)}",
            data=None
        )


@router.post(
    "/serial-number/validate/batch",
    summary="批量查询SN是否有效",
    response_model=ApiResponse,
    responses={
        200: {"description": "查询成功"},
        400: {"description": "参数错误"},
        500: {"description": "服务器内部错误"}
    }
)
async def validate_serial_number_batch(
    request: SerialNumberBatchRequest = Body(
        ...,
        examples=[
            {
                "serial_numbers": ["SN123456789", "SN987654321", "SN111222333"]
            }
        ]
    ),
    db: Session = Depends(get_db)
):
    """
    批量查询SN是否有效
    
    功能说明：
    - 批量验证多个序列号是否存在于系统中
    - 返回每个SN的验证结果和基本信息
    - 统计有效和无效的SN数量
    
    请求参数说明：
    - serial_numbers: 序列号列表（必填，数组，最少1个，最多500个）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 批量校验结果对象
      - total: 总数量
      - valid_count: 有效数量
      - invalid_count: 无效数量
      - items: 校验结果列表
        - serial_number: 序列号
        - is_valid: 是否有效（true/false）
        - asset_id: 资产ID（如果存在）
        - asset_tag: 资产标签（如果存在）
        - name: 资产名称（如果存在）
        - asset_status: 资产状态（如果存在）
        - room_id: 房间ID（如果存在）
        - category: 分类名称（如果存在）
    
    使用场景：
    - 批量导入前验证SN
    - 批量创建工单前验证设备
    - 批量查询设备信息
    
    注意事项：
    - 最少提供1个SN，最多500个
    - SN必须精确匹配
    - 返回结果按输入顺序排列
    - 统计信息包含有效和无效数量
    """
    try:
        sn_list = [sn.strip() for sn in request.serial_numbers if sn and sn.strip()]
        if not sn_list:
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message="请至少提供一个有效的SN",
                data=None
            )

        assets = db.query(Asset).filter(Asset.serial_number.in_(sn_list)).all()
        asset_map = {asset.serial_number: asset for asset in assets}

        items = []
        for sn in sn_list:
            asset = asset_map.get(sn)
            items.append({
                "serial_number": sn,
                "is_valid": asset is not None,
                "asset_id": asset.id if asset else None,
                "asset_tag": asset.asset_tag if asset else None,
                "name": asset.name if asset else None,
                "asset_status": asset.asset_status if asset else None,
                "room_id": asset.room_id if asset else None,
                "category": asset.category.name if asset and hasattr(asset, "category") and asset.category else None,
            })

        data = {
            "total": len(sn_list),
            "valid_count": sum(1 for item in items if item["is_valid"]),
            "invalid_count": sum(1 for item in items if not item["is_valid"]),
            "items": items,
        }

        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="批量校验完成",
            data=data
        )
    except Exception as e:
        logger.error("批量SN校验失败", extra={
            "operationObject": ",".join(request.serial_numbers[:5]),
            "operationType": getattr(OperationType, "ASSET_SEARCH", OperationType.ASSET_CREATE),
            "result": OperationResult.FAILED,
            "operationDetail": str(e)
        })
        raise HTTPException(status_code=500, detail=f"批量SN校验失败: {str(e)}")


@router.get(
    "/",
    summary="搜索资产",
    response_model=ApiResponse,
    responses={
        200: {"description": "查询成功"},
        400: {"description": "参数错误"},
        500: {"description": "服务器内部错误"}
    }
)
async def search_assets(
    # 分页参数
    page: int = Query(1, ge=1, description="页码，从1开始"),
    size: int = Query(10, ge=1, le=10000, description="每页数量，最大10000"),
    
    # 搜索参数
    asset_tag: Optional[str] = Query(None, description="资产标签（模糊搜索）"),
    name: Optional[str] = Query(None, description="资产名称（模糊搜索）"),
    serial_number: Optional[str] = Query(None, description="序列号（模糊搜索，支持多个序列号用逗号分隔）"),
    asset_status: Optional[str] = Query(None, description="资产状态：active（在用）/inactive（闲置）/maintenance（维护中）/retired（已退役）/disposed（已处置）"),
    lifecycle_status: Optional[str] = Query(None, description="生命周期状态：registered（已登记）/received（已到货）/inspected（已验收）/in_stock（已入库）/racked（已上架）/configured（已配置）/powered_on（已上电）/running（运行中）/powered_off（已下电）/maintenance（维护中）/retired（已退役）"),
    device_direction: Optional[str] = Query(None, description="设备去向：inbound（入库）/outbound（出库）"),
    room_id: Optional[int] = Query(None, description="房间ID（精确匹配）"),
    datacenter: Optional[str] = Query(None, description="机房缩写（精确匹配）"),
    datacenter_abbreviation: Optional[str] = Query(None, description="机房缩写（精确匹配，与datacenter参数等效）"),
    
    # 分类查询参数
    category: Optional[str] = Query(None, description="一级分类（模糊搜索）"),
    secondary_category: Optional[str] = Query(None, description="二级分类（模糊搜索）"),
    tertiary_category: Optional[str] = Query(None, description="三级分类（模糊搜索）"),
    
    # 创建时间范围查询
    created_from: Optional[datetime] = Query(None, description="创建时间起始，格式：YYYY-MM-DD HH:MM:SS"),
    created_to: Optional[datetime] = Query(None, description="创建时间结束，格式：YYYY-MM-DD HH:MM:SS"),
    
    # 其他查询参数
    is_available: Optional[bool] = Query(None, description="是否可用：true（可用）/false（不可用）"),
    model: Optional[str] = Query(None, description="设备型号（模糊搜索）"),
    vendor: Optional[str] = Query(None, description="厂商（模糊搜索）"),
    
    service: AssetService = Depends(get_asset_service)
):
    """
    资产搜索接口
    
    功能说明：
    - 支持多条件组合查询资产列表
    - 支持分页查询
    - 支持模糊搜索和精确匹配
    - 按创建时间倒序排列
    
    查询参数说明：
    - page: 页码（从1开始，默认1）
    - size: 每页数量（1-100，默认10）
    - asset_tag: 资产标签（模糊搜索）
    - name: 资产名称（模糊搜索）
    - serial_number: 序列号（模糊搜索，支持多个序列号用逗号分隔）
    - asset_status: 资产管理状态（active/inactive/maintenance/retired/disposed）
    - lifecycle_status: 生命周期状态（registered/received/inspected/in_stock/racked/configured/powered_on/running/powered_off/maintenance/retired）
    - device_direction: 设备去向（inbound/outbound）
    - room_id: 房间ID（精确匹配）
    - datacenter: 机房缩写（精确匹配）
    - category: 一级分类（模糊搜索）
    - secondary_category: 二级分类（模糊搜索）
    - tertiary_category: 三级分类（模糊搜索）
    - created_from/created_to: 创建时间范围
    - is_available: 是否可用（true/false）
    - model: 设备型号（模糊搜索）
    - vendor: 厂商（模糊搜索）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 数据对象
      - total: 总记录数
      - page: 当前页码
      - size: 每页大小
      - items: 资产列表
        - id: 资产ID
        - asset_tag: 资产标签
        - name: 资产名称
        - serial_number: 序列号
        - room_id: 房间ID
        - order_number: 订单号
        - room_name: 房间全称
        - room_abbreviation: 房间简称
        - room_number: 房间编号
        - datacenter_abbreviation: 机房缩写
        - building_number: 楼栋号
        - floor_number: 楼层号
        - quantity: 数量（默认1）
        - is_available: 是否可用
        - unavailable_reason: 不可用原因
        - vendor_name: 厂商名称
        - model_name: 型号
        - mpn: MPN编号
        - machine_model: 机型
        - three_stage_model: 三段机型
        - vendor_standard_model: 厂商标准机型
        - location_detail: 位置详情（如机柜号、U位等）
        - asset_status: 资产管理状态
        - lifecycle_status: 生命周期状态
        - device_direction: 设备去向
        - notes: 备注
        - category: 一级分类
        - secondary_category: 二级分类
        - tertiary_category: 三级分类
        - created_by: 创建人/责任人
        - extra_json: 扩展信息（JSON）
        - created_at: 创建时间（ISO格式）
        - updated_at: 更新时间（ISO格式）
    
    使用场景：
    - 资产列表页查询
    - 按多维度筛选资产
    - 按序列号查询资产
    - 按位置查询资产
    - 按分类查询资产
    - 按状态查询资产
    - 资产统计分析
    
    注意事项：
    - 所有查询参数都是可选的
    - 不传参数时返回所有资产（分页）
    - 字符串参数支持模糊搜索（除了明确标注精确匹配的）
    - serial_number支持多个序列号查询，用逗号分隔
    - 时间参数需要符合ISO格式
    - 分页参数size最大为100
    - 查询结果按创建时间倒序排列
    """
    try:
        # 合并datacenter和datacenter_abbreviation参数（优先使用datacenter_abbreviation）
        effective_datacenter = datacenter_abbreviation or datacenter
        
        # 构建搜索参数
        search_params = AssetSearchParams(
            asset_tag=asset_tag,
            name=name,
            serial_number=serial_number,
            asset_status=asset_status,
            lifecycle_status=lifecycle_status,
            device_direction=device_direction,
            is_available=is_available,
            room_id=room_id,
            category=category,
            secondary_category=secondary_category,
            tertiary_category=tertiary_category,
            created_from=created_from,
            created_to=created_to
        )
        
        pagination_params = PaginationParams(page=page, size=size)
        
        # 如果有序列号查询，直接查询数据库（支持精确匹配）
        if serial_number:
            serial_numbers = _parse_serial_numbers(serial_number)
            query = service.db.query(Asset)
            if len(serial_numbers) == 1:
                # 单个SN使用模糊匹配
                query = query.filter(Asset.serial_number.like(f"%{serial_numbers[0]}%"))
            else:
                # 多个SN使用精确匹配
                query = query.filter(Asset.serial_number.in_(serial_numbers))
            
            # 添加其他过滤条件
            if asset_tag:
                query = query.filter(Asset.asset_tag.like(f"%{asset_tag}%"))
            if name:
                query = query.filter(Asset.name.like(f"%{name}%"))
            if asset_status:
                query = query.filter(Asset.asset_status == asset_status)
            if lifecycle_status:
                query = query.filter(Asset.lifecycle_status == lifecycle_status)
            if device_direction:
                query = query.filter(Asset.device_direction == device_direction)
            if room_id:
                query = query.filter(Asset.room_id == room_id)
            if is_available is not None:
                query = query.filter(Asset.is_available == is_available)
            if model:
                query = query.filter(Asset.model.like(f"%{model}%"))
            if created_from:
                query = query.filter(Asset.created_at >= created_from)
            if created_to:
                query = query.filter(Asset.created_at <= created_to)
            
            # 添加机房过滤
            if effective_datacenter:
                query = query.join(Room, Asset.room_id == Room.id).filter(Room.datacenter_abbreviation == effective_datacenter)
            
            # 获取结果
            total = query.count()
            # 按创建时间倒序排列
            query = query.order_by(Asset.created_at.desc())
            assets = query.offset((page - 1) * size).limit(size).all()
        else:
            # 使用服务层搜索
            assets, total = service.search_assets(search_params, pagination_params, datacenter=effective_datacenter)
        
        response_items = [
            _build_asset_response(asset).model_dump()
            for asset in assets
        ]
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="查询成功",
            data={
                "total": total,
                "page": page,
                "size": size,
                "items": response_items
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询资产失败: {str(e)}")


@router.get(
    "/{asset_id}",
    response_model=ApiResponse,
    summary="查询资产详情",
    responses={
        200: {"description": "查询成功"},
        404: {"description": "资产不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_asset_detail(
    asset_id: int = Path(..., description="资产ID", example=1),
    service: AssetService = Depends(get_asset_service)
):
    """
    查询资产详情
    
    功能说明：
    - 根据资产ID查询资产的完整详细信息
    - 包含资产基本信息、位置信息、生命周期阶段信息、最新工单信息
    
    路径参数说明：
    - asset_id: 资产ID（必填，整数）
    
    返回字段说明：
    - code: 响应码（0表示成功，404表示未找到）
    - message: 响应消息
    - data: 资产详情对象
      - 基本信息：
        - id: 资产ID
        - asset_tag: 资产标签
        - name: 资产名称
        - serial_number: 序列号
        - room_id: 房间ID
        - room_name: 房间全称
        - room_abbreviation: 房间简称
        - room_number: 房间编号
        - datacenter_abbreviation: 机房缩写
        - building_number: 楼栋号
        - floor_number: 楼层号
        - quantity: 数量
        - is_available: 是否可用
        - unavailable_reason: 不可用原因
        - vendor_name: 厂商名称
        - model_name: 型号
        - vendor_standard_model: 厂商标准机型
        - location_detail: 位置详情
        - asset_status: 资产管理状态
        - lifecycle_status: 生命周期状态
        - device_direction: 设备去向
        - notes: 备注
        - created_by: 创建人/责任人
        - created_at: 创建时间（ISO格式）
        - updated_at: 更新时间（ISO格式）
        - category: 一级分类
        - secondary_category: 二级分类
        - tertiary_category: 三级分类
      - category_name: 分类名称
      - location_info: 位置信息对象
        - room: 房间信息
        - building: 楼栋信息
        - floor: 楼层信息
        - datacenter: 机房信息
      - lifecycle_stages: 生命周期阶段列表
        - id: 阶段记录ID
        - asset_id: 资产ID
        - stage_id: 阶段ID
        - status: 阶段状态（not_started/in_progress/completed/skipped/failed）
        - start_date: 开始日期
        - end_date: 结束日期
        - responsible_person: 负责人
        - notes: 备注
        - created_at: 创建时间（ISO格式）
        - updated_at: 更新时间（ISO格式）
      - latest_work_order: 最新工单信息
        - work_order_id: 工单ID
        - work_order_number: 工单号
        - operation_type: 操作类型
        - status: 工单状态
        - created_at: 创建时间
    
    使用场景：
    - 查看资产完整详情
    - 查看资产生命周期状态
    - 查看资产位置信息
    - 查看资产最新工单
    - 资产详情页展示
    
    注意事项：
    - 资产ID必须存在，否则返回404
    - 返回的生命周期阶段按阶段顺序排列
    - location_info包含完整的位置层级信息
    """
    detail = service.get_asset_detail(asset_id)
    if not detail:
        raise HTTPException(status_code=404, detail="资产不存在")

    asset = detail["asset"]
    asset_payload = _build_asset_response(asset).model_dump()

    category_name = None
    if hasattr(asset, "category_item") and asset.category_item:
        category_name = asset.category_item.item_label
    elif hasattr(asset, "category") and asset.category:
        category_name = asset.category.name

    lifecycle_stages = [
        {
            "id": stage.id,
            "asset_id": stage.asset_id,
            "stage_id": stage.stage_id,
            "status": stage.status,
            "start_date": stage.start_date,
            "end_date": stage.end_date,
            "responsible_person": stage.responsible_person,
            "notes": stage.notes,
            "created_at": stage.created_at,
            "updated_at": stage.updated_at,
        }
        for stage in detail["lifecycle_stages"]
    ]

    response_data = {
        **asset_payload,
        "category_name": category_name,
        "location_info": detail.get("location_info"),
        "lifecycle_stages": lifecycle_stages,
        "latest_work_order": detail.get("latest_work_order"),
    }

    detail_response = AssetDetailResponse(**response_data)

    return ApiResponse(
        code=ResponseCode.SUCCESS,
        message="查询成功",
        data=detail_response.model_dump()
    )
