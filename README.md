# 🎓 AUB Registrar System

A full-stack client-server course registration platform built in Python as part of EECE 350 at the American University of Beirut.  
The system simulates a real university registrar platform, enabling students to manage their courses and schedules while administrators control course offerings, all through a secure, database driven backend with both GUI and CLI interfaces.

---

## ✨ Features

- 🔐 **Secure Authentication** – Login for students and admins with SHA-256 password hashing.  
- 📡 **Client-Server Communication** – Real-time data exchange over TCP sockets using JSON.  
- 🧵 **Multi-threaded Server** – Handles multiple client connections simultaneously.  
- 🗄️ **SQLite Database Integration** – Persistent storage for users, courses, and enrollments.  
- 📚 **Student Functions** – View available courses, register, withdraw, and manage schedules.  
- 📊 **Admin Functions** – Create, update, and manage courses and student accounts.  
- 🖥️ **GUI Client** – Tkinter-based interface with dynamic views based on user roles.  
- 💻 **CLI Clients** – Terminal-based clients for both students and admins.  
- ⚠️ **Conflict & Capacity Checks** – Automatically prevents schedule conflicts and over enrollment.

---

## 🏗️ System Architecture

The project follows a **client-server architecture**:

- **Server (`server.py`)**  
  - Handles authentication and database operations.  
  - Uses threading to support multiple simultaneous connections.  
  - Communicates with clients using TCP sockets and JSON messages.

- **GUI Client (`registrar_gui.py`)**  
  - Built with Tkinter for a user friendly interface.  
  - Updates student/admin dashboards based on server responses.  

- **CLI Clients (`client_student.py`, `client_admin.py`)**  
  - Text-based alternatives for quick operations and testing.  
  - Provide the same functionality as the GUI clients.

- **Database (`registrar.db`)**  
  - SQLite database storing user accounts, course data, and enrollments.  
  - Uses threading locks to ensure safe concurrent writes.

---

## 🛠️ Tech

- **Language:** Python 3  
- **UI:** Tkinter (GUI) & Command-Line Interface (CLI)  
- **Networking:** TCP/IP sockets with JSON protocol  
- **Database:** SQLite  
- **Concurrency:** Python `threading` module

---

## 📁 Project Structure

📂 aub-registrar-system/
├── server.py              # Main server logic
├── registrar_gui.py       # GUI client
├── client_student.py      # CLI client for students
├── client_admin.py        # CLI client for admins
├── registrar.db           # SQLite database
└── README.md              # Project documentation

---

## 🚀 How to Run

Follow these steps to run the AUB Registrar System on your machine:

# 1. Clone the repository (or download the ZIP and extract it)
git clone https://github.com/YourUsername/aub-registrar-system.git
cd aub-registrar-system

# 2. Check that Python 3 is installed
python --version

# 3. Start the server
python server.py 65432

# 4. Launch the GUI client
python registrar_gui.py

# 5. (Optional) Run CLI clients
python client_student.py 65432
python client_admin.py 65432

Make sure all files (server.py, registrar_gui.py, client_student.py, client_admin.py, and registrar.db) are in the same folder before running these commands.
