# Based on section 9.2 AIS Data Cleaning from the MobilityDataScience book
# and https://github.com/mahmsakr/MobilityDataScienceClass/tree/main/Mobility%20Data%20Cleaning
from sqlalchemy import create_engine, text
import json
import zipfile
import os

from utils import get_csv_from_zip
# Load database configuration from config.json
with open("config.json", "r") as file:
    config = json.load(file)

# Construct the database URL for SQLAlchemy
database_url = (
    f"postgresql://{config['DB_USER']}:{config['DB_PASS']}@"
    f"{config['DB_HOST']}:{config['DB_PORT']}/{config['DB_NAME']}"
)

# Create the SQLAlchemy engine
engine = create_engine(database_url)
data_csv_path = get_csv_from_zip("data/aisdk-2026-03-25.zip")
data_csv_path=os.path.abspath(data_csv_path)
print(data_csv_path)
#update this based on whether you're running your db from docker or local/ this is a docker version, otherwise comment it out
container_csv_path = "/tmp/aisdk.csv"
container_name = "mobilitydb"  # Your container name
docker_cmd = f"docker cp {data_csv_path} {container_name}:{container_csv_path}"
os.system(docker_cmd)
data_csv_path = container_csv_path
print(data_csv_path)
# Data collection and 9.3 Cleaning Static Attribute +9.4 Voyage related Attribbutes:
try:
    # Read the SQL file CleaningStaticAttributes.sql
    with open("CleaningStaticAttributes.sql", "r") as sql_file:
        sql_query = sql_file.read()

    # Create a text object with parameters
    stmt = text(sql_query).bindparams(data_csv_path=data_csv_path)

    # Execute with parameter
    with engine.connect() as conn:
        # Start a transaction
        with conn.begin():
            # Execute the COPY command with parameter
            conn.execute(stmt)
            print(f"Successfully loaded data from {data_csv_path}")

except Exception as e:
    print(f"Error loading data: {e}")
    raise
