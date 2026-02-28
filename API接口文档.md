# IT资产生命周期管理系统 - API接口文档

## 文档说明

本文档整理了系统所有API接口及其对应的文件位置，便于项目交接和维护。

**基础URL**: `/api/v1`

**系统版本**: 见 `alms/version.py`

---

## 项目目录结构

```
alms/
├── .env                          # 环境变量配置文件（数据库、ES、Nacos等）
├── .gitignore                    # Git忽略文件配置
├── alms.db                       # SQLite数据库文件（开发环境）
├── API接口文档.md                # API接口文档（本文档）
├── README.md                     # 项目说明文档
├── requirements.txt              # Python依赖包列表
├── version.py                    # 版本号定义
├── init_database.py              # 数据库初始化脚本
├── import_*.xlsx                 # 导入模板示例文件
│
├── app/                          # 应用主目录
│   ├── __init__.py
│   ├── main.py                   # FastAPI应用入口
│   │
│   ├── api/                      # API路由层
│   │   ├── __init__.py
│   │   └── v1/                   # API v1版本
│   │       ├── __init__.py
│   │       ├── routers.py        # 路由注册（所有API的统一入口）
│   │       ├── users.py          # 用户管理API
│   │       ├── assets.py         # 资产管理API
│   │       ├── locations.py      # 位置管理API （房间管理）
│   │       ├── dict.py           # 数据字典API （枚举值管理）
│   │       ├── upload.py         # 文件上传API
│   │       ├── logs.py           # 日志查询API
│   │       ├── topology.py       # 拓扑管理API （设备增配管理）
│   │       ├── operations.py     # 操作记录API
│   │       ├── work_orders.py    # 工单查询API（兼容性）
│   │       ├── work_orders_unified.py           # 统一工单管理API（推荐）
│   │       ├── work_order_receiving.py          # 设备到货工单API
│   │       ├── network_cable_work_order.py      # 网线更换工单API
│   │       ├── network_issue_work_order.py      # 网络故障工单API
│   │       ├── asset_entry_exit_work_order.py   # 资产出入门工单API
│   │       ├── generic_work_order.py            # 万能类操作工单API
│   │       └── racking.py        # 设备上架API（已废弃）
│   │
│   ├── models/                   # 数据模型层（ORM）
│   │   ├── __init__.py
│   │   ├── asset_models.py       # 资产相关模型（Asset, Room, WorkOrder等）
│   │   ├── cabinet_models.py     # 机柜模型
│   │   ├── asset_relationships.py # 资产关系模型
│   │   └── models.py             # 其他模型（User等）
│   │
│   ├── schemas/                  # Pydantic Schema层（数据验证）
│   │   ├── __init__.py
│   │   ├── asset_schemas.py      # 资产Schema
│   │   ├── generic_work_order_schemas.py        # 通用工单Schema
│   │   ├── asset_entry_exit_schemas.py          # 资产出入门Schema
│   │   ├── network_cable_work_order_schemas.py  # 网线更换Schema
│   │   ├── network_issue_schemas.py             # 网络故障Schema
│   │   ├── user.py               # 用户Schema
│   │   ├── auth.py               # 认证Schema
│   │   └── item.py               # 其他Schema
│   │
│   ├── services/                 # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── asset_service.py      # 资产服务（AssetService, LocationService）
│   │   ├── work_order_service.py # 工单服务
│   │   ├── genericWorkOrderService.py  # 通用工单服务
│   │   ├── elasticsearch_service.py    # ES日志服务
│   │   ├── nacos_service.py      # Nacos配置中心服务
│   │   ├── user_service.py       # 用户服务
│   │   ├── auth_service.py       # 认证服务
│   │   ├── item_service.py       # 其他服务
│   │   └── operation_batch_service.py  # 批次操作服务
│   │
│   ├── core/                     # 核心配置
│   │   ├── __init__.py
│   │   ├── config.py             # 应用配置类
│   │   ├── logging_config.py     # 日志配置
│   │   ├── runtime_config.py     # 运行时配置（Nacos）
│   │   └── security.py           # 安全配置
│   │
│   ├── db/                       # 数据库配置
│   │   ├── __init__.py
│   │   └── session.py            # 数据库会话管理
│   │
│   ├── middleware/               # 中间件
│   │   └── logging_middleware.py # 日志中间件
│   │
│   ├── utils/                    # 工具函数
│   │   ├── __init__.py
│   │   ├── dict_helper.py        # 字典辅助函数
│   │   ├── log_helper.py         # 日志辅助函数
│   │   └── logger.py             # 日志工具
│   │
│   ├── constants/                # 常量定义
│   │   ├── __init__.py
│   │   └── operation_types.py    # 操作类型常量
│   │
│   ├── scripts/                  # 脚本工具
│   │   ├── fix_receiving_batch_ids.py      # 修复批次ID脚本
│   │   └── operation_batch_migration.py    # 批次迁移脚本
│   │
│   ├── tests/                    # 测试代码
│   │   ├── __init__.py
│   │   ├── conftest.py           # pytest配置
│   │   ├── test_auth.py          # 认证测试
│   │   ├── test_items.py         # 项目测试
│   │   └── test_users.py         # 用户测试
│   │
│   ├── static/                   # 静态文件
│   │   ├── favicon.png           # 网站图标
│   │   ├── swagger-ui-bundle.js  # Swagger UI JS
│   │   └── swagger-ui.css        # Swagger UI CSS
│   │
│   ├── templates/                # 模板文件
│   │   ├── __init__.py
│   │   └── index.html            # 首页模板
│   │
│   └── examples/                 # 示例代码
│       ├── __init__.py
│       └── test.py
│
├── docker/                       # Docker配置
│   └── aiot.alms/
│       └── Dockerfile            # Docker镜像构建文件
│
├── logs/                         # 日志文件目录
│   ├── app_YYYYMMDD.log          # 应用日志（文本格式）
│   └── app_YYYYMMDD.json.log     # 应用日志（JSON格式）
│
└── nacos-data/                   # Nacos数据目录
    └── snapshot/                 # Nacos配置快照
```

### 核心文件说明

| 文件/目录 | 说明 |
|----------|------|
| `app/main.py` | FastAPI应用入口，包含应用初始化、路由注册、中间件配置 |
| `app/api/v1/routers.py` | 所有API路由的统一注册入口 |
| `app/models/asset_models.py` | 核心数据模型（资产、房间、工单等） |
| `app/services/` | 业务逻辑层，包含各模块的服务类 |
| `app/core/config.py` | 应用配置，从环境变量读取配置 |
| `.env` | 环境变量配置文件（数据库、ES、Nacos等） |
| `init_database.py` | 数据库初始化脚本，创建表和基础数据 |
| `requirements.txt` | Python依赖包列表 |

---

## 目录

1. [用户管理](#1-用户管理)
2. [资产管理](#2-资产管理)
3. [位置管理](#3-位置管理)
4. [数据字典管理](#4-数据字典管理)
5. [工单管理](#5-工单管理)
6. [文件上传](#6-文件上传)
7. [日志查询](#7-日志查询)
8. [拓扑管理](#8-拓扑管理)
9. [操作记录](#9-操作记录)

---

## 1. 用户管理

**文件位置**: `alms/app/api/v1/users.py`

**路由前缀**: `/api/v1/users`

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | POST | 创建用户 | username, email, password |
| `/` | GET | 获取用户列表 | skip, limit |
| `/{user_id}` | GET | 获取用户详情 | user_id |
| `/{user_id}` | PUT | 更新用户信息 | user_id, user_in |
| `/{user_id}` | DELETE | 删除用户 | user_id |

---

## 2. 资产管理

**文件位置**: `alms/app/api/v1/assets.py`

**路由前缀**: `/api/v1/assets`

**服务层**: `alms/app/services/asset_service.py`

**数据模型**: `alms/app/models/asset_models.py`


### 2.1 资产导入导出

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/import/template` | GET | 下载资产导入模板 | - |
| `/import` | POST | 批量导入资产（Excel） | file, operator |
| `/import/error-report/{filename}` | GET | 下载导入失败报告 | filename |
| `/export` | GET | 批量导出资产（Excel） | 支持多种筛选条件 |

### 2.2 资产CRUD

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | POST | 创建资产 | asset_data, operator |
| `/{asset_id}` | GET | 获取资产详情 | asset_id |
| `/{asset_id}` | PUT | 更新资产信息 | asset_id, asset_data |
| `/{asset_id}` | DELETE | 删除资产 | asset_id |
| `/{asset_id}/availability` | PUT | 更新资产可用状态 | asset_id, is_available, unavailable_reason |

### 2.3 资产查询

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | GET | 查询资产列表 | asset_tag, name, serial_number, room_id等 |
| `/search` | GET | 高级搜索资产 | 支持多条件组合查询 |
| `/batch/serial-numbers` | POST | 批量校验序列号 | serial_numbers |

### 2.4 资产统计

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/statistics/overview` | GET | 资产概览统计 | - |
| `/statistics/by-category` | GET | 按分类统计 | - |
| `/statistics/by-room` | GET | 按房间统计 | - |
| `/statistics/by-status` | GET | 按状态统计 | - |

---

## 3. 位置管理

**文件位置**: `alms/app/api/v1/locations.py`

**路由前缀**: `/api/v1/locations`

**服务层**: `alms/app/services/asset_service.py` (LocationService)

**数据模型**: `alms/app/models/asset_models.py` (Room, RoomType)

### 3.1 房间类型管理

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/room-types` | GET | 获取房间类型列表 | is_active |
| `/room-types/{type_id}` | GET | 获取房间类型详情 | type_id |
| `/room-types` | POST | 创建房间类型 | room_type_data |
| `/room-types/{type_id}` | PUT | 更新房间类型 | type_id, room_type_data |
| `/room-types/{type_id}` | DELETE | 删除房间类型 | type_id |

### 3.2 房间管理

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/rooms` | GET | 获取房间列表 | datacenter, building, floor等 |
| `/rooms/{room_id}` | GET | 获取房间详情 | room_id |
| `/rooms` | POST | 创建房间 | room_data |
| `/rooms/{room_id}` | PUT | 更新房间 | room_id, room_data |
| `/rooms/{room_id}` | DELETE | 删除房间 | room_id |

### 3.3 房间导入导出

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/rooms/import/template` | GET | 下载房间导入模板 | - |
| `/rooms/import` | POST | 批量导入房间（Excel） | file, operator |
| `/rooms/import/error-report/{filename}` | GET | 下载导入失败报告 | filename |

### 3.4 房间查询辅助

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/rooms/location-options` | GET | 获取楼号/楼层选项 | datacenter, building |
| `/rooms/location-options/all` | GET | 获取全部楼号与楼层 | datacenter |
| `/rooms/datacenters` | GET | 获取机房列表 | - |
| `/rooms/numbers` | GET | 获取房间号列表 | datacenter |

### 3.5 房间统计

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/rooms/statistics/datacenter` | GET | 按机房统计 | - |
| `/rooms/statistics/building-floor` | GET | 按楼层统计 | - |
| `/rooms/statistics/type` | GET | 按房间类型统计 | - |

---

## 4. 数据字典管理

**文件位置**: `alms/app/api/v1/dict.py`

**路由前缀**: `/api/v1/dict`

**数据模型**: `alms/app/models/asset_models.py` (DictType, DictItem)

### 4.1 字典类型管理

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/types` | GET | 字典类型列表 | keyword, status, page, page_size |
| `/types` | POST | 新增字典类型（支持批量创建字典项） | type_code, type_name, items |
| `/types/{type_id}` | PUT | 更新字典类型 | type_id, payload |
| `/types/{type_id}` | DELETE | 删除字典类型 | type_id |

### 4.2 字典项管理

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/types/{type_code}/items` | GET | 查询字典项 | type_code, keyword, status, level |
| `/types/{type_code}/items` | POST | 新增字典项 | type_code, payload |
| `/items/{item_id}` | PUT | 更新字典项 | item_id, payload |
| `/items/{item_id}` | DELETE | 删除字典项 | item_id |

---

## 5. 工单管理

工单管理系统包含多个模块，支持不同类型的工单操作。

### 5.1 统一工单管理（推荐使用）

**文件位置**: `alms/app/api/v1/work_orders_unified.py`

**路由前缀**: `/api/v1/work-orders`

**服务层**: `alms/app/services/genericWorkOrderService.py`

**数据模型**: `alms/app/models/asset_models.py` (WorkOrder, WorkOrderItem)

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/operation-types/options` | GET | 获取操作类型两级联动数据 | - |
| `/create` | POST | 创建工单（通用） | operation_type, title, creator, items等 |
| `/` | GET | 查询工单列表 | work_order_number, operation_type, status等 |
| `/{work_order_id}` | GET | 查询工单详情 | work_order_id |
| `/{work_order_id}/items` | GET | 查询工单明细 | work_order_id |
| `/{work_order_id}/execute` | POST | 执行工单 | work_order_id, operator |
| `/{work_order_id}/complete` | POST | 完成工单 | work_order_id, operator |
| `/{work_order_id}/cancel` | POST | 取消工单 | work_order_id, operator, reason |

**支持的工单类型**:
- `receiving`: 设备到货
- `racking`: 设备上架
- `power_management`: 电源管理（上电/下电）
- `configuration`: 设备增配
- `network_cable`: 网线更换
- `maintenance`: 设备维护

### 5.2 设备到货工单

**文件位置**: `alms/app/api/v1/work_order_receiving.py`

**路由前缀**: `/api/v1/receiving`

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/import/template` | GET | 下载到货工单导入模板 | - |
| `/import` | POST | 批量导入到货工单（Excel） | file, operator |
| `/import/error-report/{filename}` | GET | 下载导入失败报告 | filename |
| `/batches` | GET | 查询到货批次列表 | batch_id, status等 |
| `/batches/{batch_id}` | GET | 查询批次详情 | batch_id |
| `/batches/{batch_id}/items` | GET | 查询批次明细 | batch_id |

### 5.3 网线更换工单

**文件位置**: `alms/app/api/v1/network_cable_work_order.py`

**路由前缀**: `/api/v1/network-cable-work-order`

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | POST | 创建网线更换工单 | work_order_data |
| `/` | GET | 查询网线更换工单列表 | work_order_number, status等 |
| `/{work_order_id}` | GET | 查询工单详情 | work_order_id |
| `/{work_order_id}/execute` | POST | 执行工单 | work_order_id, operator |
| `/{work_order_id}/complete` | POST | 完成工单 | work_order_id, operator |

### 5.4 网络故障/变更配合工单

**文件位置**: `alms/app/api/v1/network_issue_work_order.py`

**路由前缀**: `/api/v1/network-issue-work-order`

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | POST | 创建网络故障工单 | work_order_data |
| `/` | GET | 查询网络故障工单列表 | work_order_number, status等 |
| `/{work_order_id}` | GET | 查询工单详情 | work_order_id |
| `/{work_order_id}/execute` | POST | 执行工单 | work_order_id, operator |
| `/{work_order_id}/complete` | POST | 完成工单 | work_order_id, operator |

### 5.5 资产出入门工单

**文件位置**: `alms/app/api/v1/asset_entry_exit_work_order.py`

**路由前缀**: `/api/v1/asset-entry-exit-work-order`

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | POST | 创建资产出入门工单 | work_order_data |
| `/` | GET | 查询资产出入门工单列表 | work_order_number, status等 |
| `/{work_order_id}` | GET | 查询工单详情 | work_order_id |
| `/{work_order_id}/execute` | POST | 执行工单 | work_order_id, operator |
| `/{work_order_id}/complete` | POST | 完成工单 | work_order_id, operator |

### 5.6 万能类操作工单

**文件位置**: `alms/app/api/v1/generic_work_order.py`

**路由前缀**: `/api/v1/generic-work-order`

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | POST | 创建万能工单 | work_order_data |
| `/` | GET | 查询万能工单列表 | work_order_number, status等 |
| `/{work_order_id}` | GET | 查询工单详情 | work_order_id |
| `/{work_order_id}/execute` | POST | 执行工单 | work_order_id, operator |
| `/{work_order_id}/complete` | POST | 完成工单 | work_order_id, operator |

### 5.7 工单查询（兼容性API）

**文件位置**: `alms/app/api/v1/work_orders.py`

**路由前缀**: `/api/v1/work-orders-legacy`

**说明**: 此接口为兼容性接口，逐步废弃，建议使用统一工单管理接口。

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | GET | 查询工单列表 | work_order_number, operation_type, status等 |
| `/{work_order_id}` | GET | 查询工单详情 | work_order_id |
| `/number/{work_order_number}` | GET | 根据工单号查询工单 | work_order_number |

---

## 6. 文件上传

**文件位置**: `alms/app/api/v1/upload.py`

**路由前缀**: `/api/v1/upload`

**配置文件**: `alms/app/core/config.py`

**配置项**:
- `PICTURE_DIR`: 图片存储目录，默认 `/opt/aiot/images`
- `PICTURE_HTTP`: 图片访问URL前缀，默认 `https://download.sihua.tech/alms/images`
- `MAX_UPLOAD_SIZE`: 最大上传大小，默认 10MB
- `ALLOWED_EXTENSIONS`: 允许的文件扩展名，默认 jpg, jpeg, png, gif, bmp, webp

### 6.1 图片上传

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/image` | POST | 上传单张图片 | file, category, prefix |
| `/images` | POST | 批量上传图片 | files, category, prefix |

### 6.2 图片访问

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/preview/{category}/{filename}` | GET | 预览图片（原图） | category, filename |
| `/thumbnail/{category}/{filename}` | GET | 获取缩略图 | category, filename, width, height |

### 6.3 图片管理

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/image` | DELETE | 删除图片 | url |
| `/list/{category}` | GET | 列出分类下的所有图片 | category, page, page_size |

---

## 7. 日志查询

**文件位置**: `alms/app/api/v1/logs.py`

**路由前缀**: `/api/v1/logs`

**服务层**: `alms/app/services/elasticsearch_service.py`

**说明**: 日志存储在Elasticsearch中，支持高级查询和分析。

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | GET | 查询操作日志 | operation_type, operator, start_time, end_time等 |
| `/statistics` | GET | 日志统计分析 | start_time, end_time, group_by |
| `/export` | GET | 导出日志（Excel） | 支持多种筛选条件 |

**支持的操作类型** (定义在 `alms/app/constants/operation_types.py`):
- 资产操作: `ASSET_CREATE`, `ASSET_UPDATE`, `ASSET_DELETE`, `ASSET_SET_AVAILABLE`, `ASSET_SET_UNAVAILABLE`
- 工单操作: `WORK_ORDER_CREATE`, `WORK_ORDER_EXECUTE`, `WORK_ORDER_COMPLETE`, `WORK_ORDER_CANCEL`
- 设备操作: `DEVICE_POWER_ON`, `DEVICE_POWER_OFF`, `DEVICE_RACKING`, `DEVICE_CONFIGURATION`

---

## 8. 拓扑管理

**文件位置**: `alms/app/api/v1/topology.py`

**路由前缀**: `/api/v1/topology`

**说明**: 管理设备之间的网络连接关系和拓扑结构。

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/connections` | GET | 查询网络连接列表 | asset_id, connection_type等 |
| `/connections` | POST | 创建网络连接 | connection_data |
| `/connections/{connection_id}` | GET | 查询连接详情 | connection_id |
| `/connections/{connection_id}` | PUT | 更新连接信息 | connection_id, connection_data |
| `/connections/{connection_id}` | DELETE | 删除连接 | connection_id |
| `/graph/{asset_id}` | GET | 获取设备拓扑图 | asset_id, depth |

---

## 9. 操作记录

**文件位置**: `alms/app/api/v1/operations.py`

**路由前缀**: `/api/v1/operations`

**说明**: 记录和查询系统中的各类操作记录。

| 接口路径 | 方法 | 功能说明 | 主要参数 |
|---------|------|---------|---------|
| `/` | GET | 查询操作记录列表 | operation_type, operator, start_time, end_time等 |
| `/{operation_id}` | GET | 查询操作记录详情 | operation_id |
| `/statistics` | GET | 操作统计分析 | start_time, end_time, group_by |

---

## 附录

### A. 核心数据模型

**文件位置**: `alms/app/models/asset_models.py`

主要模型:
- `Asset`: 资产表
- `Room`: 房间表
- `RoomType`: 房间类型表
- `DictType`: 字典类型表
- `DictItem`: 字典项表
- `WorkOrder`: 工单表
- `WorkOrderItem`: 工单明细表
- `AssetLifecycleStatus`: 资产生命周期状态表
- `AssetChangeLog`: 资产变更日志表
- `MaintenanceRecord`: 维护记录表
- `NetworkConnection`: 网络连接表
- `AssetConfiguration`: 资产配置表

**文件位置**: `alms/app/models/cabinet_models.py`

主要模型:
- `Cabinet`: 机柜表

### B. 核心服务层

| 服务文件 | 说明 |
|---------|------|
| `alms/app/services/asset_service.py` | 资产管理服务（AssetService, LocationService） |
| `alms/app/services/work_order_service.py` | 工单管理服务 |
| `alms/app/services/genericWorkOrderService.py` | 通用工单服务 |
| `alms/app/services/elasticsearch_service.py` | Elasticsearch日志服务 |
| `alms/app/services/nacos_service.py` | Nacos配置中心服务 |
| `alms/app/services/user_service.py` | 用户管理服务 |

### C. Schema定义

**文件位置**: `alms/app/schemas/`

主要Schema文件:
- `asset_schemas.py`: 资产相关Schema（AssetCreate, AssetUpdate, AssetResponse等）
- `generic_work_order_schemas.py`: 通用工单Schema
- `asset_entry_exit_schemas.py`: 资产出入门工单Schema
- `network_cable_work_order_schemas.py`: 网线更换工单Schema
- `network_issue_schemas.py`: 网络故障工单Schema
- `user.py`: 用户Schema
- `auth.py`: 认证Schema

### D. 配置文件

| 配置文件 | 说明 |
|---------|------|
| `alms/.env` | 环境变量配置（数据库、ES、Nacos等） |
| `alms/app/core/config.py` | 应用配置类 |
| `alms/app/core/logging_config.py` | 日志配置 |
| `alms/app/core/security.py` | 安全配置 |

### E. 数据库初始化

**文件位置**: `alms/init_database.py`

**说明**: 初始化数据库表结构和基础数据（生命周期阶段、房间类型、数据字典等）

### F. 路由注册

**文件位置**: `alms/app/api/v1/routers.py`

**说明**: 所有API路由的统一注册入口，定义了各模块的路由前缀和标签。

### G. 常量定义

**文件位置**: `alms/app/constants/operation_types.py`

**说明**: 定义了系统中所有的操作类型常量和工单类型选项。

---

## 快速查找指南

### 按功能查找

| 功能 | 主要文件 |
|------|---------|
| 资产导入导出 | `assets.py` |
| 工单创建 | `work_orders_unified.py` |
| 设备到货 | `work_order_receiving.py` |
| 电源管理 | `work_orders_unified.py` (operation_type=power_management) |
| 设备上架 | `work_orders_unified.py` (operation_type=racking) |
| 设备增配 | `work_orders_unified.py` (operation_type=configuration) |
| 图片上传 | `upload.py` |
| 日志查询 | `logs.py` |
| 房间管理 | `locations.py` |
| 数据字典 | `dict.py` |

### 按URL前缀查找

| URL前缀 | 文件 |
|---------|------|
| `/api/v1/users` | `users.py` |
| `/api/v1/assets` | `assets.py` |
| `/api/v1/locations` | `locations.py` |
| `/api/v1/dict` | `dict.py` |
| `/api/v1/work-orders` | `work_orders_unified.py` |
| `/api/v1/receiving` | `work_order_receiving.py` |
| `/api/v1/network-cable-work-order` | `network_cable_work_order.py` |
| `/api/v1/network-issue-work-order` | `network_issue_work_order.py` |
| `/api/v1/asset-entry-exit-work-order` | `asset_entry_exit_work_order.py` |
| `/api/v1/generic-work-order` | `generic_work_order.py` |
| `/api/v1/upload` | `upload.py` |
| `/api/v1/logs` | `logs.py` |
| `/api/v1/topology` | `topology.py` |
| `/api/v1/operations` | `operations.py` |

---

## 注意事项

1. **工单系统**: 推荐使用统一工单管理接口 (`/api/v1/work-orders`)，旧的独立工单接口逐步废弃。

2. **文件上传**: 图片上传后会返回两种URL：
   - CDN URL (`url`): 用于生产环境外网访问
   - 预览URL (`preview_url`): 用于内网或调试环境

3. **日志系统**: 所有重要操作都会记录到Elasticsearch，可通过日志接口查询和分析。

4. **数据字典**: 系统中的枚举值（如资产状态、工单类型等）都通过数据字典管理，支持动态配置。

5. **权限控制**: 当前版本未实现完整的权限控制，建议在生产环境添加认证和授权中间件。

6. **API文档**: 系统集成了Swagger UI，可访问 `/docs` 查看交互式API文档。

---

**文档生成时间**: 2025-12-15

**维护人员**: [待填写]

**联系方式**: [待填写]
