
import threading
import time
import socket
import json
import random
from protocol import Packet, PacketParser, MessageType
from reliability import ReliableUDP

class TestClient:
    def __init__(self, username: str, server_host: str = "localhost", server_port: int = 5000):
        self.username = username
        self.server_addr = (server_host, server_port)
        self.sock = None
        self.reliable_udp = None
        self.running = False
        self.connected = False
        
        # Statistics
        self.messages_sent = 0
        self.messages_received = 0
        self.delivery_times = []
        
    def connect(self):
        """Connect to the server"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(1.0)
            
            self.reliable_udp = ReliableUDP(self.sock)
            
            # Send join request
            join_packet = Packet.create_join(self.username)
            
            join_success = threading.Event()
            
            def on_join_ack(delivery_time, retries):
                print(f"[{self.username}] Connected to server")
                self.connected = True
                join_success.set()
            
            def on_join_timeout(retries):
                print(f"[{self.username}] Failed to connect")
                join_success.set()
            
            self.reliable_udp.send_reliable(
                join_packet, 
                self.server_addr,
                on_ack=on_join_ack,
                on_timeout=on_join_timeout
            )
            
            # Start receive loop
            self.running = True
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            # Wait for connection
            join_success.wait(timeout=10)
            
            return self.connected
            
        except Exception as e:
            print(f"[{self.username}] Connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from the server"""
        if self.connected:
            leave_packet = Packet.create_leave(self.username)
            self.reliable_udp.send_reliable(leave_packet, self.server_addr)
            print(f"[{self.username}] Disconnected")
        
        self.running = False
        self.connected = False
        
        if self.reliable_udp:
            self.reliable_udp.stop()
        
        if self.sock:
            self.sock.close()
    
    def send_message(self, content: str):
        """Send a message"""
        if not self.connected:
            return False
        
        message_packet = Packet.create_message(self.username, content)
        
        def on_ack(delivery_time, retries):
            self.delivery_times.append(delivery_time)
            print(f"[{self.username}] Message sent: '{content}' (time: {delivery_time:.3f}s)")
        
        def on_timeout(retries):
            print(f"[{self.username}] Failed to send message: '{content}'")
        
        self.reliable_udp.send_reliable(
            message_packet,
            self.server_addr,
            on_ack=on_ack,
            on_timeout=on_timeout
        )
        
        self.messages_sent += 1
        return True
    
    def _receive_loop(self):
        """Receive messages"""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                packet = PacketParser.parse(data)
                
                if packet:
                    self._handle_packet(packet)
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[{self.username}] Receive error: {e}")
                break
    
    def _handle_packet(self, packet: Packet):
        """Handle incoming packet"""
        if packet.message_type == MessageType.MESSAGE.value:
            self.messages_received += 1
            
            # Send ACK
            ack_packet = Packet.create_ack(self.username, packet.message_id)
            self.reliable_udp._send_packet(ack_packet, self.server_addr)
            
            # Log received message
            if packet.sender != "server":
                print(f"[{self.username}] Received from {packet.sender}: {packet.content}")
        
        elif packet.message_type == MessageType.USER_LIST.value:
            # Send ACK
            ack_packet = Packet.create_ack(self.username, packet.message_id)
            self.reliable_udp._send_packet(ack_packet, self.server_addr)
            
            try:
                users = json.loads(packet.content)
                print(f"[{self.username}] Online users: {users}")
            except json.JSONDecodeError:
                pass
        
        elif packet.message_type == MessageType.ACK.value:
            self.reliable_udp.handle_ack(packet)
    
    def get_stats(self):
        """Get client statistics"""
        avg_delivery_time = sum(self.delivery_times) / len(self.delivery_times) if self.delivery_times else 0
        return {
            'username': self.username,
            'messages_sent': self.messages_sent,
            'messages_received': self.messages_received,
            'average_delivery_time': avg_delivery_time
        }

def run_test_scenario():
    """Run a test scenario with multiple clients"""
    print("Starting UDP Chat Test Scenario")
    print("=" * 50)
    
    # Create test clients
    clients = [
        TestClient("Alice"),
        TestClient("Bob"),
        TestClient("Charlie")
    ]
    
    # Connect all clients
    print("\n1. Connecting clients...")
    for client in clients:
        if client.connect():
            print(f"   ✓ {client.username} connected")
        else:
            print(f"   ✗ {client.username} failed to connect")
            return
        time.sleep(1)
    
    print("\n2. Waiting for user lists to sync...")
    time.sleep(3)
    
    # Send test messages
    print("\n3. Sending test messages...")
    
    test_messages = [
        ("Alice", "Hello everyone!"),
        ("Bob", "Hi Alice! How are you?"),
        ("Charlie", "Hey there! This is a test message."),
        ("Alice", "I'm doing great, thanks Bob!"),
        ("Bob", "This UDP chat is working well!"),
        ("Charlie", "Let's test some special characters: 你好 🌟"),
        ("Alice", "Testing reliability mechanisms..."),
        ("Bob", "Message with timestamp: " + str(time.time())),
    ]
    
    for sender_name, message in test_messages:
        # Find the sender client
        sender = next((c for c in clients if c.username == sender_name), None)
        if sender:
            sender.send_message(message)
            time.sleep(random.uniform(1, 3))  # Random delay between messages
    
    print("\n4. Letting messages propagate...")
    time.sleep(5)
    
    # Test client leaving and rejoining
    print("\n5. Testing client disconnect/reconnect...")
    clients[1].disconnect()
    time.sleep(2)
    
    clients[0].send_message("Bob left the chat")
    time.sleep(2)
    
    if clients[1].connect():
        print(f"   ✓ {clients[1].username} reconnected")
        time.sleep(2)
        clients[1].send_message("I'm back!")
        time.sleep(2)
    
    # Print statistics
    print("\n6. Final Statistics:")
    print("-" * 50)
    for client in clients:
        stats = client.get_stats()
        print(f"{stats['username']:>10}: "
              f"Sent: {stats['messages_sent']:2d}, "
              f"Received: {stats['messages_received']:2d}, "
              f"Avg Delivery: {stats['average_delivery_time']:.3f}s")
    
    # Disconnect all clients
    print("\n7. Disconnecting clients...")
    for client in clients:
        client.disconnect()
        time.sleep(0.5)
    
    print("\nTest scenario completed!")

if __name__ == "__main__":
    try:
        run_test_scenario()
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
