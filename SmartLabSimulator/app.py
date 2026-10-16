import json

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from config import Config

db = SQLAlchemy()


def create_app():
    app = Flask(__name__, template_folder="frontend", static_folder="static")
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        from models import AuditLog, Booking, Computer, SyscallLog, TaskLog, User
        db.create_all()

        if Computer.query.count() == 0:
            sample_computers = [
                Computer(
                    computer_name="PC-01",
                    ip_address="192.168.1.10",
                    processor="Intel i7",
                    ram_gb=16,
                    storage_gb=512,
                    operating_system="Ubuntu 22.04",
                    status="AVAILABLE",
                ),
                Computer(
                    computer_name="PC-02",
                    ip_address="192.168.1.11",
                    processor="Intel i5",
                    ram_gb=8,
                    storage_gb=256,
                    operating_system="Windows 11",
                    status="IN_USE",
                ),
                Computer(
                    computer_name="PC-03",
                    ip_address="192.168.1.12",
                    processor="AMD Ryzen 5",
                    ram_gb=12,
                    storage_gb=512,
                    operating_system="Fedora",
                    status="MAINTENANCE",
                ),
                Computer(
                    computer_name="PC-04",
                    ip_address="192.168.1.13",
                    processor="Intel i9",
                    ram_gb=32,
                    storage_gb=1024,
                    operating_system="Windows 10",
                    status="AVAILABLE",
                ),
            ]
            db.session.add_all(sample_computers)
            db.session.commit()

        # DBMS extras: views, triggers and demo users
        from database_objects import create_database_objects, seed_users
        create_database_objects()
        seed_users()

    # OS <-> DBMS bridge: every system call is also saved in the syscall_log table.
    import syscalls

    def save_syscall(record):
        with app.app_context():
            db.session.add(SyscallLog(
                syscall=record["syscall"], category=record["category"],
                args=json.dumps(record["args"], default=str), status=record["status"],
                duration_ms=record["duration_ms"], caller_pid=record["caller_pid"]))
            db.session.commit()

    syscalls.set_hook(save_syscall)

    from routes import main
    app.register_blueprint(main)

    return app