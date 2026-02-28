"""
Elasticsearch服务
用于查询业务日志
"""

import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

load_dotenv()


class ElasticsearchService:
    """Elasticsearch查询服务"""
    
    def __init__(self):
        """初始化ES客户端"""
        self.host = os.getenv("ELASTICSEARCH_HOST", "localhost")
        self.port = int(os.getenv("ELASTICSEARCH_PORT", "9200"))
        self.index = os.getenv("ELASTICSEARCH_INDEX", "alms-logs-*")
        
        # 读取认证配置
        use_ssl = os.getenv("ELASTICSEARCH_USE_SSL", "false").lower() == "true"
        username = os.getenv("ELASTICSEARCH_USERNAME")
        password = os.getenv("ELASTICSEARCH_PASSWORD")
        api_key = os.getenv("ELASTICSEARCH_API_KEY")
        
        # 构建URL
        scheme = "https" if use_ssl else "http"
        es_url = f"{scheme}://{self.host}:{self.port}"
        
        # 创建ES客户端
        try:
            # 优先使用API Key认证
            if api_key:
                self.client = Elasticsearch(
                    [es_url],
                    api_key=api_key,
                    verify_certs=False,  # 生产环境建议设为True
                    request_timeout=30,
                    max_retries=2,
                    retry_on_timeout=True
                )
                print(f"Elasticsearch client initialized with API Key: {es_url}")
            # 其次使用用户名密码
            elif username and password:
                self.client = Elasticsearch(
                    [es_url],
                    basic_auth=(username, password),
                    verify_certs=False,
                    request_timeout=30,
                    max_retries=2,
                    retry_on_timeout=True
                )
                print(f"Elasticsearch client initialized with basic auth: {es_url}")
            # 无认证
            else:
                self.client = Elasticsearch(
                    [es_url],
                    verify_certs=False,
                    request_timeout=30,
                    max_retries=2,
                    retry_on_timeout=True
                )
                print(f"Elasticsearch client initialized without auth: {es_url}")
        except Exception as e:
            print(f"Warning: Failed to initialize Elasticsearch client: {e}")
            self.client = None
    
    def get_device_lifecycle(
        self,
        serial_number: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        size: int = 100
    ) -> Dict[str, Any]:
        """
        获取设备生命周期日志
        
        Args:
            serial_number: 设备序列号
            start_time: 开始时间 (ISO格式，可选)
            end_time: 结束时间 (ISO格式，可选)
            size: 返回记录数量限制
        
        Returns:
            Dict: 包含状态码和数据的字典
            {
                "code": int,  # 状态码
                "message": str,  # 状态消息
                "data": {       # 响应数据
                    "serial_number": str,
                    "total": int,
                    "logs": List[Dict]
                }
            }
        """
        try:
            if not serial_number:
                return {
                    "code": 400,
                    "message": "设备序列号不能为空",
                    "data": None
                }
                
            # 构建查询条件
            must_conditions = [
                {"term": {"operationObject.keyword": serial_number}},
                {"term": {"logType.keyword": "business"}}
            ]
            
            # 添加时间范围过滤
            if start_time or end_time:
                time_range = {}
                if start_time:
                    time_range["gte"] = start_time
                if end_time:
                    time_range["lte"] = end_time
                must_conditions.append({
                    "range": {"operationTime": time_range}
                })
            
            # ES查询DSL
            query = {
                "query": {
                    "bool": {
                        "must": must_conditions
                    }
                },
                "sort": [
                    {"operationTime": {"order": "asc"}}
                ],
                "size": size
            }
            
            if self.client is None:
                return {
                    "code": 500,
                    "message": "Elasticsearch 客户端未初始化",
                    "data": None
                }
            
            # 执行查询
            response = self.client.search(
                index=self.index,
                body=query
            )
            
            # 提取日志记录
            hits = response.get("hits", {}).get("hits", [])
            total = response.get("hits", {}).get("total", {}).get("value", 0)
            logs = []
            
            for hit in hits:
                source = hit.get("_source", {})
                logs.append({
                    "operationTime": source.get("operationTime"),
                    "operationType": source.get("operationType"),
                    "operationObject": source.get("operationObject"),
                    "operator": source.get("operator"),
                    "result": source.get("result"),
                    "businessType": source.get("businessType"),
                    "source": source.get("source"),
                    "operationDetail": source.get("operationDetail"),
                    "remark": source.get("remark"),
                })
            
            # 返回成功响应
            return {
                "code": 200,  # 成功状态码
                "message": "查询成功",
                "data": {
                    "serial_number": serial_number,
                    "total": total,
                    "logs": logs
                }
            }
            
        except Exception as e:
            # 记录错误日志
            error_msg = f"查询设备生命周期失败: {str(e)}"
            print(error_msg)  # 实际项目中应该使用日志记录
            
            return {
                "code": 500,  # 服务器内部错误
                "message": error_msg,
                "data": None
            }
    
    def get_operation_statistics(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取操作统计信息
        
        Args:
            start_time: 开始时间 (ISO格式，可选)
            end_time: 结束时间 (ISO格式，可选)
        
        Returns:
            操作统计信息
        """
        # 构建时间范围过滤
        must_conditions = [{"term": {"logType.keyword": "business"}}]
        
        if start_time or end_time:
            time_range = {}
            if start_time:
                time_range["gte"] = start_time
            if end_time:
                time_range["lte"] = end_time
            must_conditions.append({
                "range": {"operationTime": time_range}
            })
        
        # ES聚合查询
        query = {
            "query": {
                "bool": {
                    "must": must_conditions
                }
            },
            "size": 0,
            "aggs": {
                "by_operation_type": {
                    "terms": {
                        "field": "operationType.keyword",
                        "size": 50
                    }
                },
                "by_result": {
                    "terms": {
                        "field": "result.keyword"
                    }
                },
                "by_operator": {
                    "terms": {
                        "field": "operator.keyword",
                        "size": 20
                    }
                }
            }
        }
        
        try:
            response = self.client.search(
                index=self.index,
                body=query
            )
            
            aggs = response.get("aggregations", {})
            
            return {
                "total": response.get("hits", {}).get("total", {}).get("value", 0),
                "by_operation_type": [
                    {"operation": bucket["key"], "count": bucket["doc_count"]}
                    for bucket in aggs.get("by_operation_type", {}).get("buckets", [])
                ],
                "by_result": [
                    {"result": bucket["key"], "count": bucket["doc_count"]}
                    for bucket in aggs.get("by_result", {}).get("buckets", [])
                ],
                "by_operator": [
                    {"operator": bucket["key"], "count": bucket["doc_count"]}
                    for bucket in aggs.get("by_operator", {}).get("buckets", [])
                ]
            }
            
        except Exception as e:
            raise Exception(f"Failed to query Elasticsearch: {str(e)}")
    
    def check_connection(self) -> bool:
        """检查ES连接状态"""
        try:
            return self.client.ping()
        except Exception:
            return False


# 全局ES服务实例
_es_service = None


def get_elasticsearch_service() -> ElasticsearchService:
    """获取ES服务实例"""
    global _es_service
    if _es_service is None:
        _es_service = ElasticsearchService()
    return _es_service
