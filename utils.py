
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


# dash app

def create_dash_app(df, engine, perform_kalman_filtering):
    app = dash.Dash(__name__)

    # App layout
    app.layout = html.Div([
        html.H1("AIS Data Cleaning Dashboard", style={'text-align': 'center'}),

        dcc.Tabs(id='tabs', value='tab1', children=[
            dcc.Tab(label='Visual Exploration', value='tab1', children=[
                html.Div([
                    dcc.Dropdown(
                        id='mmsi-dropdown-viz',
                        options=[{'label': i, 'value': i}
                                 for i in df['mmsi'].unique()],
                        value=df['mmsi'].unique()[0]
                    ),
                    dcc.Graph(id='viz-plot'),
                    html.Button("Download as PDF", id="download-btn-viz"),
                    dcc.Download(id="download-pdf-viz")
                ])
            ]),

            dcc.Tab(label='Time Series Smoothing', value='tab2', children=[
                html.Div([
                    html.Div([
                        dcc.Dropdown(
                            id='mmsi-dropdown-smooth',
                            options=[{'label': i, 'value': i}
                                     for i in df['mmsi'].unique()],
                            value=df['mmsi'].unique()[0],
                            style={'width': '48%', 'display': 'inline-block'}
                        ),
                        dcc.Dropdown(
                            id='signal-dropdown-smooth',
                            options=[
                                {'label': 'SOG', 'value': 'sog'},
                                {'label': 'COG', 'value': 'cog'},
                                {'label': 'Heading', 'value': 'heading'}
                            ],
                            value='sog',
                            style={'width': '48%', 'float': 'right',
                                   'display': 'inline-block'}
                        ),
                    ]),
                    dcc.Graph(id='smooth-plot'),
                    html.Button("Download as PDF", id="download-btn-smooth"),
                    dcc.Download(id="download-pdf-smooth")
                ])
            ]),

            dcc.Tab(label='Outlier Detection', value='tab3', children=[
                html.Div([
                    html.Div([
                        dcc.Dropdown(
                            id='mmsi-dropdown-outlier',
                            options=[{'label': i, 'value': i}
                                     for i in df['mmsi'].unique()],
                            value=df['mmsi'].unique()[0],
                            style={'width': '48%', 'display': 'inline-block'}
                        ),
                        dcc.Dropdown(
                            id='signal-dropdown-outlier',
                            options=[
                                {'label': 'SOG', 'value': 'sog'},
                                {'label': 'COG', 'value': 'cog'},
                                {'label': 'Heading', 'value': 'heading'}
                            ],
                            value='sog',
                            style={'width': '48%', 'float': 'right',
                                   'display': 'inline-block'}
                        ),
                    ]),
                    dcc.Graph(id='outlier-plot'),
                    html.Button("Download as PDF", id="download-btn-outlier"),
                    dcc.Download(id="download-pdf-outlier")
                ])
            ]),

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

    # Callbacks
    @app.callback(
        Output('viz-plot', 'figure'),
        Input('mmsi-dropdown-viz', 'value')
    )
    def update_viz_plot(selected_mmsi):
        filtered_df = df[df['mmsi'] == selected_mmsi]
        scaled_sog = filtered_df['sog'] * 5
        return {
            'data': [
                go.Scatter(
                    x=filtered_df['timestamp'], y=scaled_sog, mode='lines', name='Scaled SOG (x5)'),
                go.Scatter(
                    x=filtered_df['timestamp'], y=filtered_df['cog'], mode='lines', name='COG'),
                go.Scatter(
                    x=filtered_df['timestamp'], y=filtered_df['heading'], mode='lines', name='Heading')
            ],
            'layout': go.Layout(
                title=f'MMSI {selected_mmsi} - Visual Exploration',
                xaxis_title='Timestamp',
                yaxis_title='Value',
                margin={'l': 80, 'b': 140, 't': 50, 'r': 10},
                font=dict(family="Times New Roman", size=18, color="black"),
                autosize=False,
                width=950,
                height=400,
                hovermode='closest'
            )
        }

    @app.callback(
        Output("download-pdf-viz", "data"),
        Input("download-btn-viz", "n_clicks"),
        State("viz-plot", "figure"),
        prevent_initial_call=True
    )
    def download_pdf_viz(n_clicks, fig):
        pdf_bytes = BytesIO()
        pio.write_image(fig, pdf_bytes, format="pdf",
                        engine="kaleido", width=980, height=410)
        pdf_bytes.seek(0)
        return dcc.send_bytes(pdf_bytes.read(), "viz_plot.pdf")

    @app.callback(
        Output('smooth-plot', 'figure'),
        [Input('mmsi-dropdown-smooth', 'value'),
         Input('signal-dropdown-smooth', 'value')]
    )
    def update_smooth_plot(selected_mmsi, selected_signal):
        filtered_df = df[df['mmsi'] == selected_mmsi]
        mean_col = f'{selected_signal}_mean_smoothed'
        median_col = f'{selected_signal}_median_smoothed'
        return {
            'data': [
                go.Scatter(x=filtered_df['timestamp'], y=filtered_df[selected_signal],
                           mode='lines', name=selected_signal.upper()),
                go.Scatter(x=filtered_df['timestamp'], y=filtered_df[mean_col],
                           mode='lines', name=f'{selected_signal.upper()} Mean Smoothed'),
                go.Scatter(x=filtered_df['timestamp'], y=filtered_df[median_col],
                           mode='lines', name=f'{selected_signal.upper()} Median Smoothed')
            ],
            'layout': go.Layout(
                title=f'MMSI {selected_mmsi} - {selected_signal.upper()} Smoothing',
                xaxis_title='Timestamp',
                yaxis_title=selected_signal.upper(),
                margin={'l': 80, 'b': 140, 't': 50, 'r': 10},
                font=dict(family="Times New Roman", size=18, color="black"),
                autosize=False,
                width=950,
                height=400,
                hovermode='closest'
            )
        }

    @app.callback(
        Output("download-pdf-smooth", "data"),
        Input("download-btn-smooth", "n_clicks"),
        State("smooth-plot", "figure"),
        prevent_initial_call=True
    )
    def download_pdf_smooth(n_clicks, fig):
        pdf_bytes = BytesIO()
        pio.write_image(fig, pdf_bytes, format="pdf",
                        engine="kaleido", width=980, height=410)
        pdf_bytes.seek(0)
        return dcc.send_bytes(pdf_bytes.read(), "smooth_plot.pdf")

    @app.callback(
        Output('outlier-plot', 'figure'),
        [Input('mmsi-dropdown-outlier', 'value'),
         Input('signal-dropdown-outlier', 'value')]
    )
    def update_outlier_plot(selected_mmsi, selected_signal):
        filtered_df = df[df['mmsi'] == selected_mmsi]
        outlier_col = f'{selected_signal}_outliers'
        return {
            'data': [
                go.Scatter(x=filtered_df['timestamp'], y=filtered_df[selected_signal],
                           mode='lines', name=selected_signal.upper()),
                go.Scatter(
                    x=filtered_df.loc[filtered_df[outlier_col], 'timestamp'],
                    y=filtered_df.loc[filtered_df[outlier_col],
                                      selected_signal],
                    mode='markers',
                    name=f'{selected_signal.upper()} Outliers',
                    marker=dict(color='red', size=8, symbol='circle')
                )
            ],
            'layout': go.Layout(
                title=f'MMSI {selected_mmsi} - {selected_signal.upper()} Outlier Detection',
                xaxis_title='Timestamp',
                yaxis_title=selected_signal.upper(),
                margin={'l': 80, 'b': 140, 't': 50, 'r': 10},
                font=dict(family="Times New Roman", size=18, color="black"),
                autosize=False,
                width=950,
                height=400,
                hovermode='closest'
            )
        }

    @app.callback(
        Output("download-pdf-outlier", "data"),
        Input("download-btn-outlier", "n_clicks"),
        State("outlier-plot", "figure"),
        prevent_initial_call=True
    )
    def download_pdf_outlier(n_clicks, fig):
        pdf_bytes = BytesIO()
        pio.write_image(fig, pdf_bytes, format="pdf",
                        engine="kaleido", width=980, height=410)
        pdf_bytes.seek(0)
        return dcc.send_bytes(pdf_bytes.read(), "outlier_plot.pdf")

    @app.callback(
        Output('traj-plot', 'figure'),
        Input('mmsi-dropdown-traj', 'value')
    )
    def update_graph(selected_mmsi):
        if selected_mmsi is not None:
            # Fetch trajectory data
            query = f"SELECT geomproj, t AS timestamp FROM AISInputSample WHERE mmsi = {selected_mmsi} ORDER BY t;"
            gdf = gpd.read_postgis(query, engine, geom_col='geomproj')

            # Call the Kalman filtering function
            smoothed_coords = perform_kalman_filtering(gdf)

            # Prepare data for plotting
            original_x = gdf.geometry.x
            original_y = gdf.geometry.y
            smoothed_x = [coord[0] for coord in smoothed_coords]
            smoothed_y = [coord[1] for coord in smoothed_coords]

            # Plotting the trajectories
            fig = go.Figure()
            fig.add_trace(go.Scattergl(x=original_x, y=original_y, mode='lines', name='Original Path'))
            fig.add_trace(go.Scattergl(x=smoothed_x, y=smoothed_y, mode='lines', name='Smoothed Path'))
            fig.update_layout(xaxis_title='x-coordinate', yaxis_title='y-coordinate', 
                            xaxis=dict(
                                tickmode='auto',
                                tickformat=',',  # This will ensure that numbers are separated by commas but not in scientific notation
                            ),
                            yaxis=dict(
                                tickmode='auto',
                                tickformat=','
                            ),
                            margin={'l': 80, 'b': 140, 't': 50, 'r': 10},
                            font=dict(
                                family="Times New Roman",
                                size=18,
                                color= "black"
                            ),
                            autosize=False,
                            width=1000,
                            height=400,
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
