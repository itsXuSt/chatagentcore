"""QQ Adapter Client using botpy"""

import asyncio
import threading
import json
import uuid
import time
from typing import Any, Callable, Dict, Optional
from loguru import logger

try:
    import botpy
    from botpy.message import Message as BotpyMessage, GroupMessage, C2CMessage
    from botpy.types.message import Message as MessagePayload
    HAS_BOTPY = True
except ImportError:
    HAS_BOTPY = False
    logger.warning("botpy not installed, run: pip install qq-botpy")

from chatagentcore.adapters.base import BaseAdapter, Message


class QQBotClient(botpy.Client):
    """Custom BotPy Client to handle events"""
    
    def __init__(self, intents: "botpy.Intents", message_handler: Optional[Callable[[Message], None]], adapter: "QQAdapter"):
        super().__init__(intents=intents)
        self.message_handler = message_handler
        self.adapter = adapter
        self.robot_info = None

    async def on_ready(self):
        self.robot_info = self.robot
        logger.info(f"QQ Bot 「{self.robot.name}」 is ready!")

    async def on_at_message_create(self, message: BotpyMessage):
        """Handle Guild @Bot messages"""
        self._handle_message(message, "guild")

    async def on_group_at_message_create(self, message: GroupMessage):
        """Handle Group @Bot messages"""
        self._handle_message(message, "group")

    async def on_c2c_message_create(self, message: C2CMessage):
        """Handle Private messages"""
        self._handle_message(message, "user")

    def _handle_message(self, message: Any, conversation_type: str):
        """Convert and dispatch message"""
        try:
            # Extract content
            content_str = getattr(message, "content", "")
            
            # Construct sender info
            # GroupMessage/C2CMessage has author as Member/User object
            author = getattr(message, "author", None)
            sender_id = ""
            if author:
                sender_id = getattr(author, "id", "") or getattr(author, "user_openid", "") or getattr(author, "member_openid", "")
            
            # Fallback if author object doesn't have what we expect (BotPy structure can vary)
            if not sender_id:
                # Try direct attributes on message (some events might flatten it)
                sender_id = getattr(message, "author_id", "") 

            sender_name = "User" # hard to get name sometimes without extra API call
            
            # Construct conversation info
            conversation_id = ""
            if conversation_type == "group":
                conversation_id = getattr(message, "group_openid", "")
            elif conversation_type == "guild":
                conversation_id = getattr(message, "channel_id", "")
            elif conversation_type == "user":
                conversation_id = sender_id # for C2C, conv id is usually the user openid

            # Store the message_id for potential replies
            msg_id = getattr(message, "id", "")
            if msg_id and conversation_id and self.adapter:
                self.adapter._last_msg_ids[conversation_id] = msg_id

            msg_obj = Message(
                platform="qq",
                message_id=msg_id,
                sender={"id": sender_id, "name": sender_name, "type": "user"},
                conversation={"id": conversation_id, "type": conversation_type},
                content={"type": "text", "text": content_str},
                timestamp=int(time.time()) # Timestamp is often not readily available in simple format
            )
            
            if self.message_handler:
                self.message_handler(msg_obj)
            else:
                logger.warning("No message handler set for QQ adapter")
                
        except Exception as e:
            logger.error(f"Error handling QQ message: {e}")


def _run_bot_in_thread(client: QQBotClient, appid: str, secret: str):
    """Run bot in a separate thread with its own loop"""
    # Create new loop for this thread
    # We need to set the event loop for this thread so botpy can find it
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # IMPORTANT: Update client's loop to the new thread loop
    # because client might have been initialized in a different thread
    client.loop = loop
    
    try:
        logger.info(f"Starting QQ Bot with AppID: {appid}")
        # botpy client needs to be initialized with intents, done in __init__
        # but we need to pass appid/secret to run/start
        
        # We use run() which is blocking and handles the loop
        client.run(appid=appid, secret=secret)
    except Exception as e:
        logger.error(f"QQ Bot crashed: {e}")
    finally:
        try:
            loop.close()
        except:
            pass


class QQAdapter(BaseAdapter):
    """QQ Platform Adapter"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.app_id = config.get("app_id")
        self.token = config.get("token") # This is AppSecret
        self.client: Optional[QQBotClient] = None
        self._thread: Optional[threading.Thread] = None
        self._message_handler: Optional[Callable[[Message], None]] = None
        # Cache for last message IDs to support passive replies
        self._last_msg_ids: Dict[str, str] = {}

    async def initialize(self) -> None:
        if not HAS_BOTPY:
            raise ImportError("qq-botpy is not installed")
        
        if not self.app_id or not self.token:
            logger.error("QQ Adapter requires app_id and token (secret)")
            return

        logger.info(f"Initializing QQ Adapter (AppID: {self.app_id})")
        
        # Initialize Intents
        # Enable public messages (group/c2c) and guild messages
        intents = botpy.Intents(public_messages=True, public_guild_messages=True)
        
        self.client = QQBotClient(
            intents=intents, 
            message_handler=self._message_handler,
            adapter=self
        )
        
        # Run in thread
        self._thread = threading.Thread(
            target=_run_bot_in_thread,
            args=(self.client, self.app_id, self.token),
            daemon=True,
            name="QQBotThread"
        )
        self._thread.start()
        # Wait a bit for thread to start (optional)
        await asyncio.sleep(0.5)

    async def shutdown(self) -> None:
        if self.client:
            # client.close() is async
            # We need to call it from a loop. 
            # But the client is running in another loop/thread.
            # botpy doesn't have a thread-safe close method easily accessible from outside?
            # Actually client.close() just sets self._closed = True and awaits http.close().
            # It should be safe to call if we can schedule it on the client's loop?
            # Or just set _closed flag if we could access it.
            
            # Simple approach: let the thread die when main process dies (daemon=True)
            # But for clean shutdown:
            try:
                # We can't easily await client.close() because it needs to run on client's loop
                # If we assume client.run() checks _closed, maybe we can just close the loop?
                pass
            except Exception as e:
                logger.error(f"Error closing QQ client: {e}")
                
        logger.info("QQ Adapter shutdown")

    def set_message_handler(self, handler: Callable[[Message], None]):
        self._message_handler = handler
        if self.client:
            self.client.message_handler = handler

    async def send_message(
        self, to: str, message_type: str, content: str, conversation_type: str = "user"
    ) -> str:
        if not self.client or not self.client.api or not self.client.loop:
            raise RuntimeError("QQ Client not ready")
        
        # Fallback for empty conversation_type from client
        if not conversation_type:
            logger.warning(f"Empty conversation_type for QQ message to {to}, defaulting to 'user'")
            conversation_type = "user"
            
        try:
            # Use the last received message_id as msg_id for passive reply
            msg_id_to_reply = self._last_msg_ids.get(to, "0")
            
            # The actual API call that MUST run on the client's loop
            async def _do_send():
                try:
                    res = None
                    if conversation_type == "group":
                        res = await self.client.api.post_group_message(
                            group_openid=to,
                            msg_type=0, 
                            msg_id=msg_id_to_reply, 
                            content=content
                        )
                    elif conversation_type == "user":
                        res = await self.client.api.post_c2c_message(
                            openid=to,
                            msg_type=0,
                            msg_id=msg_id_to_reply, 
                            content=content
                        )
                    elif conversation_type == "guild":
                        res = await self.client.api.post_message(
                            channel_id=to,
                            content=content
                        )
                    
                    # Log response for debugging
                    logger.info(f"QQ API Response ({conversation_type}, reply_to={msg_id_to_reply}): {res}")
                    
                    if res is None:
                        return ""
                    
                    # Handle both dict and object response types from botpy
                    if isinstance(res, dict):
                        return res.get("id", res.get("msg_id", ""))
                    else:
                        return getattr(res, "id", getattr(res, "msg_id", ""))
                        
                except Exception as e:
                    logger.error(f"QQ API internal error during _do_send: {e}", exc_info=True)
                    return ""

            # Submit the coroutine to the client's loop and wait for it
            # This fixes "Timeout context manager should be used inside a task" error
            future = asyncio.run_coroutine_threadsafe(_do_send(), self.client.loop)
            # Wrap the concurrent.futures.Future into an asyncio.Future and await it
            return await asyncio.wrap_future(future)
            
        except Exception as e:
            logger.error(f"Failed to send QQ message: {e}")
            raise e
