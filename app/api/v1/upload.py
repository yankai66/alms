"""
文件上传API
提供图片/附件上传、预览、缩略图、删除功能

配置说明：
- PICTURE_DIR: 图片存储目录，默认 /opt/aiot/images
- PICTURE_HTTP: 图片访问URL前缀，默认 https://download.sihua.tech/alms/images
- MAX_UPLOAD_SIZE: 最大上传大小，默认 10MB
- ALLOWED_EXTENSIONS: 允许的文件扩展名，默认 jpg, jpeg, png, gif, bmp, webp
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Path as PathParam
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse

from app.core.config import settings
from app.schemas.asset_schemas import ApiResponse, ResponseCode

router = APIRouter()


def get_file_extension(filename: str) -> str:
    """获取文件扩展名（小写）"""
    if '.' in filename:
        return filename.rsplit('.', 1)[1].lower()
    return ''


def generate_filename(original_filename: str, prefix: str = "") -> str:
    """
    生成唯一文件名
    格式: {prefix}_{日期}_{uuid}.{扩展名}
    """
    ext = get_file_extension(original_filename)
    date_str = datetime.now().strftime("%Y%m%d")
    unique_id = uuid.uuid4().hex[:8]
    
    if prefix:
        return f"{prefix}_{date_str}_{unique_id}.{ext}"
    return f"{date_str}_{unique_id}.{ext}"


def ensure_upload_dir(subdir: str = "") -> Path:
    """确保上传目录存在"""
    base_dir = Path(settings.PICTURE_DIR)
    if subdir:
        upload_dir = base_dir / subdir
    else:
        upload_dir = base_dir
    
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


@router.post(
    "/image",
    summary="上传单张图片",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "上传成功",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "上传成功示例",
                            "value": {
                                "code": 0,
                                "message": "上传成功",
                                "data": {
                                    "filename": "power_on_20251211_a1b2c3d4.jpg",
                                    "url": "https://download.sihua.tech/alms/images/work_order/power_on_20251211_a1b2c3d4.jpg",
                                    "preview_url": "/api/v1/upload/preview/work_order/power_on_20251211_a1b2c3d4.jpg",
                                    "thumbnail_url": "/api/v1/upload/thumbnail/work_order/power_on_20251211_a1b2c3d4.jpg",
                                    "size": 102400,
                                    "content_type": "image/jpeg"
                                }
                            }
                        },
                        "invalid_type": {
                            "summary": "文件类型不支持",
                            "value": {
                                "code": 400,
                                "message": "不支持的文件类型: pdf，支持的类型: jpg, jpeg, png, gif, bmp, webp",
                                "data": None
                            }
                        },
                        "file_too_large": {
                            "summary": "文件过大",
                            "value": {
                                "code": 400,
                                "message": "文件过大，最大允许 10.0MB",
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def upload_image(
    file: UploadFile = File(..., description="图片文件（支持jpg/jpeg/png/gif/bmp/webp，最大10MB）"),
    category: str = Query("work_order", description="分类目录，用于组织文件存储。可选值：work_order（工单）、asset（资产）、cabinet（机柜）、other（其他）"),
    prefix: str = Query("", description="文件名前缀，便于识别文件用途。如：power_on（上电）、power_off（下电）、receiving（到货）")
):
    """
    上传单张图片
    
    ## 功能说明
    上传图片到服务器，返回可访问的URL。支持CDN访问和本地预览两种方式。
    
    ## 请求方式
    - Content-Type: multipart/form-data
    
    ## 参数说明
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | file | File | 是 | 图片文件 |
    | category | string | 否 | 分类目录，默认work_order |
    | prefix | string | 否 | 文件名前缀 |
    
    ## 支持的图片格式
    - jpg, jpeg, png, gif, bmp, webp
    
    ## 文件大小限制
    - 最大 10MB（可通过MAX_UPLOAD_SIZE配置修改）
    
    ## 返回字段说明
    | 字段 | 类型 | 说明 |
    |------|------|------|
    | filename | string | 保存的文件名（唯一） |
    | url | string | CDN访问URL（生产环境使用） |
    | preview_url | string | 本地预览URL（内网/调试使用） |
    | thumbnail_url | string | 缩略图URL |
    | size | int | 文件大小（字节） |
    | content_type | string | 文件MIME类型 |
    
    ## 使用场景
    1. 电源管理工单 - 上电/下电照片
    2. 设备到货工单 - 设备照片
    3. 资产管理 - 设备照片
    4. 机柜管理 - 机柜照片
    
    ## curl示例
    ```bash
    curl -X POST "http://localhost:8000/api/v1/upload/image?category=work_order&prefix=power_on" \\
      -H "Content-Type: multipart/form-data" \\
      -F "file=@/path/to/photo.jpg"
    ```
    
    ## 前端示例（JavaScript）
    ```javascript
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    
    const response = await fetch('/api/v1/upload/image?category=work_order&prefix=power_on', {
        method: 'POST',
        body: formData
    });
    const result = await response.json();
    console.log(result.data.url);  // CDN URL
    ```
    """
    try:
        # 1. 验证文件扩展名
        ext = get_file_extension(file.filename)
        if ext not in settings.ALLOWED_EXTENSIONS:
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message=f"不支持的文件类型: {ext}，支持的类型: {', '.join(settings.ALLOWED_EXTENSIONS)}",
                data=None
            )
        
        # 2. 读取文件内容
        content = await file.read()
        
        # 3. 验证文件大小
        if len(content) > settings.MAX_UPLOAD_SIZE:
            max_size_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message=f"文件过大，最大允许 {max_size_mb}MB",
                data=None
            )
        
        # 4. 生成文件名和路径
        filename = generate_filename(file.filename, prefix)
        upload_dir = ensure_upload_dir(category)
        file_path = upload_dir / filename
        
        # 5. 保存文件
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 6. 生成访问URL
        url = f"{settings.PICTURE_HTTP.rstrip('/')}/{category}/{filename}"
        preview_url = f"/api/v1/upload/preview/{category}/{filename}"
        thumbnail_url = f"/api/v1/upload/thumbnail/{category}/{filename}"
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="上传成功",
            data={
                "filename": filename,
                "url": url,
                "preview_url": preview_url,
                "thumbnail_url": thumbnail_url,
                "size": len(content),
                "content_type": file.content_type
            }
        )
        
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"上传失败: {str(e)}",
            data=None
        )



@router.post(
    "/images",
    summary="批量上传图片",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "上传完成",
            "content": {
                "application/json": {
                    "examples": {
                        "all_success": {
                            "summary": "全部成功",
                            "value": {
                                "code": 0,
                                "message": "上传完成，成功 3 张，失败 0 张",
                                "data": {
                                    "total": 3,
                                    "success_count": 3,
                                    "failed_count": 0,
                                    "files": [
                                        {
                                            "original_name": "photo1.jpg",
                                            "filename": "power_on_20251211_a1b2c3d4.jpg",
                                            "url": "https://download.sihua.tech/alms/images/work_order/power_on_20251211_a1b2c3d4.jpg",
                                            "preview_url": "/api/v1/upload/preview/work_order/power_on_20251211_a1b2c3d4.jpg",
                                            "size": 102400,
                                            "success": True
                                        },
                                        {
                                            "original_name": "photo2.jpg",
                                            "filename": "power_on_20251211_b2c3d4e5.jpg",
                                            "url": "https://download.sihua.tech/alms/images/work_order/power_on_20251211_b2c3d4e5.jpg",
                                            "preview_url": "/api/v1/upload/preview/work_order/power_on_20251211_b2c3d4e5.jpg",
                                            "size": 98765,
                                            "success": True
                                        }
                                    ],
                                    "urls": [
                                        "https://download.sihua.tech/alms/images/work_order/power_on_20251211_a1b2c3d4.jpg",
                                        "https://download.sihua.tech/alms/images/work_order/power_on_20251211_b2c3d4e5.jpg"
                                    ]
                                }
                            }
                        },
                        "partial_success": {
                            "summary": "部分成功",
                            "value": {
                                "code": 0,
                                "message": "上传完成，成功 2 张，失败 1 张",
                                "data": {
                                    "total": 3,
                                    "success_count": 2,
                                    "failed_count": 1,
                                    "files": [
                                        {
                                            "original_name": "photo1.jpg",
                                            "filename": "power_on_20251211_a1b2c3d4.jpg",
                                            "url": "https://download.sihua.tech/alms/images/work_order/power_on_20251211_a1b2c3d4.jpg",
                                            "size": 102400,
                                            "success": True
                                        },
                                        {
                                            "original_name": "document.pdf",
                                            "success": False,
                                            "error": "不支持的文件类型: pdf"
                                        }
                                    ],
                                    "urls": [
                                        "https://download.sihua.tech/alms/images/work_order/power_on_20251211_a1b2c3d4.jpg"
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }
    }
)
async def upload_images(
    files: List[UploadFile] = File(..., description="图片文件列表（最多10张，每张最大10MB）"),
    category: str = Query("work_order", description="分类目录：work_order/asset/cabinet/other"),
    prefix: str = Query("", description="文件名前缀：power_on/power_off/receiving等")
):
    """
    批量上传图片
    
    ## 功能说明
    一次上传多张图片，返回所有图片的URL列表。支持部分成功场景。
    
    ## 请求方式
    - Content-Type: multipart/form-data
    
    ## 参数说明
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | files | File[] | 是 | 图片文件列表，最多10张 |
    | category | string | 否 | 分类目录，默认work_order |
    | prefix | string | 否 | 文件名前缀 |
    
    ## 返回字段说明
    | 字段 | 类型 | 说明 |
    |------|------|------|
    | total | int | 总文件数 |
    | success_count | int | 成功数量 |
    | failed_count | int | 失败数量 |
    | files | array | 每个文件的详细信息 |
    | urls | array | 成功上传的URL列表（便于直接使用） |
    
    ## 使用场景
    - 工单创建时一次上传多张附件图片
    - 设备到货时上传多张设备照片
    
    ## curl示例
    ```bash
    curl -X POST "http://localhost:8000/api/v1/upload/images?category=work_order&prefix=power_on" \\
      -H "Content-Type: multipart/form-data" \\
      -F "files=@photo1.jpg" \\
      -F "files=@photo2.jpg" \\
      -F "files=@photo3.jpg"
    ```
    
    ## 前端示例（JavaScript）
    ```javascript
    const formData = new FormData();
    for (const file of fileInput.files) {
        formData.append('files', file);
    }
    
    const response = await fetch('/api/v1/upload/images?category=work_order', {
        method: 'POST',
        body: formData
    });
    const result = await response.json();
    console.log(result.data.urls);  // URL数组，可直接用于工单attachments字段
    ```
    """
    try:
        # 限制最多10张
        if len(files) > 10:
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message="一次最多上传10张图片",
                data=None
            )
        
        results = []
        urls = []
        success_count = 0
        failed_count = 0
        
        for file in files:
            try:
                # 验证扩展名
                ext = get_file_extension(file.filename)
                if ext not in settings.ALLOWED_EXTENSIONS:
                    results.append({
                        "original_name": file.filename,
                        "success": False,
                        "error": f"不支持的文件类型: {ext}"
                    })
                    failed_count += 1
                    continue
                
                # 读取内容
                content = await file.read()
                
                # 验证大小
                if len(content) > settings.MAX_UPLOAD_SIZE:
                    results.append({
                        "original_name": file.filename,
                        "success": False,
                        "error": "文件过大"
                    })
                    failed_count += 1
                    continue
                
                # 保存文件
                filename = generate_filename(file.filename, prefix)
                upload_dir = ensure_upload_dir(category)
                file_path = upload_dir / filename
                
                with open(file_path, "wb") as f:
                    f.write(content)
                
                url = f"{settings.PICTURE_HTTP.rstrip('/')}/{category}/{filename}"
                preview_url = f"/api/v1/upload/preview/{category}/{filename}"
                
                results.append({
                    "original_name": file.filename,
                    "filename": filename,
                    "url": url,
                    "preview_url": preview_url,
                    "size": len(content),
                    "success": True
                })
                urls.append(url)
                success_count += 1
                
            except Exception as e:
                results.append({
                    "original_name": file.filename,
                    "success": False,
                    "error": str(e)
                })
                failed_count += 1
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message=f"上传完成，成功 {success_count} 张，失败 {failed_count} 张",
            data={
                "total": len(files),
                "success_count": success_count,
                "failed_count": failed_count,
                "files": results,
                "urls": urls
            }
        )
        
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"上传失败: {str(e)}",
            data=None
        )



@router.get(
    "/preview/{category}/{filename}",
    summary="预览图片（原图）",
    responses={
        200: {
            "description": "图片文件流",
            "content": {
                "image/jpeg": {},
                "image/png": {},
                "image/gif": {},
                "image/webp": {},
                "image/bmp": {}
            }
        },
        404: {
            "description": "图片不存在",
            "content": {
                "application/json": {
                    "example": {"detail": "图片不存在"}
                }
            }
        }
    }
)
async def preview_image(
    category: str = PathParam(..., description="分类目录，如: work_order, asset, cabinet", example="work_order"),
    filename: str = PathParam(..., description="文件名（上传时返回的filename）", example="power_on_20251211_a1b2c3d4.jpg")
):
    """
    预览图片（原图）
    
    ## 功能说明
    通过本地服务预览图片原图，适用于：
    - 内网环境无法访问CDN
    - 开发调试阶段
    - 需要通过API网关访问图片
    
    ## 路径参数
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | category | string | 是 | 分类目录 |
    | filename | string | 是 | 文件名 |
    
    ## 返回
    - 直接返回图片文件流（二进制）
    - Content-Type 根据图片类型自动设置
    
    ## 使用示例
    ```
    GET /api/v1/upload/preview/work_order/power_on_20251211_a1b2c3d4.jpg
    ```
    
    ## 前端使用
    ```html
    <img src="/api/v1/upload/preview/work_order/power_on_20251211_a1b2c3d4.jpg" />
    ```
    
    ## 两种访问方式对比
    | 方式 | URL | 适用场景 |
    |------|-----|---------|
    | CDN | https://download.sihua.tech/alms/images/... | 生产环境 |
    | 本地预览 | /api/v1/upload/preview/... | 内网/调试 |
    """
    file_path = Path(settings.PICTURE_DIR) / category / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    
    # 获取MIME类型
    ext = get_file_extension(filename)
    mime_types = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "webp": "image/webp"
    }
    media_type = mime_types.get(ext, "application/octet-stream")
    
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename
    )


@router.get(
    "/thumbnail/{category}/{filename}",
    summary="获取缩略图",
    responses={
        200: {
            "description": "缩略图文件流",
            "content": {
                "image/jpeg": {},
                "image/png": {},
                "image/gif": {},
                "image/webp": {}
            }
        },
        404: {
            "description": "图片不存在",
            "content": {
                "application/json": {
                    "example": {"detail": "图片不存在"}
                }
            }
        }
    }
)
async def get_thumbnail(
    category: str = PathParam(..., description="分类目录", example="work_order"),
    filename: str = PathParam(..., description="文件名", example="power_on_20251211_a1b2c3d4.jpg"),
    width: int = Query(200, description="缩略图宽度（像素）", ge=50, le=800, example=200),
    height: int = Query(200, description="缩略图高度（像素）", ge=50, le=800, example=200)
):
    """
    获取图片缩略图
    
    ## 功能说明
    返回指定尺寸的缩略图，用于列表展示、预览等场景。
    缩略图会保持原图比例，在指定的宽高范围内缩放。
    
    ## 路径参数
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | category | string | 是 | 分类目录 |
    | filename | string | 是 | 文件名 |
    
    ## 查询参数
    | 参数 | 类型 | 必填 | 默认值 | 范围 | 说明 |
    |------|------|------|--------|------|------|
    | width | int | 否 | 200 | 50-800 | 缩略图宽度 |
    | height | int | 否 | 200 | 50-800 | 缩略图高度 |
    
    ## 使用示例
    ```
    # 默认200x200
    GET /api/v1/upload/thumbnail/work_order/photo.jpg
    
    # 自定义尺寸150x150
    GET /api/v1/upload/thumbnail/work_order/photo.jpg?width=150&height=150
    
    # 列表小图100x100
    GET /api/v1/upload/thumbnail/work_order/photo.jpg?width=100&height=100
    ```
    
    ## 前端使用
    ```html
    <!-- 列表缩略图 -->
    <img src="/api/v1/upload/thumbnail/work_order/photo.jpg?width=100&height=100" />
    
    <!-- 预览缩略图 -->
    <img src="/api/v1/upload/thumbnail/work_order/photo.jpg?width=300&height=300" />
    ```
    
    ## 依赖说明
    - 需要安装 Pillow 库：`pip install Pillow`
    - 如果未安装 Pillow，将返回原图
    
    ## 性能说明
    - 缩略图是实时生成的，不会缓存
    - 对于频繁访问的图片，建议前端缓存或使用CDN
    """
    file_path = Path(settings.PICTURE_DIR) / category / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    
    ext = get_file_extension(filename)
    mime_types = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "webp": "image/webp"
    }
    media_type = mime_types.get(ext, "image/jpeg")
    
    try:
        from PIL import Image
        import io
        
        # 打开图片并生成缩略图
        with Image.open(file_path) as img:
            img.thumbnail((width, height), Image.Resampling.LANCZOS)
            
            # 保存到内存
            buffer = io.BytesIO()
            img_format = "JPEG" if ext in ["jpg", "jpeg"] else ext.upper()
            if img_format == "JPG":
                img_format = "JPEG"
            img.save(buffer, format=img_format)
            buffer.seek(0)
            
            return StreamingResponse(buffer, media_type=media_type)
            
    except ImportError:
        # 如果没有安装Pillow，返回原图
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename
        )
    except Exception:
        # 其他错误也返回原图
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename
        )



@router.delete(
    "/image",
    summary="删除图片",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "操作结果",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "删除成功",
                            "value": {
                                "code": 0,
                                "message": "删除成功",
                                "data": {
                                    "url": "https://download.sihua.tech/alms/images/work_order/power_on_20251211_a1b2c3d4.jpg"
                                }
                            }
                        },
                        "not_found": {
                            "summary": "图片不存在",
                            "value": {
                                "code": 404,
                                "message": "图片不存在",
                                "data": None
                            }
                        },
                        "invalid_url": {
                            "summary": "无效的URL",
                            "value": {
                                "code": 400,
                                "message": "无效的图片URL",
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def delete_image(
    url: str = Query(..., description="图片的完整URL（上传时返回的url字段）", example="https://download.sihua.tech/alms/images/work_order/power_on_20251211_a1b2c3d4.jpg"),
):
    """
    删除已上传的图片
    
    ## 功能说明
    根据图片URL删除服务器上的图片文件。
    
    ## 参数说明
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | url | string | 是 | 图片的完整URL |
    
    ## 使用示例
    ```
    DELETE /api/v1/upload/image?url=https://download.sihua.tech/alms/images/work_order/photo.jpg
    ```
    
    ## curl示例
    ```bash
    curl -X DELETE "http://localhost:8000/api/v1/upload/image?url=https://download.sihua.tech/alms/images/work_order/photo.jpg"
    ```
    
    ## 注意事项
    - 只能删除本系统上传的图片（URL必须以配置的PICTURE_HTTP开头）
    - 删除后无法恢复
    - 删除前请确保该图片不再被引用
    
    ## 安全说明
    - 接口会验证URL前缀，防止删除非本系统的文件
    - 建议在生产环境添加权限控制
    """
    try:
        # 从URL提取文件路径
        base_url = settings.PICTURE_HTTP.rstrip('/')
        if not url.startswith(base_url):
            return ApiResponse(
                code=ResponseCode.BAD_REQUEST,
                message="无效的图片URL",
                data=None
            )
        
        relative_path = url[len(base_url):].lstrip('/')
        file_path = Path(settings.PICTURE_DIR) / relative_path
        
        if not file_path.exists():
            return ApiResponse(
                code=ResponseCode.NOT_FOUND,
                message="图片不存在",
                data=None
            )
        
        # 删除文件
        file_path.unlink()
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="删除成功",
            data={"url": url}
        )
        
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"删除失败: {str(e)}",
            data=None
        )


@router.get(
    "/list/{category}",
    summary="列出分类下的所有图片",
    response_model=ApiResponse,
    responses={
        200: {
            "description": "图片列表",
            "content": {
                "application/json": {
                    "example": {
                        "code": 0,
                        "message": "查询成功",
                        "data": {
                            "category": "work_order",
                            "total": 3,
                            "files": [
                                {
                                    "filename": "power_on_20251211_a1b2c3d4.jpg",
                                    "url": "https://download.sihua.tech/alms/images/work_order/power_on_20251211_a1b2c3d4.jpg",
                                    "preview_url": "/api/v1/upload/preview/work_order/power_on_20251211_a1b2c3d4.jpg",
                                    "thumbnail_url": "/api/v1/upload/thumbnail/work_order/power_on_20251211_a1b2c3d4.jpg",
                                    "size": 102400,
                                    "created_at": "2025-12-11T10:30:00"
                                }
                            ]
                        }
                    }
                }
            }
        }
    }
)
async def list_images(
    category: str = PathParam(..., description="分类目录", example="work_order"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页数量", ge=1, le=100)
):
    """
    列出分类下的所有图片
    
    ## 功能说明
    查询指定分类目录下的所有图片，支持分页。
    
    ## 路径参数
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | category | string | 是 | 分类目录 |
    
    ## 查询参数
    | 参数 | 类型 | 必填 | 默认值 | 说明 |
    |------|------|------|--------|------|
    | page | int | 否 | 1 | 页码 |
    | page_size | int | 否 | 20 | 每页数量（1-100） |
    
    ## 返回字段说明
    | 字段 | 类型 | 说明 |
    |------|------|------|
    | category | string | 分类目录 |
    | total | int | 总文件数 |
    | page | int | 当前页码 |
    | page_size | int | 每页数量 |
    | files | array | 文件列表 |
    
    ## 使用场景
    - 管理后台查看已上传的图片
    - 清理无用图片
    """
    try:
        upload_dir = Path(settings.PICTURE_DIR) / category
        
        if not upload_dir.exists():
            return ApiResponse(
                code=ResponseCode.SUCCESS,
                message="查询成功",
                data={
                    "category": category,
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "files": []
                }
            )
        
        # 获取所有图片文件
        all_files = []
        for ext in settings.ALLOWED_EXTENSIONS:
            all_files.extend(upload_dir.glob(f"*.{ext}"))
        
        # 按修改时间倒序排序
        all_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        total = len(all_files)
        
        # 分页
        start = (page - 1) * page_size
        end = start + page_size
        page_files = all_files[start:end]
        
        files_data = []
        for file_path in page_files:
            stat = file_path.stat()
            filename = file_path.name
            files_data.append({
                "filename": filename,
                "url": f"{settings.PICTURE_HTTP.rstrip('/')}/{category}/{filename}",
                "preview_url": f"/api/v1/upload/preview/{category}/{filename}",
                "thumbnail_url": f"/api/v1/upload/thumbnail/{category}/{filename}",
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        
        return ApiResponse(
            code=ResponseCode.SUCCESS,
            message="查询成功",
            data={
                "category": category,
                "total": total,
                "page": page,
                "page_size": page_size,
                "files": files_data
            }
        )
        
    except Exception as e:
        return ApiResponse(
            code=ResponseCode.INTERNAL_ERROR,
            message=f"查询失败: {str(e)}",
            data=None
        )
