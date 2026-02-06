"""FastAPI application"""

import asyncio
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from chatagentcore.core.event_bus import get_event_bus
from chatagentcore.core.config_manager import get_config_manager
from chatagentcore.core.adapter_manager import get_adapter_manager
from chatagentcore.storage.logger import LogConfig
from chatagentcore.api.websocket.manager import get_manager
from chatagentcore.api.models.message import WSAuthMessage, WSSubscribeMessage, WSMessage
from chatagentcore.api.schemas.config import Settings
from chatagentcore.api.routes import message as message_routes
from chatagentcore.api.routes import webhook as webhook_routes
from chatagentcore.adapters.base import Message as BaseMessage


def _default_message_handler(message: BaseMessage) -> None:
    """
    默认消息处理器 - 打印接收到的消息并广播到 WebSocket

    Args:
        message: 收到的消息对象
    """
    sender_id = message.sender.get("id", "")
    sender_name = message.sender.get("name", "")
    conv_id = message.conversation.get("id", "")
    conv_type = message.conversation.get("type", "")

    logger.info("=" * 70)
    logger.info("📨 收到消息 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(f"平台: {message.platform}")
    logger.info(f"发送者: {sender_name} ({sender_id})")
    logger.info(f"会话: {conv_type}:{conv_id}")

    content = message.content
    msg_type = content.get("type", "unknown")

    # 显示消息内容
    if msg_type == "text" and content.get("text"):
        text = content["text"]
        if text:
            # 多行消息分行显示
            for line in text.split("\n"):
                logger.info(f"内容: {line[:100]}")  # 限制每行长度
        else:
            logger.info("内容: [空消息]")
    elif msg_type == "interactive":
        logger.info("类型: 交互卡片消息")
        data = content.get("data", {})
        if isinstance(data, dict):
            logger.info(f"卡片数据: {str(data)[:200]}...")
    elif msg_type == "post":
        logger.info("类型: 富文本消息")
        data = content.get("data", {})
        if isinstance(data, dict):
            logger.info(f"富文本数据: {str(data)[:200]}...")
    else:
        logger.info(f"类型: {msg_type}")
        data = content.get("data", {})
        if data:
            data_str = str(data)[:100]
            logger.info(f"数据: {data_str}...")

    logger.info("=" * 70)

    # 广播消息到 WebSocket 订阅者
    ws_payload = {
        "platform": message.platform,
        "sender": message.sender,
        "conversation": message.conversation,
        "content": message.content,
        "timestamp": int(time.time())
    }

    ws_msg = WSMessage(
        type="message",
        channel="messages",
        timestamp=int(time.time()),
        payload=ws_payload
    )

    # 获取当前运行的事件循环并创建广播任务
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(ws_manager.broadcast(ws_msg, channel="messages"))
    except Exception as e:
        logger.error(f"Failed to broadcast message via WebSocket: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("Starting ChatAgentCore...")

    # 加载配置
    config_manager = get_config_manager()
    config_manager.load()

    # 配置日志
    log_config = LogConfig(
        log_dir=config_manager.config.logging.file.rsplit("/", 1)[0],
        level=config_manager.config.logging.level,
    )
    log_config.setup()

    # 获取适配器管理器并注册适配器类
    adapter_manager = get_adapter_manager()
    from chatagentcore.adapters.feishu import FeishuAdapter
    from chatagentcore.adapters.dingtalk import DingTalkAdapter
    from chatagentcore.adapters.qq import QQAdapter
    adapter_manager.register("feishu", FeishuAdapter)
    adapter_manager.register("dingtalk", DingTalkAdapter)
    adapter_manager.register("qq", QQAdapter)

    # 根据配置加载启用的平台适配器
    platforms_config = {}
    for platform, cfg in [
        ("feishu", config_manager.platforms.feishu),
        ("wecom", config_manager.platforms.wecom),
        ("dingtalk", config_manager.platforms.dingtalk),
        ("qq", config_manager.platforms.qq),
    ]:
        if cfg.enabled:
            # 直接使用 model_dump() 获取完整配置，已包含所有字段
            # FeishuConfig 现在包含：enabled, type, app_id, app_secret, connection_mode, domain 等
            platform_dict = cfg.model_dump()
            platforms_config[platform] = platform_dict

    if platforms_config:
        logger.info(f"Loading platforms: {list(platforms_config.keys())}")
        await adapter_manager.load_all(platforms_config)

        # 为每个适配器设置默认消息处理器（打印接收到的消息）
        for platform_name in platforms_config.keys():
            adapter = adapter_manager.get_adapter(platform_name)
            if adapter:
                adapter.set_message_handler(_default_message_handler)
    else:
        logger.warning("No platforms enabled in configuration")

    # 启动事件总线
    event_bus = get_event_bus()
    await event_bus.start()

    # 启动配置文件监控
    await config_manager.watch(interval=5.0)

    # 同步有效的 API Token 到 WebSocket 管理器
    if config_manager.config.auth.token:
        ws_manager.set_valid_tokens([config_manager.config.auth.token])

    # 启动清理过期连接的后台任务
    async def prune_task():
        while True:
            try:
                await asyncio.sleep(30)
                count = await ws_manager.prune_stale_connections(timeout=90.0)
                if count > 0:
                    logger.info(f"Background task pruned {count} stale connections")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in prune_task: {e}")

    prune_job = asyncio.create_task(prune_task())

    logger.info("ChatAgentCore started successfully")

    yield

    # 关闭时执行
    logger.info("Shutting down ChatAgentCore...")
    prune_job.cancel()
    await event_bus.stop()
    await config_manager.stop_watch()

    # 卸载所有适配器
    await adapter_manager.unload_all()

    logger.info("ChatAgentCore shut down")


# 创建 FastAPI 应用
app = FastAPI(
    title="ChatAgentCore API",
    description="聊天机器人中间服务 API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(message_routes.router)
app.include_router(webhook_routes.router)

# WebSocket 连接管理器
ws_manager = get_manager()


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "ChatAgentCore",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    adapter_manager = get_adapter_manager()
    return {
        "status": "healthy",
        "plugins_loaded": adapter_manager.loaded_platforms_count,
    }


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket 事件端点

    客户端可以订阅频道接收实时消息和事件
    """
    user_id = await ws_manager.connect(websocket)

    try:
        while True:
            # 接收客户端消息
            data: dict = await websocket.receive_json()
            ws_manager.update_last_seen(websocket)
            msg_type = data.get("type")

            if msg_type == "auth":
                # 处理认证
                auth_msg = WSAuthMessage(**data)
                await ws_manager.handle_auth(websocket, auth_msg)

            elif msg_type == "ping":
                # 处理 Ping 并返回 Pong
                pong_msg = WSMessage(
                    type="pong",
                    channel="system",
                    timestamp=int(time.time()),
                    payload={"ping_timestamp": data.get("timestamp")}
                )
                await ws_manager.send_json(websocket, pong_msg)

            elif msg_type == "subscribe":
                # 处理订阅
                if not ws_manager.is_authenticated(websocket):
                    await websocket.close(code=4008, reason="Authenticate first")
                    return

                sub_msg = WSSubscribeMessage(**data)
                await ws_manager.handle_subscribe(websocket, sub_msg)

            else:
                # 未知消息类型
                logger.warning(f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await ws_manager.disconnect(websocket)




def create_app(config: Settings | None = None) -> FastAPI:
    """
    创建应用实例（用于测试）

    Args:
        config: 可选的配置对象

    Returns:
        FastAPI 应用实例
    """
    if config is not None:
        # 这里可以设置自定义配置
        pass
    return app


if __name__ == "__main__":
    import uvicorn

    config_manager = get_config_manager()
    config_manager.load()

    uvicorn.run(
        "api.main:app",
        host=config_manager.config.server.host,
        port=config_manager.config.server.port,
        reload=config_manager.config.server.debug,
    )
