"""Unified message models"""

from typing import Any, Dict, Optional, Literal
from pydantic import BaseModel, Field


class SenderInfo(BaseModel):
    """发送者信息"""

    id: str = Field(..., description="发送者 ID")
    name: str = Field("", description="发送者名称")
    avatar: str = Field("", description="头像 URL")


class ConversationInfo(BaseModel):
    """会话信息"""

    id: str = Field(..., description="会话 ID")
    type: str = Field(..., description="会话类型")
    name: str = Field("", description="会话名称")


class MessageContent(BaseModel):
    """消息内容"""

    type: str = Field(..., description="内容类型")
    text: str = Field("", description="文本内容")
    url: str = Field("", description="媒体 URL（图片、文件等）")
    data: Dict[str, Any] = Field(default_factory=dict, description="附加数据")


class Message(BaseModel):
    """统一消息格式"""

    platform: str = Field(..., description="平台名称: feishu | wecom | dingtalk")
    message_id: str = Field(..., description="消息 ID")
    sender: SenderInfo = Field(..., description="发送者信息")
    conversation: ConversationInfo = Field(..., description="会话信息")
    content: MessageContent = Field(..., description="消息内容")
    timestamp: int = Field(..., description="Unix 时间戳")

    model_config = {"json_schema_extra": {"example": {
        "platform": "feishu",
        "message_id": "msg_123456",
        "sender": {"id": "user_123", "name": "张三", "avatar": ""},
        "conversation": {"id": "conv_123", "type": "group", "name": "技术群"},
        "content": {"type": "text", "text": "你好", "url": "", "data": {}},
        "timestamp": 1700000000
    }}}


class SendMessageRequest(BaseModel):
    """发送消息请求"""

    platform: str = Field(..., description="平台名称")
    to: str = Field(..., description="接收者 ID（用户 ID 或群 ID）")
    message_type: str = Field("text", description="消息类型: text, card, image等")
    content: str = Field(..., description="消息内容")
    conversation_type: str = Field("user", description="会话类型: user/group, 兼容chat")


class SendMessageResponse(BaseModel):
    """发送消息响应"""

    code: int = Field(0, description="状态码: 0 成功，非 0 失败")
    message: str = Field("success", description="响应消息")
    data: Optional[Dict[str, str]] = Field(None, description="响应数据")
    timestamp: int = Field(..., description="Unix 时间戳")


class MessageStatusRequest(BaseModel):
    """消息状态查询请求"""

    platform: str = Field(..., description="平台名称")
    message_id: str = Field(..., description="消息 ID")


class MessageStatusResponse(BaseModel):
    """消息状态响应"""

    code: int = Field(0, description="状态码")
    message: str = Field("success", description="响应消息")
    data: Optional[Dict[str, Any]] = Field(None, description="状态数据")
    timestamp: int = Field(..., description="Unix 时间戳")


class ConversationListRequest(BaseModel):
    """会话列表查询请求"""

    platform: str = Field(..., description="平台名称")
    limit: int = Field(50, description="每页数量", ge=1, le=100)
    cursor: Optional[str] = Field(None, description="分页游标")


class ConversationInfoResponse(BaseModel):
    """会话信息响应"""

    conversation_id: str = Field(..., description="会话 ID")
    type: Literal["user", "group"] = Field(..., description="会话类型")
    name: str = Field("", description="会话名称")
    unread_count: int = Field(0, description="未读消息数")


class ConversationListResponse(BaseModel):
    """会话列表响应"""

    code: int = Field(0, description="状态码")
    message: str = Field("success", description="响应消息")
    data: Optional[Dict[str, Any]] = Field(None, description="会话列表数据")
    timestamp: int = Field(..., description="Unix 时间戳")


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""

    platform: str = Field(..., description="平台名称")
    enabled: Optional[bool] = Field(None, description="是否启用")


class ConfigResponse(BaseModel):
    """配置响应"""

    code: int = Field(0, description="状态码")
    message: str = Field("success", description="响应消息")
    data: Optional[Dict[str, Any]] = Field(None, description="配置数据")
    timestamp: int = Field(..., description="Unix 时间戳")


class ErrorResponse(BaseModel):
    """错误响应"""

    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误消息")
    data: Optional[Dict[str, Any]] = Field(None, description="错误详情")
    timestamp: int = Field(..., description="Unix 时间戳")


# WebSocket 消息类型
class WSAuthMessage(BaseModel):
    """WebSocket 认证消息"""

    type: Literal["auth"] = "auth"
    token: str = Field(..., description="认证 Token")


class WSSubscribeMessage(BaseModel):
    """WebSocket 订阅消息"""

    type: Literal["subscribe"] = "subscribe"
    channels: list[str] = Field(..., description="要订阅的频道列表")


class WSPingMessage(BaseModel):
    """WebSocket Ping 消息"""

    type: Literal["ping"] = "ping"
    timestamp: int = Field(..., description="时间戳")


class WSMessage(BaseModel):
    """WebSocket 消息"""

    type: Literal["message", "event", "error", "auth_ack", "ping", "pong"] = Field(..., description="消息类型")
    channel: str = Field("", description="频道名称")
    timestamp: int = Field(..., description="时间戳")
    payload: Optional[Dict[str, Any]] = Field(None, description="消息内容")


__all__ = [
    "SenderInfo",
    "ConversationInfo",
    "MessageContent",
    "Message",
    "SendMessageRequest",
    "SendMessageResponse",
    "MessageStatusRequest",
    "MessageStatusResponse",
    "ConversationListRequest",
    "ConversationInfoResponse",
    "ConversationListResponse",
    "ConfigUpdateRequest",
    "ConfigResponse",
    "ErrorResponse",
    "WSAuthMessage",
    "WSSubscribeMessage",
    "WSPingMessage",
    "WSMessage",
]
