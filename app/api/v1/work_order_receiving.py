"""
设备到货工单管理API
基于WorkOrder统一工单系统
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body, Query, Path
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import pandas as pd
from datetime import datetime

from app.db.session import get_db
from app.models.asset_models import Asset, Room, WorkOrder, WorkOrderItem
from app.schemas.asset_schemas import ApiResponse, ResponseCode
from app.core.logging_config import get_logger
from app.core.config import settings
from app.services.work_order_service import create_work_order as create_external_work_order
from app.constants.operation_types import OperationResult

router = APIRouter()
logger = get_logger(__name__)

# =====================================================
# 模板下载
# =====================================================

@router.get(
    "/import/template",
    summary="下载设备到货导入模板",
    responses={
        200: {"description": "模板文件下载成功"},
        404: {"description": "模板文件不存在"}
    }
)
async def download_receiving_import_template():
    """
    下载设备到货导入模板
    
    功能说明：
    - 提供固定的Excel模板文件（import_device.xlsx）
    - 用于批量导入设备到货信息
    
    返回说明：
    - 返回Excel文件流
    - 文件名：设备到货导入模板.xlsx
    - Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    
    模板包含列：
    - *到货单号: 批次号（必填）
    - *SN: 设备序列号（必填，必须已存在于系统）
    - *房间: 目标房间简称（必填）
    - id: 用户自定义ID（可选）
    - 来源业务: 来源业务描述（可选）
    - 一级分类: 设备一级分类名称（可选）
    - 二级分类: 设备二级分类名称（可选）
    - 三级分类: 设备三级分类名称（可选）
    - 厂商标准机型: 厂商标准机型（可选）
    - *设备类型: 设备类型描述（可选）
    - 机房: 机房名称（可选）
    - 型号: 设备型号（可选）
    - MPN: MPN编号（可选）
    
    使用场景：
    - 批量导入设备到货前下载模板
    - 了解导入格式要求
    
    注意事项：
    - 模板文件必须存在于项目根目录
    - 带*号的列为必填列
    """
    template_path = settings.BASE_DIR / "import_device.xlsx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="设备到货导入模板不存在")
    return FileResponse(
        template_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="设备到货导入模板.xlsx"
    )

# =====================================================
# 工单回调通知
# =====================================================

SUPPORTED_WORK_ORDER_BUSINESS_TYPES = {
    "receiving",          # 设备到货
    "racking",           # 设备上架
    "configuration",     # 设备增配
    "power_on",          # 电源开启
    "power_off",         # 电源关闭
    "asset_accounting"   # 资产出入门
}

class WorkOrderNotificationRequest(BaseModel):
    """工单系统通知请求模型"""
    notification_type: str = Field(..., description="通知类型：approve-审核通过, reject-审核拒绝, complete-验收完成, update-更新信息")
    business_type: Optional[str] = Field(None, description="业务类型标识（可选，用于验证，如receiving、racking、configuration等）")
    business_id: str = Field(..., description="业务主键（批次ID）- 通过此字段定位工单")
    work_order_number: Optional[str] = Field(None, description="工单号（可选，用于更新工单号）")
    status: str = Field(..., description="状态（如：approved, rejected, completed）")
    close_time: Optional[datetime] = Field(None, description="结单时间（可选）")
    inspector: str = Field(..., description="验收人（必填）")
    extra_data: Optional[Dict[str, Any]] = Field(None, description="额外数据（JSON格式，便于扩展）")
    remark: str = Field(..., description="备注信息（必填）")

@router.post(
    "/work-order/notify",
    summary="工单系统回调通知接口",
    response_model=ApiResponse,
    responses={
        200: {"description": "通知处理成功"},
        400: {"description": "参数错误"},
        404: {"description": "工单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def work_order_notification(
    request: WorkOrderNotificationRequest = Body(
        ...,
        examples=[
            {
                "notification_type": "approve",
                "business_id": "RECV20251205120000",
                "work_order_number": "WO202512050001",
                "status": "approved",
                "inspector": "张三",
                "remark": "审核通过，可以开始处理"
            },
            {
                "notification_type": "complete",
                "business_id": "RACK20251205120000",
                "work_order_number": "WO202512050002",
                "status": "completed",
                "close_time": "2025-12-05T18:00:00",
                "inspector": "李四",
                "remark": "验收完成，设备已上架",
                "extra_data": {
                    "completion_rate": "100%",
                    "quality_score": 95
                }
            },
            {
                "notification_type": "complete",
                "business_id": "AEE_20251205120000",
                "business_type": "asset_accounting",
                "status": "completed",
                "inspector": "王五",
                "remark": "资产出入门完成，设备已搬入",
                "extra_data": {
                    "entry_exit_type": "move_in"
                }
            }
        ]
    ),
    db: Session = Depends(get_db)
):
    """
    接收工单系统的回调通知（统一回调接口）
    
    功能说明：
    - 接收外部工单系统的状态变更通知
    - 更新内部工单状态和信息
    - 支持多种通知类型和工单类型
    - 自动处理特定工单类型的业务逻辑
    
    支持的通知类型：
    - approve: 审核通过
    - reject: 审核拒绝  
    - complete: 验收完成
    - update: 更新信息（工单号、状态等）
    
    支持的工单类型（business_type）：
    - receiving: 设备到货工单
    - racking: 设备上架工单
    - configuration: 设备增配工单
    - power_on: 电源开启工单
    - power_off: 电源关闭工单
    - asset_accounting: 资产出入门工单（完成时自动更新资产状态）
    
    请求参数说明：
    - notification_type: 通知类型（必填）
    - business_id: 业务主键/批次ID（必填）- **核心定位字段，通过此字段查询工单并获取业务类型**
    - business_type: 业务类型标识（可选，用于验证，如receiving、racking、asset_accounting等）
    - work_order_number: 工单号（可选，用于更新工单号）
    - status: 状态（必填，如approved、rejected、completed）
    - close_time: 结单时间（可选，ISO格式）
    - inspector: 验收人（必填）
    - extra_data: 额外数据（可选，JSON格式）
    - remark: 备注信息（必填）
    
    业务类型识别机制：
    1. 通过 business_id 查询工单
    2. 从工单的 operation_type 字段获取真实的业务类型
    3. 如果请求中提供了 business_type，会验证是否匹配（仅记录警告，不阻止处理）
    4. 根据工单的 operation_type 执行对应的业务逻辑
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 更新结果
      - batch_id: 批次ID
      - work_order_number: 工单号
      - status: 内部状态
      - work_order_status: 工单状态
      - updated_at: 更新时间（ISO格式）
      - updated_assets_count: 更新的资产数量（仅asset_accounting工单完成时返回）
    
    状态映射关系：
    传入状态 → 内部状态(status) / 外部工单状态(work_order_status)
    - approved → processing / processing（审核通过，进行中）
    - complete/completed → completed / completed（已完成）
    - rejected/reject → cancelled / failed（拒绝/失败）
    - failed → failed / failed（失败）
    
    注：外部工单状态(work_order_status)只有3个值：processing、completed、failed
    
    资产出入门工单特殊处理：
    当 business_type=asset_accounting 且 status=completed 时，会自动：
    1. 更新资产的 device_direction（设备去向）
       - move_in（搬入）→ inbound（入库）
       - move_out（搬出）→ outbound（出库）
    2. 更新资产的 room_id（位置）
    3. 更新资产的 lifecycle_status（生命周期状态）
       - move_in → received（已到货）
       - move_out → shipped（已发货）
    4. 更新工单明细状态为 completed
    
    使用场景：
    - 外部工单系统审核通过后通知
    - 外部工单系统验收完成后通知
    - 外部工单系统拒绝后通知
    - 更新工单号和状态
    - 资产出入门工单完成后自动更新资产状态
    
    注意事项：
    - business_id必须存在
    - 通知会追加到工单描述中
    - extra_data会保存到工单的extra字段
    - 资产出入门工单完成时会自动更新相关资产状态
    - 此接口替代了原有的 /api/v1/asset-entry-exit-work-order/callback 接口
    """
    try:
        business_id = request.business_id.strip()
        
        if not business_id:
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message="缺少业务标识：business_id 必填",
                data=None
            )
        
        # 1. 通过 business_id 查询工单（唯一真实来源）
        work_order = db.query(WorkOrder).filter(
            WorkOrder.batch_id == business_id
        ).first()
        
        if not work_order:
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message=f"未找到批次ID为 {business_id} 的工单",
                data=None
            )
        
        # 2. 从工单中获取真实的业务类型
        actual_business_type = work_order.operation_type
        
        # 3. 如果请求中提供了 business_type，验证是否匹配（可选验证）
        if request.business_type:
            request_business_type = request.business_type.strip().lower()
            if request_business_type != actual_business_type:
                logger.warning(
                    f"工单类型不匹配: 请求的 business_type={request_business_type}, "
                    f"工单实际 operation_type={actual_business_type}, batch_id={business_id}"
                )
                # 这里只记录警告，不阻止处理，因为以数据库中的为准
        
        # 4. 验证工单类型是否在支持列表中
        if actual_business_type not in SUPPORTED_WORK_ORDER_BUSINESS_TYPES:
            logger.error(f"不支持的工单类型: {actual_business_type}, batch_id={business_id}")
            return ApiResponse(
                code=ResponseCode.PARAM_ERROR,
                message=f"不支持的工单类型: {actual_business_type}",
                data=None
            )
        
        logger.info(f"处理工单回调: batch_id={business_id}, operation_type={actual_business_type}, status={request.status}")
        
        # 更新工单字段
        if request.work_order_number:
            work_order.work_order_number = request.work_order_number
        
        work_order.operator = request.inspector
        work_order.reviewer = request.inspector
        
        if request.close_time:
            work_order.close_time = request.close_time
        
        # 状态映射：外部传入状态 → 内部状态(status) + 外部工单状态(work_order_status)
        # 外部工单状态只有3个：processing（进行中）、completed（已完成）、failed（失败）
        internal_status_mapping = {
            'approved': 'processing',      # 审核通过 → 内部状态：处理中
            'complete': 'completed',       # 完成 → 内部状态：已完成
            'completed': 'completed',      # 完成 → 内部状态：已完成
            'rejected': 'cancelled',       # 拒绝 → 内部状态：已取消
            'reject': 'cancelled',         # 拒绝 → 内部状态：已取消
            'failed': 'failed',            # 失败 → 内部状态：失败
        }
        
        work_order_status_mapping = {
            'approved': 'processing',      # 审核通过 → 外部工单状态：进行中
            'complete': 'completed',       # 完成 → 外部工单状态：已完成
            'completed': 'completed',      # 完成 → 外部工单状态：已完成
            'rejected': 'failed',          # 拒绝 → 外部工单状态：失败
            'reject': 'failed',            # 拒绝 → 外部工单状态：失败
            'failed': 'failed',            # 失败 → 外部工单状态：失败
        }
        
        request_status = request.status.lower()
        
        # 更新内部状态
        if request_status in internal_status_mapping:
            work_order.status = internal_status_mapping[request_status]
        
        # 更新外部工单状态（只能是 processing/completed/failed）
        if request_status in work_order_status_mapping:
            work_order.work_order_status = work_order_status_mapping[request_status]
        else:
            # 如果传入的状态不在映射中，默认保持 processing
            work_order.work_order_status = 'processing'
        
        # 更新备注
        if request.remark:
            current_remark = work_order.description or ""
            work_order.description = f"{current_remark}\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {request.remark}"
        
        # 保存extra_data
        if request.extra_data:
            if not work_order.extra:
                work_order.extra = {}
            work_order.extra['callback_data'] = request.extra_data
            work_order.extra['last_callback_time'] = datetime.now().isoformat()
        
        # 如果是资产出入门工单（asset_accounting）且状态为完成，更新资产状态
        # 添加调试日志
        logger.info(f"[调试] 检查是否需要更新资产状态: operation_type={work_order.operation_type}, request_status={request_status}, mapped_status={work_order_status_mapping.get(request_status)}")
        
        if (work_order.operation_type == "asset_accounting" and 
            request_status in ['complete', 'completed'] and 
            work_order_status_mapping.get(request_status) == 'completed'):
            
            logger.info(f"[调试] 进入资产状态更新逻辑")
            
            # 从工单extra中获取出入类型
            extra = work_order.extra or {}
            entry_exit_type = extra.get("entry_exit_type")
            
            logger.info(f"[调试] entry_exit_type={entry_exit_type}, extra={extra}")
            
            # 根据出入类型确定资产的设备去向
            # move_in (搬入) -> inbound (入库)
            # move_out (搬出) -> outbound (出库)
            new_direction = "inbound" if entry_exit_type == "move_in" else "outbound"
            
            # 获取所有工单明细
            items = db.query(WorkOrderItem).filter(
                WorkOrderItem.work_order_id == work_order.id
            ).all()
            
            updated_count = 0
            logger.info(f"[调试] 找到 {len(items)} 条工单明细，开始更新资产状态")
            
            # 更新每个资产的状态
            for item in items:
                try:
                    logger.info(f"[调试] 处理明细: asset_id={item.asset_id}, asset_sn={item.asset_sn}")
                    asset = db.query(Asset).get(item.asset_id)
                    logger.info(f"[调试] 查询资产结果: asset={'存在' if asset else '不存在'}")
                    if asset:
                        old_direction = asset.device_direction
                        logger.info(f"[调试] 更新资产 {asset.serial_number}: 当前去向={old_direction}, 新去向={new_direction}")
                        
                        # 1. 更新设备去向（device_direction）
                        if entry_exit_type:
                            asset.device_direction = new_direction
                            logger.info(f"[调试] 已更新 device_direction: {old_direction} → {new_direction}")
                        
                        # 2. 更新资产位置（room_id）- 如果有目标房间
                        if item.operation_data:
                            target_room_id = item.operation_data.get('target_room_id')
                            if target_room_id:
                                asset.room_id = target_room_id
                        
                        # 3. 根据出入类型更新生命周期状态（lifecycle_status）
                        if entry_exit_type == 'move_in':
                            asset.lifecycle_status = 'received'  # 搬入：已到货
                        elif entry_exit_type == 'move_out':
                            asset.lifecycle_status = 'shipped'  # 搬出：已发货
                        
                        # 4. 更新工单明细状态
                        item.status = 'completed'
                        item.executed_at = datetime.now()
                        item.executed_by = request.inspector
                        
                        updated_count += 1
                        logger.info(f"[调试] updated_count 累加后: {updated_count}")
                        
                        # 记录资产状态变更日志
                        logger.info("资产出入门工单完成，更新资产状态", extra={
                            "operationObject": asset.serial_number,
                            "operationType": "asset.entry_exit_update",
                            "operator": request.inspector,
                            "result": OperationResult.SUCCESS,
                            "operationDetail": f"设备去向: {old_direction} → {new_direction}, 出入类型: {entry_exit_type}, 关联工单: {business_id}"
                        })
                except Exception as asset_error:
                    logger.error(f"更新资产失败: {str(asset_error)}, asset_id: {item.asset_id}")
                    # 不中断整个流程，继续处理其他资产
            
            # 记录更新数量到extra
            extra['updated_assets_count'] = updated_count
            extra['callback_time'] = datetime.now().isoformat()
            work_order.extra = extra
        
        db.commit()
        db.refresh(work_order)
        
        logger.info(f"工单回调成功: batch_id={business_id}, notification_type={request.notification_type}, status={request.status}")
        
        # 构建返回数据
        response_data = {
            "batch_id": work_order.batch_id,
            "work_order_number": work_order.work_order_number,
            "status": work_order.status,
            "work_order_status": work_order.work_order_status,
            "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None
        }
        
        # 如果是资产出入门工单且已完成，返回更新的资产数量
        if work_order.operation_type == "asset_accounting" and work_order.work_order_status == "completed":
            extra = work_order.extra or {}
            response_data["updated_assets_count"] = extra.get("updated_assets_count", 0)
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="工单状态更新成功",
            data=response_data
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"工单回调失败: {str(e)}")
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"工单状态更新失败: {str(e)}",
            data=None
        )


@router.post(
    "/import",
    summary="导入设备到货Excel",
    responses={
        200: {"description": "导入成功"},
        400: {"description": "参数错误或数据验证失败"},
        404: {"description": "设备或房间不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def import_receiving_excel(
    file: UploadFile = File(..., description="设备到货Excel文件（.xlsx格式）"),
    operator: str = Form(..., description="操作人姓名"),
    db: Session = Depends(get_db)
):
    """
    导入设备到货Excel，创建到货工单
    
    功能说明：
    - 批量导入设备到货信息
    - 自动创建到货工单和明细
    - 自动调用外部工单系统创建工单
    - 验证设备和房间是否存在
    - 支持部分失败，生成错误报告
    
    Excel必填列：
    - *到货单号: 批次号（供应商的到货单号）
    - *SN: 设备序列号（必须已存在于系统）
    - *房间: 目标房间简称（必须已存在于系统）
    
    Excel可选列：
    - id: 用户自定义ID（字符串，不验证）
    - 来源业务: 来源业务描述（字符串）
    - 一级分类: 设备一级分类名称
    - 二级分类: 设备二级分类名称
    - 三级分类: 设备三级分类名称
    - 厂商标准机型: 厂商标准机型（字符串）
    - *设备类型: 设备类型描述
    - 机房: 机房名称
    - 型号: 设备型号
    - MPN: MPN编号
    
    请求参数说明：
    - file: Excel文件（必填，.xlsx格式）
    - operator: 操作人（必填）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 导入结果
      - batch_id: 批次ID（系统生成，格式：RECV{YYYYMMDDHHmmss}）
      - arrival_order_number: 到货单号（来自Excel）
      - work_order_id: 工单ID
      - work_order_number: 外部工单号
      - items_count: 导入设备数量
      - status: 工单状态
      - work_order_status: 工单外部状态
      - external_work_order_created: 外部工单是否创建成功
      - items: 设备明细列表
        - serial_number: 序列号
        - asset_tag: 资产标签
        - from_room: 原房间
        - to_room: 目标房间
      - success_count: 成功数量
      - failure_count: 失败数量
      - error_report: 错误报告下载链接（如有失败记录）
    
    执行流程：
    1. 解析Excel文件
    2. 验证必填列是否存在
    3. 生成批次ID（RECV{YYYYMMDDHHmmss}）
    4. 验证所有SN是否存在于系统
    5. 验证所有房间是否存在于系统
    6. 创建WorkOrder记录
    7. 创建WorkOrderItem记录（每台设备一条）
    8. 调用外部工单系统创建工单
    9. 提交事务（外部工单创建成功后）
    10. 返回导入结果
    
    使用场景：
    - 批量导入设备到货信息
    - 创建设备到货工单
    - 设备入库管理
    
    注意事项：
    - Excel文件必须使用提供的模板格式
    - 所有SN必须已存在于系统中
    - 所有房间必须已存在于系统中
    - 批次ID不能重复
    - 如果外部工单创建失败，整个事务会回滚
    - 支持部分失败，失败记录会生成错误报告
    - 错误报告可通过error_report链接下载
    """
    
    try:
        # 1. 验证文件格式
        if not file.filename:
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": "文件格式不正确，导入失败！",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        
        # 检查文件扩展名
        allowed_extensions = ['.xlsx', '.xls']
        file_ext = file.filename.lower().split('.')[-1] if '.' in file.filename else ''
        if not file_ext or f'.{file_ext}' not in allowed_extensions:
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": "文件格式不正确，导入失败！",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        
        # 2. 解析Excel
        try:
            df = pd.read_excel(file.file, engine='openpyxl')
        except Exception as parse_error:
            logger.error(f"Excel文件解析失败: {str(parse_error)}")
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": "文件格式不正确，导入失败！",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        
        if df.empty:
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": "Excel文件为空",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        
        # 2. 验证必填列
        required_cols = ['*到货单号', '*SN', '*房间']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": f"缺少必填列: {', '.join(missing_cols)}",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        
        # 3. 生成统一的批次ID和获取到货单号
        # 生成批次ID（统一格式：RECV{YYYYMMDDHHmmss}）
        batch_id = f"RECV{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 获取到货单号（来自Excel，这是供应商的到货单号）
        arrival_order_number = str(df['*到货单号'].iloc[0]).strip()
        if not arrival_order_number:
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": "到货单号不能为空",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        
        # 检查批次ID是否已存在
        existing = db.query(WorkOrder).filter(
            WorkOrder.batch_id == batch_id
        ).first()
        if existing:
            return {
                "code": ResponseCode.ALREADY_EXISTS,
                "message": f"批次ID已存在: {batch_id}",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        
        # 4. 预加载所有SN对应的资产（不再直接报错，改为逐行验证）
        serial_numbers = df['*SN'].dropna().astype(str).str.strip().tolist()
        if not serial_numbers:
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": "Excel中没有有效的序列号",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        
        # 去重
        unique_serial_numbers = list(set(serial_numbers))
        
        assets = db.query(Asset).filter(
            Asset.serial_number.in_(unique_serial_numbers)
        ).all()
        
        sn_to_asset = {a.serial_number: a for a in assets}
        
        # 5. 预加载所有房间（不再直接报错，改为逐行验证）
        room_names = df['*房间'].dropna().astype(str).str.strip().unique().tolist()
        
        rooms = db.query(Room).filter(
            Room.room_abbreviation.in_(room_names)
        ).all() if room_names else []
        
        room_name_to_room = {r.room_abbreviation: r for r in rooms}
        
        # 6. 先验证所有行，收集成功和失败的记录
        validated_rows = []  # 验证通过的行
        error_rows = []  # 验证失败的行
        success_count = 0
        failure_count = 0
        seen_sns = set()  # 用于检测重复SN
        
        for idx, row in df.iterrows():
            sn = str(row['*SN']).strip() if pd.notna(row.get('*SN')) else ''
            room_name = str(row['*房间']).strip() if pd.notna(row.get('*房间')) else ''

            try:
                if not sn:
                    raise ValueError("SN为空")
                if not room_name:
                    raise ValueError("房间为空")
                if sn not in sn_to_asset:
                    raise ValueError(f"序列号不存在: {sn}")
                if room_name not in room_name_to_room:
                    raise ValueError(f"房间不存在: {room_name}")
                
                # 检查是否重复
                if sn in seen_sns:
                    raise ValueError(f"序列号重复: {sn}")
                seen_sns.add(sn)

                asset = sn_to_asset[sn]
                target_room = room_name_to_room[room_name]

                # 验证通过，保存验证结果
                validated_rows.append({
                    "idx": idx,
                    "row": row,
                    "sn": sn,
                    "asset": asset,
                    "target_room": target_room,
                    "room_name": room_name
                })
                success_count += 1
            except Exception as row_err:
                from copy import deepcopy
                failure_count += 1
                row_copy = deepcopy(row)
                row_copy["错误信息"] = str(row_err)
                row_copy["行号"] = idx + 2
                error_rows.append(row_copy)

        # 获取第一行的分类信息（假设同批次设备类型相同）
        first_row = df.iloc[0]
        
        # 优先使用Excel中的分类列，如果没有则从资产的category获取
        device_category_level1 = None
        device_category_level2 = None
        device_category_level3 = None
        
        if pd.notna(first_row.get('一级分类')):
            device_category_level1 = str(first_row.get('一级分类')).strip()
        elif pd.notna(first_row.get('*设备类型')):
            # 如果没有填一级分类，但有设备类型，使用设备类型作为一级分类
            device_category_level1 = str(first_row.get('*设备类型')).strip()
        else:
            # 最后从第一个资产的category获取
            first_asset = assets[0] if assets else None
            if first_asset and hasattr(first_asset, 'category') and first_asset.category:
                device_category_level1 = first_asset.category.name
        
        if pd.notna(first_row.get('二级分类')):
            device_category_level2 = str(first_row.get('二级分类')).strip()
        
        if pd.notna(first_row.get('三级分类')):
            device_category_level3 = str(first_row.get('三级分类')).strip()
        
        # 获取机房信息（假设同批次在同一机房）
        first_room = rooms[0] if rooms else None
        datacenter = first_room.datacenter_abbreviation if first_room and hasattr(first_room, 'datacenter_abbreviation') else None
        
        # 获取来源业务（从第一行）
        source_business = None
        if pd.notna(first_row.get('来源业务')):
            source_business = str(first_row.get('来源业务')).strip()
        
        # 如果所有行都失败，生成错误报告并返回（不创建工单）
        if success_count == 0 and failure_count > 0:
            error_report_url = None
            try:
                import os
                import pandas as _pd
                from datetime import datetime as _dt
                from urllib.parse import quote

                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                temp_dir = os.path.abspath(os.path.join(base_dir, "..", "temp"))
                os.makedirs(temp_dir, exist_ok=True)
                ts = _dt.now().strftime("%Y%m%d%H%M%S")
                error_report_path = os.path.join(temp_dir, f"设备到货导入失败记录_{ts}.xlsx")
                err_df = _pd.DataFrame(error_rows)
                err_df.to_excel(error_report_path, index=False)
                filename = os.path.basename(error_report_path)
                error_report_url = f"/api/v1/receiving/import/error-report/{quote(filename)}"
            except Exception:
                error_report_url = None
            
            message = f"导入成功{success_count}条，导入失败{failure_count}条"
            if error_report_url:
                message += "，请下载错误报告查看详情"
            
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": message,
                "data": {
                    "batch_id": None,
                    "arrival_order_number": arrival_order_number,
                    "work_order_id": None,
                    "work_order_number": None,
                    "items_count": 0,
                    "status": None,
                    "work_order_status": None,
                    "external_work_order_created": False,
                    "items": [],
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "error_report": error_report_url
                }
            }
        
        # 7. 创建WorkOrder（只有在有成功记录时才创建）
        work_order = WorkOrder(
            batch_id=batch_id,
            operation_type="receiving",
            title=f"设备到货-{arrival_order_number}",
            arrival_order_number=arrival_order_number,
            status="pending",
            creator=operator,
            description=f"通过Excel导入的设备到货单，共{len(df)}台设备",
            device_count=success_count,  # 使用成功数量
            device_category_level1=device_category_level1,
            device_category_level2=device_category_level2,
            device_category_level3=device_category_level3,
            datacenter=datacenter,
            source_order_number=source_business or arrival_order_number,
            extra={
                'import_method': 'excel',
                'file_name': file.filename,
                'total_rows': len(df)
            }
        )
        db.add(work_order)
        db.flush()
        
        # 8. 创建WorkOrderItem（只为验证通过的行创建）
        items_created = []
        for validated in validated_rows:
            idx = validated["idx"]
            row = validated["row"]
            sn = validated["sn"]
            asset = validated["asset"]
            target_room = validated["target_room"]
            room_name = validated["room_name"]

            # 构建operation_data，包含所有可选字段
            operation_data = {
                # 基础信息
                "serial_number": sn,
                "asset_tag": asset.asset_tag,
                "current_room_id": asset.room_id,
                "current_room_name": asset.room.room_abbreviation if asset.room else None,
                "target_room_id": target_room.id,
                "target_room_name": target_room.room_abbreviation,
                "target_room_full_name": target_room.room_full_name,
                "row_number": idx + 2,  # Excel行号（从2开始）

                # 原有可选列
                "device_type": str(row.get('*设备类型', '')) if pd.notna(row.get('*设备类型')) else '',
                "datacenter": str(row.get('机房', '')) if pd.notna(row.get('机房')) else '',
                "model": str(row.get('型号', '')) if pd.notna(row.get('型号')) else '',
                "mpn": str(row.get('MPN', '')) if pd.notna(row.get('MPN')) else '',

                # 新增可选列
                "custom_id": str(row.get('id', '')) if pd.notna(row.get('id')) else '',
                "source_business": str(row.get('来源业务', '')) if pd.notna(row.get('来源业务')) else '',
                "category_level1": str(row.get('一级分类', '')) if pd.notna(row.get('一级分类')) else '',
                "category_level2": str(row.get('二级分类', '')) if pd.notna(row.get('二级分类')) else '',
                "category_level3": str(row.get('三级分类', '')) if pd.notna(row.get('三级分类')) else '',
                "vendor_standard_model": str(row.get('厂商标准机型', '')) if pd.notna(row.get('厂商标准机型')) else ''
            }

            item = WorkOrderItem(
                work_order_id=work_order.id,
                asset_id=asset.id,
                asset_sn=sn,
                asset_tag=asset.asset_tag,
                operation_data=operation_data,
                status="pending",
                item_room=target_room.room_abbreviation,
                item_datacenter=str(row.get('机房', '')) if pd.notna(row.get('机房')) else datacenter
            )
            db.add(item)
            items_created.append({
                "serial_number": sn,
                "asset_tag": asset.asset_tag,
                "from_room": asset.room.room_abbreviation if asset.room else "无",
                "to_room": room_name
            })

        # 如果存在失败行，生成错误报告
        error_report_url = None
        if error_rows:
            try:
                import os
                import pandas as _pd
                from datetime import datetime as _dt
                from urllib.parse import quote

                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                temp_dir = os.path.abspath(os.path.join(base_dir, "..", "temp"))
                os.makedirs(temp_dir, exist_ok=True)
                ts = _dt.now().strftime("%Y%m%d%H%M%S")
                error_report_path = os.path.join(temp_dir, f"设备到货导入失败记录_{ts}.xlsx")
                err_df = _pd.DataFrame(error_rows)
                err_df.to_excel(error_report_path, index=False)
                filename = os.path.basename(error_report_path)
                error_report_url = f"/api/v1/receiving/import/error-report/{quote(filename)}"
            except Exception:
                error_report_url = None

        # 9. 先flush但不commit，等待外部工单创建成功后再提交
        db.flush()
        
        # 8. 调用外部工单系统创建工单
        external_work_order_result = await create_external_work_order(
            db=db,
            work_order_type="receiving",
            business_id=batch_id,
            title=f"设备到货-{arrival_order_number}",
            creator_name=operator,
            assignee=operator,  # 如果有指派人可以从Excel或参数传入
            description=f"设备到货工单，共{len(items_created)}台设备，分类：{device_category_level1 or '未分类'}"
        )
        
        # 9. 检查外部工单创建结果
        if not external_work_order_result or not external_work_order_result.get("success"):
            # 外部工单创建失败，回滚整个事务
            db.rollback()
            error_msg = external_work_order_result.get('error') if external_work_order_result else '外部工单系统无响应'
            logger.error(f"外部工单创建失败，回滚事务: {error_msg}")
            return {
                "code": ResponseCode.EXTERNAL_API_ERROR,
                "message": f"工单创建失败: {error_msg}",
                "data": {"success_count": success_count, "failure_count": failure_count, "error_report": error_report_url}
            }
        
        # 10. 外部工单创建成功，提交事务
        db.commit()
        db.refresh(work_order)
        logger.info(f"外部工单创建成功: {external_work_order_result.get('work_order_number')}")
        
        # 11. 记录日志
        logger.info(f"Receiving work order created", extra={
            "operationObject": batch_id,
            "operationType": "work_order.create",
            "operator": operator,
            "result": "success",
            "operationDetail": f"创建设备到货工单，共{len(items_created)}台设备"
        })
        
        # 构建返回消息
        message = f"导入成功{success_count}条，导入失败{failure_count}条"
        if failure_count > 0 and error_report_url:
            message += "，请下载错误报告查看失败详情"
        
        return {
            "code": 0,
            "message": message,
            "data": {
                "batch_id": batch_id,
                "arrival_order_number": arrival_order_number,
                "work_order_id": work_order.id,
                "work_order_number": work_order.work_order_number,  # 返回外部工单号
                "items_count": len(items_created),
                "status": work_order.status,
                "work_order_status": work_order.work_order_status,
                "external_work_order_created": True,  # 能到这里说明外部工单创建成功
                "items": items_created,
                "success_count": success_count,
                "failure_count": failure_count,
                "error_report": error_report_url
            }
        }
        
    except Exception as e:
        logger.error(f"Import receiving excel failed: {str(e)}")
        # 如果是文件格式相关的错误，返回明确的提示
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ['excel', 'openpyxl', 'xlrd', 'format', 'corrupt', 'invalid']):
            return {
                "code": ResponseCode.PARAM_ERROR,
                "message": "文件格式不正确，导入失败！",
                "data": {"success_count": 0, "failure_count": 0, "error_report": None}
            }
        return {
            "code": ResponseCode.INTERNAL_ERROR,
            "message": f"导入失败: {str(e)}",
            "data": {"success_count": 0, "failure_count": 0, "error_report": None}
        }


@router.get(
    "/import/error-report/{filename}",
    summary="下载设备到货导入失败报告",
    responses={
        200: {"description": "文件下载成功"},
        404: {"description": "文件不存在"}
    }
)
async def download_receiving_error_report(
    filename: str = Path(..., description="错误报告文件名")
):
    """
    下载设备到货导入失败报告
    
    功能说明：
    - 下载导入失败的Excel错误报告
    - 包含失败原因和行号信息
    
    路径参数说明：
    - filename: 错误报告文件名（从导入接口返回的error_report链接中获取）
    
    返回说明：
    - 返回Excel文件流
    - Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    - 文件包含原始数据和错误信息列
    
    使用场景：
    - 导入失败后下载错误报告
    - 查看失败原因
    - 修正数据后重新导入
    
    注意事项：
    - 文件存储在temp目录
    - 文件名格式：设备到货导入失败记录_{timestamp}.xlsx
    """
    import os
    from fastapi.responses import FileResponse
    from urllib.parse import quote

    # 路径与生成错误报告时保持一致
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    temp_dir = os.path.abspath(os.path.join(base_dir, "..", "temp"))

    safe_name = os.path.basename(filename)
    file_path = os.path.join(temp_dir, safe_name)
    if not os.path.exists(file_path):
        return {"code": ResponseCode.NOT_FOUND, "message": "文件不存在", "data": None}

    # 使用 FileResponse 的 filename 参数自动处理中文文件名
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=safe_name,
    )


@router.get(
    "/detail/{batch_id}",
    summary="查询到货工单详情",
    responses={
        200: {
            "description": "查询成功",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "查询成功",
                        "data": {
                            "batch_id": "RECV20251205120000",
                            "title": "设备到货-DH20251205001",
                            "description": "通过Excel导入的设备到货单，共5台设备",
                            "operation_type": "receiving",
                            "status": "completed",
                            "work_order_status": "completed",
                            "device_destination": "入库",
                            "work_order_number": "WO202512050001",
                            "arrival_order_number": "DH20251205001",
                            "source_order_number": "来源业务001",
                            "source_business": "Asset",
                            "creator": "张三",
                            "operator": "李四",
                            "assignee": "李四",
                            "reviewer": "王五",
                            "datacenter": "北京数据中心",
                            "room": "TEST-ROOM-01",
                            "device_category_level1": "服务器",
                            "device_category_level2": "机架式服务器",
                            "device_category_level3": None,
                            "device_count": 5,
                            "items_count": 5,
                            "completed_count": 5,
                            "pending_count": 0,
                            "failed_count": 0,
                            "created_at": "2025-12-05T12:00:00",
                            "start_time": "2025-12-05T12:30:00",
                            "completed_time": "2025-12-05T14:00:00",
                            "close_time": None,
                            "updated_at": "2025-12-05T14:00:00",
                            "extra": {"import_method": "excel", "file_name": "设备到货.xlsx"},
                            "remark": None,
                            "failure_reason": None,
                            "items": [
                                {
                                    "id": 1,
                                    "asset_id": 100,
                                    "serial_number": "SN123456",
                                    "category_level1": "服务器",
                                    "category_level2": "机架式服务器",
                                    "category_level3": None,
                                    "datacenter": "北京数据中心",
                                    "room": "TEST-ROOM-01",
                                    "model": "R740",
                                    "mpn": "MPN001",
                                    "vendor_standard_model": "Dell PowerEdge R740",
                                    "device_direction": "inbound",
                                    "process_status": "completed",
                                    "status": "completed",
                                    "result": "入库成功",
                                    "error_message": None,
                                    "asset_tag": "AT001",
                                    "asset_name": "Dell服务器R740",
                                    "current_room": "仓库",
                                    "target_room": "TEST-ROOM-01",
                                    "target_room_id": 10,
                                    "device_type": "服务器",
                                    "custom_id": "USER001",
                                    "source_business": "项目A",
                                    "executed_at": "2025-12-05T14:00:00",
                                    "executed_by": "李四"
                                }
                            ]
                        }
                    }
                }
            }
        },
        404: {"description": "到货单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_receiving_detail(
    batch_id: str = Path(..., description="批次ID", example="RECV20251205120000"),
    db: Session = Depends(get_db)
):
    """
    获取到货工单详细信息
    
    功能说明：
    - 查询到货工单的完整详细信息
    - 包含工单基本信息、外部工单信息、设备分类和统计信息
    - 包含所有设备明细列表
    
    路径参数说明：
    - batch_id: 批次ID（必填，格式：RECV{YYYYMMDDHHmmss}）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 工单详情对象
      - batch_id: 批次ID
      - title: 工单标题
      - description: 工单描述
      - operation_type: 操作类型（receiving）
      - status: 工单内部状态（pending/processing/completed/cancelled）
      - work_order_status: 工单外部状态
      - device_destination: 设备去向（工单完成时为"入库"，否则为空）
      - work_order_number: 外部工单号
      - arrival_order_number: 到货单号（供应商）
      - source_order_number: 来源单号
      - source_business: 来源业务（设备到货工单固定为"Asset"）
      - creator: 创建人
      - operator: 操作人
      - assignee: 指派人
      - reviewer: 审核人
      - datacenter: 机房
      - room: 房间
      - device_category_level1: 设备一级分类
      - device_category_level2: 设备二级分类
      - device_category_level3: 设备三级分类
      - device_count: 设备总数
      - items_count: 明细条数
      - completed_count: 已完成数量
      - pending_count: 待处理数量
      - failed_count: 失败数量
      - created_at: 创建时间（ISO格式）
      - start_time: 开始时间（ISO格式）
      - completed_time: 完成时间（ISO格式）
      - close_time: 关闭时间（ISO格式）
      - updated_at: 更新时间（ISO格式）
      - extra: 扩展信息（JSON）
      - remark: 备注
      - failure_reason: 失败原因（如有）
      - items: 设备明细列表（从资产表实时获取最新信息）
        - id: 明细ID
        - asset_id: 资产ID
        - serial_number: 序列号（SN）
        - category_level1: 一级分类（从资产获取）
        - category_level2: 二级分类（从资产获取）
        - category_level3: 三级分类（从资产获取）
        - datacenter: 机房（从资产房间获取）
        - room: 房间（从资产房间获取）
        - model: 型号（从资产获取）
        - mpn: MPN编号
        - vendor_standard_model: 厂商标准机型（从资产获取）
        - device_direction: 设备去向（从资产获取：inbound-入库/outbound-出库）
        - process_status: 处理状态（外部工单状态）
        - status: 明细状态（pending/completed/failed）
        - result: 执行结果
        - error_message: 错误信息
        - asset_tag: 资产标签
        - asset_name: 资产名称
        - current_room: 当前房间
        - target_room: 目标房间
        - target_room_id: 目标房间ID
        - device_type: 设备类型
        - custom_id: 自定义ID
        - source_business: 来源业务
        - executed_at: 执行时间（ISO格式）
        - executed_by: 执行人
    
    使用场景：
    - 查看到货工单详情
    - 查看设备明细列表
    - 查看执行进度和状态
    - 导出到货单信息
    
    注意事项：
    - batch_id必须存在且operation_type为receiving
    - 统计信息根据items的status自动计算
    """
    
    work_order = db.query(WorkOrder).filter(
        WorkOrder.batch_id == batch_id,
        WorkOrder.operation_type == "receiving"
    ).first()
    
    if not work_order:
        raise HTTPException(404, f"到货单不存在: {batch_id}")
    
    # 获取所有明细
    items = db.query(WorkOrderItem).filter(
        WorkOrderItem.work_order_id == work_order.id
    ).all()
    
    items_data = []
    completed_count = 0
    pending_count = 0
    failed_count = 0
    
    for item in items:
        asset = item.asset
        
        # 统计状态
        if item.status == "completed":
            completed_count += 1
        elif item.status == "failed":
            failed_count += 1
        else:
            pending_count += 1
        
        # 获取分类名称（从字典项关联获取）
        category_level1 = None
        category_level2 = None
        category_level3 = None
        if asset:
            if asset.category_item:
                category_level1 = asset.category_item.item_label
            if asset.secondary_category_item:
                category_level2 = asset.secondary_category_item.item_label
            if asset.tertiary_category_item:
                category_level3 = asset.tertiary_category_item.item_label
        
        # 获取房间和机房信息
        room_name = None
        datacenter = None
        if asset and asset.room:
            room_name = asset.room.room_abbreviation or asset.room.room_full_name
            datacenter = asset.room.datacenter_abbreviation
        
        items_data.append({
            # 核心标识
            "id": item.id,
            "asset_id": item.asset_id,
            "serial_number": item.asset_sn or (asset.serial_number if asset else None),
            
            # 分类信息（从资产获取）
            "category_level1": category_level1 or item.operation_data.get('category_level1'),
            "category_level2": category_level2 or item.operation_data.get('category_level2'),
            "category_level3": category_level3 or item.operation_data.get('category_level3'),
            
            # 位置信息（从资产获取）
            "datacenter": datacenter or item.item_datacenter,
            "room": room_name or item.operation_data.get('target_room_name'),
            
            # 型号信息（从资产获取）
            "model": asset.model if asset else item.operation_data.get('model'),
            "mpn": item.operation_data.get('mpn'),
            "vendor_standard_model": asset.vendor_standard_model if asset else item.operation_data.get('vendor_standard_model'),
            
            # 设备去向（从资产获取）
            "device_direction": asset.device_direction if asset else None,
            
            # 处理状态（外部工单状态）
            "process_status": work_order.work_order_status,
            
            # 明细状态
            "status": item.status,
            "result": item.result,
            "error_message": item.error_message,
            
            # 其他信息
            "asset_tag": item.asset_tag or (asset.asset_tag if asset else None),
            "asset_name": asset.name if asset else None,
            "current_room": item.operation_data.get('current_room_name'),
            "target_room": item.operation_data.get('target_room_name'),
            "target_room_id": item.operation_data.get('target_room_id'),
            "device_type": item.operation_data.get('device_type'),
            "custom_id": item.operation_data.get('custom_id'),
            "source_business": item.operation_data.get('source_business'),
            
            # 执行信息
            "executed_at": item.executed_at.isoformat() if item.executed_at else None,
            "executed_by": item.executed_by
        })
    
    return {
        "code": 0,
        "message": "查询成功",
        "data": {
            # 基本信息
            "batch_id": work_order.batch_id,
            "title": work_order.title,
            "description": work_order.description,
            "operation_type": work_order.operation_type,
            
            # 状态信息
            "status": work_order.status,
            "work_order_status": work_order.work_order_status,
            
            # 设备去向：工单完成时为"入库"，否则为空
            "device_destination": "入库" if work_order.work_order_status == "completed" else None,
            
            # 外部工单信息
            "work_order_number": work_order.work_order_number,
            "arrival_order_number": work_order.arrival_order_number,
            "source_order_number": work_order.source_order_number,
            "source_business": "Asset",  # 来源业务（设备到货工单固定为"Asset"）
            
            # 人员信息
            "creator": work_order.creator,
            "operator": work_order.operator,
            "assignee": work_order.assignee,
            "reviewer": work_order.reviewer,
            
            # 位置和分类信息
            "datacenter": work_order.datacenter,
            "room": work_order.room,
            "device_category_level1": work_order.device_category_level1,
            "device_category_level2": work_order.device_category_level2,
            "device_category_level3": work_order.device_category_level3,
            
            # 统计信息
            "device_count": work_order.device_count,
            "items_count": len(items_data),
            "completed_count": completed_count,
            "pending_count": pending_count,
            "failed_count": failed_count,
            
            # 时间信息
            "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
            "start_time": work_order.start_time.isoformat() if work_order.start_time else None,
            "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
            "close_time": work_order.close_time.isoformat() if work_order.close_time else None,
            "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None,
            
            # 扩展信息
            "extra": work_order.extra,
            "remark": work_order.remark,
            "failure_reason": work_order.extra.get("failure_reason") if work_order.extra else None,
            
            # 明细列表
            "items": items_data
        }
    }


@router.put(
    "/{batch_id}/complete",
    summary="完成到货工单",
    responses={
        200: {"description": "完成成功"},
        400: {"description": "参数错误或工单状态不允许"},
        404: {"description": "到货单不存在"},
        500: {"description": "服务器内部错误"}
    }
)
async def complete_receiving(
    batch_id: str = Path(..., description="批次ID", example="RECV20251205120000"),
    operator: str = Form(..., description="操作人姓名"),
    comments: str = Form(None, description="备注信息（可选）"),
    db: Session = Depends(get_db)
):
    """
    完成设备到货工单
    
    功能说明：
    - 批量更新所有设备的位置和状态
    - 更新工单状态为已完成
    - 记录操作日志到ES
    
    执行操作：
    1. 更新所有设备的room_id为目标房间
    2. 更新设备lifecycle_status为"received"（已到货）
    3. 更新WorkOrderItem状态为"completed"
    4. 更新工单状态为"completed"
    5. 记录ES日志
    
    路径参数说明：
    - batch_id: 批次ID（必填）
    
    表单参数说明：
    - operator: 操作人（必填）
    - comments: 备注信息（可选）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 执行结果
      - batch_id: 批次ID
      - updated_count: 成功更新数量
      - failed_count: 失败数量
      - failed_items: 失败明细列表（如有）
        - serial_number: 序列号
        - reason: 失败原因
    
    使用场景：
    - 设备到货验收完成后执行
    - 批量更新设备位置
    - 完成到货流程
    
    注意事项：
    - 工单必须存在且operation_type为receiving
    - 工单状态必须不是completed，否则返回400
    - 工单必须有设备明细
    - 每个设备必须有target_room_id
    - 失败的设备不会阻止其他设备更新
    - 所有操作会记录到ES日志
    """
    
    # 1. 获取工单
    work_order = db.query(WorkOrder).filter(
        WorkOrder.batch_id == batch_id,
        WorkOrder.operation_type == "receiving"
    ).first()
    
    if not work_order:
        raise HTTPException(404, f"到货单不存在: {batch_id}")
    
    if work_order.status == "completed":
        raise HTTPException(400, "到货单已完成，不能重复操作")
    
    # 2. 获取所有WorkOrderItem
    items = db.query(WorkOrderItem).filter(
        WorkOrderItem.work_order_id == work_order.id
    ).all()
    
    if not items:
        raise HTTPException(400, "到货单没有设备明细")
    
    # 3. 批量更新Asset
    updated_count = 0
    failed_items = []
    current_time = datetime.now()
    
    for item in items:
        try:
            asset = db.query(Asset).get(item.asset_id)
            if not asset:
                failed_items.append({
                    "serial_number": item.asset_sn or item.operation_data.get('serial_number'),
                    "reason": "资产不存在"
                })
                item.status = "failed"
                item.error_message = "资产不存在"
                continue
            
            target_room_id = item.operation_data.get('target_room_id')
            if not target_room_id:
                failed_items.append({
                    "serial_number": item.asset_sn,
                    "reason": "缺少目标房间ID"
                })
                item.status = "failed"
                item.error_message = "缺少目标房间ID"
                continue
            
            # 更新位置和状态
            old_room_id = asset.room_id
            old_room_name = asset.room.room_abbreviation if asset.room else "未知"
            
            asset.room_id = target_room_id
            asset.lifecycle_status = "received"
            
            # 更新WorkOrderItem状态和执行信息
            item.status = "completed"
            item.result = "success"
            item.executed_at = current_time
            item.executed_by = operator
            
            updated_count += 1
            
            # 记录ES日志
            logger.info("Device received", extra={
                "operationObject": asset.serial_number,
                "operationType": "device.inbound",
                "operator": operator,
                "result": "success",
                "operationDetail": f"从房间{old_room_name}到货至房间{item.operation_data.get('target_room_name', target_room_id)}"
            })
            
        except Exception as e:
            failed_items.append({
                "serial_number": item.asset_sn or item.operation_data.get('serial_number'),
                "reason": str(e)
            })
            item.status = "failed"
            item.error_message = str(e)
            logger.error(f"Update asset failed: {str(e)}")
    
    # 4. 更新工单状态
    work_order.status = "completed"
    work_order.completed_time = datetime.now()
    work_order.operator = operator
    if comments:
        work_order.remark = comments
    
    db.commit()
    
    # 5. 记录工单完成日志
    logger.info(f"Receiving work order completed", extra={
        "operationObject": batch_id,
        "operationType": "work_order.complete",
        "operator": operator,
        "result": "success",
        "operationDetail": f"到货工单完成，成功{updated_count}台，失败{len(failed_items)}台"
    })
    
    return {
        "code": 0,
        "message": "到货完成",
        "data": {
            "batch_id": batch_id,
            "updated_count": updated_count,
            "failed_count": len(failed_items),
            "failed_items": failed_items if failed_items else None
        }
    }


@router.get(
    "/statistics",
    summary="到货工单统计",
    responses={
        200: {"description": "统计成功"},
        500: {"description": "服务器内部错误"}
    }
)
async def get_receiving_statistics(
    start_date: Optional[str] = Query(None, description="开始日期，格式：YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期，格式：YYYY-MM-DD"),
    datacenter: Optional[str] = Query(None, description="机房（精确匹配）"),
    db: Session = Depends(get_db)
):
    """
    获取到货工单统计信息
    
    功能说明：
    - 统计到货工单的多维度数据
    - 支持按时间范围和机房筛选
    - 提供按状态、机房、设备分类的统计
    
    查询参数说明：
    - start_date: 开始日期（可选，格式：YYYY-MM-DD）
    - end_date: 结束日期（可选，格式：YYYY-MM-DD）
    - datacenter: 机房（可选，精确匹配）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 统计数据对象
      - summary: 总体统计
        - total_orders: 工单总数
        - total_devices: 设备总数
      - by_status: 按状态统计（字典）
        - {status}: 状态名称
          - order_count: 工单数量
          - device_count: 设备数量
      - by_datacenter: 按机房统计（列表）
        - datacenter: 机房名称
        - order_count: 工单数量
        - device_count: 设备数量
      - by_category_level1: 按设备一级分类统计（列表）
        - category: 分类名称
        - order_count: 工单数量
        - device_count: 设备数量
      - by_category_level2: 按设备二级分类统计（列表）
        - category: 分类名称
        - order_count: 工单数量
        - device_count: 设备数量
    
    使用场景：
    - 到货工单数据分析
    - 生成统计报表
    - 监控到货情况
    - 按机房查看到货统计
    - 按设备类型查看到货统计
    
    注意事项：
    - 只统计operation_type为receiving的工单
    - 时间范围基于工单创建时间
    - 日期格式必须为YYYY-MM-DD
    - 统计数据实时计算
    """
    from sqlalchemy import func
    
    query = db.query(WorkOrder).filter(
        WorkOrder.operation_type == "receiving"
    )
    
    # 时间范围过滤
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(WorkOrder.created_at >= start_dt)
        except:
            pass
    
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            query = query.filter(WorkOrder.created_at <= end_dt)
        except:
            pass
    
    if datacenter:
        query = query.filter(WorkOrder.datacenter == datacenter)
    
    # 总体统计
    total_orders = query.count()
    total_devices = query.with_entities(func.sum(WorkOrder.device_count)).scalar() or 0
    
    # 按状态统计
    status_stats = db.query(
        WorkOrder.status,
        func.count(WorkOrder.id).label('count'),
        func.sum(WorkOrder.device_count).label('device_count')
    ).filter(
        WorkOrder.operation_type == "receiving"
    ).group_by(WorkOrder.status).all()
    
    status_data = {}
    for stat in status_stats:
        status_data[stat[0]] = {
            "order_count": stat[1],
            "device_count": stat[2] or 0
        }
    
    # 按机房统计
    datacenter_stats = db.query(
        WorkOrder.datacenter,
        func.count(WorkOrder.id).label('count'),
        func.sum(WorkOrder.device_count).label('device_count')
    ).filter(
        WorkOrder.operation_type == "receiving",
        WorkOrder.datacenter.isnot(None)
    ).group_by(WorkOrder.datacenter).all()
    
    datacenter_data = []
    for stat in datacenter_stats:
        datacenter_data.append({
            "datacenter": stat[0],
            "order_count": stat[1],
            "device_count": stat[2] or 0
        })
    
    # 按设备一级分类统计
    category_level1_stats = db.query(
        WorkOrder.device_category_level1,
        func.count(WorkOrder.id).label('count'),
        func.sum(WorkOrder.device_count).label('device_count')
    ).filter(
        WorkOrder.operation_type == "receiving",
        WorkOrder.device_category_level1.isnot(None)
    ).group_by(WorkOrder.device_category_level1).all()
    
    category_level1_data = []
    for stat in category_level1_stats:
        category_level1_data.append({
            "category": stat[0],
            "order_count": stat[1],
            "device_count": stat[2] or 0
        })
    
    # 按设备二级分类统计
    category_level2_stats = db.query(
        WorkOrder.device_category_level2,
        func.count(WorkOrder.id).label('count'),
        func.sum(WorkOrder.device_count).label('device_count')
    ).filter(
        WorkOrder.operation_type == "receiving",
        WorkOrder.device_category_level2.isnot(None)
    ).group_by(WorkOrder.device_category_level2).all()
    
    category_level2_data = []
    for stat in category_level2_stats:
        category_level2_data.append({
            "category": stat[0],
            "order_count": stat[1],
            "device_count": stat[2] or 0
        })
    
    return {
        "code": 0,
        "message": "统计成功",
        "data": {
            "summary": {
                "total_orders": total_orders,
                "total_devices": int(total_devices)
            },
            "by_status": status_data,
            "by_datacenter": datacenter_data,
            "by_category_level1": category_level1_data,
            "by_category_level2": category_level2_data
        }
    }


@router.get(
    "/",
    summary="查询到货工单列表",
    responses={
        200: {"description": "查询成功"},
        500: {"description": "服务器内部错误"}
    }
)
async def list_receiving_orders(
    status: Optional[str] = Query(None, description="工单状态：pending（待处理）/processing（处理中）/completed（已完成）/cancelled（已取消）"),
    creator: Optional[str] = Query(None, description="创建人（模糊搜索）"),
    datacenter: Optional[str] = Query(None, description="机房（精确匹配）"),
    category_level1: Optional[str] = Query(None, description="设备一级分类（模糊搜索）"),
    category_level2: Optional[str] = Query(None, description="设备二级分类（模糊搜索）"),
    category_level3: Optional[str] = Query(None, description="设备三级分类（模糊搜索）"),
    work_order_number: Optional[str] = Query(None, description="外部工单号（精确匹配）"),
    arrival_order_number: Optional[str] = Query(None, description="到货单号（精确匹配）"),
    source_order_number: Optional[str] = Query(None, description="来源业务单号（模糊搜索）"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=10000, description="每页大小，最大10000"),
    db: Session = Depends(get_db)
):
    """
    查询设备到货工单列表
    
    功能说明：
    - 查询所有到货工单列表
    - 支持多条件筛选
    - 支持分页查询
    - 按创建时间倒序排列
    
    查询参数说明：
    - status: 工单状态（pending/processing/completed/cancelled）
    - creator: 创建人（模糊搜索）
    - datacenter: 机房（精确匹配）
    - category_level1: 设备一级分类（模糊搜索）
    - category_level2: 设备二级分类（模糊搜索）
    - category_level3: 设备三级分类（模糊搜索）
    - work_order_number: 外部工单号（精确匹配）
    - arrival_order_number: 到货单号（精确匹配）
    - source_order_number: 来源业务单号（模糊搜索）
    - page: 页码（从1开始）
    - page_size: 每页大小（1-100）
    
    返回字段说明：
    - code: 响应码（0表示成功）
    - message: 响应消息
    - data: 数据对象
      - total: 总记录数
      - page: 当前页码
      - page_size: 每页大小
      - items: 工单列表
        - batch_id: 批次ID
        - work_order_number: 外部工单号
        - arrival_order_number: 到货单号
        - source_order_number: 来源单号
        - title: 工单标题
        - status: 工单内部状态
        - work_order_status: 工单外部状态
        - creator: 创建人
        - operator: 操作人
        - datacenter: 机房
        - device_category_level1: 设备一级分类
        - device_category_level2: 设备二级分类
        - device_category_level3: 设备三级分类
        - device_count: 设备数量
        - created_at: 创建时间（ISO格式）
        - completed_time: 完成时间（ISO格式）
        - close_time: 关闭时间（ISO格式）
    
    使用场景：
    - 查询所有到货工单
    - 按状态筛选工单
    - 按机房筛选工单
    - 按设备分类筛选工单
    - 按工单号查询
    - 到货工单列表页展示
    
    注意事项：
    - 只返回operation_type为receiving的工单
    - 所有查询参数都是可选的
    - 字符串参数支持模糊搜索（除了精确匹配的字段）
    - 分页参数page_size最大为100
    """
    
    query = db.query(WorkOrder).filter(
        WorkOrder.operation_type == "receiving"
    )
    
    # 应用筛选条件
    if status:
        query = query.filter(WorkOrder.status == status)
    if creator:
        query = query.filter(WorkOrder.creator.like(f"%{creator}%"))
    if datacenter:
        query = query.filter(WorkOrder.datacenter == datacenter)
    if category_level1:
        query = query.filter(WorkOrder.device_category_level1.like(f"%{category_level1}%"))
    if category_level2:
        query = query.filter(WorkOrder.device_category_level2.like(f"%{category_level2}%"))
    if category_level3:
        query = query.filter(WorkOrder.device_category_level3.like(f"%{category_level3}%"))
    if work_order_number:
        query = query.filter(WorkOrder.work_order_number == work_order_number)
    if arrival_order_number:
        query = query.filter(WorkOrder.arrival_order_number == arrival_order_number)
    if source_order_number:
        query = query.filter(WorkOrder.source_order_number.like(f"%{source_order_number}%"))
    
    # 总数
    total = query.count()
    
    # 分页
    orders = query.order_by(
        WorkOrder.created_at.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    
    items = []
    for order in orders:
        items.append({
            "batch_id": order.batch_id,
            "work_order_number": order.work_order_number,
            "arrival_order_number": order.arrival_order_number,
            "source_order_number": order.source_order_number,
            "title": order.title,
            "status": order.status,
            "work_order_status": order.work_order_status,
            "creator": order.creator,
            "operator": order.operator,
            "datacenter": order.datacenter,
            "device_category_level1": order.device_category_level1,
            "device_category_level2": order.device_category_level2,
            "device_category_level3": order.device_category_level3,
            "device_count": order.device_count,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "completed_time": order.completed_time.isoformat() if order.completed_time else None,
            "close_time": order.close_time.isoformat() if order.close_time else None
        })
    
    return {
        "code": 0,
        "message": "查询成功",
        "data": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items
        }
    }
