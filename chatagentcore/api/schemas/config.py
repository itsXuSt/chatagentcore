"""Configuration schemas using Pydantic"""

from typing import Literal
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthConfig(BaseModel):
    """认证配置"""

    type: Literal["fixed_token", "jwt"] = Field(default="fixed_token", description="认证类型")
    token: str = Field(default="", description="固定 API Token（当 type=fixed_token 时使用）")

    # JWT 配置（当 type=jwt 时使用）
    jwt_secret: str = Field(default="", description="JWT 密钥")
    jwt_algorithm: str = Field(default="HS256", description="JWT 算法")
    jwt_expire_hours: int = Field(default=24, description="JWT 过期时间（小时）")

    @field_validator("token")
    @classmethod
    def validate_fixed_token(cls, v: str, info) -> str:
        """验证固定 Token"""
        if info.data.get("type") == "fixed_token" and not v:
            raise ValueError("token is required when type is fixed_token")
        return v


class LoggingConfig(BaseModel):
    """日志配置"""

    level: str = Field(default="INFO", description="日志级别")
    file: str = Field(default="logs/chatagentcore.log", description="日志文件路径")
    rotation: str = Field(default="10 MB", description="日志轮转大小")
    retention: str = Field(default="30 days", description="日志保留时间")


class PlatformConfig(BaseModel):
    """平台配置基类"""

    enabled: bool = Field(default=False, description="是否启用此平台")
    type: str = Field(default="app", description="平台类型：app | group")


class FeishuConfig(PlatformConfig):
    """飞书配置"""

    app_id: str = Field(default="", description="飞书应用 ID")
    app_secret: str = Field(default="", description="飞书应用密钥")
    verification_token: str = Field(default="", description="验证令牌（Webhook 验证使用）")
    encrypt_key: str = Field(default="", description="加密密钥（可选）")
    connection_mode: Literal["websocket", "webhook"] = Field(default="websocket", description="连接模式：websocket(推荐) | webhook")
    domain: Literal["feishu", "lark"] = Field(default="feishu", description="域名：feishu | lark")

    @field_validator("app_id", "app_secret")
    @classmethod
    def validate_feishu_keys(cls, v: str, info) -> str:
        """验证飞书配置"""
        if info.data.get("enabled") and not v:
            raise ValueError(f"{info.field_name} is required when platform is enabled")
        return v


class WecomConfig(PlatformConfig):
    """企业微信配置"""

    corp_id: str = Field(default="", description="企业 ID")
    agent_id: str = Field(default="", description="应用 ID")
    secret: str = Field(default="", description="应用密钥")
    token: str = Field(default="", description="令牌")
    encoding_aes_key: str = Field(default="", description="加密密钥")

    @field_validator("corp_id", "agent_id", "secret", "token", "encoding_aes_key")
    @classmethod
    def validate_wecom_keys(cls, v: str, info) -> str:
        """验证企业微信配置"""
        if info.data.get("enabled") and not v:
            raise ValueError(f"{info.field_name} is required when platform is enabled")
        return v


class DingTalkConfig(PlatformConfig):
    """钉钉配置"""

    app_key: str = Field(default="", description="应用 Key (Client ID)")
    app_secret: str = Field(default="", description="应用密钥 (Client Secret)")
    connection_mode: Literal["websocket", "webhook"] = Field(default="websocket", description="连接模式：websocket(推荐) | webhook")
    
    # 以下用于 Webhook 模式，Stream 模式不需要
    token: str = Field(default="", description="令牌")
    aes_key: str = Field(default="", description="AES 密钥")

    @field_validator("app_key", "app_secret")
    @classmethod
    def validate_dingtalk_keys(cls, v: str, info) -> str:
        """验证钉钉配置"""
        if info.data.get("enabled") and not v:
            raise ValueError(f"{info.field_name} is required when platform is enabled")
        return v


class QQConfig(PlatformConfig):
    """QQ 机器人配置"""

    app_id: str = Field(default="", description="机器人 AppID")
    token: str = Field(default="", description="机器人 Token (AppSecret)")
    
    @field_validator("app_id", "token")
    @classmethod
    def validate_qq_keys(cls, v: str, info) -> str:
        """验证 QQ 配置"""
        if info.data.get("enabled") and not v:
            raise ValueError(f"{info.field_name} is required when platform is enabled")
        return v


class PlatformsConfig(BaseModel):
    """所有平台配置"""

    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    wecom: WecomConfig = Field(default_factory=WecomConfig)
    dingtalk: DingTalkConfig = Field(default_factory=DingTalkConfig)
    qq: QQConfig = Field(default_factory=QQConfig)


class ServerConfig(BaseModel):
    """服务器配置"""

    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(default=8000, description="监听端口")
    debug: bool = Field(default=False, description="调试模式")


class Settings(BaseSettings):
    """应用配置（支持从环境变量和文件加载）"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CAC_",  # 环境变量前缀
        case_sensitive=False,
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    platforms: PlatformsConfig = Field(default_factory=PlatformsConfig)

    # 可选：从 YAML 文件加载的配置路径
    config_file: str = Field(default="config/config.yaml", description="配置文件路径")


__all__ = [
    "Settings",
    "ServerConfig",
    "AuthConfig",
    "LoggingConfig",
    "PlatformsConfig",
    "PlatformConfig",
    "FeishuConfig",
    "WecomConfig",
    "DingTalkConfig",
    "QQConfig",
]
