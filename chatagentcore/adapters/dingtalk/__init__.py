"""DingTalk adapter implementation - 支持 Stream Mode 长连接方式"""

import asyncio
import json
import time
from typing import Dict, Any, Callable, Optional, Final
from loguru import logger
from chatagentcore.adapters.base import BaseAdapter, Message
from chatagentcore.adapters.dingtalk.client import DingTalkClientSDK, HAS_SDK


class DingTalkAdapter(BaseAdapter):
    """钉钉适配器 - 支持 Stream Mode 长连接模式"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化钉钉适配器

        Args:
            config: 平台配置
                - client_id: 钉钉应用 AppKey
                - client_secret: 钉钉应用 AppSecret
        """
        super().__init__(config)

        self.client_id = config.get("client_id") or config.get("app_key", "")
        self.client_secret = config.get("client_secret") or config.get("app_secret", "")
        
        # 事件处理器
        self._message_handler: Optional[Callable] = None

        # 客户端
        self._client: Optional[DingTalkClientSDK] = None

        # WebSocket 相关
        self._ws_started: bool = False

    async def initialize(self) -> None:
        """初始化适配器"""
        if not HAS_SDK:
            raise ImportError(
                "dingtalk-stream SDK 未安装，请运行: pip install dingtalk-stream"
            )

        logger.info("初始化钉钉适配器 (Stream Mode)...")

        # 处理器映射
        # 注意: 这里的 TOPIC 匹配 SDK 中的 /v1.0/im/bot/messages/get
        event_handlers = {
            "/v1.0/im/bot/messages/get": self._handle_bot_message
        }

        # 创建客户端
        self._client = DingTalkClientSDK(
            client_id=self.client_id,
            client_secret=self.client_secret,
            event_handlers=event_handlers,
        )

        # 启动长连接
        success = self._client.start_ws()
        if success:
            self._ws_started = True
            logger.info("钉钉适配器初始化完成 - Stream Mode 已启动")
        else:
            raise RuntimeError("钉钉 Stream Mode 启动失败")

    async def _handle_bot_message(self, ding_msg: Any) -> None:
        """
        处理钉钉机器人消息事件
        
        Args:
            ding_msg: dingtalk_stream.ChatbotMessage 对象
        """
        try:
            # 转换为标准 Message 对象
            message = self._parse_message(ding_msg)
            
            logger.info(f"收到钉钉消息: {message.sender['name']} -> {message.content['text'][:50]}")

            # 调用消息处理器
            if self._message_handler:
                if asyncio.iscoroutinefunction(self._message_handler):
                    await self._message_handler(message)
                else:
                    self._message_handler(message)
        except Exception as e:
            logger.error(f"处理钉钉消息异常: {e}")

    def _parse_message(self, ding_msg: Any) -> Message:
        """将钉钉 SDK 消息对象转换为标准 Message 对象"""
        # ding_msg 是 dingtalk_stream.ChatbotMessage
        
        # 提取文本内容
        text_content = ""
        if ding_msg.message_type == "text":
            text_content = ding_msg.text.content if ding_msg.text else ""
        elif ding_msg.message_type == "richText":
            texts = ding_msg.get_text_list()
            text_content = "".join(texts) if texts else "[富文本]"
        else:
            text_content = f"[{ding_msg.message_type}]"

        # 判断会话类型 (1: 单聊, 2: 群聊)
        conv_type = "group" if ding_msg.conversation_type == "2" else "user"
        
        # 对于单聊，会话 ID 应该是用户 ID，以便后续回复
        conv_id = ding_msg.conversation_id
        if conv_type == "user":
            conv_id = ding_msg.sender_staff_id or ding_msg.sender_id

        return Message(
            platform="dingtalk",
            message_id=str(ding_msg.message_id),
            sender={
                "id": ding_msg.sender_staff_id or ding_msg.sender_id,
                "name": ding_msg.sender_nick or "DingTalkUser",
                "type": "user",
            },
            conversation={
                "id": conv_id,
                "type": conv_type,
            },
            content={
                "type": "text" if ding_msg.message_type == "text" else ding_msg.message_type,
                "text": text_content,
                "data": ding_msg.to_dict(),
            },
            timestamp=int(ding_msg.create_at) if ding_msg.create_at else int(time.time() * 1000),
        )

    async def send_message(
        self, to: str, message_type: str, content: str, conversation_type: str = "user"
    ) -> str:
        """发送消息"""
        if not self._client:
            raise RuntimeError("客户端未初始化")
            
        success = await self._client.send_message(
            to=to,
            message_type=message_type,
            content=content,
            conversation_type=conversation_type
        )
        
        if success:
            return f"ding_{int(time.time())}"
        raise Exception("钉钉消息发送失败")

    def set_message_handler(self, handler: Callable[[Message], None]):
        """设置消息处理器"""
        self._message_handler = handler

    async def shutdown(self) -> None:
        """关闭适配器"""
        logger.info("关闭钉钉适配器...")
        if self._client:
            await self._client.close()
            self._client = None
        self._ws_started = False

    async def health_check(self) -> bool:
        """健康检查"""
        return self._ws_started and self._client is not None


__all__ = ["DingTalkAdapter"]
