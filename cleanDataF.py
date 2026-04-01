# Based on section 9.2 AIS Data Cleaning from the MobilityDataScience book
# and https://github.com/mahmsakr/MobilityDataScienceClass/tree/main/Mobility%20Data%20Cleaning
from utils import create_dash_app
import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objects as go
from io import BytesIO
import plotly.io as pio
import geopandas as gpd
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from stonesoup.models.transition.linear import CombinedLinearGaussianTransitionModel, ConstantVelocity
from stonesoup.models.measurement.linear import LinearGaussian
from stonesoup.predictor.kalman import KalmanPredictor
from stonesoup.updater.kalman import KalmanUpdater
from stonesoup.types.state import GaussianState
from stonesoup.types.detection import Detection
from stonesoup.types.array import CovarianceMatrix
from stonesoup.types.hypothesis import SingleHypothesis
import json
import warnings
warnings.filterwarnings('ignore')

# Load database configuration
with open("config.json", "r") as file:
    config = json.load(file)

database_url = (
    f"postgresql://{config['DB_USER']}:{config['DB_PASS']}@"
    f"{config['DB_HOST']}:{config['DB_PORT']}/{config['DB_NAME']}"
)
engine = create_engine(database_url)

# Fetch data for 10 random MMSIs
query = """
    SELECT MMSI, T AS Timestamp, SOG, COG, Heading
    FROM AISInputSample
    WHERE MMSI IN (
        SELECT MMSI
        FROM (SELECT DISTINCT MMSI FROM AISInputSample) AS UniqueMMSIs
        ORDER BY RANDOM() LIMIT 20
    )
    ORDER BY MMSI, t;
"""
df = pd.read_sql_query(query, engine)
df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y-%m-%d %H:%M:%S')

# Apply median mean smoothing
window_size = 10
df['sog_mean_smoothed'] = df['sog'].rolling(
    window=window_size, center=True).mean()
df['sog_median_smoothed'] = df['sog'].rolling(
    window=window_size, center=True).median()
df['cog_mean_smoothed'] = df['cog'].rolling(
    window=window_size, center=True).mean()
df['cog_median_smoothed'] = df['cog'].rolling(
    window=window_size, center=True).median()
df['heading_mean_smoothed'] = df['heading'].rolling(
    window=window_size, center=True).mean()
df['heading_median_smoothed'] = df['heading'].rolling(
    window=window_size, center=True).median()

# Outlier detection function


def detect_outliers(data, column):
    Q1 = data[column].quantile(0.25)
    Q3 = data[column].quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    return (data[column] < lower_bound) | (data[column] > upper_bound)
df['sog_outliers'] = detect_outliers(df, 'sog')
df['cog_outliers'] = detect_outliers(df, 'cog')
df['heading_outliers'] = detect_outliers(df, 'heading')


# Kalman filter function for trajectory
def perform_kalman_filtering(gdf):
    measurements = []
    for _, row in gdf.iterrows():
            
        sog_val = row.get('sog', 0)
        cog_val = row.get('cog', 0)
        
        # Handle None/NaN
        if sog_val is None or pd.isna(sog_val):
            sog_val = 0
        if cog_val is None or pd.isna(cog_val):
            cog_val = 0

        measurements.append({
            'x': row.geomproj.x,
            'y': row.geomproj.y,
            'sog': sog_val * 0.514444,  # knots to m/s
            'cog': np.radians(cog_val), # degrees to radians
            't': row.timestamp
        })
    
    # Sort by timestamp (critical!)
    measurements.sort(key=lambda m: m['t'])
    
    # ============================================================================
    # 2. Initialize with first measurement
    # ============================================================================
    m0 = measurements[0]
    x = np.array([
        m0['x'],
        m0['sog'] * np.sin(m0['cog']),  # vx from same measurement
        m0['y'],
        m0['sog'] * np.cos(m0['cog'])   # vy from same measurement
    ]).reshape(4, 1)
    
    P = np.eye(4) * 100
    Q = np.diag([1, 5, 1, 5])      # process noise
    R = np.eye(2) * 100             # measurement noise
    
    H = np.array([
        [1, 0, 0, 0],
        [0, 0, 1, 0]
    ])
    
    # ============================================================================
    # 3. Filter loop
    # ============================================================================
    filtered = []
    
    for i, m in enumerate(measurements):
        z = np.array([m['x'], m['y']]).reshape(2, 1)
        
        if i == 0:
            x_filt = x.copy()
        else:
            # Time since last measurement
            dt = (m['t'] - measurements[i-1]['t']).total_seconds()
            
            # State transition
            F = np.array([
                [1, dt, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, dt],
                [0, 0, 0, 1]
            ])
            
            # Predict
            x_pred = F @ x
            P_pred = F @ P @ F.T + Q
            
            # Update
            y = z - H @ x_pred
            S = H @ P_pred @ H.T + R
            K = P_pred @ H.T @ np.linalg.inv(S)
            
            x_filt = x_pred + K @ y
            P = (np.eye(4) - K @ H) @ P_pred
        
        filtered.append(x_filt.copy())
        x = x_filt
    
    # Return smoothed positions
    return np.array([[s[0,0], s[2,0]] for s in filtered])

# Create Dash app for all data cleaning steps in different tabs each
app = create_dash_app(df, engine, perform_kalman_filtering)
# Launch dash visualization
if __name__ == '__main__':
    app.run(debug=True)
