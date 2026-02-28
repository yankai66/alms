"""
业务操作类型常量定义
用于日志记录的标准化操作类型
"""


class OperationType:
    """操作类型常量"""
    
    # 资产管理
    ASSET_CREATE = "asset.create"
    ASSET_UPDATE = "asset.update"
    ASSET_DELETE = "asset.delete"
    ASSET_EXPORT = "asset.export"
    ASSET_IMPORT = "asset.import"
    
    # 资产状态
    ASSET_SET_AVAILABLE = "asset.set_available"
    ASSET_SET_UNAVAILABLE = "asset.set_unavailable"
    
    # 设备库存
    DEVICE_INBOUND = "device.inbound"
    DEVICE_OUTBOUND = "device.outbound"
    
    # 设备机架
    DEVICE_RACK_ON = "device.rack_on"
    DEVICE_RACK_OFF = "device.rack_off"
    
    # 设备电源
    DEVICE_POWER_ON = "device.power_on"
    DEVICE_POWER_OFF = "device.power_off"
    
    # 工单管理
    WORK_ORDER_CREATE = "work_order.create"
    WORK_ORDER_PROCESS = "work_order.process"
    WORK_ORDER_EXECUTE = "work_order.execute"
    WORK_ORDER_COMPLETE = "work_order.complete"
    
    # 电源管理工单
    POWER_MANAGEMENT_START = "power_management.start"       # 开始
    POWER_MANAGEMENT_SUBMIT = "power_management.submit"     # 提单
    POWER_MANAGEMENT_EXECUTE = "power_management.execute"   # 执行
    POWER_MANAGEMENT_COMPLETE = "power_management.complete" # 结单
    NETWORK_CABLE_WORK_ORDER_CREATE = "network_cable_work_order.create"
    NETWORK_CABLE_WORK_ORDER_PROCESS = "network_cable_work_order.process"
    MANUAL_USB_INSTALL_CREATE = "manual_usb_install.create"
    MANUAL_USB_INSTALL_PROCESS = "manual_usb_install.process"
    NETWORK_ISSUE_WORK_ORDER_CREATE = "network_issue_work_order.create"
    NETWORK_ISSUE_WORK_ORDER_PROCESS = "network_issue_work_order.process"
    ASSET_ENTRY_EXIT_CREATE = "asset_entry_exit.create"
    GENERIC_WORK_ORDER_CREATE = "generic_work_order.create"
    GENERIC_WORK_ORDER_PROCESS = "generic_work_order.process"
    GENERIC_OPERATION_CREATE = "generic_operation.create"
    GENERIC_OPERATION_PROCESS = "generic_operation.process"
    GENERIC_NON_OPERATION_CREATE = "generic_non_operation.create"
    GENERIC_NON_OPERATION_PROCESS = "generic_non_operation.process"
    GENERIC_ASSET_CREATE = "generic_asset.create"
    GENERIC_ASSET_PROCESS = "generic_asset.process"


OPERATION_CATEGORY_OPTIONS = [
    {
        "label": "服务器",
        "value": "server",
        "children": [
            {
                "label": "设备到货",
                "value": "receiving",
            },
            {
                "label": "设备上架",
                "value": "racking",
            },
            {
                "label": "设备上下电",
                "value": "power_management",
            },
            {
                "label": "设备增配",
                "value": "configuration",
            },
            {
                "label": "服务器网线/光纤更换",
                "value": "network_cable",
            },
            {
                "label": "手工U盘装机",
                "value": "manual_usb_install",
            },
        ],
    },
    {
        "label": "网络",
        "value": "network",
        "children": [
            {
                "label": "网络故障/变更配合单",
                "value": "network_issue_coordination",
            }
        ],
    },
    {
        "label": "其他",
        "value": "others",
        "children": [
            {
                "label": "资产出入门",
                "value": "asset_accounting",
            },
            {
                "label": "操作类工单",
                "value": "generic_operation",
            },
            {
                "label": "非操作类工单",
                "value": "generic_non_operation",
            },
            {
                "label": "资产类工单",
                "value": "generic_asset",
            },
        ],
    },
]


class OperationResult:
    """操作结果常量"""
    SUCCESS = "success"
    FAILED = "failed"
