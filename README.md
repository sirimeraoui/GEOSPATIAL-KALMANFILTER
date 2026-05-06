<!-- Based on section 9.2 AIS Data Cleaning from the MobilityDataScience book
#and https://github.com/mahmsakr/MobilityDataScienceClass/tree/main/Mobility%20Data%20Cleaning-->

<!-- For DEMO -->
- docker pull --platform=linux/amd64 mobilitydb/mobilitydb  (permission issue? do sudo groupadd docker and sudo usermod -aG docker $USER and newgrp docker)
- docker volume create mobilitydb_data
- docker run --name mobilitydb -e POSTGRES_PASSWORD=mysecretpassword -p 25431:5432 -v mobilitydb_data:/var/lib/postgresql -d mobilitydb/mobilitydb
- alternative (docker start mobilitydb) if you already have the container
- python3 -m venv name
- source name/bin/activate
- pip install -r req.txt if there is one


Add this dataset to the data folder: [aisdk-2026-03-25.zip from this link: http://aisdata.ais.dk/?prefix= ](https://docs.mobilitydb.com/pub/aisdk-2024-03-01.zip)


#### How to run this once your env is setup?
1. first run init.py to clean static attributes and prepare the db (this will take a while)
2. Run app.py for other cleaning including Kalman filtering, this will get the Dash app running , 
3. Added the total uncertainties and kalman gain values to the plot of the vanilla kalman filter (green line)
