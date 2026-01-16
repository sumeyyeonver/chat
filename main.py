
#!/usr/bin/env python3
"""
UDP Chat Application
A reliable UDP-based chat system with GUI client and command-line server.

Usage:
    python main.py server          # Run chat server
    python main.py client          # Run GUI client
    python main.py test            # Run test simulation
    python main.py --help          # Show this help
"""

import sys
import argparse
import json
import logging

def run_server():
    """Run the chat server"""
    from server import ChatServer
    
    # Load configuration
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print("Warning: config.json not found, using defaults")
        config = {
            "server": {"host": "0.0.0.0", "port": 5000},
            "timeouts": {"ack_timeout": 3.0, "max_retries": 3}
        }
    
    server = ChatServer(
        host=config['server']['host'],
        port=config['server']['port']
    )
    
    print(f"Starting UDP Chat Server on {config['server']['host']}:{config['server']['port']}")
    print("Press Ctrl+C to stop the server")
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop()
        
        # Print final statistics
        stats = server.get_stats()
        print("\nServer Statistics:")
        print(f"Total messages handled: {stats['total_messages']}")
        print(f"Peak concurrent users: {stats['connected_users']}")
        print(f"Average delivery time: {stats['average_delivery_time']:.3f}s")
        print(f"Total retransmissions: {stats['total_retransmissions']}")

def run_client():
    """Run the GUI client"""
    try:
        import tkinter as tk
        from client_gui import ChatClient
        
        root = tk.Tk()
        client = ChatClient(root)
        root.mainloop()
        
    except ImportError:
        print("Error: tkinter not available. GUI client cannot run.")
        print("Try running the test simulation instead: python main.py test")

def run_test():
    """Run the test simulation"""
    from test_clients import run_test_scenario
    
    print("Running automated test scenario...")
    print("Make sure the server is running first!")
    print("You can start it with: python main.py server")
    
    input("Press Enter to continue when server is ready...")
    
    try:
        run_test_scenario()
    except Exception as e:
        print(f"Test failed: {e}")
        print("Make sure the server is running and accessible.")

def show_help():
    """Show help information"""
    print(__doc__)
    print("\nFeatures:")
    print("- Reliable UDP communication with ACK/retransmission")
    print("- Multi-user chat with online user tracking")
    print("- GUI client with Tkinter")
    print("- Comprehensive logging and performance metrics")
    print("- Custom message protocol with type safety")
    print("- Configurable timeouts and retry limits")
    
    print("\nConfiguration:")
    print("Edit config.json to change server settings, timeouts, and logging options.")
    
    print("\nFiles:")
    print("- server.py: Chat server implementation")
    print("- client_gui.py: GUI chat client")
    print("- protocol.py: Message protocol definitions")
    print("- reliability.py: UDP reliability mechanisms")
    print("- test_clients.py: Automated test clients")
    print("- config.json: Configuration file")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="UDP Chat Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        'mode',
        choices=['server', 'client', 'test', 'help'],
        nargs='?',
        default='help',
        help='Mode to run: server, client, test, or help'
    )
    
    args = parser.parse_args()
    
    if args.mode == 'server':
        run_server()
    elif args.mode == 'client':
        run_client()
    elif args.mode == 'test':
        run_test()
    else:
        show_help()

if __name__ == "__main__":
    main()
