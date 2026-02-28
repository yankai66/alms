
from app.services.assetService import assetService


class GenericWorkOrderService:
    
    @staticmethod
    def get_generic_work_order_detail(work_order,items,db):
        
        topology_data=[]
        devices_data = []
        for item in items:
            asset = item.asset
            devices_data.append({
                "serial_number": item.asset_sn,
                "asset_tag": item.asset_tag,
                "asset_name": asset.name if asset else None,
                "item_status": item.status,
                "result": item.result,
                "error_message": item.error_message,
                "operation_data": item.operation_data,
                "executed_at": item.executed_at.isoformat() if item.executed_at else None,
                "executed_by": item.executed_by
            })
            if work_order.operation_type == "generic_asset":
            
                topology = assetService.get_device_topology(
                    sn=item.asset_sn,
                    db=db
                )
                topology_data.append(
                    topology
                )
        
        # 构建响应数据
        response_data = {
            "work_order_number": work_order.work_order_number,
            "batch_id": work_order.batch_id,
            "title": work_order.title,
            "datacenter": work_order.datacenter,
            "priority": work_order.extra.get('priority') if work_order.extra else None,
            "work_order_type": work_order.extra.get('work_order_type') if work_order.extra else None,
            "business_type": work_order.extra.get('business_type') if work_order.extra else None,
            "operation_type": work_order.extra.get('operation_type') if work_order.extra else None,
            "source_order_number": work_order.source_order_number,
            "operation_type_detail": work_order.extra.get('operation_type_detail') if work_order.extra else None,
            "is_business_online": work_order.extra.get('is_business_online') if work_order.extra else None,
            "operation_sub_type": work_order.extra.get('operation_sub_type') if work_order.extra else None,
            "estimated_operation_time": work_order.extra.get('estimated_operation_time') if work_order.extra else None,
            "sop": work_order.extra.get('sop') if work_order.extra else None,
            "execution_location": work_order.extra.get('execution_location') if work_order.extra else None,
            "precautions": work_order.extra.get('precautions') if work_order.extra else None,
            "service_content": work_order.extra.get('service_content') if work_order.extra else None,
            "assignee": work_order.assignee,
            "status": work_order.status,
            "work_order_status": work_order.work_order_status,
            "remark": work_order.remark,  # 创建时的备注
            "processing_result": work_order.extra.get('processing_result') if work_order.extra else None,  # 处理结果
            "failure_reason": work_order.extra.get('failure_reason') if work_order.extra else None,  # 失败原因
            "accept_remark": work_order.extra.get('accept_remark') if work_order.extra else None,  # 接单备注
            "close_remark": work_order.description if work_order.status == 'completed' else None,  # 结单备注
            "creator": work_order.creator,
            "operator": work_order.operator,  # 处理人
            "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
            "completed_time": work_order.completed_time.isoformat() if work_order.completed_time else None,
            "close_time": work_order.close_time.isoformat() if work_order.close_time else None,
            "devices": devices_data,
            "device_count": len(devices_data),
            "topology": topology_data if len(topology_data) > 0 else None
        }

        return response_data