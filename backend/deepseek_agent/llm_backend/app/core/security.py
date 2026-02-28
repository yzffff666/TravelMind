from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings
from app.services.user_service import UserService
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

# 创建 OAuth2 密码授权方案
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# 创建访问令牌
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    # 复制数据
    to_encode = data.copy()
    if expires_delta:
        # 如果过期时间不为空，则设置过期时间
        expire = datetime.utcnow() + expires_delta
    # 如果过期时间为空，则设置过期时间为15分钟
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    # 更新数据
    to_encode.update({"exp": expire})
    # 编码令牌
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

# 获取当前用户
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
):
    # 如果令牌无效，则抛出异常
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # 解码令牌
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            # 如果邮箱为空，则抛出异常
            raise credentials_exception
    except JWTError:
        # 如果解码失败，则抛出异常
        raise credentials_exception
        
    # 获取用户
    user_service = UserService(db)
    user = await user_service.get_user_by_email(email)
    if user is None:
        # 如果用户不存在，则抛出异常
        raise credentials_exception
    return user 