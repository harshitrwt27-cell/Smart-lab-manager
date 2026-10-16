import os

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False


load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv(
        "DB_NAME",
        "sqlite:///resource_manager.db",
    )

    SQLALCHEMY_DATABASE_URI = (
        DATABASE_URL
        if DATABASE_URL.startswith("sqlite://")
        else (
            f"mysql+pymysql://"
            f"{os.getenv('DB_USER', 'root')}:"
            f"{os.getenv('DB_PASSWORD', '')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:"
            f"{os.getenv('DB_PORT', '3306')}/"
            f"{os.getenv('DB_NAME', 'resource_manager')}"
        )
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False