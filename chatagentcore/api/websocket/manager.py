"""WebSocket connection manager"""

import asyncio
import json
from typing import Dict, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from chatagentcore.api.models.message import WSMessage, WSAuthMessage, WSSubscribeMessage


class ConnectionManager:
    """WebSocket 连接管理器 - 管理活跃连接和消息广播"""

    def __init__(self):
        # 活跃连接: websocket -> 用户信息
        self._connections: Dict[WebSocket, Dict[str, Any]] = {}

        # 用户订阅: user_id -> {频道 -> set of websocket}
        self._subscriptions: Dict[str, Dict[str, Set[WebSocket]]] = {}

        # Token 验证（简单版本）
        self._valid_tokens: Set[str] = {"your_api_token"}

    def set_valid_tokens(self, tokens: list[str]) -> None:
        """设置有效的 Token 列表"""
        self._valid_tokens = set(tokens)
        logger.info(f"Updated valid tokens, count: {len(self._valid_tokens)}")

    async def connect(self, websocket: WebSocket) -> str:
        """
        接受新连接

        Args:
            websocket: WebSocket 连接

        Returns:
            用户 ID（使用连接 ID 的简化版本）
        """
        await websocket.accept()

        # 生成简单的用户 ID
        user_id = f"ws_user_{id(websocket)}"
        import time

        self._connections[websocket] = {
            "user_id": user_id,
            "authenticated": False,
            "last_seen": time.time(),
        }

        # 初始化用户的订阅
        self._subscriptions[user_id] = {}

        logger.info(f"WebSocket connected: {user_id}")
        return user_id

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        断开连接

        Args:
            websocket: WebSocket 连接
        """
        if websocket not in self._connections:
            return

        user_id = self._connections[websocket]["user_id"]

        # 从所有订阅中移除
        if user_id in self._subscriptions:
            for channel in list(self._subscriptions[user_id].keys()):
                self.unsubscribe(websocket, channel)
            del self._subscriptions[user_id]

        # 移除连接
        del self._connections[websocket]

        logger.info(f"WebSocket disconnected: {user_id}")

    def update_last_seen(self, websocket: WebSocket) -> None:
        """更新最后看到连接的时间"""
        if websocket in self._connections:
            import time
            self._connections[websocket]["last_seen"] = time.time()

    async def prune_stale_connections(self, timeout: float = 60.0) -> int:
        """
        清理过期的连接

        Args:
            timeout: 超时时间（秒）

        Returns:
            清理的连接数
        """
        import time
        now = time.time()
        stale = []

        for websocket, info in self._connections.items():
            if now - info.get("last_seen", 0) > timeout:
                stale.append(websocket)

        for websocket in stale:
            logger.warning(f"Pruning stale WebSocket connection: {info.get('user_id')}")
            try:
                await websocket.close(code=1000)
            except Exception:
                pass
            await self.disconnect(websocket)

        return len(stale)

    async def send_json(self, websocket: WebSocket, data: WSMessage) -> None:
        """
        发送 JSON 消息到指定连接

        Args:
            websocket: WebSocket 连接
            data: 消息数据
        """
        try:
            # 确保时间戳存在
            dumped_data = data.model_dump()
            if "timestamp" not in dumped_data or not dumped_data["timestamp"]:
                import time
                dumped_data["timestamp"] = int(time.time())
            await websocket.send_json(dumped_data)
        except Exception as e:
            logger.error(f"Error sending message to websocket: {e}")
            await self.disconnect(websocket)

    async def broadcast(self, data: WSMessage, channel: str = "*") -> int:
        """
        广播消息到所有订阅了指定频道的连接

        Args:
            data: 消息数据
            channel: 频道名称，"*" 表示广播给所有连接

        Returns:
            成功发送的连接数
        """
        sent_count = 0
        disconnected: list[WebSocket] = []

        if channel == "*":
            # 广播给所有连接
            for websocket in list(self._connections.keys()):
                try:
                    await self.send_json(websocket, data)
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error broadcasting to websocket: {e}")
                    disconnected.append(websocket)
        else:
            # 广播给订阅了指定频道的连接
            for user_id, channels in list(self._subscriptions.items()):
                if channel in channels:
                    for websocket in list(channels[channel]):
                        try:
                            await self.send_json(websocket, data)
                            sent_count += 1
                        except Exception as e:
                            logger.error(f"Error broadcasting to channel {channel}: {e}")
                            disconnected.append(websocket)

        # 清理断开的连接
        for websocket in disconnected:
            await self.disconnect(websocket)

        if sent_count > 0:
            logger.debug(f"Broadcasted to {sent_count} connections on channel: {channel}")

        return sent_count

    def subscribe(self, websocket: WebSocket, channel: str) -> bool:
        """
        订阅频道

        Args:
            websocket: WebSocket 连接
            channel: 频道名称，支持通配符如 "message:*"

        Returns:
            是否订阅成功
        """
        if websocket not in self._connections:
            return False

        user_id = self._connections[websocket]["user_id"]

        if channel not in self._subscriptions[user_id]:
            self._subscriptions[user_id][channel] = set()

        self._subscriptions[user_id][channel].add(websocket)
        logger.debug(f"User {user_id} subscribed to channel: {channel}")
        return True

    def unsubscribe(self, websocket: WebSocket, channel: str) -> bool:
        """
        取消订阅

        Args:
            websocket: WebSocket 连接
            channel: 频道名称

        Returns:
            是否取消成功
        """
        if websocket not in self._connections:
            return False

        user_id = self._connections[websocket]["user_id"]

        if channel in self._subscriptions.get(user_id, {}):
            self._subscriptions[user_id][channel].discard(websocket)
            if not self._subscriptions[user_id][channel]:
                del self._subscriptions[user_id][channel]
            logger.debug(f"User {user_id} unsubscribed from channel: {channel}")
            return True

        return False

    def is_authenticated(self, websocket: WebSocket) -> bool:
        """
        检查连接是否已认证

        Args:
            websocket: WebSocket 连接

        Returns:
            是否已认证
        """
        return self._connections.get(websocket, {}).get("authenticated", False)

    def set_authenticated(self, websocket: WebSocket, authenticated: bool) -> None:
        """
        设置连接认证状态

        Args:
            websocket: WebSocket 连接
            authenticated: 是否已认证
        """
        if websocket in self._connections:
            self._connections[websocket]["authenticated"] = authenticated

    def validate_token(self, token: str) -> bool:
        """
        验证 Token

        Args:
            token: 待验证的 Token

        Returns:
            是否有效
        """
        return token in self._valid_tokens

    def get_connection_id(self, websocket: WebSocket) -> Optional[str]:
        """
        获取连接 ID

        Args:
            websocket: WebSocket 连接

        Returns:
            连接 ID
        """
        return self._connections.get(websocket, {}).get("user_id")

    def get_connection_info(self, user_id: str) -> Optional[Dict[str, str]]:
        """
        获取连接信息

        Args:
            user_id: 用户 ID

        Returns:
            连接信息
        """
        for websocket, info in self._connections.items():
            if info.get("user_id") == user_id:
                return info
        return None

    async def handle_auth(self, websocket: WebSocket, message: WSAuthMessage) -> bool:
        """
        处理认证消息

        Args:
            websocket: WebSocket 连接
            message: 认证消息

        Returns:
            是否认证成功
        """
        if self.validate_token(message.token):
            self.set_authenticated(websocket, True)
            user_id = self.get_connection_id(websocket)

            # 发送认证成功响应
            ack = WSMessage(
                type="auth_ack",
                channel="system",
                timestamp=int(__import__("time").time()),
                payload={"user_id": user_id, "status": "authenticated"},
            )
            await self.send_json(websocket, ack)

            logger.info(f"WebSocket authenticated: {user_id}")
            return True
        else:
            # 认证失败
            ack = WSMessage(
                type="error",
                channel="system",
                timestamp=int(__import__("time").time()),
                payload={"error": "Invalid token", "code": 401},
            )
            await self.send_json(websocket, ack)
            return False

    async def handle_subscribe(self, websocket: WebSocket, message: WSSubscribeMessage) -> None:
        """
        处理订阅消息

        Args:
            websocket: WebSocket 连接
            message: 订阅消息
        """
        for channel in message.channels:
            self.subscribe(websocket, channel)
            logger.debug(f"Subscribed to channel: {channel}")

        # 发送订阅确认
        ack = WSMessage(
            type="event",
            channel="system",
            timestamp=int(__import__("time").time()),
            payload={"event": "subscribed", "channels": message.channels},
        )
        await self.send_json(websocket, ack)

    def get_connections_count(self) -> int:
        """获取活跃连接数"""
        return len(self._connections)

    def get_subscribers_count(self, channel: str) -> int:
        """
        获取指定频道的订阅者数量

        Args:
            channel: 频道名称

        Returns:
            订阅者数量
        """
        count = 0
        for user_id, channels in self._subscriptions.items():
            if channel in channels:
                count += len(channels[channel])
            elif "*" in channels:
                count += len(channels["*"])
        return count


# 全局连接管理器实例
_manager: ConnectionManager | None = None


def get_manager() -> ConnectionManager:
    """获取全局连接管理器实例"""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


__all__ = ["ConnectionManager", "get_manager"]