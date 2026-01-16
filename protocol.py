
import json
import time
import uuid
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional,Tuple

class MessageType(Enum):
    MESSAGE = "message"
    PRIVATE_MESSAGE = "private_message"
    ACK = "ack"
    JOIN = "join"
    LEAVE = "leave"
    USER_LIST = "user_list"
    HEARTBEAT = "heartbeat"
    ERROR = "error"

@dataclass
class Packet:
    message_type: str
    sender: str
    timestamp: float
    message_id: str
    content: str
    recipient: Optional[str] = None
    
    def to_json(self) -> str:
        """Convert packet to JSON string for transmission"""
        return json.dumps(asdict(self))
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Packet':
        """Create packet from JSON string"""
        data = json.loads(json_str)
        return cls(**data)
    
    @classmethod
    def create_message(cls, sender: str, content: str, recipient: Optional[str] = None) -> 'Packet':
        """Create a message packet"""
        return cls(
            message_type=MessageType.MESSAGE.value,
            sender=sender,
            timestamp=time.time(),
            message_id=str(uuid.uuid4()),
            content=content,
            recipient=recipient
        )
    
    @classmethod
    def create_ack(cls, sender: str, original_message_id: str) -> 'Packet':
        """Create an ACK packet"""
        return cls(
            message_type=MessageType.ACK.value,
            sender=sender,
            timestamp=time.time(),
            message_id=str(uuid.uuid4()),
            content=original_message_id
        )
    
    @classmethod
    def create_join(cls, sender: str) -> 'Packet':
        """Create a join packet"""
        return cls(
            message_type=MessageType.JOIN.value,
            sender=sender,
            timestamp=time.time(),
            message_id=str(uuid.uuid4()),
            content="join_request"
        )
    
    @classmethod
    def create_leave(cls, sender: str) -> 'Packet':
        """Create a leave packet"""
        return cls(
            message_type=MessageType.LEAVE.value,
            sender=sender,
            timestamp=time.time(),
            message_id=str(uuid.uuid4()),
            content="leave_request"
        )
    
    @classmethod
    def create_user_list(cls, sender: str, users: Dict[str, Tuple[str, int]]) -> 'Packet':
        """Create a user list packet containing usernames and their addresses."""
        return cls(
            message_type=MessageType.USER_LIST.value,
            sender=sender,
            timestamp=time.time(),
            message_id=str(uuid.uuid4()),
            content=json.dumps(users)
        )
    
    @classmethod
    def create_heartbeat(cls, sender: str) -> 'Packet':
        """Create a heartbeat packet"""
        return cls(
            message_type=MessageType.HEARTBEAT.value,
            sender=sender,
            timestamp=time.time(),
            message_id=str(uuid.uuid4()),
            content="heartbeat"
        )
    
    @classmethod
    def create_private_message(cls, sender: str, recipient: str, content: str) -> 'Packet':
        """Create a private message packet"""
        return cls(
            message_type=MessageType.PRIVATE_MESSAGE.value,
            sender=sender,
            timestamp=time.time(),
            message_id=str(uuid.uuid4()),
            content=content,
            recipient=recipient
        )

class PacketParser:
    @staticmethod
    def parse(data: bytes) -> Optional[Packet]:
        """Parse incoming packet data"""
        try:
            json_str = data.decode('utf-8')
            return Packet.from_json(json_str)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as e:
            print(f"Error parsing packet: {e}")
            return None
    
    @staticmethod
    def serialize(packet: Packet) -> bytes:
        """Serialize packet for transmission"""
        return packet.to_json().encode('utf-8')
