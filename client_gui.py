import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import socket
import threading
import time
import json
import logging
import queue
from typing import Optional, Dict,Tuple
from protocol import Packet, PacketParser, MessageType
from reliability import ReliableUDP

class ThreadSafeLogHandler(logging.Handler):
    """Thread-safe logging handler that queues messages for GUI updates"""
    def __init__(self, message_queue):
        super().__init__()
        self.message_queue = message_queue
        
    def emit(self, record):
        try:
            msg = self.format(record)
            self.message_queue.put(('log', msg))
        except Exception:
            pass

class ChatCanvas:
    """A custom scrollable canvas to display message bubbles."""
    def __init__(self, parent, colors):
        self.colors = colors
        self.parent = parent
        
        self.canvas = tk.Canvas(
            parent, 
            bg=self.colors.get('bg_chat', '#e5ddd5'), 
            highlightthickness=0
        )
        self.scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.canvas.yview)
        # Use a standard tk.Frame for the chat content to avoid ttk style conflicts inside
        self.chat_frame = tk.Frame(self.canvas, bg=self.colors.get('bg_chat', '#e5ddd5'))

        self.chat_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.chat_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        
        self.parent.grid_rowconfigure(0, weight=1)
        self.parent.grid_columnconfigure(0, weight=1)
        
        self.chat_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind('<Configure>', self._on_canvas_configure)

        self._wraplength = 400 # Initial value

    def _on_canvas_configure(self, event):
        """Dynamically adjust wraplength when canvas is resized."""
        self._wraplength = event.width - 80
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_frame_configure(self, event=None):
        """Reset the scroll region to encompass the inner frame"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def add_message_bubble(self, sender: str, message: str, msg_type: str = "normal"):
        """Add a styled message bubble to the canvas."""
        timestamp = time.strftime("%H:%M")

        if msg_type in ("self",):
            align = 'e'
            bubble_color = self.colors['self_bubble']
            text_color = '#000000'
        elif msg_type in ("other",):
            align = 'w'
            bubble_color = self.colors['other_bubble']
            text_color = '#000000'
        else: # System, error, warning etc.
            align = 'c'
            bubble_color = self.colors['system_bubble']
            text_color = '#555555'

        row_frame = tk.Frame(self.chat_frame, bg=self.colors['bg_chat'])
        row_frame.pack(fill='x', padx=10, pady=(2, 3))
        
        bubble = tk.Frame(row_frame, bg=bubble_color)
        
        if align == 'c':
            bubble.pack(anchor='c')
        else:
            bubble.pack(anchor=align)

        if msg_type in ("self", "other"):
            if msg_type == "other":
                sender_label = tk.Label(
                    bubble, text=sender, 
                    font=('Segoe UI', 9, 'bold'),
                    bg=bubble_color,
                    fg='#3498db'
                )
                sender_label.pack(anchor='w', padx=(8, 0), pady=(4, 0))

            message_label = tk.Label(
                bubble, text=message, 
                wraplength=self._wraplength, 
                justify=tk.LEFT,
                font=('Segoe UI', 11),
                bg=bubble_color,
                fg=text_color,
            )
            message_label.pack(anchor='w', padx=8, pady=(0, 2))

            timestamp_label = tk.Label(
                bubble, text=timestamp,
                font=('Segoe UI', 8),
                bg=bubble_color,
                fg='#888888'
            )
            timestamp_label.pack(anchor='e', padx=8, pady=(0, 4))
        else:
             message_label = tk.Label(
                bubble, text=f"{message}", 
                wraplength=self._wraplength, 
                justify=tk.CENTER,
                font=('Segoe UI', 9, 'italic'),
                bg=bubble_color,
                fg=text_color,
            )
             message_label.pack(padx=10, pady=5)


        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)

class PrivateChatTab:
    """Individual private chat tab"""
    def __init__(self, parent_notebook, username, chat_client, colors):
        self.username = username
        self.chat_client = chat_client
        self.colors = colors
        
        self.frame = ttk.Frame(parent_notebook, style='Modern.TFrame', padding="10")
        parent_notebook.add(self.frame, text=f"💬 {username}")
        
        self.chat_area_frame = ttk.Frame(self.frame, style='Card.TFrame')
        self.chat_area_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        self.messages_display = ChatCanvas(self.chat_area_frame, self.colors)

        self.message_var = tk.StringVar()
        self.message_entry = ttk.Entry(self.frame, textvariable=self.message_var, style='Modern.TEntry', font=('Segoe UI', 11))
        self.message_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.message_entry.bind('<Return>', self._send_private_message)
        
        self.send_btn = ttk.Button(self.frame, text="Send", style='Send.TButton', command=self._send_private_message)
        self.send_btn.grid(row=1, column=1)
        
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        
        self.add_message("System", f"Private chat with {username}", "system")
    
    def _send_private_message(self, event=None):
        message = self.message_var.get().strip()
        if message and self.chat_client.connected:
            self.chat_client.send_private_message(self.username, message)
            # Add to local display immediately
            self.add_message(self.chat_client.username, message, "self")
            self.message_var.set("")
    
    def add_message(self, sender: str, message: str, msg_type: str = "normal"):
        self.messages_display.add_message_bubble(sender, message, msg_type)

class ModernChatClient:
    def __init__(self, master):
        self.master = master
        self.master.title("UDP Chat Client")
        self.master.geometry("1200x800")
        self.master.minsize(900, 700)
        
        self.sock = None
        self.server_addr = None
        self.username = ""
        self.connected = False
        self.running = False
        self.reliable_udp = None
        self.messages_sent = 0
        self.messages_received = 0
        self.delivery_times = []
        self.message_queue = queue.Queue()
        self.receive_thread = None
        self.heartbeat_thread = None
        self.private_chats: Dict[str, PrivateChatTab] = {}
        self.user_addresses: Dict[str, Tuple[str, int]] = {}
        
        self.setup_styles()
        self.setup_ui()
        self.setup_logging()
        self.load_config()
        
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.process_messages()
    
    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self.colors = {
            'bg_primary': "#FDF6F0", 'bg_secondary': "#C0D5D1",
            'bg_accent': '#F6BD72', 'bg_success': '#A7D7C5',
            'bg_warning': '#f39c12', 'bg_error': "#e87f73",
            'fg_primary': '#2c3e50', 'fg_secondary': '#555555',
            'fg_accent': '#ffffff',
            'bg_chat': "#F5EAE1",
            'self_bubble': '#A7D7C5',
            'other_bubble': '#ffffff',
            'system_bubble': '#fff9c4'
        }
        
        self.style.configure('Modern.TFrame', background=self.colors['bg_primary'])
        self.style.configure('Card.TFrame', background=self.colors['bg_secondary'], relief='flat', borderwidth=1)
        self.style.configure('Modern.TLabel', background="#99ACA8", foreground="black", font=('Segoe UI', 10))
        self.style.configure('Header.TLabel', background=self.colors['bg_secondary'], foreground='#001F54', font=('Segoe UI', 12, 'bold'))
        self.style.configure('Status.TLabel', background=self.colors['bg_primary'], foreground=self.colors['fg_secondary'], font=('Segoe UI', 9))
        self.style.configure('Modern.TEntry', fieldbackground="#F4EEE9", foreground='#000000', borderwidth=1, insertcolor='#000000')
        self.style.configure('Message.TEntry', fieldbackground='#FDF6F0', foreground=self.colors['fg_primary'], borderwidth=1, insertcolor=self.colors['fg_primary'])
        self.style.configure('Connect.TButton', background=self.colors['bg_accent'], foreground=self.colors['fg_accent'], font=('Segoe UI', 10, 'bold'), padding=(10, 5))
        self.style.configure('Send.TButton', background="#F6BD72", foreground=self.colors['fg_accent'], font=('Segoe UI', 10), padding=(10, 5))
        self.style.configure('Disconnect.TButton', background=self.colors['bg_error'], foreground=self.colors['fg_accent'], font=('Segoe UI', 10, 'bold'), padding=(10, 5))
        
        self.master.configure(bg=self.colors['bg_primary'])
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.master, style='Modern.TFrame', padding="15")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        conn_card = ttk.Frame(main_frame, style='Card.TFrame', padding="15")
        conn_card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 15))
        
        ttk.Label(conn_card, text="🔗 Connection", style='Header.TLabel').grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 10))
        ttk.Label(conn_card, text="Username:", style='Modern.TLabel').grid(row=1, column=0, sticky=tk.W, padx=(0, 10))
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(conn_card, textvariable=self.username_var, style='Modern.TEntry', width=15)
        self.username_entry.grid(row=1, column=1, padx=(0, 20), sticky=tk.W)
        ttk.Label(conn_card, text="Server:", style='Modern.TLabel').grid(row=1, column=2, sticky=tk.W, padx=(0, 10))
        self.server_var = tk.StringVar(value="localhost:5000")
        self.server_entry = ttk.Entry(conn_card, textvariable=self.server_var, style='Modern.TEntry', width=20)
        self.server_entry.grid(row=1, column=3, padx=(0, 20), sticky=tk.W)
        self.connect_btn = ttk.Button(conn_card, text="Connect", style='Connect.TButton', command=self.toggle_connection)
        self.connect_btn.grid(row=1, column=4, padx=(10, 0))
        
        content_frame = ttk.Frame(main_frame, style='Modern.TFrame')
        content_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 15))
        
        left_panel = ttk.Frame(content_frame, style='Modern.TFrame')
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        self.chat_notebook = ttk.Notebook(left_panel)
        self.chat_notebook.grid(row=0, column=0, sticky="nsew")
        
        self.public_frame = ttk.Frame(self.chat_notebook, style='Modern.TFrame', padding="10")
        self.chat_notebook.add(self.public_frame, text="🌐 Public Chat")
        
        public_chat_area = ttk.Frame(self.public_frame, style='Card.TFrame')
        public_chat_area.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        self.public_messages_display = ChatCanvas(public_chat_area, self.colors)

        self.message_var = tk.StringVar()
        self.message_entry = ttk.Entry(self.public_frame, textvariable=self.message_var, style='Modern.TEntry', font=('Segoe UI', 11))
        self.message_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.message_entry.bind('<Return>', lambda e: self.send_public_message())
        
        self.send_btn = ttk.Button(self.public_frame, text="Send to All", style='Send.TButton', command=self.send_public_message)
        self.send_btn.grid(row=1, column=1)
        
        self.public_frame.columnconfigure(0, weight=1)
        self.public_frame.rowconfigure(0, weight=1)
        
        right_panel = ttk.Frame(content_frame, style='Card.TFrame', padding="15")
        right_panel.grid(row=0, column=1, sticky="ns")
        
        ttk.Label(right_panel, text="👥 Online Users", style='Header.TLabel').grid(row=0, column=0, sticky=tk.W, pady=(0, 10))
        ttk.Label(right_panel, text="Double-click to start private chat:", style='Modern.TLabel').grid(row=1, column=0, sticky=tk.W, pady=(0, 5))
        
        self.users_listbox = tk.Listbox(right_panel, width=25, height=20, bg=self.colors['bg_primary'], fg=self.colors['fg_primary'], selectbackground=self.colors['bg_accent'], selectforeground=self.colors['fg_accent'], font=('Segoe UI', 10), relief='flat', borderwidth=0, activestyle='none')
        self.users_listbox.grid(row=2, column=0, sticky="ns")
        self.users_listbox.bind('<Double-Button-1>', self.on_user_double_click)
        
        logs_card = ttk.Frame(main_frame, style='Card.TFrame', padding="15")
        logs_card.grid(row=2, column=0, columnspan=2, sticky="ew")
        
        ttk.Label(logs_card, text="📋 System Logs", style='Header.TLabel').grid(row=0, column=0, sticky=tk.W, pady=(0, 10))
        
        self.logs_text = scrolledtext.ScrolledText(logs_card, height=6, bg=self.colors['bg_primary'], fg=self.colors['fg_secondary'], font=('Consolas', 9), relief='flat', borderwidth=0, state=tk.DISABLED, wrap=tk.WORD)
        self.logs_text.grid(row=1, column=0, sticky="ew")
        
        status_frame = ttk.Frame(main_frame, style='Modern.TFrame')
        status_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        
        self.status_var = tk.StringVar(value="🔴 Disconnected")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, style='Status.TLabel')
        self.status_label.grid(row=0, column=0, sticky=tk.W)
        
        self.perf_var = tk.StringVar(value="Messages: 0 sent, 0 received")
        self.perf_label = ttk.Label(status_frame, textvariable=self.perf_var, style='Status.TLabel')
        self.perf_label.grid(row=0, column=1, sticky=tk.E)
        
        self.master.columnconfigure(0, weight=1); self.master.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1); main_frame.rowconfigure(1, weight=1)
        content_frame.columnconfigure(0, weight=1); content_frame.columnconfigure(1, weight=0); content_frame.rowconfigure(0, weight=1)
        left_panel.columnconfigure(0, weight=1); left_panel.rowconfigure(0, weight=1)
        right_panel.rowconfigure(2, weight=1)
        logs_card.columnconfigure(0, weight=1)
        status_frame.columnconfigure(1, weight=1)
        
        self.message_entry.config(state=tk.DISABLED); self.send_btn.config(state=tk.DISABLED)
        
        self.add_public_message("System", "Welcome to UDP Chat! Connect to a server to start chatting.", "system")

    def setup_logging(self):
        self.logger = logging.getLogger('ModernChatClient')
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        
        try:
            file_handler = logging.FileHandler('client.log')
            file_handler.setLevel(logging.INFO)
            gui_handler = ThreadSafeLogHandler(self.message_queue)
            gui_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            gui_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
            self.logger.addHandler(gui_handler)
            self.logger.info("Modern Chat Client initialized")
        except Exception as e:
            print(f"Failed to setup logging: {e}")

    def load_config(self):
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                server_host = config.get('server', {}).get('host', 'localhost')
                server_port = config.get('server', {}).get('port', 5000)
                if server_host == "0.0.0.0": server_host = "localhost"
                self.server_var.set(f"{server_host}:{server_port}")
                self.logger.info(f"Configuration loaded: {server_host}:{server_port}")
        except Exception as e:
            self.logger.warning(f"Failed to load config: {e}, using defaults")

    def on_user_double_click(self, event):
        try:
            selection = self.users_listbox.curselection()
            if selection:
                user_text = self.users_listbox.get(selection[0])
                username = user_text.replace("👤 ", "").replace("👥 ", "").replace(" (me)", "").strip()
                if username != self.username:
                    self.open_private_chat(username)
        except Exception as e:
            self.logger.error(f"Error handling user double-click: {e}")

    def open_private_chat(self, username):
        try:
            if username not in self.private_chats:
                private_tab = PrivateChatTab(self.chat_notebook, username, self, self.colors)
                self.private_chats[username] = private_tab
                self.logger.info(f"Opened private chat with {username}")
            
            for i in range(self.chat_notebook.index("end")):
                if username in self.chat_notebook.tab(i, "text"):
                    self.chat_notebook.select(i)
                    break
        except Exception as e:
            self.logger.error(f"Error opening private chat: {e}")

    def process_messages(self):
        try:
            while not self.message_queue.empty():
                message_type, data = self.message_queue.get_nowait()
                if message_type == 'log': self._add_log_message(data)
                elif message_type == 'public_message': self.add_public_message(*data)
                elif message_type == 'private_message': self.add_private_message(*data)
                elif message_type == 'private_message_error':
                    recipient, msg = data
                    if recipient in self.private_chats:
                        self.private_chats[recipient].add_message("System", msg, "system")
                elif message_type == 'user_list': self._update_users_list(data)
                elif message_type == 'status': self.status_var.set(data)
                elif message_type == 'connection_ui': self._update_connection_ui(data)
                elif message_type == 'clear_users': self._clear_users_list()
                elif message_type == 'performance': self._update_performance_stats()
        except queue.Empty:
            pass
        except Exception as e:
            print(f"Error processing messages: {e}")
        self.master.after(100, self.process_messages)

    def _add_log_message(self, msg):
        try:
            self.logs_text.config(state=tk.NORMAL)
            self.logs_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            self.logs_text.config(state=tk.DISABLED)
            self.logs_text.see(tk.END)
        except Exception: pass

    def toggle_connection(self):
        if not self.connected: self.connect_to_server()
        else: self.disconnect_from_server()

    def connect_to_server(self):
        username = self.username_var.get().strip()
        server_str = self.server_var.get().strip()
        if not username: messagebox.showerror("Error", "Please enter a username"); return
        if not server_str: messagebox.showerror("Error", "Please enter server address"); return
        
        try:
            host, port = server_str.split(':'); port = int(port)
        except ValueError: messagebox.showerror("Error", "Invalid server address format (use host:port)"); return
        
        try:
            self.logger.info(f"Attempting to connect to {host}:{port} as {username}")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(1.0)
            self.reliable_udp = ReliableUDP(self.sock)
            self.server_addr = (host, port)
            self.username = username
            
            join_packet = Packet.create_join(username)
            self.reliable_udp.send_reliable(
                join_packet, self.server_addr,
                on_ack=self._on_join_ack, on_timeout=self._on_join_timeout)
            
            self.running = True
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True); self.receive_thread.start()
            print("Heartbeat thread başlatılıyor...")
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self.heartbeat_thread.start()
            self.message_queue.put(('status', "🟡 Connecting..."))
        except Exception as e:
            error_msg = f"Failed to connect: {e}"; messagebox.showerror("Connection Error", error_msg); self.logger.error(error_msg)

    def _on_join_ack(self, delivery_time, retries):
        self.connected = True
        self.message_queue.put(('connection_ui', True))
        self.message_queue.put(('public_message', ("System", "✅ Connected to server successfully!", "system")))
        self.logger.info(f"Connected successfully (delivery time: {delivery_time:.3f}s, retries: {retries})")

    def _on_join_timeout(self, retries):
        error_msg = f"Failed to connect to server after {retries} attempts"
        self.message_queue.put(('public_message', ("System", f"❌ {error_msg}", "system")))
        self.logger.error(error_msg)
        self.master.after(0, self.disconnect_from_server)

    def _update_connection_ui(self, connected):
        try:
            if connected:
                self.connect_btn.config(text="Disconnect", style='Disconnect.TButton')
                self.username_entry.config(state=tk.DISABLED)
                self.server_entry.config(state=tk.DISABLED)
                self.message_entry.config(state=tk.NORMAL)
                self.send_btn.config(state=tk.NORMAL)
                self.status_var.set(f"🟢 Connected as {self.username}")
            else:
                self.connect_btn.config(text="Connect", style='Connect.TButton')
                self.username_entry.config(state=tk.NORMAL)
                self.server_entry.config(state=tk.NORMAL)
                self.message_entry.config(state=tk.DISABLED)
                self.send_btn.config(state=tk.DISABLED)
                self.status_var.set("🔴 Disconnected")
        except Exception as e:
            self.logger.error(f"Error updating connection UI: {e}")

    def disconnect_from_server(self):
        try:
            if self.connected and self.sock and self.reliable_udp:
                self.logger.info("Disconnecting from server...")
                leave_packet = Packet.create_leave(self.username)
                self.reliable_udp.send_reliable(leave_packet, self.server_addr)
        except Exception as e: self.logger.error(f"Error sending leave packet: {e}")
        
        self.running = False; self.connected = False
        if self.sock: self.sock.close(); self.sock = None
        if self.reliable_udp: self.reliable_udp.stop(); self.reliable_udp = None
        
        for username in list(self.private_chats.keys()):
            try:
                for i in range(self.chat_notebook.index("end")):
                    if username in self.chat_notebook.tab(i, "text"):
                        self.chat_notebook.forget(i); break
            except Exception: pass
        self.private_chats.clear()
        
        self.message_queue.put(('connection_ui', False))
        self.message_queue.put(('clear_users', None))
        self.message_queue.put(('public_message', ("System", "🔌 Disconnected from server", "system")))
        self.logger.info("Disconnected from server")

    def send_public_message(self):
        if not self.connected or not self.reliable_udp: return
        message = self.message_var.get().strip()
        if not message: return
        try:
            self.add_public_message(self.username, message, "self")
            self.message_var.set("")
            
            message_packet = Packet.create_message(self.username, message)
            on_ack = lambda dt, r: (self.delivery_times.append(dt), self.logger.info(f"Public msg delivered ({dt:.3f}s, {r} retries)"), self.message_queue.put(('performance', None)))
            on_timeout = lambda r: (self.message_queue.put(('public_message', ("System", f"❌ Failed to send after {r} retries", "system"))), self.logger.error(f"Public msg timeout after {r} retries"))
            self.reliable_udp.send_reliable(message_packet, self.server_addr, on_ack=on_ack, on_timeout=on_timeout)
            self.messages_sent += 1
            self.logger.info(f"Public message sent: {message[:50]}...")
            self.message_queue.put(('performance', None))
        except Exception as e:
            self.logger.error(f"Error sending public message: {e}")
            self.add_public_message("System", f"❌ Error sending: {e}", "system")

    def send_private_message(self, recipient, message):
        """Send a private message directly to a specific user (P2P)."""
        if not self.connected or not self.reliable_udp:
            return
        
        # Alıcının adresini kendi adres defterimizden bulalım.
        recipient_addr = self.user_addresses.get(recipient)

        if not recipient_addr:
            # Eğer kullanıcı listede yoksa (belki ayrılmıştır), hata göster.
            error_msg = f"User '{recipient}' is not online or address is unknown."
            self.logger.error(error_msg)
            if recipient in self.private_chats:
                self.private_chats[recipient].add_message("System", f"❌ {error_msg}", "system")
            return

        try:
            private_packet = Packet.create_private_message(self.username, recipient, message)
            
            # ACK ve Timeout callback'leri aynı kalabilir.
            def on_ack(delivery_time, retries):
                self.delivery_times.append(delivery_time)
                self.logger.info(f"P2P message to {recipient} delivered ({delivery_time:.3f}s, {retries} retries)")
                self.message_queue.put(('performance', None))
            
            def on_timeout(retries):
                error_msg = f"Failed to send P2P message to {recipient} after {retries} retries"
                self.message_queue.put(('private_message_error', (recipient, f"❌ {error_msg}")))
                self.logger.error(error_msg)
            
            # ÖNEMLİ: Paketi artık server_addr'a değil, doğrudan alıcının adresine gönderiyoruz.
            self.reliable_udp.send_reliable(
                private_packet,
                recipient_addr, # <-- DEĞİŞİKLİK BURADA
                on_ack=on_ack,
                on_timeout=on_timeout
            )
            
            self.messages_sent += 1
            self.logger.info(f"P2P message sent to {recipient} at {recipient_addr}: {message[:50]}...")
            self.message_queue.put(('performance', None))
            
        except Exception as e:
            error_msg = f"Error sending P2P message: {e}"
            self.logger.error(error_msg)
            if recipient in self.private_chats:
                self.private_chats[recipient].add_message("System", f"❌ {error_msg}", "system")

    def _receive_loop(self):
        while self.running:
            try:
                if not self.sock: break
                data, addr = self.sock.recvfrom(4096)
                packet = PacketParser.parse(data)
                if packet: self._handle_packet(packet, addr)
            except socket.timeout: continue
            except Exception as e:
                if self.running: self.logger.error(f"Receive error: {e}"); time.sleep(0.1)

    def _handle_packet(self, packet: Packet, addr: tuple):
        try:
            # ACK paketlerine ACK gönderilmez, bu yüzden önce kontrol et.
            if packet.message_type != MessageType.ACK.value:
                ack_packet = Packet.create_ack(self.username, packet.message_id)
                if self.reliable_udp: self.reliable_udp._send_packet(ack_packet, addr)

            # Şimdi paket tipine göre işlem yap
            if packet.message_type == MessageType.MESSAGE.value:
                self.messages_received += 1
                msg_type_for_gui = "system" if packet.sender == "server" else "other"
                self.message_queue.put(('public_message', (packet.sender, packet.content, msg_type_for_gui)))
                self.message_queue.put(('performance', None))
                self.logger.info(f"Public message received from {packet.sender} at {addr}")

            elif packet.message_type == MessageType.PRIVATE_MESSAGE.value:
                self.messages_received += 1
                self.message_queue.put(('private_message', (packet.sender, packet.content, "other")))
                self.message_queue.put(('performance', None))
                self.logger.info(f"P2P message received from {packet.sender} at {addr}")

            elif packet.message_type == MessageType.USER_LIST.value:
                try:
                    self.message_queue.put(('user_list', json.loads(packet.content)))
                except json.JSONDecodeError: self.logger.error("Failed to parse user list")
            
            elif packet.message_type == MessageType.ACK.value:
                if self.reliable_udp: self.reliable_udp.handle_ack(packet)
                
        except Exception as e: self.logger.error(f"Error handling packet: {e}")

    def _heartbeat_loop(self):
        print("Heartbeat thread çalışıyor!")
        while self.running and self.connected:
            print("Heartbeat gönderiliyor...")
            try:
                if self.reliable_udp:
                    self.reliable_udp.send_reliable(Packet.create_heartbeat(self.username), self.server_addr)
                    self.logger.info("Heartbeat sent")
                time.sleep(30)
            except Exception as e:
                print(f"Heartbeat error: {e}")
                self.logger.error(f"Heartbeat error: {e}")
                time.sleep(5)

    def add_public_message(self, sender: str, message: str, msg_type: str = "normal"):
        try:
            if msg_type in ["success", "warning", "error", "system"]:
                self.public_messages_display.add_message_bubble("System", f"[{sender}] {message}", "system")
            else:
                self.public_messages_display.add_message_bubble(sender, message, msg_type)
        except Exception as e: print(f"Error adding public message: {e}")

    def add_private_message(self, sender: str, message: str, msg_type: str = "normal"):
        try:
            if sender != self.username and sender not in self.private_chats:
                self.open_private_chat(sender)
            if sender in self.private_chats:
                self.private_chats[sender].add_message(sender, message, msg_type)
        except Exception as e: self.logger.error(f"Error adding private message: {e}")

    def _update_users_list(self, users_with_addresses: Dict[str, list]):
        """Update the users list and their addresses."""
        try:
            # Gelen veri {'akin': ['127.0.0.1', 59190], 'eylül': ...} formatında olacak.
            # JSON'dan geçerken tuple'lar listeye dönüşür, biz bunları tekrar tuple yapacağız.
            self.user_addresses = {user: tuple(addr) for user, addr in users_with_addresses.items()}
            self.logger.info(f"Updated user addresses: {self.user_addresses}")

            self.users_listbox.delete(0, tk.END)
            # Sadece kullanıcı isimlerini alıp sıralayarak listeye ekleyelim.
            for user in sorted(self.user_addresses.keys()):
                if user == self.username:
                    self.users_listbox.insert(tk.END, f"👤 {user} (me)")
                else:
                    self.users_listbox.insert(tk.END, f"👥 {user}")
        except Exception as e:
            self.logger.error(f"Error updating users list: {e}")

    def _clear_users_list(self):
        try: self.users_listbox.delete(0, tk.END)
        except Exception: pass

    def _update_performance_stats(self):
        try:
            avg_time = sum(self.delivery_times) / len(self.delivery_times) if self.delivery_times else 0
            self.perf_var.set(f"Messages: {self.messages_sent} sent, {self.messages_received} received | Avg delivery: {avg_time:.3f}s")
        except Exception as e: self.logger.error(f"Error updating performance stats: {e}")

    def on_closing(self):
        try:
            self.logger.info("Application closing...")
            self.running = False
            if self.connected: self.disconnect_from_server()
            time.sleep(0.5)
            if self.sock: self.sock.close()
            self.master.destroy()
        except Exception as e:
            print(f"Error during shutdown: {e}"); self.master.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    client = ModernChatClient(root)
    root.mainloop()