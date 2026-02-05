"""Message router for routing messages to correct adapters"""

import asyncio
import uuid
from typing import Dict, Optional
from loguru import logger
from chatagentcore.core.adapter_manager import AdapterManager, get_adapter_manager


class MessageRouter:
    """消息路由器 - 负责将消息路由到正确的适配器"""

    def __init__(self, adapter_manager: AdapterManager):
        """
        初始化消息路由器

        Args:
            adapter_manager: 适配器管理器实例
        """
        self.adapter_manager = adapter_manager
        self._pending_messages: Dict[str, asyncio.Future] = {}
        self._running = False

    async def route_outgoing(
        self, platform: str, to: str, message_type: str, content: str, conversation_type: str = "user"
    ) -> str:
        """
        路由要发送到平台的消息

        Args:
            platform: 平台名称
            to: 接收者 ID
            message_type: 消息类型 text | image | card
            content: 消息内容
            conversation_type: 会话类型 user | group

        Returns:
            发送后的消息 ID

        Raises:
            ValueError: 平台未加载
        """
        logger.debug(f"Routing outgoing message to platform: {platform}, to: {to}")

        adapter = self.adapter_manager.get_adapter(platform)
        if adapter is None:
            raise ValueError(f"Adapter not loaded for platform: {platform}")

        try:
            message_id = await adapter.send_message(to, message_type, content, conversation_type)
            logger.info(f"Message sent: {message_id}")
            return message_id
        except Exception as e:
            logger.error(f"Error sending message to {platform}: {e}")
            raise

    def create_message_id(self) -> str:
        """
        创建唯一的消息 ID

        Returns:
            消息 ID
        """
        return f"msg_{uuid.uuid4().hex}"

    async def send_and_wait(
        self, platform: str, to: str, message_type: str, content: str, conversation_type: str = "user", timeout: float = 30.0
    ) -> str:
        """
        发送消息并等待发送完成

        Args:
            platform: 平台名称
            to: 接收者 ID
            message_type: 消息类型
            content: 消息内容
            conversation_type: 会话类型
            timeout: 超时时间（秒）

        Returns:
            消息 ID

        Raises:
            asyncio.TimeoutError: 发送超时
        """
        message_id = self.create_message_id()
        future: asyncio.Future[str] = asyncio.Future()
        self._pending_messages[message_id] = future

        try:
            # 发送消息
            result_id = await asyncio.wait_for(
                self.route_outgoing(platform, to, message_type, content, conversation_type), timeout
            )

            # 标记为完成
            future.set_result(result_id)
            return result_id
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            self._pending_messages.pop(message_id, None)

    async def validate_platform_config(self, platform: str, config: Dict) -> bool:
        """
        验证平台配置是否有效

        Args:
            platform: 平台名称
            config: 配置数据

        Returns:
            True 表示有效，False 表示无效
        """
        if not config.get("enabled", False):
            return False

        return True


# 全局消息路由器实例
_router: MessageRouter | None = None


def get_router() -> MessageRouter:
    """获取全局消息路由器实例"""
    global _router
    if _router is None:
        _router = MessageRouter(get_adapter_manager())
    return _router


__all__ = ["MessageRouter", "get_router"]
