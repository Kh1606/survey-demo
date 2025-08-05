from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# SQLite URL: file 'test.db' in this folder
db_url = "sqlite:///./test.db"
engine = create_engine(db_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)