import os
import urllib.parse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Define constants for connection details
db_user = os.environ.get("MYSQL_USER", "root")
db_pass_raw = os.environ.get("MYSQL_PASSWORD", "your_password")
db_name = os.environ.get("MYSQL_DB", "users_db")

# ENCODE THE PASSWORD to handle special chars like @, #, /
db_pass = urllib.parse.quote_plus(db_pass_raw)

# check for Cloud SQL Connection Name
cloud_sql_connection_name = os.environ.get("INSTANCE_CONNECTION_NAME")

if cloud_sql_connection_name:
    # CLOUD RUN: Connect via Unix Socket
    # Format: mysql+pymysql://user:pass@/dbname?unix_socket=/cloudsql/INSTANCE_NAME
    socket_path = f"/cloudsql/{cloud_sql_connection_name}"
    DATABASE_URL = f"mysql+pymysql://{db_user}:{db_pass}@/{db_name}?unix_socket={socket_path}"
else:
    # LOCAL: Connect via TCP (IP Address)
    db_host = os.environ.get("MYSQL_HOST", "localhost")
    db_port = os.environ.get("MYSQL_PORT", "3306")

    # SQLAlchemy Connection String Format:
    # mysql+pymysql://user:password@host:port/db_name
    DATABASE_URL = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

# create the SQLAlchemy engine and session
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    Dependency to get DB session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()