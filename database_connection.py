import os
from sqlalchemy import create_engine, URL
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Define constants for connection details
db_user = os.environ.get("MYSQL_USER", "root")
db_pass = os.environ.get("MYSQL_PASSWORD", "your_password")
db_name = os.environ.get("MYSQL_DB", "bookings_db")
db_host = os.environ.get("MYSQL_HOST", "localhost")
db_port = int(os.environ.get("MYSQL_PORT", 3306))
connection_name = os.environ.get("INSTANCE_CONNECTION_NAME")

# DETECT WINDOWS (Force TCP)
if os.name == 'nt':
    print("--- DETECTED WINDOWS: Ignoring Unix Socket configuration ---")
    connection_name = None

# BUILD THE URL OBJECT SAFELY
# This method automatically handles special characters like '@' in passwords
if connection_name:
    # Cloud Run (Unix Socket)
    connection_url = URL.create(
        drivername="mysql+pymysql",
        username=db_user,
        password=db_pass,
        database=db_name,
        query={"unix_socket": f"/cloudsql/{connection_name}"}
    )
    
else:
    # Local (TCP)
    connection_url = URL.create(
        drivername="mysql+pymysql",
        username=db_user,
        password=db_pass,
        host=db_host,
        port=db_port,
        database=db_name
    )
    print(db_pass)

# CREATE ENGINE
engine = create_engine(connection_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

if __name__ == "__main__":
    try:
        print(f"--- ATTEMPTING CONNECTION TO: {db_host} ---")
        with engine.connect() as connection:
            print(f"--- SUCCESS: Connected to database '{db_name}' ---")
    except Exception as e:
        print(f"--- FAILURE: Could not connect ---")
        print(f"Error: {e}")
