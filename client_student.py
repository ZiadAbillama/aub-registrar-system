import socket
import json
import sys
import getpass

SERVER_HOST = '127.0.0.1'
BUFFER_SIZE = 4096

def send_request(sock, action, data=None):
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
    print(f"\n--- {title} ---")
    if not courses:
        print("No courses to display.")
        return

    headers = ["Name", "Schedule", "Capacity"]
    if courses and 'remaining_seats' in courses[0]:
        headers.append("Remaining Seats")

    col_widths = {header: len(header) for header in headers}
    for course in courses:
        col_widths["Name"] = max(col_widths["Name"], len(str(course.get('name', 'N/A'))))
        col_widths["Schedule"] = max(col_widths["Schedule"], len(str(course.get('schedule', 'N/A'))))
        col_widths["Capacity"] = max(col_widths["Capacity"], len(str(course.get('capacity', 'N/A'))))
        if "Remaining Seats" in headers:
            col_widths["Remaining Seats"] = max(col_widths["Remaining Seats"], len(str(course.get('remaining_seats', 'N/A'))))

    header_line = " | ".join(f"{h:<{col_widths[h]}}" for h in headers)
    print(header_line)
    print("-" * len(header_line))

    for course in courses:
        row_data = [
            str(course.get('name', 'N/A')),
            str(course.get('schedule', 'N/A')),
            str(course.get('capacity', 'N/A'))
        ]
        if "Remaining Seats" in headers:
            row_data.append(str(course.get('remaining_seats', 'N/A')))

        print(" | ".join(f"{row_data[i]:<{col_widths[h]}}" for i, h in enumerate(headers)))

    print("-" * len(header_line))

def main(port):
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        print(f"Connecting to server at {SERVER_HOST}:{port}...")
        client_socket.connect((SERVER_HOST, port))
        print("Connected successfully.")
    except socket.error as e:
        print(f"[Error] Could not connect to server: {e}")
        sys.exit(1)

    logged_in = False
    while not logged_in:
        username = input("Enter username: ")
        password = getpass.getpass("Enter password: ")

        if not username or not password:
            print("Username and password cannot be empty.")
            continue

        response = send_request(client_socket, 'login_student', {'username': username, 'password': password})

        if response is None:
            client_socket.close()
            sys.exit(1)

        if response.get('status') == 'success':
            print("\nLogin successful!")
            logged_in = True
            registered_courses = response.get('data', {}).get('registered_courses', [])
            if registered_courses:
                display_courses(registered_courses, "Your Registered Courses")
            else:
                print("No courses registered yet.")
        else:
            print(f"[Login Failed] {response.get('message', 'Unknown error')}")
            retry = input("Try again? (y/n): ").lower()
            if retry != 'y':
                client_socket.close()
                sys.exit(0)

    while True:
        print("\n--- Student Menu ---")
        print("Commands:")
        print("  list courses          - Show available courses")
        print("  my courses            - Show your registered courses")
        print("  register <course_name> - Register for a course")
        print("  withdraw <course_name> - Withdraw from a course")
        print("  logout                - Exit the application")

        command_input = input("> ").strip()
        parts = command_input.split(maxsplit=1)
        command = parts[0] if parts else ""
        argument = parts[1] if len(parts) > 1 else None

        if command == 'list' and argument == 'courses':
            response = send_request(client_socket, 'list_courses_student')
            if response and response.get('status') == 'success':
                display_courses(response.get('data', {}).get('courses', []), "Available Courses")
            elif response:
                print(f"[Error] {response.get('message', 'Failed to list courses')}")

        elif command == 'my' and argument == 'courses':
            response = send_request(client_socket, 'my_courses')
            if response and response.get('status') == 'success':
                display_courses(response.get('data', {}).get('registered_courses', []), "Your Registered Courses")
            elif response:
                print(f"[Error] {response.get('message', 'Failed to fetch registered courses')}")

        elif command == 'register':
            if not argument:
                print("Usage: register <course_name>")
                continue
            response = send_request(client_socket, 'register_course', {'course_name': argument})
            if response:
                print(f"[{response.get('status', 'error').upper()}] {response.get('message', 'No message received')}")
                if response.get('status') == 'success':
                    my_courses_resp = send_request(client_socket, 'my_courses')
                    if my_courses_resp and my_courses_resp.get('status') == 'success':
                        display_courses(my_courses_resp.get('data', {}).get('registered_courses', []), "Updated Registered Courses")

        elif command == 'withdraw':
            if not argument:
                print("Usage: withdraw <course_name>")
                continue
            response = send_request(client_socket, 'withdraw_course', {'course_name': argument})
            if response:
                print(f"[{response.get('status', 'error').upper()}] {response.get('message', 'No message received')}")
                if response.get('status') == 'success':
                    my_courses_resp = send_request(client_socket, 'my_courses')
                    if my_courses_resp and my_courses_resp.get('status') == 'success':
                        display_courses(my_courses_resp.get('data', {}).get('registered_courses', []), "Updated Registered Courses")

        elif command == 'logout':
            print("Logging out...")
            send_request(client_socket, 'logout')
            break

        else:
            print("Invalid command. Please use one of the commands listed above.")

    print("Closing connection.")
    client_socket.close()
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python client_student.py <server_port>")
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
