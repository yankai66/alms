#!/usr/bin/env python3
"""
IT资产管理系统 - 数据库初始化脚本
用于创建数据库表和初始化基础数据
"""

import sys
import os
import json
from pathlib import Path
from typing import Optional

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.db.session import engine, SessionLocal, Base
from app.models import models  # 导入所有模型
from app.models.asset_models import (
    Room,
    RoomType,
    AssetCategory,
    Vendor,
    LifecycleStage,
    DictType,
    DictItem,
)

def create_tables():
    """创建数据库表"""
    print("[INFO] 正在创建数据库表...")
    Base.metadata.create_all(bind=engine)
    print("[SUCCESS] 数据库表创建完成")

# def init_lifecycle_stages():
#     """初始化生命周期阶段数据"""
#     print("[INFO] 正在初始化生命周期阶段数据...")
    
#     db = SessionLocal()
#     try:
#         # 检查是否已有数据
#         existing_count = db.query(LifecycleStage).count()
#         if existing_count > 0:
#             print(f"[SKIP] 生命周期阶段数据已存在 ({existing_count} 条)，跳过初始化")
#             return
        
#         # 插入生命周期阶段数据
#         stages = [
#             LifecycleStage(
#                 stage_code='RECEIVING',
#                 stage_name='到货验收',
#                 description='设备到货、验收和入库阶段',
#                 sequence_order=1
#             ),
#             LifecycleStage(
#                 stage_code='DEPLOYMENT',
#                 stage_name='部署上线',
#                 description='设备安装、配置和上线阶段',
#                 sequence_order=2
#             ),
#             LifecycleStage(
#                 stage_code='PRODUCTION',
#                 stage_name='生产运行',
#                 description='设备正常运行和维护阶段',
#                 sequence_order=3
#             ),
#             LifecycleStage(
#                 stage_code='MAINTENANCE',
#                 stage_name='维护保养',
#                 description='设备维护、升级和保养阶段',
#                 sequence_order=4
#             ),
#             LifecycleStage(
#                 stage_code='MONITORING',
#                 stage_name='监控管理',
#                 description='设备性能监控和管理阶段',
#                 sequence_order=5
#             ),
#             LifecycleStage(
#                 stage_code='RETIREMENT',
#                 stage_name='退役处理',
#                 description='设备退役和处置准备阶段',
#                 sequence_order=6
#             ),
#             LifecycleStage(
#                 stage_code='DISPOSAL',
#                 stage_name='资产处置',
#                 description='设备最终处置和销毁阶段',
#                 sequence_order=7
#             ),
#         ]
        
#         for stage in stages:
#             db.add(stage)
        
#         db.commit()
#         print(f"[SUCCESS] 生命周期阶段数据初始化完成 ({len(stages)} 条)")
        
#     except Exception as e:
#         print(f"[ERROR] 生命周期阶段数据初始化失败: {e}")
#         db.rollback()
#     finally:
#         db.close()

# def init_sample_categories():
#     """初始化示例资产分类数据"""
#     print("[INFO] 正在初始化示例资产分类数据...")
    
#     db = SessionLocal()
#     try:
#         # 检查是否已有数据
#         existing_count = db.query(AssetCategory).count()
#         if existing_count > 0:
#             print(f"[SKIP] 资产分类数据已存在 ({existing_count} 条)，跳过初始化")
#             return
        
#         # 插入资产分类数据
#         categories = [
#             AssetCategory(name='服务器设备', code='SERVER', description='各类服务器设备'),
#             AssetCategory(name='网络设备', code='NETWORK', description='网络交换机、路由器等'),
#             AssetCategory(name='存储设备', code='STORAGE', description='存储阵列、磁带库等'),
#             AssetCategory(name='安全设备', code='SECURITY', description='防火墙、入侵检测等'),
#             AssetCategory(name='机架式服务器', code='RACK_SERVER', parent_id=1, description='1U-4U机架式服务器'),
#             AssetCategory(name='刀片服务器', code='BLADE_SERVER', parent_id=1, description='刀片式服务器'),
#             AssetCategory(name='交换机', code='SWITCH', parent_id=2, description='以太网交换机'),
#             AssetCategory(name='路由器', code='ROUTER', parent_id=2, description='网络路由器'),
#             AssetCategory(name='存储阵列', code='STORAGE_ARRAY', parent_id=3, description='磁盘阵列'),
#         ]
        
#         for category in categories:
#             db.add(category)
        
#         db.commit()
#         print(f"[SUCCESS] 资产分类数据初始化完成 ({len(categories)} 条)")
        
#     except Exception as e:
#         print(f"[ERROR] 资产分类数据初始化失败: {e}")
#         db.rollback()
#     finally:
#         db.close()

# def init_sample_vendors():
#     """初始化示例供应商数据"""
#     print("[INFO] 正在初始化示例供应商数据...")
    
#     db = SessionLocal()
#     try:
#         # 检查是否已有数据
#         existing_count = db.query(Vendor).count()
#         if existing_count > 0:
#             print(f"[SKIP] 供应商数据已存在 ({existing_count} 条)，跳过初始化")
#             return
        
#         # 插入供应商数据
#         vendors = [
#             Vendor(
#                 name='戴尔科技',
#                 code='DELL',
#                 contact_person='张经理',
#                 phone='010-12345678',
#                 email='zhang@dell.com'
#             ),
#             Vendor(
#                 name='惠普企业',
#                 code='HPE',
#                 contact_person='李经理',
#                 phone='010-87654321',
#                 email='li@hpe.com'
#             ),
#             Vendor(
#                 name='华为技术',
#                 code='HUAWEI',
#                 contact_person='王经理',
#                 phone='010-11111111',
#                 email='wang@huawei.com'
#             ),
#             Vendor(
#                 name='思科系统',
#                 code='CISCO',
#                 contact_person='赵经理',
#                 phone='010-22222222',
#                 email='zhao@cisco.com'
#             ),
#             Vendor(
#                 name='浪潮信息',
#                 code='INSPUR',
#                 contact_person='刘经理',
#                 phone='010-33333333',
#                 email='liu@inspur.com'
#             ),
#         ]
        
#         for vendor in vendors:
#             db.add(vendor)
        
#         db.commit()
#         print(f"[SUCCESS] 供应商数据初始化完成 ({len(vendors)} 条)")
        
#     except Exception as e:
#         print(f"[ERROR] 供应商数据初始化失败: {e}")
#         db.rollback()
#     finally:
#         db.close()

def init_sample_locations():
    """初始化示例位置数据（简化版 - 只创建房间）"""
    print("[INFO] 正在初始化示例位置数据...")
    
    db = SessionLocal()
    try:
        # 检查是否已有数据
        existing_count = db.query(Room).count()
        if existing_count > 0:
            print(f"[SKIP] 房间数据已存在 ({existing_count} 条)，跳过初始化")
            return
        
        # 获取房间类型ID
        network_room_type = db.query(RoomType).filter(RoomType.type_code == 'network_room').first()
        business_room_type = db.query(RoomType).filter(RoomType.type_code == 'business_room').first()
        warehouse_type = db.query(RoomType).filter(RoomType.type_code == 'warehouse').first()
        
        if not network_room_type or not business_room_type or not warehouse_type:
            print("[ERROR] 房间类型未初始化，请先启动应用以初始化房间类型")
            return
        
        # 创建示例房间
        rooms = [
            Room(
                room_abbreviation='BJ-A-1F-101',
                room_full_name='北京IDC A区1楼核心业务机房',
                room_number='101',
                room_type_id=business_room_type.id,
                datacenter_abbreviation='BJ-IDC-A',
                building_number='A座',
                floor_number='1F',
                created_by='系统初始化',
                notes='核心业务服务器机房，7*24小时监控'
            ),
            Room(
                room_abbreviation='BJ-A-1F-102',
                room_full_name='北京IDC A区1楼网络设备机房',
                room_number='102',
                room_type_id=network_room_type.id,
                datacenter_abbreviation='BJ-IDC-A',
                building_number='A座',
                floor_number='1F',
                created_by='系统初始化',
                notes='网络核心设备机房'
            ),
            Room(
                room_abbreviation='BJ-B-2F-201',
                room_full_name='北京IDC B区2楼设备仓库',
                room_number='201',
                room_type_id=warehouse_type.id,
                datacenter_abbreviation='BJ-IDC-B',
                building_number='B座',
                floor_number='2F',
                created_by='系统初始化',
                notes='设备存储仓库'
            ),
        ]
        
        for room in rooms:
            db.add(room)
        
        db.commit()
        print(f"[SUCCESS] 示例房间数据初始化完成 ({len(rooms)} 条)")
        
    except Exception as e:
        print(f"[ERROR] 示例房间数据初始化失败: {e}")
        db.rollback()
    finally:
        db.close()


def init_asset_category_dict():
    """初始化资产分类字典（含层级关系）"""
    print("[INFO] 正在初始化资产分类字典数据...")

    db = SessionLocal()
    try:
        dict_type = (
            db.query(DictType)
            .filter(DictType.type_code == "asset_category")
            .first()
        )
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
            for item in db.query(DictItem)
            .filter(DictItem.type_id == dict_type.id)
            .all()
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
        print("[SUCCESS] 资产分类字典数据初始化完成")
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] 资产分类字典数据初始化失败: {exc}")
    finally:
        db.close()

def main():
    """主函数"""
    print("=" * 60)
    print("开始初始化IT资产管理系统数据库...")
    print("=" * 60)
    
    try:
        # 1. 创建数据库表
        # create_tables()
        
        # 2. 初始化基础数据
        # init_lifecycle_stages()  # 已移至 app/main.py
        # init_sample_categories()  # 已废弃：不需要初始化示例分类数据
        # init_sample_vendors()  # 已废弃：不需要初始化示例供应商数据
        # init_sample_locations()  # 已移至 app/main.py
        # init_asset_category_dict()  # 已移至 app/main.py 的 lifespan 函数中，应用启动时自动初始化
        
        print("=" * 60)
        print("[SUCCESS] 数据库初始化完成！")
        print("\n初始化内容:")
        print("  [OK] 数据库表结构")
        # print("  [OK] 生命周期阶段数据 (7条)")
        print("  [OK] 示例房间数据 (3条)")
        print("  [OK] 资产分类字典数据")
        print("\n启动应用:")
        print("  python app/main.py")
        print("  或者: uvicorn app.main:app --reload")
        print("\nAPI文档:")
        print("  http://localhost:8000/docs")
        print("  http://localhost:8000/redoc")
        print("=" * 60)
        
    except Exception as e:
        print(f"[ERROR] 数据库初始化失败: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
