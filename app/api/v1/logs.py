"""
日志查询API
从Elasticsearch查询业务日志
"""

from fastapi import APIRouter, Query, HTTPException, Depends, Body, Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.services.elasticsearch_service import (
    ElasticsearchService,
    get_elasticsearch_service
)
from app.core.logging_config import get_logger
from app.constants.operation_types import OperationType, OperationResult

router = APIRouter()
logger = get_logger(__name__)

@router.get("/", summary="日志查询系统")
async def get_logs_info():
    """日志查询系统首页"""
    return {
        "code": 0,
        "message": "日志查询系统",
        "data": {
            "description": "从Elasticsearch查询业务日志",
            "available_endpoints": [
                "GET /device-lifecycle/{serial_number} - 获取设备生命周期日志"
            ]
        }
    }


@router.get("/device-lifecycle/{serial_number}", summary="获取设备生命周期")
async def get_device_lifecycle(
    serial_number: str,
    start_time: Optional[str] = Query(None, description="开始时间 (ISO 8601格式，如 2025-11-20T00:00:00Z)"),
    end_time: Optional[str] = Query(None, description="结束时间 (ISO 8601格式)"),
    size: int = Query(100, ge=1, le=10000, description="返回记录数量限制"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """
    获取指定设备的完整生命周期日志
    
    从Elasticsearch中查询该设备的所有操作记录，按时间顺序排列
    
    - **serial_number**: 设备序列号
    - **start_time**: 可选，开始时间（ISO 8601格式）
    - **end_time**: 可选，结束时间（ISO 8601格式）
    - **size**: 返回记录数量，默认100，最大1000
    
    返回示例:
    ```json
    {
      "serial_number": "TEST-SN-999",
      "total": 5,
      "logs": [
        {
          "operationTime": "2025-11-20T03:11:42.801575Z",
          "operationType": "asset.create",
          "operationObject": "TEST-SN-999",
          "operator": "admin",
          "result": "success"
        },
        {
          "operationTime": "2025-11-20T03:12:47.660715Z",
          "operationType": "asset.set_unavailable",
          "operationObject": "TEST-SN-999",
          "operator": "system",
          "result": "success"
        }
      ]
    }
    ```
    """
    # 先检查ES连接
    if not es_service.check_connection():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Elasticsearch service is unavailable",
                "message": "请确保Elasticsearch服务正在运行并且配置正确",
                "config": {
                    "host": es_service.host,
                    "port": es_service.port,
                    "index": es_service.index
                }
            }
        )
    
    try:
        result = es_service.get_device_lifecycle(
            serial_number=serial_number,
            start_time=start_time,
            end_time=end_time,
            size=size
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query device lifecycle: {str(e)}"
        )


@router.get("/statistics", summary="获取操作统计")
async def get_operation_statistics(
    start_time: Optional[str] = Query(None, description="开始时间 (ISO 8601格式)"),
    end_time: Optional[str] = Query(None, description="结束时间 (ISO 8601格式)"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """
    获取操作统计信息
    
    从Elasticsearch聚合查询各类操作的统计数据
    
    - **start_time**: 可选，开始时间（ISO 8601格式）
    - **end_time**: 可选，结束时间（ISO 8601格式）
    
    返回示例:
    ```json
    {
      "total": 1000,
      "by_operation_type": [
        {"operation": "asset.create", "count": 450},
        {"operation": "device.power_on", "count": 300}
      ],
      "by_result": [
        {"result": "success", "count": 950},
        {"result": "failed", "count": 50}
      ],
      "by_operator": [
        {"operator": "admin", "count": 600},
        {"operator": "system", "count": 400}
      ]
    }
    ```
    """
    try:
        result = es_service.get_operation_statistics(
            start_time=start_time,
            end_time=end_time
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query operation statistics: {str(e)}"
        )


@router.post("/device-lifecycle/sample", summary="生成测试生命周期日志")
async def create_sample_lifecycle_log(
    serial_number: str = Body(..., embed=True, description="需要造数的设备序列号"),
    operator: str = Body("api-tester", embed=True, description="操作人"),
    operation_type: str = Body(
        OperationType.ASSET_CREATE,
        embed=True,
        description="操作类型，默认为资产创建"
    ),
    remark: Optional[str] = Body(
        "sample lifecycle log",
        embed=True,
        description="备注信息"
    )
):
    """写入一条符合业务格式的测试日志，便于生命周期接口验证。"""

    operation_time = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    logger.info(
        "Sample lifecycle log created",
        extra={
            "operationObject": serial_number,
            "operationType": operation_type,
            "operator": operator,
            "result": OperationResult.SUCCESS,
            "operationDetail": "自动生成的生命周期测试日志",
            "remark": remark,
            "operationTime": operation_time,
        },
    )

    return {
        "code": 0,
        "message": "sample log created",
        "data": {
            "serial_number": serial_number,
            "operation_type": operation_type,
            "operator": operator,
            "operation_time": operation_time,
            "remark": remark,
        },
    }


@router.get("/health", summary="检查Elasticsearch连接")
async def check_elasticsearch_health(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """
    检查Elasticsearch连接状态
    
    返回ES是否可访问
    """
    is_connected = es_service.check_connection()
    
    if not is_connected:
        raise HTTPException(
            status_code=503,
            detail="Elasticsearch is not available"
        )
    
    return {
        "status": "healthy",
        "elasticsearch": "connected"
    }


def search_logs_from_local_files(identifier: str, start_time: Optional[str] = None, 
                                   end_time: Optional[str] = None, size: int = 100) -> List[Dict]:
    """
    从本地JSON日志文件中搜索操作记录
    
    Args:
        identifier: 工单标识（批次ID或工单号）
        start_time: 开始时间（ISO 8601格式）
        end_time: 结束时间（ISO 8601格式）
        size: 返回记录数量限制
    
    Returns:
        匹配的日志记录列表
    """
    import json
    import os
    from pathlib import Path
    
    logs = []
    # 尝试多个可能的日志目录
    possible_dirs = [Path("logs"), Path("alms/logs"), Path("../logs")]
    log_dir = None
    
    for d in possible_dirs:
        if d.exists():
            log_dir = d
            break
    
    if not log_dir:
        return logs
    
    # 获取所有JSON日志文件，按日期倒序排列
    json_files = sorted(log_dir.glob("app_*.json.log"), reverse=True)
    
    for log_file in json_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        log_entry = json.loads(line)
                        
                        # 检查是否匹配identifier
                        operation_object = log_entry.get("operationObject", "")
                        operation_detail = log_entry.get("operationDetail", "")
                        
                        if identifier in str(operation_object) or identifier in str(operation_detail):
                            # 检查时间范围
                            operation_time = log_entry.get("operationTime", "")
                            
                            if start_time and operation_time < start_time:
                                continue
                            if end_time and operation_time > end_time:
                                continue
                            
                            logs.append({
                                "operationTime": operation_time,
                                "operationType": log_entry.get("operationType"),
                                "operationObject": operation_object,
                                "operator": log_entry.get("operator"),
                                "result": log_entry.get("result"),
                                "operationDetail": operation_detail,
                                "remark": log_entry.get("remark"),
                            })
                            
                            if len(logs) >= size:
                                break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"读取日志文件失败 {log_file}: {str(e)}")
            continue
        
        if len(logs) >= size:
            break
    
    # 按时间排序
    logs.sort(key=lambda x: x.get("operationTime", ""))
    return logs[:size]


@router.get("/work-order/{identifier}", summary="获取工单操作记录",
            responses={
                200: {
                    "description": "查询成功",
                    "content": {
                        "application/json": {
                            "example": {
                                "code": 0,
                                "message": "查询成功",
                                "data": {
                                    "identifier": "PWR20251210141408",
                                    "work_order_info": {
                                        "batch_id": "PWR20251210141408",
                                        "work_order_number": "LOCAL-PWR20251210141408-20251210141410",
                                        "operation_type": "power_management",
                                        "title": "A101房间设备上电",
                                        "status": "completed",
                                        "work_order_status": "processing",
                                        "room": "A101",
                                        "datacenter": "DC01",
                                        "creator": "张三",
                                        "assignee": "李四",
                                        "operator": "李四",
                                        "device_count": 0,
                                        "created_at": "2025-12-10T14:14:08",
                                        "completed_time": "2025-12-10T14:17:46",
                                        "power_action": "power_on",
                                        "power_type": "AC",
                                        "cabinet_count": 0
                                    },
                                    "total": 3,
                                    "logs": [
                                        {
                                            "operationTime": "2025-12-10T06:14:10.264463Z",
                                            "operationType": "power_management.submit",
                                            "operationObject": "PWR20251210141408",
                                            "operator": "张三",
                                            "result": "success",
                                            "operationDetail": "提交电源管理工单（上电），房间: A101",
                                            "remark": "业务上线需要"
                                        },
                                        {
                                            "operationTime": "2025-12-10T06:17:44.966248Z",
                                            "operationType": "power_management.execute",
                                            "operationObject": "PWR20251210141408",
                                            "operator": "李四",
                                            "result": "success",
                                            "operationDetail": "开始执行电源管理工单（上电），房间: A101",
                                            "remark": None
                                        },
                                        {
                                            "operationTime": "2025-12-10T06:17:46.001837Z",
                                            "operationType": "power_management.complete",
                                            "operationObject": "PWR20251210141408",
                                            "operator": "李四",
                                            "result": "success",
                                            "operationDetail": "电源管理工单结单（上电），房间: A101",
                                            "remark": "所有设备上电成功"
                                        }
                                    ],
                                    "source": "local_file"
                                }
                            }
                        }
                    }
                },
                404: {"description": "工单不存在"},
                500: {"description": "服务器内部错误"}
            })
async def get_work_order_logs(
    identifier: str = Path(..., description="工单标识（批次ID或外部工单号）", example="PWR20251210141408"),
    start_time: Optional[str] = Query(None, description="开始时间 (ISO 8601格式，如 2025-12-01T00:00:00Z)"),
    end_time: Optional[str] = Query(None, description="结束时间 (ISO 8601格式)"),
    size: int = Query(100, ge=1, le=1000, description="返回记录数量，默认100，最大1000"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """
    获取指定工单的操作记录
    
    通过工单号或批次ID查询该工单的所有操作记录。
    优先从Elasticsearch获取，ES不可用或无数据时从本地JSON日志文件获取。
    
    ## 路径参数
    - **identifier**: 工单标识（必填），支持以下格式：
      - 批次ID（如 PWR20251210120000、RACK_20251205120000、CONF20251205120000）
      - 外部工单号（如 LOCAL-PWR20251210141408-20251210141410）
    
    ## 查询参数
    - **start_time**: 开始时间（可选，ISO 8601格式，如 2025-12-01T00:00:00Z）
    - **end_time**: 结束时间（可选，ISO 8601格式）
    - **size**: 返回记录数量，默认100，最大1000
    
    ## 返回字段说明
    
    ### 顶层字段
    - **code**: 响应码，0表示成功
    - **message**: 响应消息
    - **data**: 响应数据
    
    ### data字段
    - **identifier**: 查询的工单标识
    - **work_order_info**: 工单基本信息（从数据库获取）
    - **total**: 操作记录总数
    - **logs**: 操作记录列表
    - **source**: 数据来源（elasticsearch 或 local_file）
    
    ### work_order_info字段（工单基本信息）
    - **batch_id**: 批次ID
    - **work_order_number**: 外部工单号
    - **operation_type**: 操作类型（power_management/racking/receiving/configuration等）
    - **title**: 工单标题
    - **status**: 内部状态（pending/processing/completed/cancelled）
    - **work_order_status**: 外部工单状态（processing/completed/failed）
    - **room**: 房间
    - **datacenter**: 机房/园区
    - **creator**: 创建人
    - **assignee**: 指派人
    - **operator**: 操作人
    - **device_count**: 设备数量
    - **created_at**: 创建时间
    - **completed_time**: 完成时间
    - **power_action**: 电源操作（power_on/power_off，仅电源管理工单）
    - **power_type**: 电源类型（AC/DC，仅电源管理工单）
    - **cabinet_count**: 机柜数量（仅电源管理工单）
    
    ### logs字段（操作记录列表）
    每条操作记录包含以下字段：
    - **operationTime**: 操作时间（ISO 8601格式）
    - **operationType**: 操作类型，可能的值：
      - power_management.submit: 提单（创建电源管理工单）
      - power_management.execute: 执行（开始执行电源管理工单）
      - power_management.complete: 结单（电源管理工单完成）
      - work_order.create: 创建工单（其他类型工单）
      - work_order.execute: 执行工单（其他类型工单）
      - work_order.complete: 完成工单（其他类型工单）
    - **operationObject**: 操作对象（通常是批次ID）
    - **operator**: 操作人
    - **result**: 操作结果（success/failed）
    - **operationDetail**: 操作详情描述
    - **remark**: 备注信息
    
    ## 操作记录状态说明
    工单操作记录有4种状态：
    1. **开始**: 工单创建时的初始状态（目前未单独记录）
    2. **提单**: 工单创建成功，对应 operationType 为 xxx.submit
    3. **执行**: 工单开始处理，对应 operationType 为 xxx.execute
    4. **结单**: 工单完成，对应 operationType 为 xxx.complete
    
    ## 使用场景
    1. 查看工单的完整操作历史
    2. 审计工单执行过程
    3. 追踪工单状态变更记录
    4. 排查工单执行问题
    
    ## 注意事项
    1. 支持通过批次ID或外部工单号查询
    2. ES可用时优先从ES获取，ES不可用或无数据时从本地日志文件获取
    3. 如果工单不存在于数据库，work_order_info将为null，但仍会尝试查询操作记录
    4. 操作记录按时间升序排列
    """
    from sqlalchemy.orm import Session
    from app.db.session import get_db
    from app.models.asset_models import WorkOrder
    
    # 获取数据库会话，查询工单基本信息
    db = next(get_db())
    work_order_info = None
    
    try:
        # 尝试通过batch_id或work_order_number查询工单
        work_order = db.query(WorkOrder).filter(
            (WorkOrder.batch_id == identifier) | (WorkOrder.work_order_number == identifier)
        ).first()
        
        if work_order:
            extra_data = work_order.extra or {}
            work_order_info = {
                "batch_id": work_order.batch_id,
                "work_order_number": work_order.work_order_number,
                "operation_type": work_order.operation_type,
                "title": work_order.title,
                "status": work_order.status,
                "work_order_status": work_order.work_order_status,
                "room": work_order.room,
                "datacenter": work_order.datacenter,
                "creator": work_order.creator,
                "assignee": work_order.assignee,
                "operator": work_order.operator,
                "device_count": work_order.device_count,
                "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
                "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
            }
            
            # 电源管理工单额外信息
            if work_order.operation_type == "power_management":
                work_order_info.update({
                    "power_action": extra_data.get("power_action"),
                    "power_type": extra_data.get("power_type"),
                    "cabinet_count": work_order.cabinet_count,
                })
    finally:
        db.close()
    
    # 尝试从ES查询操作记录
    logs = []
    total = 0
    source = "elasticsearch"
    
    es_available = es_service.check_connection()
    
    if es_available:
        try:
            # 构建ES查询
            query_body = {
                "bool": {
                    "should": [
                        {"match": {"operationObject": identifier}},
                        {"match": {"operationDetail": identifier}},
                    ],
                    "minimum_should_match": 1
                }
            }
            
            # 添加时间范围
            if start_time or end_time:
                time_range = {}
                if start_time:
                    time_range["gte"] = start_time
                if end_time:
                    time_range["lte"] = end_time
                
                query_body["bool"]["filter"] = [
                    {"range": {"operationTime": time_range}}
                ]
            
            # 执行ES查询
            result = es_service.client.search(
                index=es_service.index,
                body={
                    "query": query_body,
                    "sort": [{"operationTime": {"order": "asc"}}],
                    "size": size
                }
            )
            
            # 解析结果
            hits = result.get("hits", {}).get("hits", [])
            total = result.get("hits", {}).get("total", {})
            if isinstance(total, dict):
                total = total.get("value", 0)
            
            for hit in hits:
                src = hit.get("_source", {})
                logs.append({
                    "operationTime": src.get("operationTime"),
                    "operationType": src.get("operationType"),
                    "operationObject": src.get("operationObject"),
                    "operator": src.get("operator"),
                    "result": src.get("result"),
                    "operationDetail": src.get("operationDetail"),
                    "remark": src.get("remark"),
                })
        except Exception as e:
            logger.warning(f"ES查询失败，尝试从本地文件获取: {str(e)}")
            es_available = False
    
    # ES不可用、查询失败或ES返回0条记录时，从本地文件获取
    if not es_available or len(logs) == 0:
        local_logs = search_logs_from_local_files(identifier, start_time, end_time, size)
        if local_logs:
            source = "local_file"
            logs = local_logs
            total = len(logs)
    
    return {
        "code": 0,
        "message": "查询成功",
        "data": {
            "identifier": identifier,
            "work_order_info": work_order_info,
            "total": total,
            "logs": logs,
            "source": source
        }
    }
