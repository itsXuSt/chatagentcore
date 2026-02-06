"""Configuration manager with YAML support and hot reload"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any, Optional, Callable
import yaml
from loguru import logger
from chatagentcore.api.schemas.config import Settings, PlatformsConfig


class ConfigManager:
    """配置管理器 - 支持加载、热重载和验证"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self.version: int = 0
        self._config: Settings | None = None
        self._raw_config: Dict[str, Any] = {}
        self._reload_task: asyncio.Task | None = None
        self._reload_interval: float = 5.0  # 秒
        self._callbacks: list[Callable[[Settings], None]] = []

    def load(self) -> Settings:
        """
        加载配置文件

        Returns:
            配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            yaml.YAMLError: YAML 解析错误
            ValueError: 配置验证失败
        """
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            self._config = Settings()
            self._raw_config = {}
            return self._config

        logger.info(f"Loading config from: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._raw_config = yaml.safe_load(f) or {}

        # 构建 Pydantic Settings 对象
        self._config = self._raw_config_to_settings(self._raw_config)

        # 验证配置
        self._validate_config(self._config)

        self.version += 1
        logger.info(f"Config loaded successfully (v{self.version})")
        return self._config

    def reload(self) -> Settings:
        """
        重新加载配置

        Returns:
            更新后的配置对象
        """
        logger.info("Reloading config...")
        old_config = self._config
        self.load()

        # 触发回调通知配置变更
        for callback in self._callbacks:
            try:
                callback(self._config)
            except Exception as e:
                logger.error(f"Error in config callback: {e}")

        if old_config != self._config:
            logger.info("Config changed")
        else:
            logger.info("Config unchanged")

        return self._config

    async def watch(self, interval: float = 5.0) -> None:
        """
        监控配置文件变化并自动重载

        Args:
            interval: 检查间隔（秒）
        """
        self._reload_interval = interval
        self._reload_task = asyncio.create_task(self._watch_loop())
        logger.info(f"Config watch task started (interval: {interval}s)")

    async def stop_watch(self) -> None:
        """停止监控"""
        if self._reload_task:
            self._reload_task.cancel()
            try:
                await self._reload_task
            except asyncio.CancelledError:
                pass
            logger.info("Config watch task stopped")

    def on_change(self, callback: Callable[[Settings], None]) -> None:
        """
        注册配置变更回调

        Args:
            callback: 回调函数，接收新的 Settings 对象
        """
        self._callbacks.append(callback)

    @property
    def config(self) -> Settings:
        """
        获取当前配置

        Returns:
            配置对象

        Raises:
            RuntimeError: 配置未加载
        """
        if self._config is None:
            raise RuntimeError("Config not loaded. Call load() first.")
        return self._config

    @property
    def platforms(self) -> PlatformsConfig:
        """获取平台配置"""
        return self.config.platforms

    def _raw_config_to_settings(self, raw: Dict[str, Any]) -> Settings:
        """将原始配置字典转换为 Settings 对象"""
        # 这里可以根据需要实现更复杂的转换逻辑
        return Settings.model_validate(raw)

    def _validate_config(self, config: Settings) -> None:
        """验证配置"""
        # 检查是否至少启用了一个平台
        enabled_platforms = [
            name for name, platform in [
                ("feishu", config.platforms.feishu),
                ("wecom", config.platforms.wecom),
                ("dingtalk", config.platforms.dingtalk),
                ("qq", config.platforms.qq),
            ]
            if platform.enabled
        ]

        if not enabled_platforms:
            logger.warning("No platform enabled")

        # 检查认证配置
        if config.auth.type == "fixed_token" and not config.auth.token:
            logger.warning("auth.token is required when auth.type is fixed_token")

        if config.auth.type == "jwt" and not config.auth.jwt_secret:
            logger.warning("auth.jwt_secret is required when auth.type is jwt")

        logger.info(f"Enabled platforms: {enabled_platforms or 'None'}")

    async def _watch_loop(self) -> None:
        """监控循环"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return

        last_mtime = self.config_path.stat().st_mtime

        try:
            while True:
                await asyncio.sleep(self._reload_interval)

                if not self.config_path.exists():
                    logger.warning(f"Config file disappeared: {self.config_path}")
                    break

                current_mtime = self.config_path.stat().st_mtime
                if current_mtime != last_mtime:
                    logger.info("Config file changed, reloading...")
                    try:
                        self.reload()
                        last_mtime = current_mtime
                    except Exception as e:
                        logger.error(f"Failed to reload config: {e}")
        except asyncio.CancelledError:
            # 正常退出
            pass

    def to_dict(self) -> Dict[str, Any]:
        """
        将配置转为字典

        Returns:
            配置字典
        """
        if self._config is None:
            return {}
        return self._config.model_dump()


# 全局配置管理器实例
_config_manager: ConfigManager | None = None


def get_config_manager(config_path: str = "config/config.yaml") -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_path)
    return _config_manager


def get_config() -> Settings:
    """获取当前配置（快捷方式）"""
    return get_config_manager().config


__all__ = ["ConfigManager", "get_config_manager", "get_config"]
