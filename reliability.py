
import time
import threading
import socket
from typing import Dict, Callable, Tuple, Optional
from protocol import Packet, PacketParser, MessageType
import logging

class ReliableUDP:
    def __init__(self, sock: socket.socket, ack_timeout: float = 3.0, max_retries: int = 3):
        self.sock = sock
        self.ack_timeout = ack_timeout
        self.max_retries = max_retries
        self.pending_messages: Dict[str, Dict] = {}
        self.ack_callbacks: Dict[str, Callable] = {}
        self.running = True
        self.lock = threading.Lock()
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Start the timeout checker thread
        self.timeout_thread = threading.Thread(target=self._check_timeouts, daemon=True)
        self.timeout_thread.start()
    
    def send_reliable(self, packet: Packet, addr: Tuple[str, int], 
                     on_ack: Optional[Callable] = None, on_timeout: Optional[Callable] = None):
        """Send a packet reliably with ACK mechanism"""
        if packet.message_type == MessageType.ACK.value:
            # ACKs don't need reliability
            self._send_packet(packet, addr)
            return
        
        with self.lock:
            self.pending_messages[packet.message_id] = {
                'packet': packet,
                'addr': addr,
                'sent_time': time.time(),
                'retries': 0,
                'on_ack': on_ack,
                'on_timeout': on_timeout
            }
        
        self._send_packet(packet, addr)
        self.logger.info(f"Sent reliable message {packet.message_id} to {addr}")
    
    def _send_packet(self, packet: Packet, addr: Tuple[str, int]):
        """Send a packet without reliability"""
        try:
            data = PacketParser.serialize(packet)
            self.sock.sendto(data, addr)
        except Exception as e:
            self.logger.error(f"Error sending packet: {e}")
    
    def handle_ack(self, ack_packet: Packet):
        """Handle received ACK packet"""
        original_message_id = ack_packet.content
        
        with self.lock:
            if original_message_id in self.pending_messages:
                pending = self.pending_messages.pop(original_message_id)
                delivery_time = time.time() - pending['sent_time']
                
                self.logger.info(f"ACK received for message {original_message_id}, "
                               f"delivery time: {delivery_time:.3f}s")
                
                if pending['on_ack']:
                    pending['on_ack'](delivery_time, pending['retries'])
    
    def _check_timeouts(self):
        """Check for timed out messages and retransmit"""
        while self.running:
            current_time = time.time()
            to_retry = []
            to_timeout = []
            
            with self.lock:
                for msg_id, pending in list(self.pending_messages.items()):
                    if current_time - pending['sent_time'] > self.ack_timeout:
                        if pending['retries'] < self.max_retries:
                            to_retry.append(msg_id)
                        else:
                            to_timeout.append(msg_id)
            
            # Handle retries
            for msg_id in to_retry:
                with self.lock:
                    if msg_id in self.pending_messages:
                        pending = self.pending_messages[msg_id]
                        pending['retries'] += 1
                        pending['sent_time'] = current_time
                        
                        self.logger.warning(f"Retransmitting message {msg_id} "
                                          f"(attempt {pending['retries']})")
                        self._send_packet(pending['packet'], pending['addr'])
            
            # Handle timeouts
            for msg_id in to_timeout:
                with self.lock:
                    if msg_id in self.pending_messages:
                        pending = self.pending_messages.pop(msg_id)
                        self.logger.error(f"Message {msg_id} timed out after "
                                        f"{pending['retries']} retries")
                        
                        if pending['on_timeout']:
                            pending['on_timeout'](pending['retries'])
            
            time.sleep(0.1)  # Check every 100ms
    
    def stop(self):
        """Stop the reliability mechanism"""
        self.running = False
        if self.timeout_thread.is_alive():
            self.timeout_thread.join()
