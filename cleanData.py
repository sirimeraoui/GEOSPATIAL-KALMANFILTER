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


#  Kalman filtering code
# def perform_kalman_filtering(gdf):
#     timestamps = gdf['timestamp'].values
#     dt = (timestamps[1:] - timestamps[:-1]).astype('float64') / 1e9 
#     # Define measurement and transition models
#     measurement_noise_std = [10.0, 10.0]
#     measurement_model = LinearGaussian(
#         ndim_state=4,  # position and velocity in 2D
#         mapping=(0, 2),
#         noise_covar=np.diag([measurement_noise_std[0]**2, measurement_noise_std[1]**2])
#     )

#     process_noise_std = [1, 1]  # Modify based on application needs
#     transition_model = CombinedLinearGaussianTransitionModel([
#         ConstantVelocity(process_noise_std[0]**2),
#         ConstantVelocity(process_noise_std[1]**2)
#     ])

#     # Create detections
#     detections = [
#         Detection(np.array([row.geomproj.x, row.geomproj.y]), timestamp=row.timestamp, measurement_model=measurement_model)
#         for _, row in gdf.iterrows()
#     ]
    
#     # Extract initial state
#     initial_state_mean = [gdf.geomproj.iloc[0].x, 0, gdf.geomproj.iloc[0].y, 0]  # [x, x_velocity, y, y_velocity]
#     initial_state_covariance = np.diag([measurement_noise_std[0]**2, 
#                                         process_noise_std[1]**2, 
#                                         measurement_noise_std[0]**2, 
#                                         process_noise_std[1]**2])
#     initial_state = GaussianState(initial_state_mean, initial_state_covariance, timestamp=detections[0].timestamp)


#     # Kalman filter execution
#     predictor = KalmanPredictor(transition_model)
#     updater = KalmanUpdater(measurement_model)
    

#     # List to store filtered states
#     filtered_states = []

#     # Filtering process
#     for i, detection in enumerate(detections):
#         if i == 0:
#             # For the first measurement, there is no prediction step
#             predicted_state = initial_state
#         else:

#             # Predict the next state using the prior state
#             predicted_state = predictor.predict(filtered_states[-1], timestamp=detection.timestamp)

#         # Create a hypothesis associating the predicted state with the detection
#         hypothesis = SingleHypothesis(predicted_state, detection)
#         # print(hypothesis)
# #++
#         # Update the state with the hypothesis
#         updated_state = updater.update(hypothesis)

#         # Store the filtered state
#         filtered_states.append(updated_state)

#     # Extract the smoothed coordinates
#     smoothed_coords = np.array([[state.state_vector[0, 0], state.state_vector[2, 0]] for state in filtered_states])
#     return smoothed_coords




from pykalman import KalmanFilter
import numpy as np

def perform_kalman_filtering(gdf):
    # Extract x,y coordinates
    coords = np.array([[geom.x, geom.y] for geom in gdf['geomproj']])
    
    # Get time differences for velocity model
    timestamps = gdf['timestamp'].values
    dt = np.median((timestamps[1:] - timestamps[:-1]).astype('float64') / 1e9)
    
    # State: [x, vx, y, vy]
    # Transition matrix: constant velocity model
    transition_matrix = np.array([
        [1, dt, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, dt],
        [0, 0, 0, 1]
    ])
    
    # Observation matrix: we only see x and y
    observation_matrix = np.array([
        [1, 0, 0, 0],
        [0, 0, 1, 0]
    ])
    
    # Process noise (how much the model can deviate)
    process_noise = 1.0
    transition_covariance = np.diag([process_noise**2, 0.1**2, process_noise**2, 0.1**2])
    
    # Measurement noise (how much we trust observations)
    measurement_noise = 10.0
    observation_covariance = np.diag([measurement_noise**2, measurement_noise**2])
    
    # Initial state
    initial_state_mean = [coords[0, 0], 0, coords[0, 1], 0]
    initial_state_covariance = np.diag([measurement_noise**2, 100, measurement_noise**2, 100])
    
    # Create and apply Kalman filter
    kf = KalmanFilter(
        transition_matrices=transition_matrix,
        observation_matrices=observation_matrix,
        transition_covariance=transition_covariance,
        observation_covariance=observation_covariance,
        initial_state_mean=initial_state_mean,
        initial_state_covariance=initial_state_covariance
    )
    
    # Apply smoother (RTS smoother)
    smoothed_means, _ = kf.smooth(coords)
    
    # Return only x,y coordinates
    return smoothed_means[:, [0, 2]]

# Create Dash app for all data cleaning steps in different tabs each
app = create_dash_app(df, engine, perform_kalman_filtering)
# Launch dash visualization
if __name__ == '__main__':
    app.run(debug=True)
