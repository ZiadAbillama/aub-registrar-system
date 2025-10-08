import socket
import json
import sys
import getpass # For securely getting password input

# --- Configuration ---
SERVER_HOST = '127.0.0.1'
BUFFER_SIZE = 4096

# --- Helper Functions ---
# Re-using the helper functions from the student client for consistency
# (In a larger project, these might go into a shared utility module)

def send_request(sock, action, data=None):
    """Sends a JSON request to the server and returns the JSON response."""
    request = {"action": action, "data": data or {}}
    try:
        sock.sendall(json.dumps(request).encode('utf-8'))
        response_data = sock.recv(BUFFER_SIZE)
        if not response_data:
            print("\n[Error] Connection lost with the server.")
            return None
        response = json.loads(response_data.decode('utf-8'))
        return response
    except (socket.error, json.JSONDecodeError, ConnectionResetError, BrokenPipeError) as e:
        print(f"\n[Error] Communication error: {e}")
        return None
    except Exception as e:
        print(f"\n[Error] An unexpected error occurred: {e}")
        return None

def display_courses(courses, title="Courses"):
    """Prints a formatted list of courses."""
    print(f"\n--- {title} ---")
    if not courses:
        print("No courses to display.")
        return

    headers = ["Name", "Schedule", "Capacity", "Remaining Seats"]

    # Calculate column widths
    col_widths = {header: len(header) for header in headers}
    for course in courses:
        col_widths["Name"] = max(col_widths["Name"], len(str(course.get('name', 'N/A'))))
        col_widths["Schedule"] = max(col_widths["Schedule"], len(str(course.get('schedule', 'N/A'))))
        col_widths["Capacity"] = max(col_widths["Capacity"], len(str(course.get('capacity', 'N/A'))))
        col_widths["Remaining Seats"] = max(col_widths["Remaining Seats"], len(str(course.get('remaining_seats', 'N/A'))))

    # Print header
    header_line = " | ".join(f"{h:<{col_widths[h]}}" for h in headers)
    print(header_line)
    print("-" * len(header_line))

    # Print course rows
    for course in courses:
        row_data = [
            str(course.get('name', 'N/A')),
            str(course.get('schedule', 'N/A')),
            str(course.get('capacity', 'N/A')),
            str(course.get('remaining_seats', 'N/A'))
        ]
        print(" | ".join(f"{row_data[i]:<{col_widths[h]}}" for i, h in enumerate(headers)))

    print("-" * len(header_line))


# --- Main Client Logic ---
def main(port):
    """Main function for the admin client."""
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        print(f"Connecting to server at {SERVER_HOST}:{port}...")
        client_socket.connect((SERVER_HOST, port))
        print("Connected successfully.")
    except socket.error as e:
        print(f"[Error] Could not connect to server: {e}")
        sys.exit(1)

    # --- Authentication ---
    logged_in = False
    while not logged_in:
        username = input("Enter admin username: ")
        # Use getpass for password security
        password = getpass.getpass("Enter admin password: ")

        if not username or not password:
            print("Username and password cannot be empty.")
            continue

        response = send_request(client_socket, 'login_admin', {'username': username, 'password': password})

        if response is None: # Handle connection error during login
             client_socket.close()
             sys.exit(1)

        if response.get('status') == 'success':
            print("\nAdmin login successful!")
            logged_in = True
            # Display initial list of courses upon successful login
            courses = response.get('data', {}).get('courses', [])
            display_courses(courses, "Current Course List")
        else:
            print(f"[Login Failed] {response.get('message', 'Unknown error')}")
            # Ask if user wants to retry
            retry = input("Try again? (y/n): ").lower()
            if retry != 'y':
                client_socket.close()
                sys.exit(0)


    # --- Main Menu ---
    while True:
        print("\n--- Admin Menu ---")
        print("Commands:")
        print("  list courses          - Show all courses")
        print("  create course         - Add a new course")
        print("  update course         - Increase capacity of a course")
        print("  add student           - Add a new student")
        print("  logout                - Exit the application")

        command_input = input("> ").strip().lower()
        parts = command_input.split(maxsplit=1) # Split into command and potential argument
        command = parts[0] if parts else ""
        # We might need more parts for some commands, handle later
        argument = parts[1] if len(parts) > 1 else None

        if command == 'list' and argument == 'courses':
            response = send_request(client_socket, 'list_courses_admin')
            if response and response.get('status') == 'success':
                display_courses(response.get('data', {}).get('courses', []), "Current Course List")
            elif response:
                print(f"[Error] {response.get('message', 'Failed to list courses')}")

        elif command == 'create' and argument == 'course':
            try:
                name = input("Enter course name: ").strip()
                # Example schedule format: MWF 10:00-11:00 or TR 14:00-15:30
                schedule = input("Enter schedule (e.g., MWF 10:00-11:00): ").strip()
                capacity_str = input("Enter maximum capacity: ").strip()
                if not name or not schedule or not capacity_str:
                     print("All fields are required.")
                     continue
                capacity = int(capacity_str) # Let potential ValueError be caught
                if capacity <= 0:
                    print("Capacity must be a positive number.")
                    continue

                response = send_request(client_socket, 'create_course', {
                    'name': name,
                    'schedule': schedule,
                    'capacity': capacity
                })
                if response:
                    print(f"[{response.get('status', 'error').upper()}] {response.get('message', 'No message received')}")
                    # Refresh course list on success
                    if response.get('status') == 'success':
                        list_resp = send_request(client_socket, 'list_courses_admin')
                        if list_resp and list_resp.get('status') == 'success':
                           display_courses(list_resp.get('data', {}).get('courses', []), "Updated Course List")

            except ValueError:
                print("[Error] Invalid capacity. Please enter a number.")
            except Exception as e:
                 print(f"[Error] Could not create course: {e}")


        elif command == 'update' and argument == 'course':
             try:
                name = input("Enter course name to update: ").strip()
                new_capacity_str = input("Enter new (increased) capacity: ").strip()
                if not name or not new_capacity_str:
                    print("Course name and new capacity are required.")
                    continue
                new_capacity = int(new_capacity_str) # Let potential ValueError be caught

                response = send_request(client_socket, 'update_course', {
                    'name': name,
                    'capacity': new_capacity
                })
                if response:
                    print(f"[{response.get('status', 'error').upper()}] {response.get('message', 'No message received')}")
                    # Refresh course list on success
                    if response.get('status') == 'success':
                        list_resp = send_request(client_socket, 'list_courses_admin')
                        if list_resp and list_resp.get('status') == 'success':
                           display_courses(list_resp.get('data', {}).get('courses', []), "Updated Course List")

             except ValueError:
                print("[Error] Invalid capacity. Please enter a number.")
             except Exception as e:
                 print(f"[Error] Could not update course: {e}")


        elif command == 'add' and argument == 'student':
            try:
                name = input("Enter student's full name: ").strip()
                username = input("Enter student's username: ").strip()
                # Use getpass for password security
                password = getpass.getpass("Enter student's password: ")
                confirm_password = getpass.getpass("Confirm student's password: ")

                if not name or not username or not password:
                    print("Name, username, and password are required.")
                    continue
                if password != confirm_password:
                    print("[Error] Passwords do not match.")
                    continue

                response = send_request(client_socket, 'add_student', {
                    'name': name,
                    'username': username,
                    'password': password
                })
                if response:
                    print(f"[{response.get('status', 'error').upper()}] {response.get('message', 'No message received')}")

            except Exception as e:
                 print(f"[Error] Could not add student: {e}")


        elif command == 'logout':
            print("Logging out...")
            send_request(client_socket, 'logout') # Inform server
            break # Exit the loop

        else:
            print("Invalid command. Please use one of the commands listed above.")

    # --- Cleanup ---
    print("Closing connection.")
    client_socket.close()
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python client_admin.py <server_port>")
        sys.exit(1)

    try:
        server_port = int(sys.argv[1])
        main(server_port)
    except ValueError:
        print(f"Invalid port number: {sys.argv[1]}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
