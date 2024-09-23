import os
import hashlib
import json
from datetime import datetime
import pandas as pd
import math

# Dash and Plotly imports
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
import dash_cytoscape as cyto  # For interactive graph visualization

# Install dash-cytoscape and diskcache if not already installed:
# pip install dash-cytoscape
# pip install diskcache

from dash.long_callback import DiskcacheLongCallbackManager
import diskcache

# Load extra layouts for cytoscape
cyto.load_extra_layouts()

# Initialize diskcache for background callbacks
cache = diskcache.Cache("./cache")
long_callback_manager = DiskcacheLongCallbackManager(cache)


# ------------------------------
# Part 1: File Scanner
# ------------------------------

def get_file_tree(root_dir):
    tree = {
        'name': os.path.basename(root_dir) if os.path.basename(root_dir) else root_dir,
        'path': root_dir,
        'children': [],
        'type': 'directory'
    }

    file_hashes = {}
    duplicate_files = []

    def add_nodes(node):
        try:
            print(f"Scanning: {node['path']}")
            entries = os.scandir(node['path'])
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    dir_node = {
                        'name': entry.name,
                        'path': entry.path,
                        'children': [],
                        'type': 'directory'
                    }
                    add_nodes(dir_node)
                    node['children'].append(dir_node)
                elif entry.is_file(follow_symlinks=False):
                    file_info = get_file_info(entry.path)
                    if file_info:
                        print(f"File scanned: {file_info['name']}")
                        # Check for duplicates
                        file_hash = file_info['hash']
                        if file_hash:
                            if file_hash in file_hashes:
                                file_info['is_duplicate'] = True
                                # Mark the original file as duplicate as well
                                original_file = file_hashes[file_hash]
                                original_file['is_duplicate'] = True
                                duplicate_files.append((file_info, original_file))
                            else:
                                file_hashes[file_hash] = file_info
                        node['children'].append(file_info)
        except PermissionError:
            print(f"Permission denied: {node['path']}")
        except Exception as e:
            print(f"Error accessing {node['path']}: {e}")

    add_nodes(tree)
    return tree


def get_file_info(filepath):
    try:
        stat_info = os.stat(filepath)
        last_modified = datetime.fromtimestamp(stat_info.st_mtime)
        size = stat_info.st_size
        file_info = {
            'name': os.path.basename(filepath),
            'path': filepath,
            'size': size,
            'creation_date': datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
            'last_modified': last_modified.isoformat(),
            'extension': os.path.splitext(filepath)[1].lower(),
            'hash': get_file_hash(filepath),
            'type': 'file',
            # Analysis flags
            'is_duplicate': False,
            'is_old': (datetime.now() - last_modified).days > 5 * 365,  # Older than 5 years
            'is_large': size > 100 * 1024 * 1024  # Larger than 100 MB
        }
        return file_info
    except PermissionError:
        print(f"Permission denied: {filepath}")
        return None
    except Exception as e:
        print(f"Error accessing {filepath}: {e}")
        return None


def get_file_hash(filepath):
    hash_md5 = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except PermissionError:
        print(f"Permission denied: {filepath}")
        return None
    except Exception as e:
        print(f"Error hashing {filepath}: {e}")
        return None


# ------------------------------
# Part 2: Build Dash Application
# ------------------------------

# Function to convert the file tree into a format suitable for Dash Cytoscape
def build_elements(node, parent_id=None, elements=None, node_id=0):
    if elements is None:
        elements = []
    current_id = node_id
    node['id'] = str(current_id)
    color = '#58a6ff'  # Default color for directories

    if node['type'] == 'file':
        # Set color based on analysis flags
        if node.get('is_duplicate'):
            color = 'red'
        elif node.get('is_old'):
            color = 'orange'
        elif node.get('is_large'):
            color = 'purple'
        else:
            color = 'green'
    else:
        color = '#58a6ff'  # Directory color

    # Add the node
    elements.append({
        'data': {
            'id': node['id'],
            'label': node['name'],
            'type': node['type'],
            'size': node.get('size', ''),
            'path': node.get('path', ''),
            'last_modified': node.get('last_modified', ''),
            'is_duplicate': node.get('is_duplicate', False),
            'is_old': node.get('is_old', False),
            'is_large': node.get('is_large', False),
            'background_color': color  # Pass the color to use in styling
        },
        'classes': node['type'],
    })

    # Add the edge from parent to current node
    if parent_id is not None:
        elements.append({'data': {'source': parent_id, 'target': node['id']}})

    # Recursively add children
    child_id = current_id + 1
    if 'children' in node:
        for child in node['children']:
            elements, child_id = build_elements(child, node['id'], elements, child_id)
    return elements, child_id


# Initialize Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], long_callback_manager=long_callback_manager)

# Layout of the app
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("File System Visualization with Analysis"), width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.Div("Enter the root directory to scan:"),
            dcc.Input(id='directory-input', type='text', value='', style={'width': '100%'}),
            html.Button('Scan Directory', id='scan-button', n_clicks=0, style={'margin-top': '10px'}),
            html.Div(id='loading-text', children="")
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            dcc.Loading(
                id="loading-cytoscape",
                type="default",
                children=[
                    cyto.Cytoscape(
                        id='cytoscape',
                        layout={'name': 'dagre'},  # You can change the layout
                        style={'width': '100%', 'height': '600px'},
                        elements=[],
                        stylesheet=[
                            {
                                'selector': 'node',
                                'style': {
                                    'label': 'data(label)',
                                    'text-wrap': 'wrap',
                                    'text-max-width': 80,
                                    'font-size': '12px',
                                    'background-color': 'data(background_color)'
                                }
                            },
                            {
                                'selector': '.file',
                                'style': {
                                    'shape': 'rectangle'
                                }
                            },
                            {
                                'selector': '.directory',
                                'style': {
                                    'shape': 'ellipse'
                                }
                            },
                            {
                                'selector': 'edge',
                                'style': {
                                    'curve-style': 'bezier',
                                    'target-arrow-shape': 'vee'
                                }
                            }
                        ]
                    )
                ]
            )
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.Div(id='node-data')
        ], width=12)
    ])
])


# Callback to start scanning and update the graph using Dash Long Callback
@app.long_callback(
    output=[Output('loading-text', 'children'),
             Output('cytoscape', 'elements')],
    inputs=[Input('scan-button', 'n_clicks')],
    state=[State('directory-input', 'value')],
    running=[
        (Output('scan-button', 'disabled'), True, False),
        (Output('directory-input', 'disabled'), True, False),
        (Output('loading-text', 'children'), 'Scanning in progress...', '')
    ],
    # Removed 'progress' and 'cancel' parameters as they're not used
    # Removed 'background=True' as it's not needed and causes the error
)
def start_scan(n_clicks, directory):
    if n_clicks > 0 and directory:
        if not os.path.exists(directory):
            return "Directory does not exist.", []
        else:
            # Perform the scanning
            file_tree = get_file_tree(directory)
            elements, _ = build_elements(file_tree)
            return "Scanning complete.", elements
    else:
        return "", []


# Callback to display node data when a node is selected
@app.callback(
    Output('node-data', 'children'),
    Input('cytoscape', 'tapNodeData')
)
def display_node_data(data):
    if data:
        info = [
            html.H5(f"Name: {data.get('label')}"),
            html.P(f"Type: {data.get('type')}"),
            html.P(f"Path: {data.get('path')}"),
            html.P(f"Size: {format_size(data.get('size'))}" if data.get('size') else ''),
            html.P(f"Last Modified: {data.get('last_modified')}" if data.get('last_modified') else ''),
            html.P(f"Is Duplicate: {data.get('is_duplicate')}"),
            html.P(f"Is Old: {data.get('is_old')}"),
            html.P(f"Is Large: {data.get('is_large')}")
        ]
        return info
    else:
        return "Click on a node to see details."


def format_size(size_in_bytes):
    if size_in_bytes == '' or size_in_bytes is None:
        return ''
    size_in_bytes = int(size_in_bytes)
    if size_in_bytes == 0:
        return '0 B'
    size_name = ('B', 'KB', 'MB', 'GB', 'TB')
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_in_bytes / p, 2)
    return f"{s} {size_name[i]}"


# ------------------------------
# Run the Dash App
# ------------------------------
if __name__ == '__main__':
    app.run_server(debug=True)
