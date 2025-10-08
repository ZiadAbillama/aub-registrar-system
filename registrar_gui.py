import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
import socket
import json
import sys
import threading
import queue # For thread-safe communication between network thread and GUI

# --- Configuration ---
SERVER_HOST = '127.0.0.1' # Default server host
BUFFER_SIZE = 4096

# --- Network Communication Class ---
class NetworkClient:
    """Handles network communication with the server in a separate thread."""
    def __init__(self, host, port, output_queue):
        self.host = host
        self.port = port
        self.output_queue = output_queue # Queue to send results back to GUI
        self.sock = None
        self.is_connected = False
        self.request_queue = queue.Queue() # Queue for GUI to send requests
        self.network_thread = None
        self.stop_event = threading.Event()

    def connect(self):
        """Attempts to establish a connection to the server."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Add a timeout for the connection attempt
            self.sock.settimeout(5.0) # 5 seconds timeout
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None) # Reset timeout after connection
            self.is_connected = True
            # Start the listening thread only after successful connection
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
        """Adds a request to the queue to be sent by the network thread."""
        if not self.is_connected or not self.network_thread or not self.network_thread.is_alive():
             self.output_queue.put({"type": "error", "status": "error", "message": "Not connected to server."})
             # Attempt to reconnect or notify user more clearly
             return
        request = {"action": action, "data": data or {}}
        self.request_queue.put(request)

    def _listen_for_requests(self):
        """Worker thread function: waits for requests and processes them."""
        while not self.stop_event.is_set() and self.is_connected:
            try:
                # Wait for a request from the GUI thread
                request = self.request_queue.get(timeout=0.1) # Timeout to check stop_event
                if request is None: # Sentinel value to stop
                    break

                # Send the request to the server
                self.sock.sendall(json.dumps(request).encode('utf-8'))

                # Receive the response - consider potential blocking here
                # Set a timeout for receiving data as well?
                # self.sock.settimeout(10.0) # Example: 10 second timeout for response
                response_data = self.sock.recv(BUFFER_SIZE)
                # self.sock.settimeout(None) # Reset after receive

                if not response_data:
                    # Server likely closed connection or connection lost
                    self.is_connected = False
                    self.output_queue.put({"type": "connection_status", "status": "error", "message": "Connection lost with server."})
                    break # Exit thread

                response = json.loads(response_data.decode('utf-8'))
                # Put the server response onto the output queue for the GUI
                self.output_queue.put({"type": "server_response", "action": request['action'], "response": response})

            except queue.Empty:
                continue # No request, check stop_event again
            # except socket.timeout:
            #     # Handle receive timeout if implemented
            #     self.output_queue.put({"type": "error", "status": "error", "message": "Server response timed out."})
            #     # Decide whether to break or continue
            except (socket.error, json.JSONDecodeError, ConnectionResetError, BrokenPipeError) as e:
                self.is_connected = False
                self.output_queue.put({"type": "connection_status", "status": "error", "message": f"Communication error: {e}"})
                break # Exit thread on error
            except Exception as e:
                 self.is_connected = False
                 self.output_queue.put({"type": "error", "status": "error", "message": f"Network thread error: {e}"})
                 break # Exit thread on unexpected error

        # Cleanup when thread exits
        self._close_socket()
        self.is_connected = False
        if not self.stop_event.is_set(): # If exited due to error, notify GUI
            self.output_queue.put({"type": "connection_status", "status": "disconnected", "message": "Disconnected."})
        print("Network thread finished.")


    def disconnect(self):
        """Signals the network thread to stop and closes the connection."""
        if self.network_thread and self.network_thread.is_alive():
            self.stop_event.set() # Signal thread to stop
            # Add a dummy item to ensure the queue.get() doesn't block indefinitely
            # if the thread is waiting on it.
            try:
                self.request_queue.put_nowait(None) # Send sentinel value
            except queue.Full:
                pass # If queue is full, thread should eventually see stop_event
            self.network_thread.join(timeout=1.0) # Wait briefly for thread to exit

        self._close_socket()
        self.is_connected = False
        print("Disconnected.")
        # Optionally notify GUI, though usually handled by thread exit message
        # self.output_queue.put({"type": "connection_status", "status": "disconnected", "message": "Disconnected."})


    def _close_socket(self):
        """Safely closes the socket."""
        if self.sock:
            try:
                # Shutdown may fail if socket is already closed
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass # Ignore errors on shutdown
            except Exception as e:
                 print(f"Error during socket shutdown: {e}") # Log other shutdown errors
            finally:
                try:
                    self.sock.close()
                except Exception as e:
                    print(f"Error during socket close: {e}") # Log errors on close
                finally:
                    self.sock = None


# --- GUI Application Class ---
class RegistrarApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AUB Registrar Client")
        # Increased initial size slightly for better centering appearance
        self.geometry("850x650")
        self.minsize(600, 400) # Set a minimum size

        # Styling
        self.style = ttk.Style(self)
        self.style.theme_use('clam') # Use a modern theme
        self.configure(bg='#e0e0e0') # Slightly darker grey background

        # Network Client and State
        self.network_client = None
        self.user_type = None # 'student' or 'admin'
        self.username = None
        self.is_logged_in = False
        self.response_queue = queue.Queue()

        # --- UI Frames ---
        # Main container frame that allows centering
        self.main_container = ttk.Frame(self)
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # Connection Frame (will be centered within main_container)
        self.connection_frame = ttk.Frame(self.main_container, padding="20", style='Card.TFrame') # Added style
        # Style for the card look (optional)
        self.style.configure('Card.TFrame', background='#ffffff', borderwidth=1, relief='raised')

        # Main frame for student/admin view (replaces connection_frame)
        self.main_view_frame = ttk.Frame(self.main_container, padding="10")

        # Pack connection frame initially using pack for centering
        self.connection_frame.pack(expand=True) # expand=True helps center it

        # --- Connection Frame Widgets (using grid inside connection_frame) ---
        # Configure grid columns within connection_frame for alignment
        self.connection_frame.columnconfigure(0, weight=1) # Pad left
        self.connection_frame.columnconfigure(1, weight=0) # Label column
        self.connection_frame.columnconfigure(2, weight=0) # Entry column
        self.connection_frame.columnconfigure(3, weight=1) # Pad right

        # Configure grid rows for spacing
        self.connection_frame.rowconfigure(0, weight=1) # Pad top
        self.connection_frame.rowconfigure(5, weight=1) # Pad bottom


        ttk.Label(self.connection_frame, text="Server Port:", font=('Helvetica', 11)).grid(row=1, column=1, padx=5, pady=8, sticky=tk.E)
        self.port_entry = ttk.Entry(self.connection_frame, width=15, font=('Helvetica', 10))
        self.port_entry.grid(row=1, column=2, padx=5, pady=8, sticky=tk.W)
        self.port_entry.insert(0, "65432") # Default port suggestion

        ttk.Label(self.connection_frame, text="Username:", font=('Helvetica', 11)).grid(row=2, column=1, padx=5, pady=8, sticky=tk.E)
        self.username_entry = ttk.Entry(self.connection_frame, width=25, font=('Helvetica', 10))
        self.username_entry.grid(row=2, column=2, padx=5, pady=8, sticky=tk.W)

        ttk.Label(self.connection_frame, text="Password:", font=('Helvetica', 11)).grid(row=3, column=1, padx=5, pady=8, sticky=tk.E)
        self.password_entry = ttk.Entry(self.connection_frame, width=25, show="*", font=('Helvetica', 10))
        self.password_entry.grid(row=3, column=2, padx=5, pady=8, sticky=tk.W)

        # Style the button
        self.style.configure('Connect.TButton', font=('Helvetica', 11, 'bold'), padding=6)
        self.connect_button = ttk.Button(self.connection_frame, text="Connect & Login", command=self.connect_and_login, style='Connect.TButton', width=20)
        self.connect_button.grid(row=4, column=1, columnspan=2, pady=20) # Centered below inputs

        # --- Status Bar ---
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding="2 5", background='#f0f0f0')
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.set_status("Enter server port and credentials to connect.")

        # --- Main View Widgets (Created dynamically after login) ---
        self.course_tree = None
        self.my_course_tree = None # For student's registered courses
        self.action_frame = None

        # Start checking the response queue
        self.after(100, self.process_queue)

        # Handle window close event
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def set_status(self, message, is_error=False):
        """Updates the status bar text and color."""
        self.status_var.set(message)
        if is_error:
            self.status_bar.config(foreground="red")
        else:
            self.status_bar.config(foreground="black")

    def process_queue(self):
        """Processes messages from the network client queue."""
        try:
            while True: # Process all messages currently in the queue
                msg = self.response_queue.get_nowait()

                msg_type = msg.get("type")
                status = msg.get("status")
                message = msg.get("message")

                if msg_type == "connection_status":
                    if status == "success":
                        self.set_status(message)
                        # Now attempt login (if connect_and_login initiated)
                        if hasattr(self, "_pending_login_type"):
                            self.attempt_login(self._pending_login_type)
                            del self._pending_login_type # Clear pending state
                    elif status == "error":
                        messagebox.showerror("Connection Error", message)
                        self.set_status(f"Connection failed: {message}", is_error=True)
                        self.reset_to_connection_view() # Ensure we are back at connect screen
                    elif status == "disconnected":
                         self.set_status(message)
                         self.reset_to_connection_view()

                elif msg_type == "error":
                    messagebox.showerror("Error", message)
                    self.set_status(message, is_error=True)
                    # Decide if we need to reset view based on error context
                    if "Not connected" in message or "Communication error" in message:
                        self.reset_to_connection_view()

                elif msg_type == "server_response":
                    action = msg.get("action")
                    response = msg.get("response")
                    self.handle_server_response(action, response)

        except queue.Empty:
            pass # No messages currently
        finally:
            # Reschedule the queue check
            self.after(100, self.process_queue)

    def connect_and_login(self):
        """Initiates connection and then login."""
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

        # Disconnect if already connected or attempting
        if self.network_client: # and self.network_client.is_connected: # Disconnect even if attempting
            print("Disconnecting existing client before new attempt...")
            self.network_client.disconnect()
            self.network_client = None
            # Short delay to ensure resources are released?
            # self.after(100)

        # Create and connect network client
        self.set_status(f"Connecting to {SERVER_HOST}:{port}...")
        self.network_client = NetworkClient(SERVER_HOST, port, self.response_queue)

        # Ask user for login type
        login_type = self.ask_login_type()
        if not login_type: # User cancelled
            self.network_client = None # Clean up the just created client
            self.set_status("Login cancelled.")
            return

        # Store pending login type and initiate connection in background
        self._pending_login_type = login_type
        threading.Thread(target=self.network_client.connect, daemon=True).start()


    def ask_login_type(self):
        """Pops up a styled dialog to ask if logging in as student or admin."""
        dialog = Toplevel(self)
        dialog.title("Login As")
        dialog.geometry("300x130") # Adjusted size
        dialog.resizable(False, False)
        dialog.transient(self) # Keep on top of main window
        dialog.grab_set() # Modal
        dialog.configure(bg='#f0f0f0')

        # Center the dialog relative to the parent window
        x = self.winfo_rootx() + (self.winfo_width() // 2) - (300 // 2)
        y = self.winfo_rooty() + (self.winfo_height() // 2) - (130 // 2)
        dialog.geometry(f'+{x}+{y}')


        ttk.Label(dialog, text="Please select your login role:", font=('Helvetica', 11), background='#f0f0f0').pack(pady=15)

        result = tk.StringVar() # To store the choice

        def set_choice(choice):
            result.set(choice)
            dialog.destroy()

        # Frame for buttons
        btn_frame = ttk.Frame(dialog, style='TFrame') # Use default frame style or specify one
        btn_frame.pack(pady=10)
        self.style.configure('Dialog.TButton', font=('Helvetica', 10), padding=5)

        ttk.Button(btn_frame, text="Student", command=lambda: set_choice('student'), width=10, style='Dialog.TButton').pack(side=tk.LEFT, padx=15)
        ttk.Button(btn_frame, text="Admin", command=lambda: set_choice('admin'), width=10, style='Dialog.TButton').pack(side=tk.RIGHT, padx=15)

        # Handle closing dialog without selection
        dialog.protocol("WM_DELETE_WINDOW", lambda: set_choice("")) # Set empty choice on close

        self.wait_window(dialog) # Wait for dialog to close
        return result.get()


    def attempt_login(self, login_type):
        """Sends the login request after connection is established."""
        username = self.username_entry.get()
        password = self.password_entry.get() # Get password again (might be cleared)

        if not self.network_client or not self.network_client.is_connected:
             messagebox.showerror("Error", "Not connected to server.")
             self.reset_to_connection_view()
             return

        action = f"login_{login_type}" # e.g., 'login_student' or 'login_admin'
        data = {'username': username, 'password': password}
        self.set_status(f"Attempting {login_type} login as '{username}'...")
        self.network_client.send_request(action, data)


    def handle_server_response(self, action, response):
        """Processes responses received from the server."""
        if not response: # Handle case where response is None or empty
             messagebox.showerror("Server Error", "Received empty response from server.")
             self.set_status("Received empty response from server.", is_error=True)
             # Decide if disconnect is needed
             if action.startswith("login_"):
                 self.reset_to_connection_view()
             return

        status = response.get('status')
        message = response.get('message', 'No message received.')
        data = response.get('data', {})

        self.set_status(f"Server response ({action}): {status.upper()} - {message}", is_error=(status != 'success'))

        if status == 'error':
            messagebox.showerror(f"{action.replace('_', ' ').title()} Error", message)
            # If login failed, reset to connection view
            if action.startswith('login_'):
                self.reset_to_connection_view()
            return # Stop processing on error

        # --- Handle Successful Responses ---
        if action == 'login_student':
            self.username = self.username_entry.get() # Store username
            self.user_type = 'student'
            self.is_logged_in = True
            self.setup_student_ui()
            # Display initially registered courses from login response
            self.update_course_tree(self.my_course_tree, data.get('registered_courses', []), is_my_courses=True)
            self.set_status(f"Student '{self.username}' logged in. Welcome!")
            # Automatically list available courses
            self.list_available_courses()


        elif action == 'login_admin':
            self.username = self.username_entry.get() # Store username
            self.user_type = 'admin'
            self.is_logged_in = True
            self.setup_admin_ui()
             # Display initial course list from login response
            self.update_course_tree(self.course_tree, data.get('courses', []), is_my_courses=False)
            self.set_status(f"Admin '{self.username}' logged in. Welcome!")

        elif action == 'list_courses_student' or action == 'list_courses_admin':
             self.update_course_tree(self.course_tree, data.get('courses', []), is_my_courses=False)

        elif action == 'my_courses':
            self.update_course_tree(self.my_course_tree, data.get('registered_courses', []), is_my_courses=True)

        elif action in ['register_course', 'withdraw_course']:
             messagebox.showinfo("Success", message)
             # Refresh both lists after registration/withdrawal
             self.list_available_courses()
             self.list_my_courses()

        elif action in ['create_course', 'update_course', 'add_student']:
             messagebox.showinfo("Success", message)
             # Refresh course list for admin actions affecting it
             if action != 'add_student':
                 self.list_all_courses_admin() # Refresh admin's course view

        elif action == 'logout':
             # Message might already be shown by server response handling
             # messagebox.showinfo("Logout", message)
             self.reset_to_connection_view()

    def setup_main_ui_base(self):
        """Sets up the common base for student and admin UIs."""
        # Hide connection frame, show main view frame
        self.connection_frame.pack_forget()
        # Clear existing widgets in main_view_frame if any
        for widget in self.main_view_frame.winfo_children():
            widget.destroy()
        self.main_view_frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Paned window for resizing sections
        paned_window = ttk.PanedWindow(self.main_view_frame, orient=tk.VERTICAL)
        paned_window.pack(fill=tk.BOTH, expand=True)

        # Top frame for course lists
        courses_frame = ttk.Frame(paned_window, padding="5")
        paned_window.add(courses_frame, weight=3) # Give more weight

        # Bottom frame for actions
        self.action_frame = ttk.Frame(paned_window, padding="5")
        paned_window.add(self.action_frame, weight=1)

        return courses_frame # Return the frame where course lists will go

    def create_course_treeview(self, parent_frame, title, is_my_courses):
        """Creates a Treeview widget for displaying courses."""
        frame = ttk.LabelFrame(parent_frame, text=title, padding="10") # Increased padding
        # Pack side-by-side, fill available space
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)

        cols = ("Name", "Schedule", "Capacity")
        col_widths = {"Name": 220, "Schedule": 160, "Capacity": 80}
        if not is_my_courses: # Add Remaining Seats for available/all courses
            cols += ("Remaining Seats",)
            col_widths["Remaining Seats"] = 110

        tree = ttk.Treeview(frame, columns=cols, show='headings', height=15) # Increased height

        # Configure treeview style for alternating row colors (optional)
        self.style.map("Treeview", background=[('selected', '#a0c4ff')]) # Highlight selection
        tree.tag_configure('oddrow', background='#f0f8ff') # AliceBlue
        tree.tag_configure('evenrow', background='#ffffff') # White

        for col in cols:
            # Allow clicking headings to sort (implement sorting logic separately if needed)
            tree.heading(col, text=col, anchor=tk.W)#, command=lambda c=col: self.sort_treeview(tree, c, False))
            tree.column(col, width=col_widths.get(col, 100), anchor=tk.W, stretch=tk.YES) # Allow stretching

        # Scrollbars
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        tree.pack(fill=tk.BOTH, expand=True)

        return tree


    def setup_student_ui(self):
        """Configures the UI for the student view."""
        courses_frame = self.setup_main_ui_base()

        # Available Courses Treeview
        self.course_tree = self.create_course_treeview(courses_frame, "Available Courses", is_my_courses=False)

        # My Registered Courses Treeview
        self.my_course_tree = self.create_course_treeview(courses_frame, "My Registered Courses", is_my_courses=True)


        # --- Student Action Buttons ---
        btn_frame = ttk.Frame(self.action_frame)
        btn_frame.pack(pady=15) # Increased padding

        # Configure button style
        self.style.configure('Action.TButton', font=('Helvetica', 10), padding=5)

        ttk.Button(btn_frame, text="Refresh Available Courses", command=self.list_available_courses, style='Action.TButton').grid(row=0, column=0, padx=10, pady=5)
        ttk.Button(btn_frame, text="Refresh My Courses", command=self.list_my_courses, style='Action.TButton').grid(row=0, column=1, padx=10, pady=5)
        ttk.Button(btn_frame, text="Register Selected Course", command=self.register_selected_course, style='Action.TButton').grid(row=1, column=0, padx=10, pady=5)
        ttk.Button(btn_frame, text="Withdraw Selected Course", command=self.withdraw_selected_course, style='Action.TButton').grid(row=1, column=1, padx=10, pady=5)
        ttk.Button(btn_frame, text="Logout", command=self.logout, style='Action.TButton').grid(row=2, column=0, columnspan=2, padx=10, pady=15)


    def setup_admin_ui(self):
        """Configures the UI for the admin view."""
        courses_frame = self.setup_main_ui_base()

        # All Courses Treeview (Admin sees all)
        # Make this single treeview take up the whole width
        self.course_tree = self.create_course_treeview(courses_frame, "All Courses Management", is_my_courses=False)
        # Remove packing side=tk.LEFT and let it fill
        self.course_tree.master.pack_configure(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)


        # --- Admin Action Buttons ---
        btn_frame = ttk.Frame(self.action_frame)
        btn_frame.pack(pady=15) # Increased padding

        # Configure button style
        self.style.configure('Action.TButton', font=('Helvetica', 10), padding=5)

        ttk.Button(btn_frame, text="Refresh Course List", command=self.list_all_courses_admin, style='Action.TButton').grid(row=0, column=0, padx=10, pady=5)
        ttk.Button(btn_frame, text="Create New Course", command=self.create_course_popup, style='Action.TButton').grid(row=0, column=1, padx=10, pady=5)
        ttk.Button(btn_frame, text="Update Course Capacity", command=self.update_course_popup, style='Action.TButton').grid(row=1, column=0, padx=10, pady=5)
        ttk.Button(btn_frame, text="Add New Student", command=self.add_student_popup, style='Action.TButton').grid(row=1, column=1, padx=10, pady=5)
        ttk.Button(btn_frame, text="Logout", command=self.logout, style='Action.TButton').grid(row=2, column=0, columnspan=2, padx=10, pady=15)


    def update_course_tree(self, tree, courses, is_my_courses):
        """Clears and repopulates the specified course Treeview with alternating row colors."""
        if not tree: return # Treeview might not exist yet

        # Clear existing items
        for item in tree.get_children():
            tree.delete(item)

        # Insert new course data
        if courses:
            for i, course in enumerate(courses):
                tag = 'oddrow' if i % 2 != 0 else 'evenrow' # Apply alternating tags
                name = course.get('name', 'N/A')
                schedule = course.get('schedule', 'N/A')
                capacity = course.get('capacity', 'N/A')
                if is_my_courses:
                    values = (name, schedule, capacity)
                else:
                    remaining = course.get('remaining_seats', 'N/A')
                    values = (name, schedule, capacity, remaining)
                tree.insert('', tk.END, values=values, tags=(tag,))
        else:
            # Insert a placeholder if no courses
             tree.insert('', tk.END, values=("No courses to display.",) + ("",) * (len(tree["columns"]) - 1), tags=('oddrow',))


    def get_selected_course_name(self, tree):
        """Gets the name of the course selected in the specified Treeview."""
        if not tree: return None
        selection = tree.selection() # Get selected item identifiers (can be multiple)
        if not selection:
            messagebox.showwarning("Selection Error", "Please select a course from the list first.")
            return None
        # Handle only the first selected item if multiple are somehow selected
        selected_item = selection[0]
        item_values = tree.item(selected_item, 'values')
        if item_values and len(item_values) > 0:
            # Check if it's the placeholder message
            if "No courses to display" in item_values[0]:
                return None
            return item_values[0] # Assuming course name is the first column
        return None

    # --- Student Actions ---
    def list_available_courses(self):
        if self.network_client and self.is_logged_in:
            self.set_status("Fetching available courses...")
            self.network_client.send_request('list_courses_student')

    def list_my_courses(self):
        if self.network_client and self.is_logged_in:
            self.set_status("Fetching your registered courses...")
            self.network_client.send_request('my_courses')

    def register_selected_course(self):
        course_name = self.get_selected_course_name(self.course_tree) # Select from available courses
        if course_name and self.network_client and self.is_logged_in:
            self.set_status(f"Registering for '{course_name}'...")
            self.network_client.send_request('register_course', {'course_name': course_name})

    def withdraw_selected_course(self):
        course_name = self.get_selected_course_name(self.my_course_tree) # Select from *my* courses
        if course_name and self.network_client and self.is_logged_in:
            if messagebox.askyesno("Confirm Withdrawal", f"Are you sure you want to withdraw from '{course_name}'?"):
                self.set_status(f"Withdrawing from '{course_name}'...")
                self.network_client.send_request('withdraw_course', {'course_name': course_name})

    # --- Admin Actions ---
    def list_all_courses_admin(self):
         if self.network_client and self.is_logged_in:
            self.set_status("Fetching all courses...")
            self.network_client.send_request('list_courses_admin')

    def create_course_popup(self):
        """Shows a popup dialog to get new course details."""
        dialog = SimpleDialog(self, "Create New Course", ["Course Name:", "Schedule (e.g., MWF 10:00-11:00):", "Capacity:"], ["", "", ""])
        result = dialog.show()

        if result:
            name, schedule, capacity_str = result
            if not name or not schedule or not capacity_str:
                messagebox.showerror("Input Error", "All fields are required.")
                return
            try:
                capacity = int(capacity_str)
                if capacity <= 0: raise ValueError("Capacity must be positive")
            except ValueError:
                messagebox.showerror("Input Error", "Invalid capacity. Please enter a positive number.")
                return

            # Basic schedule format validation (example)
            import re
            if not re.match(r"^[MTWRFSU]+ \d{2}:\d{2}-\d{2}:\d{2}$", schedule.upper()):
                 messagebox.showerror("Input Error", "Invalid schedule format. Use Days HH:MM-HH:MM (e.g., MWF 10:00-11:00)")
                 return

            if self.network_client and self.is_logged_in:
                 self.set_status(f"Creating course '{name}'...")
                 self.network_client.send_request('create_course', {'name': name, 'schedule': schedule, 'capacity': capacity})


    def update_course_popup(self):
        """Shows a popup to update course capacity."""
        course_name = self.get_selected_course_name(self.course_tree)
        if not course_name: return

        dialog = SimpleDialog(self, f"Update Capacity for {course_name}", ["New Capacity:"], [""])
        result = dialog.show()

        if result:
            new_capacity_str = result[0]
            if not new_capacity_str:
                 messagebox.showerror("Input Error", "New capacity is required.")
                 return
            try:
                new_capacity = int(new_capacity_str)
            except ValueError:
                messagebox.showerror("Input Error", "Invalid capacity. Please enter a number.")
                return

            if self.network_client and self.is_logged_in:
                 self.set_status(f"Updating capacity for '{course_name}'...")
                 self.network_client.send_request('update_course', {'name': course_name, 'capacity': new_capacity})


    def add_student_popup(self):
        """Shows a popup to add a new student."""
        dialog = SimpleDialog(self, "Add New Student", ["Full Name:", "Username:", "Password:"], ["", "", ""], show_last='*')
        result = dialog.show()

        if result:
            name, username, password = result
            if not name or not username or not password:
                messagebox.showerror("Input Error", "All fields are required.")
                return
            if len(password) < 4: # Basic password length check
                 messagebox.showerror("Input Error", "Password must be at least 4 characters long.")
                 return

            # Optional: Add password confirmation in a more complex dialog if needed
            if self.network_client and self.is_logged_in:
                 self.set_status(f"Adding student '{username}'...")
                 self.network_client.send_request('add_student', {'name': name, 'username': username, 'password': password})


    # --- General Actions ---
    def logout(self):
        """Logs the user out and returns to the connection screen."""
        if self.network_client and self.is_logged_in:
            self.set_status("Logging out...")
            self.network_client.send_request('logout') # Server handles response via queue
            # Response handler will call reset_to_connection_view if logout is successful
        else:
             # If not logged in but somehow here, just reset view
             self.reset_to_connection_view()


    def reset_to_connection_view(self):
        """Resets the UI back to the initial connection/login state."""
        # Disconnect network client if connected
        if self.network_client:
            self.network_client.disconnect()
            self.network_client = None

        # Reset state variables
        self.user_type = None
        self.username = None
        self.is_logged_in = False

        # Hide main view frame and show connection frame (centered)
        self.main_view_frame.pack_forget()
        # Clear main view frame widgets to release resources
        for widget in self.main_view_frame.winfo_children():
            widget.destroy()
        self.connection_frame.pack(expand=True) # Re-pack connection frame centered

        # Clear credentials (optional, maybe keep username?)
        # self.username_entry.delete(0, tk.END)
        self.password_entry.delete(0, tk.END)

        self.set_status("Disconnected. Enter server port and credentials to connect.")


    def on_closing(self):
        """Handles the window closing event."""
        if messagebox.askokcancel("Quit", "Do you want to quit the application?"):
            if self.network_client:
                print("Disconnecting on close...")
                self.network_client.disconnect() # Ensure clean disconnect
            self.destroy()


# --- Helper Dialog Class (More flexible than simpledialog) ---
class SimpleDialog(Toplevel):
    """A simple custom dialog box."""
    def __init__(self, parent, title, prompts, initial_values=None, show_last=None):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.parent = parent
        self.result = None
        self.prompts = prompts
        self.initial_values = initial_values or [""] * len(prompts)
        self.show_last = show_last # Character to show for the last entry (e.g., '*')

        # Style configuration
        self.style = ttk.Style(self)
        self.style.configure('Dialog.TFrame', background='#f0f0f0')
        self.style.configure('Dialog.TLabel', background='#f0f0f0', font=('Helvetica', 10))
        self.style.configure('Dialog.TButton', font=('Helvetica', 10), padding=5)

        self.configure(bg='#f0f0f0')

        body = ttk.Frame(self, style='Dialog.TFrame')
        self.entries = []
        for i, prompt in enumerate(prompts):
            ttk.Label(body, text=prompt, style='Dialog.TLabel').grid(row=i, column=0, sticky=tk.W, padx=5, pady=5)
            entry = ttk.Entry(body, width=35, font=('Helvetica', 10)) # Increased width
            entry.grid(row=i, column=1, padx=5, pady=5, sticky=tk.EW) # Sticky EW
            entry.insert(0, self.initial_values[i])
            if i == len(prompts) - 1 and show_last:
                entry.config(show=show_last)
            self.entries.append(entry)
        body.columnconfigure(1, weight=1) # Allow entry column to expand
        body.pack(padx=15, pady=15, fill=tk.X, expand=True)

        buttonbox = ttk.Frame(self, style='Dialog.TFrame')
        ok_btn = ttk.Button(buttonbox, text="OK", width=10, command=self.ok, default=tk.ACTIVE, style='Dialog.TButton')
        ok_btn.pack(side=tk.LEFT, padx=10, pady=10)
        cancel_btn = ttk.Button(buttonbox, text="Cancel", width=10, command=self.cancel, style='Dialog.TButton')
        cancel_btn.pack(side=tk.LEFT, padx=10, pady=10)
        buttonbox.pack()

        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

        self.grab_set() # Make modal

        if self.entries:
            self.entries[0].focus_set()

        self.protocol("WM_DELETE_WINDOW", self.cancel)

        # Center the dialog relative to the parent window
        self.update_idletasks() # Ensure window size is calculated
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        dialog_width = self.winfo_width()
        dialog_height = self.winfo_height()
        x = parent_x + (parent_width // 2) - (dialog_width // 2)
        y = parent_y + (parent_height // 2) - (dialog_height // 2)
        self.geometry(f'+{x}+{y}') # Position relative to parent

        # self.wait_window(self) # Don't use wait_window here, use show() method

    def show(self):
        """Shows the dialog and waits for it to close."""
        self.wm_deiconify()
        self.entries[0].focus_force()
        self.wait_window(self)
        return self.result

    def ok(self, event=None):
        self.result = [entry.get() for entry in self.entries]
        # Basic validation example (can be expanded)
        # if not all(self.result):
        #     messagebox.showwarning("Input Required", "Please fill all fields.", parent=self)
        #     return
        self.withdraw()
        self.update_idletasks()
        # self.parent.focus_set() # May not be needed if grab_set releases properly
        self.destroy()

    def cancel(self, event=None):
        self.result = None # Ensure result is None on cancel
        # self.parent.focus_set()
        self.destroy()


# --- Main Execution ---
if __name__ == "__main__":
    app = RegistrarApp()
    app.mainloop()
