# IT资产生命周期管理系统 - 应用入口文件
#
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import ORJSONResponse
from starlette.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# 首先加载环境变量
load_dotenv()

from app.core.config import settings
from app.core.runtime_config import NacosRuntimeConfig, get_runtime_config
from app.api.v1.routers import api_router
from app.core.logging_config import setup_logging, get_logger
from app.middleware.logging_middleware import LoggingMiddleware
from app.services.nacos_service import get_nacos_manager

# 初始化日志
setup_logging()
logger = get_logger(__name__)
from app.db.session import engine, Base
from app.models import models  # 导入所有模型

# 数据库初始化
def create_database_if_not_exists():
    """自动创建数据库（如果不存在）"""
    import pymysql
    
    try:
        # 连接MySQL服务器（不指定数据库）
        connection = pymysql.connect(
            host=settings.MYSQL_HOST,
            port=settings.MYSQL_PORT,
            user=settings.MYSQL_USER,
            password=settings.MYSQL_PASSWORD,
            charset='utf8mb4'
        )
        
        cursor = connection.cursor()
        
        # 检查数据库是否存在
        cursor.execute(f"SHOW DATABASES LIKE '{settings.MYSQL_DB}'")
        result = cursor.fetchone()
        
        if result:
            print(f"Database '{settings.MYSQL_DB}' already exists")
        else:
            # 创建数据库
            cursor.execute(
                f"CREATE DATABASE {settings.MYSQL_DB} "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            print(f"Database '{settings.MYSQL_DB}' created successfully")
        
        cursor.close()
        connection.close()
        
    except Exception as e:
        print(f"Warning: Failed to check/create database: {e}")
        print("Application will continue, assuming database exists...")


def create_tables():
    """创建数据库表"""
    try:
        print("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully")
    except Exception as e:
        print(f"Failed to create database tables: {e}")
        print("Application will continue without creating tables...")
        # 不抛出异常，让应用继续启动

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Application starting up...")
    
    # 启动时自动检测并创建数据库
    logger.info("Checking and creating database if needed...")
    create_database_if_not_exists()
    
    # 启动时创建数据库表
    create_tables()
    
    # 初始化Nacos（可选）
    nacos_manager = None
    if settings.NACOS_ENABLED:
        nacos_manager = get_nacos_manager()
        app.state.nacos_manager = nacos_manager
        app.state.runtime_config = NacosRuntimeConfig()

        def _handle_nacos_config(raw: str | None, parsed):
            runtime_cfg = NacosRuntimeConfig.from_dict(parsed)
            app.state.runtime_config = runtime_cfg
            app.state.nacos_config = runtime_cfg.raw
            logger.info("Nacos config updated: %s", bool(parsed))

        nacos_manager.add_config_callback(_handle_nacos_config)
        nacos_manager.start()
    else:
        app.state.nacos_manager = None
        app.state.runtime_config = NacosRuntimeConfig()
        app.state.nacos_config = None

    # 初始化枚举数据
    from app.db.session import SessionLocal
    from app.models.asset_models import LifecycleStage, RoomType, DictType, DictItem
    from app.models.asset_models import LifecycleStatusEnum
    import json
    from typing import Optional
    
    db = SessionLocal()
    try:
        # 1. 初始化生命周期阶段数据
        existing_stages = db.query(LifecycleStage).count()
        if existing_stages == 0:
            stages = [
                LifecycleStage(stage_code='RECEIVING', stage_name='到货验收', description='设备到货、验收和入库阶段', sequence_order=1),
                LifecycleStage(stage_code='DEPLOYMENT', stage_name='部署上线', description='设备安装、配置和上线阶段', sequence_order=2),
                LifecycleStage(stage_code='POWER_ON', stage_name='设备上电', description='设备接电、通电阶段', sequence_order=3),
                LifecycleStage(stage_code='PRODUCTION', stage_name='生产运行', description='设备正常运行和维护阶段', sequence_order=4),
                LifecycleStage(stage_code='MAINTENANCE', stage_name='维护保养', description='设备维护、升级和保养阶段', sequence_order=5),
                LifecycleStage(stage_code='MONITORING', stage_name='监控管理', description='设备性能监控和管理阶段', sequence_order=6),
                LifecycleStage(stage_code='RETIREMENT', stage_name='退役处理', description='设备退役和处置准备阶段', sequence_order=7),
                LifecycleStage(stage_code='DISPOSAL', stage_name='资产处置', description='设备最终处置和销毁阶段', sequence_order=8),
            ]
            for stage in stages:
                db.add(stage)
            db.commit()
            print("Lifecycle stages data initialized successfully")
        
        # 2. 初始化房间类型数据
        existing_room_types = db.query(RoomType).count()
        if existing_room_types == 0:
            room_types = [
                RoomType(type_code='hazardous_waste_room', type_name='危废房间', description='存放危险废弃物的专用房间', sequence_order=1),
                RoomType(type_code='functional_room', type_name='功能房间', description='具有特定功能的房间（如配电、空调等）', sequence_order=2),
                RoomType(type_code='warehouse', type_name='仓库', description='存储设备和物料的仓库', sequence_order=3),
                RoomType(type_code='business_room', type_name='业务房间', description='业务系统机房', sequence_order=4),
                RoomType(type_code='transmission_room', type_name='传输房间', description='传输设备机房', sequence_order=5),
                RoomType(type_code='hda_room', type_name='HDA房间', description='HDA设备专用机房', sequence_order=6),
                RoomType(type_code='network_room', type_name='网络房间', description='网络设备机房', sequence_order=7),
                RoomType(type_code='comprehensive_room', type_name='综合房间', description='综合用途机房', sequence_order=8),
            ]
            for room_type in room_types:
                db.add(room_type)
            db.commit()
            print("Room types data initialized successfully")

        # 3. 初始化数据字典（内置枚举）
        def ensure_dict_type(code: str, name: str, description: str = "", order: int = 0):
            t = db.query(DictType).filter(DictType.type_code == code).first()
            if not t:
                t = DictType(
                    type_code=code,
                    type_name=name,
                    description=description,
                    status=1,
                    sequence_order=order,
                    built_in=1
                )
                db.add(t)
                db.commit()
                db.refresh(t)
            return t

        def ensure_dict_item(t: DictType, item_code: str, item_label: str, item_value: str = None, order: int = 0):
            exists = db.query(DictItem).filter(
                DictItem.type_id == t.id,
                DictItem.item_code == item_code
            ).first()
            if not exists:
                it = DictItem(
                    type_id=t.id,
                    item_code=item_code,
                    item_label=item_label,
                    item_value=item_value,
                    status=1,
                    sequence_order=order
                )
                db.add(it)
                db.commit()

        # 3.1 资产管理状态
        asset_status_type = ensure_dict_type(
            code="asset_status",
            name="资产管理状态",
            description="资产的管理状态（对应Asset.asset_status字段）",
            order=10
        )
        asset_status_items = [
            ("active", "在用", None, 1),
            ("inactive", "闲置", None, 2),
            ("maintenance", "维护中", None, 3),
            ("retired", "已退役", None, 4),
            ("disposed", "已处置", None, 5),
        ]
        for code, label, val, order in asset_status_items:
            ensure_dict_item(asset_status_type, code, label, val, order)

        # 3.2 资产生命周期状态
        lifecycle_status_type = ensure_dict_type(
            code="asset_lifecycle_status",
            name="资产生命周期状态",
            description="资产在生命周期中的状态（对应Asset.lifecycle_status字段）",
            order=20
        )
        lifecycle_status_items = [
            ("registered", "已登记", None, 1),
            ("received", "已到货", None, 2),
            ("inspected", "已验收", None, 3),
            ("in_stock", "已入库", None, 4),
            ("racked", "已上架", None, 5),
            ("configured", "已配置", None, 6),
            ("powered_on", "已上电", None, 7),
            ("running", "运行中", None, 8),
            ("powered_off", "已下电", None, 9),
            ("maintenance", "维护中", None, 10),
            ("retired", "已退役", None, 11),
        ]
        for code, label, val, order in lifecycle_status_items:
            ensure_dict_item(lifecycle_status_type, code, label, val, order)

        # 3.3 工单操作类型
        operation_type = ensure_dict_type(
            code="work_order_operation_type",
            name="工单操作类型",
            description="工单支持的各种操作类型（对应WorkOrder.operation_type字段）",
            order=30
        )
        operation_items = [
            ("receiving", "设备到货", None, 1),
            ("racking", "设备上架", None, 2),
            ("configuration", "设备配置", None, 3),
            ("power_management", "电源管理", None, 4),
            ("network_cable", "网线更换", None, 5),
            ("maintenance", "设备维护", None, 6),
        ]
        for code, label, val, order in operation_items:
            ensure_dict_item(operation_type, code, label, val, order)

        # 3.4 工单状态
        work_order_status_type = ensure_dict_type(
            code="work_order_status",
            name="工单状态",
            description="工单的外部状态（对应WorkOrder.work_order_status字段）",
            order=40
        )
        work_order_status_items = [
            ("processing", "进行中", None, 1),
            ("completed", "已完成", None, 2),
            ("failed", "失败", None, 3),
        ]
        for code, label, val, order in work_order_status_items:
            ensure_dict_item(work_order_status_type, code, label, val, order)

        # 3.5 生命周期阶段状态（内部流程状态）
        lifecycle_stage_status_type = ensure_dict_type(
            code="lifecycle_stage_status",
            name="生命周期阶段状态",
            description="生命周期阶段的执行状态（对应AssetLifecycleStatus.status字段）",
            order=50
        )
        lifecycle_stage_status_items = [
            (LifecycleStatusEnum.NOT_STARTED.value, "未开始", None, 1),
            (LifecycleStatusEnum.IN_PROGRESS.value, "进行中", None, 2),
            (LifecycleStatusEnum.COMPLETED.value, "已完成", None, 3),
            (LifecycleStatusEnum.SKIPPED.value, "已跳过", None, 4),
            (LifecycleStatusEnum.FAILED.value, "失败", None, 5),
        ]
        for code, label, val, order in lifecycle_stage_status_items:
            ensure_dict_item(lifecycle_stage_status_type, code, label, val, order)

        # 3.6 资产变更类型
        change_type_dict = ensure_dict_type(
            code="asset_change_type",
            name="资产变更类型",
            description="资产变更记录的类型（对应AssetChangeLog.change_type字段）",
            order=60
        )
        change_type_items = [
            ("create", "创建", None, 1),
            ("update", "更新", None, 2),
            ("move", "移动", None, 3),
            ("status_change", "状态变更", None, 4),
            ("delete", "删除", None, 5),
        ]
        for code, label, val, order in change_type_items:
            ensure_dict_item(change_type_dict, code, label, val, order)

        # 3.7 维护类型
        maintenance_type_dict = ensure_dict_type(
            code="maintenance_type",
            name="维护类型",
            description="设备维护的类型（对应MaintenanceRecord.maintenance_type字段）",
            order=70
        )
        maintenance_type_items = [
            ("preventive", "预防性维护", None, 1),
            ("corrective", "纠正性维护", None, 2),
            ("upgrade", "升级", None, 3),
            ("inspection", "检查", None, 4),
        ]
        for code, label, val, order in maintenance_type_items:
            ensure_dict_item(maintenance_type_dict, code, label, val, order)

        # 3.8 维护状态
        maintenance_status_dict = ensure_dict_type(
            code="maintenance_status",
            name="维护状态",
            description="维护记录的状态（对应MaintenanceRecord.status字段）",
            order=80
        )
        maintenance_status_items = [
            ("scheduled", "已计划", None, 1),
            ("in_progress", "进行中", None, 2),
            ("completed", "已完成", None, 3),
            ("cancelled", "已取消", None, 4),
        ]
        for code, label, val, order in maintenance_status_items:
            ensure_dict_item(maintenance_status_dict, code, label, val, order)

        # 3.9 连接类型
        connection_type_dict = ensure_dict_type(
            code="connection_type",
            name="连接类型",
            description="网络连接的类型（对应NetworkConnection.connection_type字段）",
            order=90
        )
        connection_type_items = [
            ("ethernet", "以太网", None, 1),
            ("fiber", "光纤", None, 2),
            ("console", "控制台", None, 3),
            ("power", "电源", None, 4),
            ("other", "其他", None, 5),
        ]
        for code, label, val, order in connection_type_items:
            ensure_dict_item(connection_type_dict, code, label, val, order)

        # 3.10 机房缩写
        ensure_dict_type(
            code="datacenter_abbreviation",
            name="机房缩写",
            description="机房的简称（对应Room.datacenter_abbreviation字段）",
            order=1
        )

        print("Built-in dictionary types and items initialized successfully")
        
        # 4. 初始化资产分类字典（含层级关系）
        logger.info("Initializing asset category dictionary...")
        dict_type = db.query(DictType).filter(DictType.type_code == "asset_category").first()
        if not dict_type:
            dict_type = DictType(
                type_code="asset_category",
                type_name="资产分类",
                description="资产管理使用的层级分类（整机/配件等）",
                status=1,
                sequence_order=10,
                built_in=1,
            )
            db.add(dict_type)
            db.commit()
            db.refresh(dict_type)
        
        existing_items = {
            item.item_code: item
            for item in db.query(DictItem).filter(DictItem.type_id == dict_type.id).all()
        }
        
        def _build_item_value(level: int, parent: Optional[DictItem]) -> str:
            return json.dumps(
                {
                    "level": level,
                    "parent_code": parent.item_code if parent else None,
                },
                ensure_ascii=False,
            )
        
        def upsert_item(
            code: str,
            label: str,
            level: int,
            sequence: int,
            parent: Optional[DictItem] = None,
        ) -> DictItem:
            item = existing_items.get(code)
            metadata_value = _build_item_value(level, parent)
            remark = (
                f"{level}级分类"
                if parent is None
                else f"{level}级分类，上级: {parent.item_label}"
            )
            if item:
                item.item_label = label
                item.sequence_order = sequence
                item.item_value = metadata_value
                item.remark = remark
                return item
            
            item = DictItem(
                type_id=dict_type.id,
                item_code=code,
                item_label=label,
                sequence_order=sequence,
                status=1,
                item_value=metadata_value,
                remark=remark,
            )
            db.add(item)
            db.flush()
            existing_items[code] = item
            return item
        
        category_tree = [
            {
                "code": "WHOLE_MACHINE",
                "label": "整机",
                "children": [
                    {
                        "code": "NETWORK_DEVICE",
                        "label": "数通设备",
                        "children": [
                            {"code": "NETWORK_SWITCH", "label": "交换机"},
                            {"code": "NETWORK_MAIL_GATEWAY", "label": "邮件网关"},
                            {"code": "NETWORK_ROUTER", "label": "路由器"},
                            {"code": "NETWORK_VOICE_GATEWAY", "label": "语音网关"},
                            {"code": "NETWORK_OTHER", "label": "其他数通设备"},
                            {"code": "NETWORK_LOAD_BALANCER", "label": "负载均衡设备"},
                        ],
                    },
                    {
                        "code": "TRANSMISSION_DEVICE",
                        "label": "传输设备",
                        "children": [
                            {"code": "TRANSMISSION_OTN_MANAGER", "label": "OTN网管服务器"},
                            {"code": "TRANSMISSION_OTN_EFRAME", "label": "OTN电子架"},
                            {"code": "TRANSMISSION_IPRAN", "label": "传输IPRAN设备"},
                            {"code": "TRANSMISSION_MICROWAVE", "label": "传输微波设备"},
                            {"code": "TRANSMISSION_SDH", "label": "传输SDH设备"},
                            {"code": "TRANSMISSION_OTN_PHOTONIC", "label": "OTN光子架"},
                            {"code": "TRANSMISSION_ELECTRO_OPTICAL", "label": "传输光电转换器"},
                            {"code": "TRANSMISSION_PROTOCOL_CONVERTER", "label": "传输协议转换器"},
                            {"code": "TRANSMISSION_PTN", "label": "传输PTN设备"},
                        ],
                    },
                    {
                        "code": "CABINET",
                        "label": "机柜",
                        "children": [
                            {"code": "CABINET_WHOLE", "label": "整机柜"},
                            {"code": "CABINET_ASSEMBLY", "label": "整机柜成品"},
                            {"code": "CABINET_LIQUID_COOLING", "label": "液冷柜"},
                        ],
                    },
                    {
                        "code": "SERVER",
                        "label": "服务器",
                        "children": [
                            {"code": "SERVER_ALIRACK", "label": "AliRack服务器"},
                            {"code": "SERVER_BLADE", "label": "刀片服务器"},
                            {"code": "SERVER_HIGH_DENSITY", "label": "高密机架服务器"},
                            {"code": "SERVER_RACK", "label": "机架服务器"},
                            {"code": "SERVER_NON_STANDARD", "label": "非标服务器"},
                        ],
                    },
                    {
                        "code": "MOC",
                        "label": "MOC",
                        "children": [
                            {"code": "MOC_DEFAULT", "label": "MOC"},
                        ],
                    },
                    {
                        "code": "OTHER_WHOLE",
                        "label": "其他整机",
                        "children": [
                            {"code": "OTHER_STORAGE_SWITCH", "label": "存储交换机"},
                            {"code": "OTHER_STORAGE_ENCLOSURE", "label": "存储盘柜子"},
                            {"code": "OTHER_SMALL_MACHINE", "label": "小型机"},
                            {"code": "OTHER_STORAGE_DEVICE", "label": "存储设备"},
                            {"code": "OTHER_SECURITY_DEVICE", "label": "安全设备"},
                            {"code": "OTHER_POWERSHELL_MACHINE", "label": "PowerShell整机"},
                            {"code": "OTHER_SERVER_CDU", "label": "服务器CDU"},
                        ],
                    },
                    {
                        "code": "FRAME",
                        "label": "框",
                        "children": [
                            {"code": "FRAME_HIGH_DENSITY", "label": "高密机箱"},
                            {"code": "FRAME_JBOD", "label": "Jbod柜"},
                            {"code": "FRAME_BLADE", "label": "刀柜"},
                        ],
                    },
                    {
                        "code": "INTERCONNECT_DEVICE",
                        "label": "互联设备",
                        "children": [
                            {"code": "INTERCONNECT_GENERAL", "label": "互联设备"},
                        ],
                    },
                    {
                        "code": "INVENTORY_WHOLE",
                        "label": "存货整机",
                        "children": [
                            {"code": "INVENTORY_OTHER_WHOLE", "label": "存货其他整机"},
                            {"code": "INVENTORY_SERVER_WHOLE", "label": "存货服务器整机"},
                            {"code": "INVENTORY_NETWORK_DEVICE", "label": "存货网络设备"},
                        ],
                    },
                ],
            },
            {
                "code": "WITH_SN_PARTS",
                "label": "有SN配件",
                "children": [
                    {
                        "code": "WITH_SN_TRANSMISSION_PARTS",
                        "label": "传输配件",
                        "children": [
                            {"code": "WITH_SN_TRANS_OTN_SERVICE_CARD", "label": "OTN业务板卡"},
                            {"code": "WITH_SN_TRANS_OTN_FAN_MODULE", "label": "OTN风扇模块"},
                            {"code": "WITH_SN_TRANS_OTN_OPTICAL_MODULE", "label": "OTN光模块"},
                            {"code": "WITH_SN_TRANS_OTN_POWER_CONVERTER", "label": "OTN电源转换盒"},
                            {"code": "WITH_SN_TRANS_OTN_COMMON_CARD", "label": "OTN公共板卡"},
                            {"code": "WITH_SN_TRANS_ADAPTER_BOARD", "label": "适配板"},
                            {"code": "WITH_SN_TRANS_BUSINESS_CARD_SUB", "label": "业务板（子卡）"},
                            {"code": "WITH_SN_TRANS_ENGINE_BOARD", "label": "引擎板"},
                            {"code": "WITH_SN_TRANS_FAN_MODULE", "label": "风扇模块"},
                        ],
                    },
                    {
                        "code": "WITH_SN_NETWORK_PARTS",
                        "label": "数通配件",
                        "children": [
                            {"code": "WITH_SN_NET_OPTICAL_MODULE", "label": "数通光模块"},
                            {"code": "WITH_SN_NET_BUSINESS_CARD_MAIN", "label": "业务板（母卡）"},
                            {"code": "WITH_SN_NET_POWER_MODULE", "label": "数通电源模块"},
                            {"code": "WITH_SN_NET_BUSINESS_CARD_STANDARD", "label": "业务板（标准）"},
                            {"code": "WITH_SN_NET_SWITCH_FABRIC", "label": "交换网板"},
                            {"code": "WITH_SN_NET_SYSTEM_CONTROL_BOARD", "label": "系统控制板"},
                        ],
                    },
                    {
                        "code": "WITH_SN_SERVER_PARTS",
                        "label": "服务器配件",
                        "children": [
                            {"code": "WITH_SN_SERVER_CABINET", "label": "服务器机柜"},
                            {"code": "WITH_SN_SERVER_GPU", "label": "GPU"},
                            {"code": "WITH_SN_SERVER_CONTROL_BOARD", "label": "控制板"},
                            {"code": "WITH_SN_SERVER_DISK_MODULE", "label": "硬盘模组"},
                            {"code": "WITH_SN_SERVER_OAM_BOARD", "label": "OAM板"},
                            {"code": "WITH_SN_SERVER_SWITCH_BOARD", "label": "交换板"},
                            {"code": "WITH_SN_SERVER_EXPANDER", "label": "Expander"},
                            {"code": "WITH_SN_SERVER_FAN_BOARD", "label": "风扇板"},
                            {"code": "WITH_SN_SERVER_IO_BOARD", "label": "IO板"},
                            {"code": "WITH_SN_SERVER_M2_BACKPLANE", "label": "M.2背板"},
                            {"code": "WITH_SN_SERVER_OTHER_BOARD", "label": "其他板卡"},
                            {"code": "WITH_SN_SERVER_PCBA_MAINBOARD", "label": "PCBA主板"},
                            {"code": "WITH_SN_SERVER_RETIMER_CARD", "label": "Retimer卡"},
                            {"code": "WITH_SN_SERVER_UI_BOARD", "label": "UI板"},
                            {"code": "WITH_SN_SERVER_GPU_BASEBOARD", "label": "GPU底板"},
                            {"code": "WITH_SN_SERVER_POWER_BACKPLANE", "label": "电源背板"},
                            {"code": "WITH_SN_SERVER_PSU", "label": "PSU"},
                            {"code": "WITH_SN_SERVER_QAT", "label": "QAT"},
                            {"code": "WITH_SN_SERVER_RISER_CARD", "label": "Riser卡"},
                            {"code": "WITH_SN_SERVER_ROT", "label": "ROT"},
                            {"code": "WITH_SN_SERVER_SSD", "label": "SSD"},
                            {"code": "WITH_SN_SERVER_PHY_RETIMER_CARD", "label": "Phy-Retimer卡"},
                            {"code": "WITH_SN_SERVER_L6", "label": "L6"},
                            {"code": "WITH_SN_SERVER_PCIE_BOARD", "label": "PCIE board"},
                            {"code": "WITH_SN_SERVER_HBA", "label": "HBA"},
                            {"code": "WITH_SN_SERVER_HDD", "label": "HDD"},
                            {"code": "WITH_SN_SERVER_HSM", "label": "HSM"},
                            {"code": "WITH_SN_SERVER_MEMORY", "label": "内存"},
                            {"code": "WITH_SN_SERVER_NIC", "label": "NIC"},
                            {"code": "WITH_SN_SERVER_OPTICAL_MODULE", "label": "服务器光模块"},
                            {"code": "WITH_SN_SERVER_CPU", "label": "CPU"},
                            {"code": "WITH_SN_SERVER_DISK_BACKPLANE", "label": "硬盘背板"},
                            {"code": "WITH_SN_SERVER_DPU", "label": "DPU"},
                            {"code": "WITH_SN_SERVER_FAN_MODULE", "label": "风扇模组"},
                            {"code": "WITH_SN_SERVER_FPGA", "label": "FPGA"},
                        ],
                    },
                    {
                        "code": "INVENTORY_PARTS",
                        "label": "存货配件",
                        "children": [
                            {"code": "INVENTORY_PART_OTHER", "label": "存货其他配件"},
                            {"code": "INVENTORY_PART_STORAGE_MEDIA", "label": "存货存储介质"},
                            {"code": "INVENTORY_PART_SERVER", "label": "存货服务器配件"},
                            {"code": "INVENTORY_PART_NETWORK", "label": "存货网络配件"},
                        ],
                    },
                ],
            },
        ]
        
        def upsert_tree(nodes, parent=None, level=1):
            for idx, node in enumerate(nodes, start=1):
                item = upsert_item(
                    code=node["code"],
                    label=node["label"],
                    level=level,
                    sequence=idx * 10,
                    parent=parent,
                )
                children = node.get("children")
                if children:
                    upsert_tree(children, parent=item, level=level + 1)
        
        upsert_tree(category_tree)
        db.commit()
        logger.info("Asset category dictionary initialized successfully")
        
    finally:
        db.close()
    
    yield
    
    # 关闭时的清理工作
    print("Application is shutting down...")

    if nacos_manager:
        nacos_manager.stop()
        app.state.nacos_manager = None
        app.state.runtime_config = NacosRuntimeConfig()
        app.state.nacos_config = None

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="IT资产生命周期管理系统 - 提供完整的资产管理解决方案",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,  # 使用ORJSON确保中文UTF-8编码正确
    docs_url=None,
    redoc_url=None,
)

# 全局异常处理器 - 统一响应格式
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.schemas.asset_schemas import ResponseCode


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求参数验证错误，返回统一格式"""
    errors = exc.errors()
    error_messages = []
    for error in errors:
        loc = ".".join(str(x) for x in error.get("loc", []))
        msg = error.get("msg", "")
        error_messages.append(f"{loc}: {msg}")
    
    return ORJSONResponse(
        status_code=200,
        content={
            "code": ResponseCode.PARAM_ERROR,
            "message": f"参数验证失败: {'; '.join(error_messages)}",
            "data": None
        }
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """处理HTTP异常，返回统一格式"""
    code_mapping = {
        400: ResponseCode.PARAM_ERROR,
        404: ResponseCode.NOT_FOUND,
        403: ResponseCode.PERMISSION_DENIED,
        500: ResponseCode.INTERNAL_ERROR,
    }
    code = code_mapping.get(exc.status_code, ResponseCode.INTERNAL_ERROR)
    
    return ORJSONResponse(
        status_code=200,
        content={
            "code": code,
            "message": str(exc.detail),
            "data": None
        }
    )


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add logging middleware
logger.info("Adding logging middleware...")
app.add_middleware(LoggingMiddleware)

# Include API router
logger.info("Including API router...")
app.include_router(api_router, prefix="/api/v1")

@app.get("/")
async def welcome():
    return {
        "message": "Welcome to IT Asset Lifecycle Management System (ALMS)",
        "description": "IT资产生命周期管理系统",
        "docs": "/docs",
        "redoc": "/redoc",
        "version": settings.VERSION,
        "features": [
            "资产全生命周期管理",
            "位置层级管理",
            "成本核算管理",
            "维护记录管理",
            "统计分析报表"
        ]
    }

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "service": "ALMS",
        "version": settings.VERSION
    }


@app.get("/debug/runtime-config")
async def debug_runtime_config(config: NacosRuntimeConfig = Depends(get_runtime_config)):
    """Return current runtime config snapshot (for debugging)."""
    return config.model_dump()


import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 添加图片文件静态服务
from pathlib import Path
picture_dir = Path(settings.PICTURE_DIR)
if picture_dir.exists():
    app.mount("/alms/images", StaticFiles(directory=str(picture_dir)), name="images")
    logger.info(f"Mounted images directory: {picture_dir} -> /alms/images")


@app.get("/docs", include_in_schema=False)
async def local_swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="/static/favicon.png",
    )


@app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()

if __name__ == "__main__":
    import uvicorn
    # 设置当前文件为模块路径
    import sys
    import os
    module_name = os.path.splitext(os.path.basename(__file__))[0]
    uvicorn.run(
        f"{module_name}:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
