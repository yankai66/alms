"""
机柜管理模型
"""

from sqlalchemy import Column, Integer, String, Boolean, DECIMAL, Date, ForeignKey, Index, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base


class Cabinet(Base):
    """机柜表"""
    __tablename__ = "cabinets"
    
    id = Column(Integer, primary_key=True, index=True, comment="机柜ID")
    
    # ===== 基础标识信息 =====
    cabinet_number = Column(String(100), unique=True, nullable=False, index=True, comment="机柜编号")
    cabinet_name = Column(String(200), comment="机柜名称")
    
    # ===== 位置信息 =====
    datacenter = Column(String(50), index=True, comment="机房")
    room = Column(String(50), index=True, comment="房间")
    room_number = Column(String(50), comment="房间号")
    
    # ===== 运营商信息 =====
    operator_cabinet_number = Column(String(100), comment="运营商机柜编号")
    
    # ===== 电源信息 =====
    power_type = Column(String(50), comment="电源类型（如：AC/DC/混合）")
    pdu_interface_standard = Column(String(50), comment="PDU接口标准")
    
    # ===== 机柜类型 =====
    cabinet_type = Column(String(50), comment="机柜类型（如：服务器机柜/网络机柜/存储机柜）")
    cabinet_type_detail = Column(String(100), comment="机柜类型明细")
    
    # ===== 物理规格 =====
    width = Column(String(20), comment="宽度（如：600mm）")
    size = Column(String(20), comment="大小/高度（如：42U）")
    
    # ===== 状态信息 =====
    power_status = Column(String(20), comment="上下电状态（power_on/power_off/partial）")
    usage_status = Column(String(50), comment="使用状态（in_use/idle/reserved/maintenance）")
    lifecycle_status = Column(String(50), comment="生命周期状态（与系统生命周期不同）")
    module_construction_status = Column(String(50), comment="模块建设状态")
    
    # ===== 规划信息 =====
    planning_category = Column(String(50), comment="规划大类")
    construction_density = Column(String(50), comment="建设密度")
    
    # ===== 操作记录 =====
    last_power_operation = Column(String(20), comment="最后一次电源操作（power_on/power_off）")
    last_power_operation_date = Column(Date, comment="实际上下电日期")
    last_operation_result = Column(String(50), comment="处理结果（success/failed/partial）")
    last_operation_failure_reason = Column(String(500), comment="失败原因")
    
    # ===== 容量信息 =====
    total_u_count = Column(Integer, comment="总U位数")
    used_u_count = Column(Integer, default=0, comment="已使用U位数")
    available_u_count = Column(Integer, comment="可用U位数")
    
    # ===== 管理信息 =====
    responsible_person = Column(String(100), comment="责任人")
    notes = Column(String(1000), comment="备注")
    created_by = Column(String(100), comment="创建人")
    created_at = Column(TIMESTAMP, server_default=func.now(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # ===== 索引 =====
    __table_args__ = (
        Index('idx_datacenter_room', 'datacenter', 'room'),
        Index('idx_power_status', 'power_status'),
        Index('idx_usage_status', 'usage_status'),
        Index('idx_cabinet_type', 'cabinet_type'),
    )
