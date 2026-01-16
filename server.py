import socket
import threading
import time
import json
import logging
from typing import Dict, Tuple, Set
from protocol import Packet, PacketParser, MessageType
from reliability import ReliableUDP

class ChatServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        
        self.clients: Dict[str, Tuple[str, int]] = {}  # username -> (ip, port)
        self.client_last_seen: Dict[str, float] = {}  # username -> timestamp
        self.running = True
        self.lock = threading.Lock()
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('server.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('ChatServer')
        
        # Performance metrics
        self.message_count = 0
        self.delivery_times = []
        self.retransmission_count = 0
        
        # Initialize reliable UDP
        self.reliable_udp = ReliableUDP(self.sock)
        
        self.logger.info(f"Chat server started on {host}:{port}")
    
    def start(self):
        """Start the server"""
        # Start heartbeat checker
        heartbeat_thread = threading.Thread(target=self._heartbeat_checker, daemon=True)
        heartbeat_thread.start()
        
        # Start main server loop
        try:
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(4096)
                    packet = PacketParser.parse(data)
                    
                    if packet:
                        self._handle_packet(packet, addr)
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    self.logger.error(f"Error in server loop: {e}")
        
        except KeyboardInterrupt:
            self.logger.info("Server shutdown requested")
        finally:
            self.stop()
    
    def _handle_packet(self, packet: Packet, addr: Tuple[str, int]):
        """Handle incoming packet"""
        self.logger.debug(f"Received {packet.message_type} from {packet.sender} at {addr}")
        
        # Update last seen time
        with self.lock:
            self.client_last_seen[packet.sender] = time.time()
        
        if packet.message_type == MessageType.JOIN.value:
            self._handle_join(packet, addr)
        
        elif packet.message_type == MessageType.LEAVE.value:
            self._handle_leave(packet, addr)
        
        elif packet.message_type == MessageType.MESSAGE.value:
            self._handle_message(packet, addr)
        
        elif packet.message_type == MessageType.PRIVATE_MESSAGE.value:
            self._handle_private_message(packet, addr)
        
        elif packet.message_type == MessageType.ACK.value:
            self.reliable_udp.handle_ack(packet)
        
        elif packet.message_type == MessageType.HEARTBEAT.value:
            self._handle_heartbeat(packet, addr)
    
    def _handle_join(self, packet: Packet, addr: Tuple[str, int]):
        """Handle user join request"""
        username = packet.sender
        
        with self.lock:
            if username in self.clients:
                self.logger.warning(f"User {username} already connected")
                return
            
            self.clients[username] = addr
            self.client_last_seen[username] = time.time()
        
        self.logger.info(f"User {username} joined from {addr}")
        
        # Send ACK
        ack_packet = Packet.create_ack("server", packet.message_id)
        self.reliable_udp._send_packet(ack_packet, addr)
        
        # Broadcast user list to all clients
        self._broadcast_user_list()
        
        # Notify other users
        join_notification = Packet.create_message(
            "server", 
            f"{username} joined the chat"
        )
        self._broadcast_message(join_notification, exclude=username)
    
    def _handle_leave(self, packet: Packet, addr: Tuple[str, int]):
        """Handle user leave request"""
        username = packet.sender
        
        with self.lock:
            if username in self.clients:
                del self.clients[username]
                del self.client_last_seen[username]
        
        self.logger.info(f"User {username} left the chat")
        
        # Send ACK
        ack_packet = Packet.create_ack("server", packet.message_id)
        self.reliable_udp._send_packet(ack_packet, addr)
        
        # Broadcast user list to remaining clients
        self._broadcast_user_list()
        
        # Notify other users
        leave_notification = Packet.create_message(
            "server", 
            f"{username} left the chat"
        )
        self._broadcast_message(leave_notification)
    
    def _handle_message(self, packet: Packet, addr: Tuple[str, int]):
        """Handle chat message"""
        self.message_count += 1
        
        # Send ACK to sender
        ack_packet = Packet.create_ack("server", packet.message_id)
        self.reliable_udp._send_packet(ack_packet, addr)
        
        # Log message
        self.logger.info(f"Message from {packet.sender}: {packet.content}")
        
        # Broadcast to all other clients
        self._broadcast_message(packet, exclude=packet.sender)
    
    def _handle_heartbeat(self, packet: Packet, addr: Tuple[str, int]):
        """Handle heartbeat packet"""
        ack_packet = Packet.create_ack("server", packet.message_id)
        self.reliable_udp._send_packet(ack_packet, addr)
    
    def _handle_private_message(self, packet: Packet, addr: Tuple[str, int]):
        """Handle private message"""
        self.message_count += 1
        
        # Send ACK to sender
        ack_packet = Packet.create_ack("server", packet.message_id)
        self.reliable_udp._send_packet(ack_packet, addr)
        
        # Log private message
        self.logger.info(f"Private message from {packet.sender} to {packet.recipient}: {packet.content}")
        
        # Find recipient and send message
        with self.lock:
            if packet.recipient in self.clients:
                recipient_addr = self.clients[packet.recipient]
                
                def on_ack(delivery_time, retries):
                    self.delivery_times.append(delivery_time)
                    if retries > 0:
                        self.retransmission_count += retries
                
                def on_timeout(retries):
                    self.logger.error(f"Failed to deliver private message to {packet.recipient}")
                    self.retransmission_count += retries
                
                self.reliable_udp.send_reliable(
                    packet, recipient_addr, on_ack=on_ack, on_timeout=on_timeout
                )
            else:
                # Recipient not found, send error back to sender
                error_packet = Packet.create_message(
                    "server",
                    f"User '{packet.recipient}' is not online"
                )
                self.reliable_udp.send_reliable(error_packet, addr)
    
    def _broadcast_message(self, packet: Packet, exclude: str = None):
        """Broadcast message to all connected clients"""
        with self.lock:
            clients_copy = self.clients.copy()
        
        for username, addr in clients_copy.items():
            if username != exclude:
                def on_ack(delivery_time, retries):
                    self.delivery_times.append(delivery_time)
                    if retries > 0:
                        self.retransmission_count += retries
                
                def on_timeout(retries):
                    self.logger.error(f"Failed to deliver message to {username}")
                    self.retransmission_count += retries
                
                self.reliable_udp.send_reliable(
                    packet, addr, on_ack=on_ack, on_timeout=on_timeout
                )
    
    def _broadcast_user_list(self):
        """Broadcast current user list (with addresses) to all clients"""
        with self.lock:
            # self.clients zaten {'username': ('ip', port)} formatında.
            # Bir kopyasını alıp doğrudan gönderiyoruz.
            clients_with_addresses = self.clients.copy()
            clients_to_broadcast_to = self.clients.copy()

        # Packet içeriği artık bir liste değil, bir sözlük olacak.
        user_list_packet = Packet.create_user_list("server", clients_with_addresses)
        
        for username, addr in clients_to_broadcast_to.items():
            self.reliable_udp.send_reliable(user_list_packet, addr)
            self.logger.info(f"Broadcasted user address list to {username}")
    
    def _heartbeat_checker(self):
        """Check for inactive clients and remove them"""
        while self.running:
            current_time = time.time()
            inactive_users = []
            
            with self.lock:
                for username, last_seen in self.client_last_seen.items():
                    if current_time - last_seen > 60:  # 60 seconds timeout
                        inactive_users.append(username)
            
            for username in inactive_users:
                self.logger.warning(f"Removing inactive user: {username}")
                with self.lock:
                    if username in self.clients:
                        del self.clients[username]
                        del self.client_last_seen[username]
                
                # Broadcast updated user list
                self._broadcast_user_list()
                
                # Notify other users
                leave_notification = Packet.create_message(
                    "server", 
                    f"{username} disconnected (timeout)"
                )
                self._broadcast_message(leave_notification)
            
            time.sleep(30)  # Check every 30 seconds
    
    def get_stats(self):
        """Get server performance statistics"""
        avg_delivery_time = sum(self.delivery_times) / len(self.delivery_times) if self.delivery_times else 0
        return {
            'total_messages': self.message_count,
            'connected_users': len(self.clients),
            'average_delivery_time': avg_delivery_time,
            'total_retransmissions': self.retransmission_count
        }
    
    def stop(self):
        """Stop the server"""
        self.running = False
        self.reliable_udp.stop()
        self.sock.close()
        self.logger.info("Server stopped")

    def _heartbeat_loop(self):
        while self.running and self.connected:
            print("Heartbeat gönderiliyor...")
            try:
                if self.reliable_udp:
                    self.reliable_udp.send_reliable(Packet.create_heartbeat(self.username), self.server_addr)
                time.sleep(30)
            except Exception as e:
                print(f"Heartbeat error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    # Load configuration
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {
            "server": {"host": "0.0.0.0", "port": 5000},
            "timeouts": {"ack_timeout": 3.0, "max_retries": 3}
        }
    
    server = ChatServer(
        host=config['server']['host'],
        port=config['server']['port']
    )
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop()
