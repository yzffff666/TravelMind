from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.travel import router as travel_router

# 创建主路由，所有可用的参数：https://fastapi.tiangolo.com/reference/apirouter/?h=apirouter#fastapi.APIRouter--example
api_router = APIRouter()

# 注册所有子路由，不使用前缀
api_router.include_router(auth_router, tags=["authentication"]) 
api_router.include_router(conversations_router, tags=["conversations"])
api_router.include_router(travel_router, tags=["travel"])