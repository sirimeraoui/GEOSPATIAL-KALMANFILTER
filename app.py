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
    WHERE MMSI IN (219031428, 265588470,219008145,219026706, 219016557, 219024000,219019011)
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
# Kalman formula based
def perform_vanilla_kalman_filtering(gdf):
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
    #uncertainy initial
    P = np.eye(4) * 100 #variance initial state
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
    uncertainties = []
    kalman_gains = []
    for i, m in enumerate(measurements):
        z = np.array([m['x'], m['y']]).reshape(2, 1)
        
        if i == 0:
            x_filt = x.copy()
        else:
            # Time since last measurement
            dt = (m['t'] - measurements[i-1]['t']).total_seconds()
            
            # State transition matrx
            F = np.array([
                [1, dt, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, dt],
                [0, 0, 0, 1]
            ])
            # xt+1 ​= xt​+vx​⋅dt
            # vx​t+1 ​= vx​t
            # yt+1 ​= yt​+vy​⋅dt
            # vy​t+1 ​= vy​t
            # Predicticted state 
            x_pred = F @ x
            #Prediction covariance
            P_pred = F @ P @ F.T + Q 
            
            # Update
            #equivalent to hypothesis
            #diff actual vs pred - residual distance
            y = z - H @ x_pred
            #Total uncertainty in the measurement
            S = H @ P_pred @ H.T + R
            #kalman gain K = uncertainty in prediction / total uncertainty is small K confident
            K = P_pred @ H.T @ np.linalg.inv(S)
            kalman_gains.append(K.copy())

            x_filt = x_pred + K @ y
            #uncerteinty 
            P = (np.eye(4) - K @ H) @ P_pred
        
        filtered.append(x_filt.copy())
        x = x_filt
        uncertainties.append(P.copy())
    # Return smoothed positions
    return np.array([[s[0,0], s[2,0]] for s in filtered]), np.array(uncertainties), np.array(kalman_gains)


#  Kalman filtering code
def perform_kalman_filtering(gdf):
    timestamps = gdf['timestamp'].values
    dt = (timestamps[1:] - timestamps[:-1]).astype('float64') / 1e9 
    # Define measurement and transition models
    measurement_noise_std = [10.0, 10.0]
    measurement_model = LinearGaussian(
        ndim_state=4,  # position and velocity in 2D
        mapping=(0, 2),
        noise_covar=np.diag([measurement_noise_std[0]**2, measurement_noise_std[1]**2])
    )

    process_noise_std = [1, 5]  # Modify based on application needs
    transition_model = CombinedLinearGaussianTransitionModel([
        ConstantVelocity(process_noise_std[0]**2),
        ConstantVelocity(process_noise_std[1]**2)
    ])

    # Create detections
    detections = [
        Detection(np.array([row.geomproj.x, row.geomproj.y]), timestamp=row.timestamp, measurement_model=measurement_model)
        for _, row in gdf.iterrows()
    ]
    
    # Extract initial state
    initial_state_mean = [gdf.geomproj.iloc[0].x, 0, gdf.geomproj.iloc[0].y, 0]  # [x, x_velocity, y, y_velocity]
    initial_state_covariance = np.diag([measurement_noise_std[0]**2, 
                                        process_noise_std[1]**2, 
                                        measurement_noise_std[0]**2, 
                                        process_noise_std[1]**2])
    #x:
    initial_state = GaussianState(initial_state_mean, initial_state_covariance, timestamp=detections[0].timestamp)


    # Kalman filter execution
    predictor = KalmanPredictor(transition_model)
    updater = KalmanUpdater(measurement_model)
    

    # List to store filtered states
    filtered_states = []

    # Filtering process
    for i, detection in enumerate(detections):
        if i == 0:
            # For the first measurement, there is no prediction step
            predicted_state = initial_state
        else:

            # Predict the next state using the prior state
            predicted_state = predictor.predict(filtered_states[-1], timestamp=detection.timestamp)

        # Create a hypothesis associating the predicted state with the detection
        hypothesis = SingleHypothesis(predicted_state, detection)
        # print(hypothesis)
#++
        # Update the state with the hypothesis
        updated_state = updater.update(hypothesis)

        # Store the filtered state
        filtered_states.append(updated_state)

    # Extract the smoothed coordinates
    smoothed_coords = np.array([[state.state_vector[0, 0], state.state_vector[2, 0]] for state in filtered_states])
    return smoothed_coords
# [1,3,5,7,9]
def mean_filtering(gdf):
    gdf['x_mean'] = gdf['geomproj'].apply(lambda geom: geom.x).rolling(window=3).mean()
    gdf['y_mean'] = gdf['geomproj'].apply(lambda geom: geom.y).rolling(window=3).mean()
    return gdf[['x_mean', 'y_mean']].values
def median_filtering(gdf):
    gdf['x_median'] = gdf['geomproj'].apply(lambda geom: geom.x).rolling(window=3).median()
    gdf['y_median'] = gdf['geomproj'].apply(lambda geom: geom.y).rolling(window=3).median()
    return gdf[['x_median', 'y_median']].values
    
# Create Dash app for all data cleaning steps in different tabs each
app = create_dash_app(df, engine, perform_kalman_filtering, perform_vanilla_kalman_filtering, mean_filtering, median_filtering)
# Launch dash visualization
if __name__ == '__main__':
    app.run(debug=True)
