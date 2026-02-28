from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# 优化连接池配置，防止连接泄漏和死锁
engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,          # 使用前检查连接是否有效
    pool_size=10,                # 连接池大小（默认5，增加到10）
    max_overflow=20,             # 超出连接池的额外连接数（默认10，增加到20）
    pool_recycle=3600,           # 1小时后回收连接（防止MySQL 8小时超时）
    pool_timeout=30,             # 获取连接的超时时间（秒）
    echo=False,                  # 不打印SQL（生产环境）
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 依赖注入函数
def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()