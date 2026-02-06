"""Feishu adapter implementation - 支持 WebSocket 长连接和 Webhook 回调方式"""

import sys
import asyncio
import json
from typing import Dict, Any, Callable, Optional, Final
from loguru import logger
from chatagentcore.adapters.base import BaseAdapter, Message
from chatagentcore.adapters.feishu.client import FeishuClientSDK, HAS_SDK

# Python 3.11+ 有整数转换限制，飞书消息可能包含超大数字 ID
# 设置 sys.set_int_max_str_digits(0) 移除限制
# 详情: https://docs.python.org/3/library/stdtypes.html#int-max-str-digits
if hasattr(sys, 'set_int_max_str_digits'):
    sys.set_int_max_str_digits(0)

# 连接模式常量
MODE_WEBSOCKET: Final = "websocket"
MODE_WEBHOOK: Final = "webhook"


class FeishuAdapter(BaseAdapter):
    """飞书适配器 - 支持 WebSocket 长连接模式和 Webhook 回调模式"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化飞书适配器

        Args:
            config: 平台配置
                - app_id: 飞书应用 ID
                - app_secret: 飞书应用密钥
                - connection_mode: 连接模式，"websocket"(推荐) 或 "webhook"，默认 "websocket"
                - domain: 域名，"feishu" 或 "lark"，默认 "feishu"
        """
        super().__init__(config)

        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self._connection_mode = config.get("connection_mode", MODE_WEBSOCKET) or MODE_WEBSOCKET
        self._domain = config.get("domain", "feishu") or "feishu"

        # 验证连接模式
        if self._connection_mode not in (MODE_WEBSOCKET, MODE_WEBHOOK):
            logger.warning(f"无效的连接模式: {self._connection_mode}，使用默认: {MODE_WEBSOCKET}")
            self._connection_mode = MODE_WEBSOCKET

        # 事件处理器
        self._message_handler: Optional[Callable] = None

        # 客户端
        self._client: Optional[FeishuClientSDK] = None

        # WebSocket 相关
        self._ws_started: bool = False

    async def initialize(self) -> None:
        """初始化适配器"""
        if not HAS_SDK:
            raise ImportError(
                "lark_oapi SDK 未安装，请运行: pip install lark_oapi"
            )

        mode_name = "WebSocket 长连接" if self._connection_mode == MODE_WEBSOCKET else "Webhook 回调"
        logger.info(f"初始化飞书适配器（{mode_name}）...")

        # 创建事件处理器映射（用于 WebSocket 模式）
        event_handlers = {
            "im.message.receive_v1": self._handle_ws_message_event,
            "im.message.group_at_v1": self._handle_ws_at_message_event,
            "im.chat.member.bot.added_v1": self._handle_ws_bot_added_event,
            "im.chat.member.bot.deleted_v1": self._handle_ws_bot_deleted_event,
        }

        # 创建客户端
        self._client = FeishuClientSDK(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handlers=event_handlers,
            domain=self._domain,
        )

        # 根据连接模式启动
        if self._connection_mode == MODE_WEBSOCKET:
            # WebSocket 模式：启动长连接
            success = self._client.start_ws()
            if success:
                self._ws_started = True
                logger.info("飞书适配器初始化完成 - WebSocket 长连接已启动")
                logger.info("等待接收飞书消息...")
            else:
                raise RuntimeError("WebSocket 长连接启动失败")
        else:
            # Webhook 模式：等待 HTTP 回调
            logger.info("飞书适配器初始化完成")
            logger.info("请配置 Webhook 回调地址: http://your-server:port/webhook/feishu")

    def _handle_ws_message_event(self, payload: str) -> Dict[str, Any]:
        """
        处理 WebSocket 模式下的消息事件

        Args:
            payload: 事件 JSON 字符串（可能是 bytes）

        Returns:
            响应数据
        """
        try:
            # payload 可能是 bytes 类型，需要解码为字符串
            if isinstance(payload, bytes):
                payload = payload.decode('utf-8', errors='ignore')

            event_data = json.loads(payload)
            asyncio.create_task(self._handle_message_event_async(event_data))
            return {"msg": "success"}
        except Exception as e:
            logger.error(f"WebSocket 消息事件处理异常: {e}")
            return {"msg": "failed"}

    def _handle_ws_at_message_event(self, payload: str) -> Dict[str, Any]:
        """处理 WebSocket 模式下的群 @ 消息事件"""
        try:
            # payload 可能是 bytes 类型，需要解码为字符串
            if isinstance(payload, bytes):
                payload = payload.decode('utf-8', errors='ignore')

            event_data = json.loads(payload)
            asyncio.create_task(self._handle_at_message_event_async(event_data))
            return {"msg": "success"}
        except Exception as e:
            logger.error(f"WebSocket @ 消息事件处理异常: {e}")
            return {"msg": "failed"}

    def _handle_ws_bot_added_event(self, payload: str) -> Dict[str, Any]:
        """处理机器人加入群组事件"""
        try:
            event_data = json.loads(payload)
            event = event_data.get("event", {})
            chat_id = event.get("chat_id", "")
            logger.info(f"机器人加入群组: {chat_id}")
            return {"msg": "success"}
        except Exception as e:
            logger.error(f"机器人加入事件处理异常: {e}")
            return {"msg": "failed"}

    def _handle_ws_bot_deleted_event(self, payload: str) -> Dict[str, Any]:
        """处理机器人离开群组事件"""
        try:
            event_data = json.loads(payload)
            event = event_data.get("event", {})
            chat_id = event.get("chat_id", "")
            logger.info(f"机器人离开群组: {chat_id}")
            return {"msg": "success"}
        except Exception as e:
            logger.error(f"机器人离开事件处理异常: {e}")
            return {"msg": "failed"}

    def handle_webhook(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理 Webhook 回调事件（仅 Webhook 模式）

        Args:
            event_data: 飞书推送的事件数据

        Returns:
            响应数据
        """
        if self._connection_mode != MODE_WEBHOOK:
            logger.warning("当前为 WebSocket 模式，不支持 Webhook 回调")
            return {"msg": "success"}

        try:
            header = event_data.get("header", {})
            event = event_data.get("event", "")
            event_type = header.get("event_type", "")
            log_id = header.get("log_id", "")

            logger.info(f"Received Webhook event: {event_type} (log_id: {log_id})")

            # 消息接收事件
            if event_type in ("im.message.receive_v1", "im.message.group_at_v1"):
                asyncio.create_task(self._handle_message_event_async(event_data))

            elif event_type == "im.message.group_at_v1":
                # 群 @ 消息的处理可以扩展
                asyncio.create_task(self._handle_at_message_event_async(event_data))

            return {"msg": "success"}

        except Exception as e:
            logger.error(f"处理 Webhook 事件异常: {e}")
            return {"code": 1, "msg": str(e)}

    async def _handle_message_event_async(self, event_data: Dict[str, Any]) -> None:
        """
        异步处理消息事件

        Args:
            event_data: 事件数据
        """
        try:
            message = await self._parse_message_from_event(event_data)

            logger.info(f"处理飞书消息: {message.sender['id']} -> {message.content['text'][:50]}")

            # 调用消息处理器
            if self._message_handler:
                if asyncio.iscoroutinefunction(self._message_handler):
                    await self._message_handler(message)
                else:
                    self._message_handler(message)
            else:
                logger.debug(f"收到消息但未设置处理器: {message.content['text'][:50]}")

        except Exception as e:
            logger.error(f"处理消息事件异常: {e}")

    async def _handle_at_message_event_async(self, event_data: Dict[str, Any]) -> None:
        """处理群 @ 消息事件"""
        try:
            message = await self._parse_message_from_event(event_data)
            logger.info(f"处理飞书群 @ 消息: {message.sender['id']}")

            # @ 消息也可以通过消息处理器处理
            if self._message_handler:
                content = message.content
                content["text"] = f"[群 @] {content.get('text', '')}"
                if asyncio.iscoroutinefunction(self._message_handler):
                    await self._message_handler(message)
                else:
                    self._message_handler(message)

        except Exception as e:
            logger.error(f"处理 @ 消息事件异常: {e}")

    async def _parse_message_from_event(self, event_data: Dict[str, Any]) -> Message:
        """
        从事件数据中解析消息

        Args:
            event_data: 飞书事件数据

        Returns:
            标准化的 Message 对象
        """
        header = event_data.get("header", {})
        event = event_data.get("event", {})

        # 飞书事件结构: event.data.message.message_id / chat_id / message_type / content
        # 或者 event.message.* (取决于事件类型)
        # 先尝试从 event.message 获取（WebSocket 模式）
        message_obj = event.get("message", {})
        if not message_obj:
            # 尝试从 event.data.message 获取（Webhook 模式）
            data = event.get("data", {})
            if data:
                message_obj = data.get("message", {})

        # 如果还是没有消息数据，尝试直接从 event 获取（部分事件）
        if not message_obj:
            message_obj = event

        # 提取消息数据
        message_id = message_obj.get("message_id", "")
        chat_id = message_obj.get("chat_id", "")
        # 支持两种字段名: message_type 和 msg_type
        message_type = message_obj.get("message_type") or message_obj.get("msg_type", "")

        # 解析发送者信息 - 事件结构中 sender 可能在 event.sender 或 event.data.sender
        sender_info = event.get("sender")
        if not sender_info:
            # 尝试从 data 获取
            data = event.get("data", {})
            sender_info = data.get("sender")

        sender = sender_info or {}
        sender_id = ""
        if "sender_id" in sender:
            sender_id_obj = sender.get("sender_id", {})
            sender_id = sender_id_obj.get("open_id", "")
        elif "open_id" in sender:
            sender_id = sender.get("open_id", "")
        elif "sender_type" in sender:
            # 备用方案：从 sender 对象中查找 ID
            sender_id = str(sender.get("user_id", "")) or str(sender.get("open_id", ""))

        sender_type = sender.get("sender_type", "user")

        # 解析消息内容 - 从 message 对象获取
        content_raw = message_obj.get("content", "")
        content_data = {}
        text_content = ""

        # content 可能是字符串形式的 JSON，或者是已解析的 dict
        if content_raw:
            if isinstance(content_raw, str):
                try:
                    content_data = json.loads(content_raw) if content_raw else {}
                except json.JSONDecodeError:
                    content_data = {"text": content_raw}
            elif isinstance(content_raw, dict):
                content_data = content_raw
        else:
            content_data = {"text": ""}

        logger.debug(f"Content data: {str(content_data)[:200]}")

        # 根据 message_type 处理内容
        if message_type == "text":
            if content_data and isinstance(content_data, dict):
                text_content = content_data.get("text", "")
            elif content_raw:
                text_content = str(content_data)
        elif message_type == "interactive":
            text_content = "[卡片消息]"
        elif message_type == "post":
            text_content = "[富文本消息]"
        else:
            if not message_type:
                logger.warning(f"message_type 为空，content: {str(content_data)[:200]}")
            text_content = f"[{message_type} 消息]"

        # 判断会话类型
        chat_type = message_obj.get("chat_type", "user") or ("group" if chat_id and chat_id.startswith("oc_") else "user")

        # 归一化会话 ID：私聊使用 open_id，群聊使用 chat_id
        final_conv_id = chat_id
        if chat_type == "user":
            final_conv_id = sender_id

        return Message(
            platform="feishu",
            message_id=message_id,
            sender={
                "id": sender_id,
                "name": sender_type,
                "type": sender_type,
            },
            conversation={
                "id": final_conv_id,
                "type": chat_type,
            },
            content={
                "type": message_type,
                "text": text_content,
                "data": content_data if content_data else {},
            },
            # timestamp 优先使用 message.create_time，再使用 header.create_time
            timestamp=(int(message_obj.get("create_time", 0) or header.get("create_time", 0)) * 1000),
        )

    async def shutdown(self) -> None:
        """关闭适配器"""
        logger.info("关闭飞书适配器...")

        if self._client:
            # 停止 WebSocket 长连接（如果已启动）
            if self._ws_started:
                self._client.stop_ws()
                self._ws_started = False

            await self._client.close()
            self._client = None

        logger.info("飞书适配器已关闭")

    def set_message_handler(self, handler: Callable[[Message], None]):
        """
        设置消息处理器

        Args:
            handler: 消息处理函数，接收 Message 对象
        """
        self._message_handler = handler

    @property
    def connection_mode(self) -> str:
        """获取当前连接模式"""
        return self._connection_mode

    @property
    def is_websocket_connected(self) -> bool:
        """WebSocket 是否已连接（仅 WebSocket 模式）"""
        return self._connection_mode == MODE_WEBSOCKET and self._ws_started and self._client.is_ws_started if self._client else False

    async def send_message(
        self, to: str, message_type: str, content: str, conversation_type: str = "user"
    ) -> str:
        """
        发送消息

        Args:
            to: 接收者 ID
            message_type: 消息类型
            content: 消息内容
            conversation_type: 会话类型

        Returns:
            消息 ID

        Raises:
            Exception: 发送失败
        """
        if self._client is None:
            raise RuntimeError("客户端未初始化，请先调用 initialize()")

        # 根据 conversation_type 设置 receive_id_type
        receive_id_type = "open_id" if conversation_type == "user" else "chat_id"

        if message_type == "text":
            result = await self._client.send_text_message(to, content, receive_id_type)
            if result:
                return to  # 飞书 API 返回的消息 ID 在响应中
            raise Exception("消息发送失败")

        elif message_type == "card":
            try:
                card_data = json.loads(content)
                result = await self._client.send_card_message(to, card_data, receive_id_type)
                if result:
                    return to
                raise Exception("卡片消息发送失败")
            except json.JSONDecodeError:
                # 如果不是 JSON，当作文本发送
                result = await self._client.send_text_message(to, content, receive_id_type)
                if result:
                    return to
                raise Exception("消息发送失败")
        else:
            # 其他类型暂时当作文本发送
            result = await self._client.send_text_message(to, content, receive_id_type)
            if result:
                return to
            raise Exception("消息发送失败")


__all__ = ["FeishuAdapter", "MODE_WEBSOCKET", "MODE_WEBHOOK"]
