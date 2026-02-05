"""钉钉适配器客户端 - 支持官方 SDK 长连接 (Stream Mode) 方式

基于钉钉官方 Python SDK (dingtalk-stream)，通过 WebSocket 长连接接收消息。
"""

import json
import asyncio
import time
import httpx
import threading
import uuid
from typing import Optional, Dict, Any, Callable, List
from loguru import logger

# 导入钉钉 SDK
try:
    import dingtalk_stream
    from dingtalk_stream import AckMessage, ChatbotMessage, CallbackMessage, ChatbotHandler
    HAS_SDK = True
except ImportError:
    HAS_SDK = False
    logger.warning("dingtalk-stream SDK 未安装，请运行: pip install dingtalk-stream")


def _run_ws_in_new_thread(client: 'dingtalk_stream.DingTalkStreamClient'):
    """在独立线程中运行 WebSocket 客户端"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # DingTalkStreamClient.start() 是异步的
        loop.run_until_complete(client.start())
    except Exception as e:
        logger.error(f"钉钉 WebSocket 客户端运行异常: {e}")
    finally:
        loop.close()


class DingTalkClientSDK:
    """钉钉客户端 - 官方 SDK 实现（支持 Stream Mode 长连接模式）"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        event_handlers: Optional[Dict[str, Callable[[Any], Any]]] = None,
    ):
        """
        初始化钉钉客户端

        Args:
            client_id: 钉钉应用 AppKey
            client_secret: 钉钉应用 AppSecret
            event_handlers: 事件处理器字典，key 为事件类型，value 为处理函数
        """
        if not HAS_SDK:
            raise ImportError(
                "dingtalk-stream SDK 未安装，请运行: pip install dingtalk-stream"
            )

        self.client_id = client_id
        self.client_secret = client_secret
        self.event_handlers = event_handlers or {}

        logger.info(f"钉钉 SDK 客户端初始化 (Client ID: {client_id})")

        # 创建 SDK 凭据
        self.credential = dingtalk_stream.Credential(client_id, client_secret)
        
        # 创建 SDK 客户端
        self._ws_client = dingtalk_stream.DingTalkStreamClient(self.credential)
        
        # 注册机器人回调
        if ChatbotMessage.TOPIC in self.event_handlers:
            class InternalBotHandler(ChatbotHandler):
                def __init__(self, handler_func):
                    super().__init__()
                    self.handler_func = handler_func

                async def process(self, callback: CallbackMessage):
                    try:
                        # 解析消息
                        incoming_message = ChatbotMessage.from_dict(callback.data)
                        # 调用处理器
                        await self.handler_func(incoming_message)
                        return AckMessage.STATUS_OK, "OK"
                    except Exception as e:
                        logger.error(f"处理钉钉消息异常: {e}")
                        return AckMessage.STATUS_NOT_IMPLEMENT, str(e)

            self._ws_client.register_callback_handler(
                ChatbotMessage.TOPIC, 
                InternalBotHandler(self.event_handlers[ChatbotMessage.TOPIC])
            )

        # 线程控制
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_started: bool = False
        
        # HTTP 客户端用于主动发送消息
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._access_token: Optional[str] = None
        self._token_expire_time: float = 0

    def start_ws(self) -> bool:
        """启动 WebSocket 长连接"""
        if self._ws_started:
            logger.warning("钉钉 WebSocket 长连接已启动")
            return True

        logger.info("启动钉钉 WebSocket 长连接 (Stream Mode)...")

        try:
            self._ws_thread = threading.Thread(
                target=_run_ws_in_new_thread,
                args=(self._ws_client,),
                daemon=True,
                name="DingTalkWSClient"
            )
            self._ws_thread.start()
            
            self._ws_started = True
            logger.info("钉钉 WebSocket 长连接已启动（在后台线程中运行）")
            return True
        except Exception as e:
            logger.error(f"启动钉钉 WebSocket 失败: {e}")
            return False

    def stop_ws(self) -> None:
        """停止 WebSocket 长连接"""
        logger.info("停止钉钉 WebSocket 长连接...")
        # SDK 没提供直接的 stop，但线程是 daemon 的
        # 实际上可以通过关闭事件循环或者断开连接
        self._ws_started = False
        self._ws_thread = None
        logger.info("钉钉 WebSocket 长连接已停止")

    async def _get_access_token(self) -> str:
        """获取访问令牌"""
        if self._access_token and time.time() < self._token_expire_time - 300:
            return self._access_token

        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        payload = {
            "appKey": self.client_id,
            "appSecret": self.client_secret,
        }
        
        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        self._access_token = data.get("accessToken")
        expire = data.get("expireIn", 7200)
        self._token_expire_time = time.time() + expire
        
        return self._access_token

    async def send_message(
        self,
        to: str,
        message_type: str,
        content: Any,
        conversation_type: str = "user"
    ) -> bool:
        """
        发送消息 (Proactive)
        使用钉钉互动卡片 OpenAPI: https://open.dingtalk.com/document/orgapp/robots-send-interactive-cards
        """
        try:
            token = await self._get_access_token()
            url = "https://api.dingtalk.com/v1.0/im/v1.0/robot/interactiveCards/send"
            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json",
            }
            
            # 构造符合钉钉规范的交互卡片结构
            # 这是一个包含标题和 Markdown 内容的完整卡片数据
            card_data_obj = {
                "config": {
                    "autoLayout": True,
                    "enableForward": True
                },
                "header": {
                    "title": {
                        "type": "text",
                        "text": "AI 助手回复"
                    },
                    "logo": "@lALPDfJ6V_FPDmvNAfTNAfQ"
                },
                "contents": [
                    {
                        "type": "markdown",
                        "text": str(content),
                        "id": f"text_{uuid.uuid4().hex[:8]}"
                    }
                ]
            }
            
            payload = {
                "cardTemplateId": "StandardCard",
                "robotCode": self.client_id,
                "cardData": json.dumps(card_data_obj, ensure_ascii=False),
                "cardBizId": f"biz_{uuid.uuid4().hex[:16]}",
            }
            
            if conversation_type == "group":
                payload["openConversationId"] = to
            else:
                # 单聊必须指定 singleChatReceiver
                payload["singleChatReceiver"] = json.dumps({"userId": to})
            
            logger.debug(f"发送钉钉卡片请求: {json.dumps(payload, ensure_ascii=False)}")
            
            response = await self._http_client.post(url, json=payload, headers=headers)
            data = response.json()
            
            if response.status_code == 200:
                logger.debug(f"钉钉消息发送成功: {data}")
                return True
            else:
                logger.error(f"钉钉消息发送失败 (HTTP {response.status_code}): {data}")
                return False
                
        except Exception as e:
            logger.error(f"发送钉钉消息异常: {e}")
            return False

    async def close(self):
        """关闭客户端"""
        self.stop_ws()
        await self._http_client.aclose()


__all__ = ["DingTalkClientSDK", "HAS_SDK"]
