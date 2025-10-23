import socket
import threading
import json
import sqlite3
import hashlib
import sys
import logging
from datetime import datetime

DATABASE_FILE = 'registrar.db'
HOST = '127.0.0.1'
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin_password"
MAX_COURSES_PER_STUDENT = 5
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

db_lock = threading.Lock()

def init_db():
    try:
        conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS students (
                username TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS courses (
                name TEXT PRIMARY KEY,
                schedule TEXT NOT NULL,
                capacity INTEGER NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS registrations (
                student_username TEXT NOT NULL,
                course_name TEXT NOT NULL,
                FOREIGN KEY(student_username) REFERENCES students(username),
                FOREIGN KEY(course_name) REFERENCES courses(name),
                PRIMARY KEY (student_username, course_name)
            )
        ''')
        cursor.execute("SELECT username FROM admins WHERE username = ?", (ADMIN_USERNAME,))
        if cursor.fetchone() is None:
            hashed_password = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
            cursor.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", (ADMIN_USERNAME, hashed_password))
            logging.info(f"Default admin user '{ADMIN_USERNAME}' created.")
        conn.commit()
        logging.info("Database initialized successfully.")
    except sqlite3.Error as e:
        logging.error(f"Database error during initialization: {e}")
        sys.exit(1)
    finally:
        if conn:
            conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_hash, provided_password):
    return stored_hash == hash_password(provided_password)

def parse_schedule(schedule_str):
    try:
        parts = schedule_str.split()
        if len(parts) != 2:
            return None
        days_str = parts[0].upper()
        time_str = parts[1]
        days = set()
        valid_days = "MTWRFSU"
        for char in days_str:
            if char not in valid_days:
                return None
            days.add(char)
        time_parts = time_str.split('-')
        if len(time_parts) != 2:
            return None
        start_time = datetime.strptime(time_parts[0], '%H:%M')
        end_time = datetime.strptime(time_parts[1], '%H:%M')
        start_minutes = start_time.hour * 60 + start_time.minute
        end_minutes = end_time.hour * 60 + end_time.minute
        if start_minutes >= end_minutes:
            return None
        return days, start_minutes, end_minutes
    except ValueError:
        logging.warning(f"Invalid schedule format: {schedule_str}")
        return None

def check_schedule_overlap(schedule1_str, schedule2_str):
    parsed1 = parse_schedule(schedule1_str)
    parsed2 = parse_schedule(schedule2_str)
    if not parsed1 or not parsed2:
        return False
    days1, start1, end1 = parsed1
    days2, start2, end2 = parsed2
    if not days1.intersection(days2):
        return False
    if max(start1, start2) < min(end1, end2):
        return True
    return False

def db_execute(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = None
    result = None
    acquired_lock = False
    try:
        if commit:
            db_lock.acquire()
            acquired_lock = True
        conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        if commit:
            conn.commit()
            result = True
        elif fetchone:
            result = cursor.fetchone()
        elif fetchall:
            result = cursor.fetchall()
    except sqlite3.Error as e:
        logging.error(f"Database error: {e} | Query: {query} | Params: {params}")
        if commit and conn:
            conn.rollback()
        result = False if commit else None
    finally:
        if conn:
            conn.close()
        if acquired_lock:
            db_lock.release()
    return result

def handle_login_student(data):
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return {"status": "error", "message": "Username and password required"}
    student = db_execute("SELECT password_hash FROM students WHERE username = ?", (username,), fetchone=True)
    if student and verify_password(student['password_hash'], password):
        registered_courses = get_student_registered_courses(username)
        return {"status": "success", "data": {"registered_courses": registered_courses}}
    else:
        return {"status": "error", "message": "Invalid credentials"}

def handle_login_admin(data):
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return {"status": "error", "message": "Username and password required"}
    admin = db_execute("SELECT password_hash FROM admins WHERE username = ?", (username,), fetchone=True)
    if admin and verify_password(admin['password_hash'], password):
        all_courses = get_all_courses_details()
        return {"status": "success", "data": {"courses": all_courses}}
    else:
        return {"status": "error", "message": "Invalid credentials"}

def get_all_courses_details():
    courses = db_execute("""
        SELECT c.name, c.schedule, c.capacity,
               (c.capacity - COUNT(r.course_name)) as remaining_seats
        FROM courses c
        LEFT JOIN registrations r ON c.name = r.course_name
        GROUP BY c.name, c.schedule, c.capacity
        ORDER BY c.name
    """, fetchall=True)
    return [dict(row) for row in courses] if courses else []

def get_student_registered_courses(student_username):
    courses = db_execute("""
        SELECT c.name, c.schedule, c.capacity
        FROM courses c
        JOIN registrations r ON c.name = r.course_name
        WHERE r.student_username = ?
        ORDER BY c.name
    """, (student_username,), fetchall=True)
    return [dict(row) for row in courses] if courses else []

def handle_list_courses_student(data, student_username):
    courses = get_all_courses_details()
    return {"status": "success", "data": {"courses": courses}}

def handle_list_courses_admin(data, admin_username):
    courses = get_all_courses_details()
    return {"status": "success", "data": {"courses": courses}}

def handle_my_courses(data, student_username):
    registered_courses = get_student_registered_courses(student_username)
    return {"status": "success", "data": {"registered_courses": registered_courses}}

def handle_register_course(data, student_username):
    course_name = data.get('course_name')
    if not course_name:
        return {"status": "error", "message": "Course name required"}
    course = db_execute("""
        SELECT c.name, c.schedule, c.capacity,
               (c.capacity - COUNT(r.course_name)) as remaining_seats
        FROM courses c
        LEFT JOIN registrations r ON c.name = r.course_name
        WHERE c.name = ?
        GROUP BY c.name
    """, (course_name,), fetchone=True)
    if not course:
        return {"status": "error", "message": f"Course '{course_name}' not found"}
    if course['remaining_seats'] <= 0:
        return {"status": "error", "message": f"Course '{course_name}' is full"}
    existing_reg = db_execute("SELECT 1 FROM registrations WHERE student_username = ? AND course_name = ?", (student_username, course_name), fetchone=True)
    if existing_reg:
        return {"status": "error", "message": f"You are already registered for '{course_name}'"}
    registered_courses = get_student_registered_courses(student_username)
    if len(registered_courses) >= MAX_COURSES_PER_STUDENT:
        return {"status": "error", "message": f"Cannot register for more than {MAX_COURSES_PER_STUDENT} courses"}
    new_course_schedule = course['schedule']
    for reg_course in registered_courses:
        if check_schedule_overlap(new_course_schedule, reg_course['schedule']):
            return {"status": "error", "message": f"Schedule conflict with '{reg_course['name']}' ({reg_course['schedule']})"}
    success = db_execute("INSERT INTO registrations (student_username, course_name) VALUES (?, ?)", (student_username, course_name), commit=True)
    if success:
        logging.info(f"Student '{student_username}' registered for course '{course_name}'")
        return {"status": "success", "message": f"Successfully registered for '{course_name}'"}
    else:
        return {"status": "error", "message": "Failed to register for course due to a database error"}

def handle_withdraw_course(data, student_username):
    course_name = data.get('course_name')
    if not course_name:
        return {"status": "error", "message": "Course name required"}
    existing_reg = db_execute("SELECT 1 FROM registrations WHERE student_username = ? AND course_name = ?", (student_username, course_name), fetchone=True)
    if not existing_reg:
        return {"status": "error", "message": f"You are not registered for '{course_name}'"}
    success = db_execute("DELETE FROM registrations WHERE student_username = ? AND course_name = ?", (student_username, course_name), commit=True)
    if success:
        logging.info(f"Student '{student_username}' withdrew from course '{course_name}'")
        return {"status": "success", "message": f"Successfully withdrew from '{course_name}'"}
    else:
        return {"status": "error", "message": "Failed to withdraw from course due to a database error"}

def handle_create_course(data, admin_username):
    name = data.get('name')
    schedule = data.get('schedule')
    capacity = data.get('capacity')
    if not name or not schedule or capacity is None:
        return {"status": "error", "message": "Course name, schedule, and capacity required"}
    try:
        capacity = int(capacity)
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
    except ValueError:
        return {"status": "error", "message": "Invalid capacity value"}
    if not parse_schedule(schedule):
        return {"status": "error", "message": "Invalid schedule format. Use Days HH:MM-HH:MM (e.g., MWF 10:00-11:00)"}
    existing = db_execute("SELECT 1 FROM courses WHERE name = ?", (name,), fetchone=True)
    if existing:
        return {"status": "error", "message": f"Course '{name}' already exists"}
    success = db_execute("INSERT INTO courses (name, schedule, capacity) VALUES (?, ?, ?)", (name, schedule, capacity), commit=True)
    if success:
        logging.info(f"Admin '{admin_username}' created course '{name}'")
        return {"status": "success", "message": f"Course '{name}' created successfully"}
    else:
        return {"status": "error", "message": "Failed to create course due to a database error"}

def handle_update_course(data, admin_username):
    name = data.get('name')
    new_capacity = data.get('capacity')
    if not name or new_capacity is None:
        return {"status": "error", "message": "Course name and new capacity required"}
    try:
        new_capacity = int(new_capacity)
    except ValueError:
        return {"status": "error", "message": "Invalid capacity value"}
    course = db_execute("SELECT capacity FROM courses WHERE name = ?", (name,), fetchone=True)
    if not course:
        return {"status": "error", "message": f"Course '{name}' not found"}
    current_capacity = course['capacity']
    if new_capacity <= current_capacity:
        return {"status": "error", "message": f"New capacity ({new_capacity}) must be greater than current capacity ({current_capacity})"}
    success = db_execute("UPDATE courses SET capacity = ? WHERE name = ?", (new_capacity, name), commit=True)
    if success:
        logging.info(f"Admin '{admin_username}' updated capacity for course '{name}' to {new_capacity}")
        return {"status": "success", "message": f"Capacity for course '{name}' updated to {new_capacity}"}
    else:
        return {"status": "error", "message": "Failed to update course capacity due to a database error"}

def handle_add_student(data, admin_username):
    name = data.get('name')
    username = data.get('username')
    password = data.get('password')
    if not name or not username or not password:
        return {"status": "error", "message": "Student name, username, and password required"}
    existing = db_execute("SELECT 1 FROM students WHERE username = ?", (username,), fetchone=True)
    if existing:
        return {"status": "error", "message": f"Student username '{username}' already exists"}
    hashed_password = hash_password(password)
    success = db_execute("INSERT INTO students (name, username, password_hash) VALUES (?, ?, ?)", (name, username, hashed_password), commit=True)
    if success:
        logging.info(f"Admin '{admin_username}' added student '{username}'")
        return {"status": "success", "message": f"Student '{username}' added successfully"}
    else:
        return {"status": "error", "message": "Failed to add student due to a database error"}

def handle_client(conn, addr):
    logging.info(f"Connection established with {addr}")
    is_authenticated = False
    user_type = None
    username = None
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                logging.info(f"Client {addr} disconnected (no data received).")
                break
            try:
                request = json.loads(data.decode('utf-8'))
                action = request.get('action')
                req_data = request.get('data', {})
                response = {"status": "error", "message": "Invalid action"}
                if not is_authenticated:
                    if action == 'login_student':
                        response = handle_login_student(req_data)
                        if response['status'] == 'success':
                            is_authenticated = True
                            user_type = 'student'
                            username = req_data['username']
                            logging.info(f"Student '{username}' authenticated from {addr}")
                    elif action == 'login_admin':
                        response = handle_login_admin(req_data)
                        if response['status'] == 'success':
                            is_authenticated = True
                            user_type = 'admin'
                            username = req_data['username']
                            logging.info(f"Admin '{username}' authenticated from {addr}")
                    else:
                        response = {"status": "error", "message": "Authentication required"}
                else:
                    if user_type == 'student':
                        if action == 'list_courses_student':
                            response = handle_list_courses_student(req_data, username)
                        elif action == 'register_course':
                            response = handle_register_course(req_data, username)
                        elif action == 'withdraw_course':
                            response = handle_withdraw_course(req_data, username)
                        elif action == 'my_courses':
                            response = handle_my_courses(req_data, username)
                        elif action == 'logout':
                            response = {"status": "success", "message": "Logged out"}
                            is_authenticated = False
                        else:
                            response = {"status": "error", "message": "Invalid action for student"}
                    elif user_type == 'admin':
                        if action == 'list_courses_admin':
                            response = handle_list_courses_admin(req_data, username)
                        elif action == 'create_course':
                            response = handle_create_course(req_data, username)
                        elif action == 'update_course':
                            response = handle_update_course(req_data, username)
                        elif action == 'add_student':
                            response = handle_add_student(req_data, username)
                        elif action == 'logout':
                            response = {"status": "success", "message": "Logged out"}
                            is_authenticated = False
                        else:
                            response = {"status": "error", "message": "Invalid action for admin"}
                conn.sendall(json.dumps(response).encode('utf-8'))
                if action == 'logout' and response['status'] == 'success':
                    logging.info(f"User '{username}' ({user_type}) logged out from {addr}")
                    break
            except json.JSONDecodeError:
                conn.sendall(json.dumps({"status": "error", "message": "Invalid JSON format"}).encode('utf-8'))
            except Exception as e:
                logging.error(f"Error handling request from {addr}: {e}", exc_info=True)
                try:
                    conn.sendall(json.dumps({"status": "error", "message": "An internal server error occurred"}).encode('utf-8'))
                except Exception as send_e:
                    logging.error(f"Failed to send error response to {addr}: {send_e}")
    except ConnectionResetError:
        logging.warning(f"Client {addr} forcefully closed the connection.")
    except Exception as e:
        logging.error(f"An unexpected error occurred with client {addr}: {e}", exc_info=True)
    finally:
        logging.info(f"Closing connection with {addr}")
        conn.close()

def main(port):
    init_db()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HOST, port))
        server_socket.listen(5)
        logging.info(f"Server listening on {HOST}:{port}")
        while True:
            try:
                conn, addr = server_socket.accept()
                client_thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
                client_thread.start()
            except Exception as e:
                logging.error(f"Error accepting connection: {e}")
    except OSError as e:
        logging.error(f"Failed to bind to {HOST}:{port}. Error: {e}. Is the port already in use?")
    except KeyboardInterrupt:
        logging.info("Server shutting down...")
    finally:
        logging.info("Closing server socket.")
        server_socket.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python server.py <port>")
        sys.exit(1)
    try:
        server_port = int(sys.argv[1])
        if not (1024 <= server_port <= 65535):
            raise ValueError("Port must be between 1024 and 65535")
        main(server_port)
    except ValueError as e:
        print(f"Invalid port number: {sys.argv[1]}. {e}")
        sys.exit(1)
    except Exception as e:
        logging.critical(f"Server failed to start: {e}", exc_info=True)
        sys.exit(1)
