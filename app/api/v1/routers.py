from fastapi import APIRouter
from app.api.v1 import users, assets, locations, dict, topology, work_orders, operations, logs, network_cable_work_order, work_order_receiving, work_orders_unified, network_issue_work_order, generic_work_order, asset_entry_exit_work_order, upload
# from app.api.v1 import racking  # 已废弃，功能迁移到统一工单系统
# 注意：staging, receiving, configurations, power_on 已废弃，功能合并到统一工单系统

api_router = APIRouter()

# 用户管理
api_router.include_router(users.router, prefix="/users", tags=["users"])

# IT资产管理
api_router.include_router(assets.router, prefix="/assets", tags=["assets"])
api_router.include_router(locations.router, prefix="/locations", tags=["locations"])

# 数据字典管理
api_router.include_router(dict.router, prefix="/dict", tags=["dict"])

# 设备上架管理 - 已迁移到统一工单系统，旧API已禁用
# api_router.include_router(racking.router, prefix="/racking-legacy", tags=["racking-legacy"])

# 设备拓扑管理
api_router.include_router(topology.router, prefix="/topology", tags=["topology"])

# 统一工单管理系统（推荐使用）
api_router.include_router(work_order_receiving.router, prefix="/receiving", tags=["receiving"])
api_router.include_router(work_orders_unified.router, prefix="/work-orders", tags=["work-orders"])

# 兼容性API（逐步废弃）
api_router.include_router(work_orders.router, prefix="/work-orders-legacy", tags=["work-orders-legacy"])

# 服务器网线/光纤更换工单管理
api_router.include_router(network_cable_work_order.router, prefix="/network-cable-work-order", tags=["network-cable-work-order"])

# 网络故障/变更配合工单管理
api_router.include_router(network_issue_work_order.router, prefix="/network-issue-work-order", tags=["network-issue-work-order"])

# 资产出入门工单管理
api_router.include_router(asset_entry_exit_work_order.router, prefix="/asset-entry-exit-work-order", tags=["asset-entry-exit-work-order"])

# 万能类操作工单管理
api_router.include_router(generic_work_order.router, prefix="/generic-work-order", tags=["generic-work-order"])

# 日志查询（从Elasticsearch）
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])

# 文件上传
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
