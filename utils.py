
from sqlalchemy import create_engine
import numpy as np
import pandas as pd
import geopandas as gpd
import plotly.io as pio
from io import BytesIO
import plotly.graph_objects as go
from dash import dcc, html, Input, Output, State
import dash
import os
import zipfile


# dash app
def create_dash_app(df, engine, perform_kalman_filtering, perform_vanilla_kalman_filtering, mean_filtering,median_filtering):
    app = dash.Dash(__name__)
    # App layout
    app.layout = html.Div([
        html.H1("AIS Data Cleaning Dashboard", style={'text-align': 'center'}),

        dcc.Tabs(id='tabs', value='tab1', children=[
            dcc.Tab(label='Trajectory Smoothing (Kalman)', value='tab4', children=[
                html.Div([
                    dcc.Dropdown(
                        id='mmsi-dropdown-traj',
                        options=[{'label': i, 'value': i}
                                 for i in df['mmsi'].unique()],
                        value=df['mmsi'].unique()[0]
                    ),
                    dcc.Graph(id='traj-plot'),
                    html.Button("Download as PDF", id="download-btn-traj"),
                    dcc.Download(id="download-pdf-traj")
                ])
            ])
        ])
    ])

    @app.callback(
        Output('traj-plot', 'figure'),
        Input('mmsi-dropdown-traj', 'value')
    )
    def update_graph(selected_mmsi):
        if selected_mmsi is not None:
            # Fetch trajectory data with ShipType and CargoType
            query = f"""
                SELECT geomproj, t AS timestamp, sog, cog, 
                    ShipType, CargoType, NavigationalStatus
                FROM AISInputSample 
                WHERE mmsi = {selected_mmsi} 
                ORDER BY t 
                LIMIT 20;
            """ 
            gdf = gpd.read_postgis(query, engine, geom_col='geomproj')

            if len(gdf) == 0:
                return go.Figure()

            # Call the Kalman filtering function
            smoothed_coords = perform_kalman_filtering(gdf)
            smoothed_coords_vanilla = perform_vanilla_kalman_filtering(gdf)
            mean_smoothed_coords = mean_filtering(gdf)
            median_smoothed_coords = median_filtering(gdf)
            # Prepare data for plotting
            original_x = gdf.geometry.x
            original_y = gdf.geometry.y
            timestamps = gdf['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
            sog_values = gdf['sog']
            shiptypes = gdf['shiptype'].fillna('Unknown')
            cargotypes = gdf['cargotype'].fillna('Unknown')
            nav_status = gdf['navigationalstatus'].fillna('Unknown')

            # Create hover text with ShipType and CargoType
            hover_text = [
                f"Time: {t}<br>"
                f"X: {x:.0f}<br>"
                f"Y: {y:.0f}<br>"
                f"SOG: {f'{sog:.1f}' if sog is not None else 'N/A'} knots<br>" 
                f"Status: {status}<br>"
                f"Ship Type: {ship}<br>"
                f"Cargo Type: {cargo}"
                for t, x, y, sog, status, ship, cargo in zip(
                    timestamps, original_x, original_y, 
                    sog_values, nav_status, shiptypes, cargotypes
                )
            ]

            smoothed_x = [coord[0] for coord in smoothed_coords] if len(smoothed_coords) > 0 else []
            smoothed_y = [coord[1] for coord in smoothed_coords] if len(smoothed_coords) > 0 else []
            smoothed_x_vanilla = [coord[0] for coord in smoothed_coords_vanilla] if len(smoothed_coords_vanilla) > 0 else []
            smoothed_y_vanilla = [coord[1] for coord in smoothed_coords_vanilla] if len(smoothed_coords_vanilla) > 0 else []
            mean_smoothed_x = [coord[0] for coord in mean_smoothed_coords] if len(mean_smoothed_coords) > 0 else []
            mean_smoothed_y = [coord[1] for coord in mean_smoothed_coords] if len(mean_smoothed_coords) > 0 else []
            median_smoothed_x = [coord[0] for coord in median_smoothed_coords] if len(median_smoothed_coords) > 0 else []
            median_smoothed_y = [coord[1] for coord in median_smoothed_coords] if len(median_smoothed_coords) > 0 else []

            # Plotting the trajectories
            fig = go.Figure()
            
            # Original path with hover info
            fig.add_trace(go.Scattergl(
                x=original_x, 
                y=original_y, 
                mode='lines+markers',
                name='Original Path',
                text=hover_text,
                hovertemplate='<b>Original Point</b><br>%{text}<extra></extra>',
                marker=dict(size=6, color='blue'),
                line=dict(width=1, color='blue')
            ))
            
            # Smoothed path
            if len(smoothed_x_vanilla) > 0:
                fig.add_trace(go.Scattergl(
                    x=smoothed_x_vanilla, 
                    y=smoothed_y_vanilla, 
                    mode='lines',
                    name='Smoothed Path Vanilla',
                    line=dict(width=2, color='green', dash='dash')
                ))
            
            if len(smoothed_x) > 0:
                fig.add_trace(go.Scattergl(
                    x=smoothed_x, 
                    y=smoothed_y, 
                    mode='lines',
                    name='Smoothed Path',
                    line=dict(width=2, color='red', dash='dash')
                ))
            if len(mean_smoothed_x) > 0:
                fig.add_trace(go.Scattergl(
                    x=mean_smoothed_x, 
                    y=mean_smoothed_y, 
                    mode='lines',
                    name='Mean Smoothed Path',
                    line=dict(width=2, color='orange', dash='dash'),
                    visible='legendonly'

                ))
            if len(median_smoothed_x) > 0:
                fig.add_trace(go.Scattergl(
                    x=median_smoothed_x, 
                    y=median_smoothed_y, 
                    mode='lines',
                    name='Median Smoothed Path',
                    line=dict(width=2, color='purple', dash='dash'),
                    visible='legendonly'
                ))
            
            # Get ship info for title
            ship_type = shiptypes.iloc[0] if len(shiptypes) > 0 else "Unknown"
            cargo_type = cargotypes.iloc[0] if len(cargotypes) > 0 else "Unknown"
            
            fig.update_layout(
                title=f"MMSI {selected_mmsi} | Ship: {ship_type} | Cargo: {cargo_type}",
                xaxis_title='x-coordinate (meters)',
                yaxis_title='y-coordinate (meters)', 
                xaxis=dict(
                    tickmode='auto',
                    tickformat=',',
                ),
                yaxis=dict(
                    tickmode='auto',
                    tickformat=','
                ),
                margin={'l': 80, 'b': 140, 't': 80, 'r': 10},
                font=dict(
                    family="Times New Roman",
                    size=18,
                    color="black"
                ),
                autosize=False,
                width=1000,
                height=500,
                hovermode='closest'
            )
            return fig

        return go.Figure()

    @app.callback(
        Output("download-pdf-traj", "data"),
        Input("download-btn-traj", "n_clicks"),
        State("traj-plot", "figure"),
        prevent_initial_call=True
    )
    def download_pdf_traj(n_clicks, fig):
        pdf_bytes = BytesIO()
        pio.write_image(fig, pdf_bytes, format="pdf",
                        engine="kaleido", width=1030, height=530)
        pdf_bytes.seek(0)
        return dcc.send_bytes(pdf_bytes.read(), "trajectory_plot.pdf")

    return app
# AIS DEMO
def get_csv_from_zip(zip_path, extract_path="data"):
    # Ensure data filder exists
    os.makedirs(extract_path, exist_ok=True)
    csv_files = [f for f in os.listdir(extract_path) if f.endswith(".csv")]
    if csv_files:
        return os.path.join(extract_path, csv_files[0])
# unzio
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_path)
    csv_files = [f for f in os.listdir(extract_path) if f.endswith(".csv")]
    if not csv_files:
        raise Exception(
            "No CSV found in ZIP! Try downloading a different AIS dataset.")
    return os.path.join(extract_path, csv_files[0])


