#!/usr/bin/env python3
"""QQ Bot 双向对话测试工具

支持接收 QQ 频道/群消息并通过命令行回复，实现双向对话功能。
"""

import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from loguru import logger
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from chatagentcore.core.config_manager import get_config_manager
# Import QQ Adapter related classes
try:
    import botpy
    from chatagentcore.adapters.qq.client import QQBotClient, _run_bot_in_thread, Message
    HAS_BOTPY = True
except ImportError:
    HAS_BOTPY = False

class ChatSession:
    """会话状态管理"""

    def __init__(self):
        self.client: Optional[QQBotClient] = None
        self.app_id: str = ""
        self.token: str = ""
        
        self.target_id: Optional[str] = None
        self.target_type: str = "user" # user, group, guild
        self.last_msg_id: str = "0"
        
        self.last_sender_id: Optional[str] = None
        self.last_target_type: str = "user"
        
        self.message_count = 0
        self.running = True
        self.send_loop: Optional[asyncio.AbstractEventLoop] = None


# 全局会话实例
CHAT_SESSION = ChatSession()


def print_welcome_banner() -> None:
    """打印欢迎界面"""
    banner = """
╔════════════════════════════════════════════════════════════╗
║            QQ Bot 双向对话工具                             ║
║       ChatAgentCore - QQ Interactive Chat                   ║
╚════════════════════════════════════════════════════════════╝

使用说明:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 确保已在 config/config.yaml 中配置 QQ AppID 和 Token
2. 确保 QQ 机器人已加入群或频道
3. 向机器人发送消息建立会话
4. 命令行直接输入文本回复消息
5. 命令:
   /status      - 查看连接状态
   /set <ID> <Type> - 设置回复目标 (Type: user, group, guild)
   /help        - 显示帮助
   /quit        - 退出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    print(banner)


def print_message_received(msg: Message):
    """打印接收到的消息"""
    timestamp = datetime.fromtimestamp(msg.timestamp) if msg.timestamp else datetime.now()
    sender_name = msg.sender.get("name", "User")
    sender_id = msg.sender.get("id", "")
    content = msg.content.get("text", "")
    conv_type = msg.conversation.get("type", "unknown")
    conv_id = msg.conversation.get("id", "")

    print(f"\n[{timestamp.strftime('%H:%M:%S')}] 📨 {sender_name} ({sender_id}) [{conv_type}]:")
    print("-" * 60)
    print(content)
    print("-" * 60)
    print(f"\n回复: ", end="", flush=True)


def message_handler(msg: Message):
    """处理接收到的消息"""
    CHAT_SESSION.message_count += 1
    CHAT_SESSION.last_msg_id = msg.message_id
    
    # 更新会话目标
    sender_id = msg.sender.get("id")
    conv_id = msg.conversation.get("id")
    conv_type = msg.conversation.get("type")
    
    if conv_type == "group":
        CHAT_SESSION.last_sender_id = conv_id # Reply to group
        CHAT_SESSION.last_target_type = "group"
    elif conv_type == "guild":
        CHAT_SESSION.last_sender_id = conv_id # Reply to channel
        CHAT_SESSION.last_target_type = "guild"
    else: # user
        CHAT_SESSION.last_sender_id = sender_id
        CHAT_SESSION.last_target_type = "user"
        
    # 如果没有设置目标，自动锁定当前会话
    if not CHAT_SESSION.target_id:
        CHAT_SESSION.target_id = CHAT_SESSION.last_sender_id
        CHAT_SESSION.target_type = CHAT_SESSION.last_target_type
        print(f"[系统] 已锁定会话目标: {CHAT_SESSION.target_id} ({CHAT_SESSION.target_type})")
        
    print_message_received(msg)


def run_qq_bot(session: ChatSession):
    """运行 QQ Bot"""
    # Create a loop for initialization (botpy requires get_event_loop() in __init__)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    intents = botpy.Intents(public_messages=True, public_guild_messages=True)
    
    # Mock adapter as None since it's not used in critical path of Client
    session.client = QQBotClient(
        intents=intents,
        message_handler=message_handler,
        adapter=None
    )
    
    # 使用 helper 函数运行在当前线程（这里已经是子线程了）
    # 但 _run_bot_in_thread 会创建新 loop。
    # 我们直接调用 _run_bot_in_thread
    try:
        _run_bot_in_thread(session.client, session.app_id, session.token)
    except Exception as e:
        logger.error(f"QQ Bot 运行异常: {e}")
        session.running = False
    finally:
        # Close the init loop
        try:
            loop.close()
        except:
            pass


def _run_async_in_loop(coro) -> Any:
    """在共享的事件循环中运行异步任务"""
    if CHAT_SESSION.send_loop is None or CHAT_SESSION.send_loop.is_closed():
        # 如果 loop 关闭了，我们没法简单重启，因为这是在主线程调用的
        logger.error("发送循环未运行")
        return False

    try:
        future = asyncio.run_coroutine_threadsafe(coro, CHAT_SESSION.send_loop)
        return future.result(timeout=30)
    except Exception as e:
        logger.error(f"运行异步任务失败: {e}")
        print(f"❌ 发送失败: {e}")
        return False


async def send_reply(text: str) -> bool:
    """发送回复消息"""
    if not CHAT_SESSION.client or not CHAT_SESSION.client.api or not CHAT_SESSION.client.loop:
        print("❌ 客户端未就绪")
        return False
        
    target = CHAT_SESSION.target_id
    ttype = CHAT_SESSION.target_type
    
    if not target:
        print("❌ 未设置回复目标，请先接收消息或使用 /set")
        return False
        
    logger.info(f"发送消息到: {target} ({ttype})")
    
    try:
        msg_id_to_reply = CHAT_SESSION.last_msg_id
        
        async def _do_send():
            if ttype == "group":
                res = await CHAT_SESSION.client.api.post_group_message(
                    group_openid=target,
                    msg_type=0, 
                    msg_id=msg_id_to_reply, 
                    content=text
                )
                return res.get("id", "")
                
            elif ttype == "user":
                res = await CHAT_SESSION.client.api.post_c2c_message(
                    openid=target,
                    msg_type=0,
                    msg_id=msg_id_to_reply, 
                    content=text
                )
                return res.get("id", "")
                
            elif ttype == "guild":
                 res = await CHAT_SESSION.client.api.post_message(
                     channel_id=target,
                     content=text
                 )
                 return res.get("id", "")
            return ""

        # IMPORTANT: Run the API call on the BOT's loop
        future = asyncio.run_coroutine_threadsafe(_do_send(), CHAT_SESSION.client.loop)
        msg_id = await asyncio.wrap_future(future)
             
        if msg_id:
            print(f"✅ 发送成功")
            return True
        else:
            print("❌ 发送可能失败 (无 ID 返回)")
            return False
            
    except Exception as e:
        print(f"❌ 发送异常: {e}")
        return False


def main():
    print_welcome_banner()
    
    if not HAS_BOTPY:
        print("❌ 未安装 qq-botpy，请运行: pip install qq-botpy")
        return

    # 加载配置
    config_manager = get_config_manager()
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        return
        
    config_manager.config_path = config_path
    config_manager.load()
    
    qq_config = config_manager.config.platforms.qq
    if not qq_config.enabled:
        print("❌ QQ 平台未在配置中启用")
        return
        
    CHAT_SESSION.app_id = qq_config.app_id
    CHAT_SESSION.token = qq_config.token
    
    if not CHAT_SESSION.app_id or not CHAT_SESSION.token:
        print("❌ 配置中缺少 app_id 或 token")
        return

    # 初始化发送循环
    send_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(send_loop)
    CHAT_SESSION.send_loop = send_loop

    def run_event_loop():
        asyncio.set_event_loop(send_loop)
        asyncio.run(send_loop.run_forever())

    loop_thread = threading.Thread(target=run_event_loop, daemon=True)
    loop_thread.start()
    
    # 启动 QQ Bot 线程
    bot_thread = threading.Thread(target=run_qq_bot, args=(CHAT_SESSION,), daemon=True)
    bot_thread.start()
    
    print("⏳ 正在启动 QQ Bot...")
    time.sleep(2)
    print("✅ 后台线程已启动 (请关注日志输出确认连接成功)")
    print("回复: ", end="", flush=True)

    # 主循环
    while CHAT_SESSION.running:
        try:
            user_input = input().strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
                break
                
            if user_input.lower() == "/status":
                print(f"消息数: {CHAT_SESSION.message_count}")
                print(f"当前目标: {CHAT_SESSION.target_id} ({CHAT_SESSION.target_type})")
                
            elif user_input.startswith("/set"):
                parts = user_input.split()
                if len(parts) == 3:
                    CHAT_SESSION.target_id = parts[1]
                    CHAT_SESSION.target_type = parts[2]
                    print(f"✅ 目标已更新: {CHAT_SESSION.target_id} ({CHAT_SESSION.target_type})")
                else:
                    print("❌ 用法: /set <ID> <Type>")
            
            elif user_input == "/help":
                print("Commands: /status, /set <ID> <Type>, /quit")
                
            else:
                _run_async_in_loop(send_reply(user_input))
                
            print("回复: ", end="", flush=True)
            
        except (KeyboardInterrupt, EOFError):
            break
            
    print("再见!")

if __name__ == "__main__":
    main()
