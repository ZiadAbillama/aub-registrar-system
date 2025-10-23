import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
import socket
import json
import sys
import threading
import queue

SERVER_HOST = '127.0.0.1'
BUFFER_SIZE = 4096

class NetworkClient:
    def __init__(self, host, port, output_queue):
        self.host = host
        self.port = port
        self.output_queue = output_queue
        self.sock = None
        self.is_connected = False
        self.request_queue = queue.Queue()
        self.network_thread = None
        self.stop_event = threading.Event()

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            self.is_connected = True
            self.stop_event.clear()
            self.network_thread = threading.Thread(target=self._listen_for_requests, daemon=True)
            self.network_thread.start()
            self.output_queue.put({"type": "connection_status", "status": "success", "message": f"Connected to {self.host}:{self.port}"})
            return True
        except socket.timeout:
            self.is_connected = False
            self.output_queue.put({"type": "connection_status", "status": "error", "message": f"Connection timed out to {self.host}:{self.port}"})
            return False
        except socket.error as e:
            self.is_connected = False
            self.output_queue.put({"type": "connection_status", "status": "error", "message": f"Connection failed: {e}"})
            return False
        except Exception as e:
            self.is_connected = False
            self.output_queue.put({"type": "connection_status", "status": "error", "message": f"An unexpected error occurred during connection: {e}"})
            return False

    def send_request(self, action, data=None):
        if not self.is_connected or not self.network_thread or not self.network_thread.is_alive():
            self.output_queue.put({"type": "error", "status": "error", "message": "Not connected to server."})
            return
        request = {"action": action, "data": data or {}}
        self.request_queue.put(request)

    def _listen_for_requests(self):
        while not self.stop_event.is_set() and self.is_connected:
            try:
                request = self.request_queue.get(timeout=0.1)
                if request is None:
                    break
                self.sock.sendall(json.dumps(request).encode('utf-8'))
                response_data = self.sock.recv(BUFFER_SIZE)
                if not response_data:
                    self.is_connected = False
                    self.output_queue.put({"type": "connection_status", "status": "error", "message": "Connection lost with server."})
                    break
                response = json.loads(response_data.decode('utf-8'))
                self.output_queue.put({"type": "server_response", "action": request['action'], "response": response})
            except queue.Empty:
                continue
            except (socket.error, json.JSONDecodeError, ConnectionResetError, BrokenPipeError) as e:
                self.is_connected = False
                self.output_queue.put({"type": "connection_status", "status": "error", "message": f"Communication error: {e}"})
                break
            except Exception as e:
                self.is_connected = False
                self.output_queue.put({"type": "error", "status": "error", "message": f"Network thread error: {e}"})
                break
        self._close_socket()
        self.is_connected = False
        if not self.stop_event.is_set():
            self.output_queue.put({"type": "connection_status", "status": "disconnected", "message": "Disconnected."})
        print("Network thread finished.")

    def disconnect(self):
        if self.network_thread and self.network_thread.is_alive():
            self.stop_event.set()
            try:
                self.request_queue.put_nowait(None)
            except queue.Full:
                pass
            self.network_thread.join(timeout=1.0)
        self._close_socket()
        self.is_connected = False
        print("Disconnected.")

    def _close_socket(self):
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            except Exception as e:
                print(f"Error during socket shutdown: {e}")
            finally:
                try:
                    self.sock.close()
                except Exception as e:
                    print(f"Error during socket close: {e}")
                finally:
                    self.sock = None

class RegistrarApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AUB Registrar Client")
        self.geometry("850x650")
        self.minsize(600, 400)
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.configure(bg='#e0e0e0')
        self.network_client = None
        self.user_type = None
        self.username = None
        self.is_logged_in = False
        self.response_queue = queue.Queue()
        self.main_container = ttk.Frame(self)
        self.main_container.pack(fill=tk.BOTH, expand=True)
        self.connection_frame = ttk.Frame(self.main_container, padding="20", style='Card.TFrame')
        self.style.configure('Card.TFrame', background='#ffffff', borderwidth=1, relief='raised')
        self.main_view_frame = ttk.Frame(self.main_container, padding="10")
        self.connection_frame.pack(expand=True)
        self.connection_frame.columnconfigure(0, weight=1)
        self.connection_frame.columnconfigure(1, weight=0)
        self.connection_frame.columnconfigure(2, weight=0)
        self.connection_frame.columnconfigure(3, weight=1)
        self.connection_frame.rowconfigure(0, weight=1)
        self.connection_frame.rowconfigure(5, weight=1)
        ttk.Label(self.connection_frame, text="Server Port:", font=('Helvetica', 11)).grid(row=1, column=1, padx=5, pady=8, sticky=tk.E)
        self.port_entry = ttk.Entry(self.connection_frame, width=15, font=('Helvetica', 10))
        self.port_entry.grid(row=1, column=2, padx=5, pady=8, sticky=tk.W)
        self.port_entry.insert(0, "65432")
        ttk.Label(self.connection_frame, text="Username:", font=('Helvetica', 11)).grid(row=2, column=1, padx=5, pady=8, sticky=tk.E)
        self.username_entry = ttk.Entry(self.connection_frame, width=25, font=('Helvetica', 10))
        self.username_entry.grid(row=2, column=2, padx=5, pady=8, sticky=tk.W)
        ttk.Label(self.connection_frame, text="Password:", font=('Helvetica', 11)).grid(row=3, column=1, padx=5, pady=8, sticky=tk.E)
        self.password_entry = ttk.Entry(self.connection_frame, width=25, show="*", font=('Helvetica', 10))
        self.password_entry.grid(row=3, column=2, padx=5, pady=8, sticky=tk.W)
        self.style.configure('Connect.TButton', font=('Helvetica', 11, 'bold'), padding=6)
        self.connect_button = ttk.Button(self.connection_frame, text="Connect & Login", command=self.connect_and_login, style='Connect.TButton', width=20)
        self.connect_button.grid(row=4, column=1, columnspan=2, pady=20)
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding="2 5", background='#f0f0f0')
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.set_status("Enter server port and credentials to connect.")
        self.course_tree = None
        self.my_course_tree = None
        self.action_frame = None
        self.after(100, self.process_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def set_status(self, message, is_error=False):
        self.status_var.set(message)
        self.status_bar.config(foreground="red" if is_error else "black")

    def process_queue(self):
        try:
            while True:
                msg = self.response_queue.get_nowait()
                msg_type = msg.get("type")
                status = msg.get("status")
                message = msg.get("message")
                if msg_type == "connection_status":
                    if status == "success":
                        self.set_status(message)
                        if hasattr(self, "_pending_login_type"):
                            self.attempt_login(self._pending_login_type)
                            del self._pending_login_type
                    elif status == "error":
                        messagebox.showerror("Connection Error", message)
                        self.set_status(f"Connection failed: {message}", is_error=True)
                        self.reset_to_connection_view()
                    elif status == "disconnected":
                        self.set_status(message)
                        self.reset_to_connection_view()
                elif msg_type == "error":
                    messagebox.showerror("Error", message)
                    self.set_status(message, is_error=True)
                    if "Not connected" in message or "Communication error" in message:
                        self.reset_to_connection_view()
                elif msg_type == "server_response":
                    action = msg.get("action")
                    response = msg.get("response")
                    self.handle_server_response(action, response)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

    def connect_and_login(self):
        port_str = self.port_entry.get()
        username = self.username_entry.get()
        password = self.password_entry.get()
        if not port_str.isdigit():
            messagebox.showerror("Input Error", "Port must be a valid number.")
            return
        port = int(port_str)
        if not (1024 <= port <= 65535):
            messagebox.showerror("Input Error", "Port must be between 1024 and 65535.")
            return
        if not username or not password:
            messagebox.showerror("Input Error", "Username and password are required.")
            return
        if self.network_client:
            print("Disconnecting existing client before new attempt...")
            self.network_client.disconnect()
            self.network_client = None
        self.set_status(f"Connecting to {SERVER_HOST}:{port}...")
        self.network_client = NetworkClient(SERVER_HOST, port, self.response_queue)
        login_type = self.ask_login_type()
        if not login_type:
            self.network_client = None
            self.set_status("Login cancelled.")
            return
        self._pending_login_type = login_type
        threading.Thread(target=self.network_client.connect, daemon=True).start()

    def ask_login_type(self):
        dialog = Toplevel(self)
        dialog.title("Login As")
        dialog.geometry("300x130")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg='#f0f0f0')
        x = self.winfo_rootx() + (self.winfo_width() // 2) - (300 // 2)
        y = self.winfo_rooty() + (self.winfo_height() // 2) - (130 // 2)
        dialog.geometry(f'+{x}+{y}')
        ttk.Label(dialog, text="Please select your login role:", font=('Helvetica', 11), background='#f0f0f0').pack(pady=15)
        result = tk.StringVar()
        def set_choice(choice):
            result.set(choice)
            dialog.destroy()
        btn_frame = ttk.Frame(dialog, style='TFrame')
        btn_frame.pack(pady=10)
        self.style.configure('Dialog.TButton', font=('Helvetica', 10), padding=5)
        ttk.Button(btn_frame, text="Student", command=lambda: set_choice('student'), width=10, style='Dialog.TButton').pack(side=tk.LEFT, padx=15)
        ttk.Button(btn_frame, text="Admin", command=lambda: set_choice('admin'), width=10, style='Dialog.TButton').pack(side=tk.RIGHT, padx=15)
        dialog.protocol("WM_DELETE_WINDOW", lambda: set_choice(""))
        self.wait_window(dialog)
        return result.get()
