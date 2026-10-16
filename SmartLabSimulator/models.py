from datetime import datetime

from app import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="student")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Computer(db.Model):
    __tablename__ = "computers"

    id = db.Column(db.Integer, primary_key=True)
    computer_name = db.Column(db.String(50), unique=True, nullable=False)
    ip_address = db.Column(db.String(50))
    processor = db.Column(db.String(100))
    ram_gb = db.Column(db.Integer)
    storage_gb = db.Column(db.Integer)
    operating_system = db.Column(db.String(100))
    status = db.Column(db.String(20), default="AVAILABLE")

    def to_dict(self):
        return {
            "id": self.id,
            "computer_name": self.computer_name,
            "ip_address": self.ip_address,
            "processor": self.processor,
            "ram_gb": self.ram_gb,
            "storage_gb": self.storage_gb,
            "operating_system": self.operating_system,
            "status": self.status,
        }


class Booking(db.Model):
    __tablename__ = "bookings"
    __table_args__ = (
        # The database itself refuses a booking that ends before it starts.
        db.CheckConstraint("end_time > start_time", name="ck_booking_time"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    computer_id = db.Column(db.Integer, db.ForeignKey("computers.id"), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default="ACTIVE")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "computer_id": self.computer_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "status": self.status,
        }


class TaskLog(db.Model):
    """One row per lab task (PCB) that was ever created. OS data stored in the DBMS."""
    __tablename__ = "task_log"

    id = db.Column(db.Integer, primary_key=True)
    pid = db.Column(db.Integer, nullable=False, index=True)
    program = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.String(10), default="normal")
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    computer_id = db.Column(db.Integer, db.ForeignKey("computers.id"))
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    exit_code = db.Column(db.Integer)


class SyscallLog(db.Model):
    """Every system call made through syscalls.invoke() is saved here."""
    __tablename__ = "syscall_log"

    id = db.Column(db.Integer, primary_key=True)
    syscall = db.Column(db.String(30), nullable=False, index=True)
    category = db.Column(db.String(20))
    args = db.Column(db.Text)
    status = db.Column(db.String(10))
    duration_ms = db.Column(db.Float)
    caller_pid = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class AuditLog(db.Model):
    """Filled automatically by database triggers (see database_objects.py)."""
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(30))
    action = db.Column(db.String(10))
    row_id = db.Column(db.Integer)
    detail = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
