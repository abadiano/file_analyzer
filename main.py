# General imports
import os
import hashlib
from datetime import datetime
import math
import time

# Dash and Plotly imports
import dash
from dash import html, dcc, callback_context
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State, ALL, MATCH
from dash.exceptions import PreventUpdate
import dash_cytoscape as cyto  # For interactive graph visualization
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

def get_file_tree(root_dir, batch_size=10):
    node_id_counter = [0]  # Use a list to make it mutable within nested functions

    tree = {
        'name': os.path.basename(root_dir) if os.path.basename(root_dir) else root_dir,
        'path': root_dir,
        'children': [],
        'type': 'directory',
        'id': node_id_counter[0]  # Assign unique ID
    }
    node_id_counter[0] += 1

    file_hashes = {}
    duplicate_files = []

    def add_nodes(node):
        try:
            entries = os.scandir(node['path'])
            files_to_hash = []
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    dir_node = {
                        'name': entry.name,
                        'path': entry.path,
                        'children': [],
                        'type': 'directory',
                        'id': node_id_counter[0]  # Assign unique ID
                    }
                    node_id_counter[0] += 1
                    add_nodes(dir_node)
                    node['children'].append(dir_node)
                elif entry.is_file(follow_symlinks=False):
                    files_to_hash.append(entry.path)

                    if len(files_to_hash) >= batch_size:
                        process_file_batch(files_to_hash, node, file_hashes, duplicate_files, node_id_counter)
                        files_to_hash = []  # Reset the batch list

            if files_to_hash:
                process_file_batch(files_to_hash, node, file_hashes, duplicate_files, node_id_counter)

        except PermissionError:
            print(f"Permission denied: {node['path']}")
        except Exception as e:
            print(f"Error accessing {node['path']}: {e}")

    add_nodes(tree)
    return tree

def process_file_batch(filepaths, node, file_hashes, duplicate_files, node_id_counter):
    batch_hashes = get_file_hashes(filepaths)

    for filepath, file_hash in batch_hashes.items():
        file_info = get_file_info(filepath, node_id_counter)
        if file_info:
            if file_hash:
                if file_hash in file_hashes:
                    file_info['is_duplicate'] = True
                    original_file = file_hashes[file_hash]
                    original_file['is_duplicate'] = True
                    duplicate_files.append((file_info, original_file))
                else:
                    file_hashes[file_hash] = file_info
            node['children'].append(file_info)

def get_file_info(filepath, node_id_counter):
    try:
        stat_info = os.stat(filepath)
        last_modified = datetime.fromtimestamp(stat_info.st_mtime)
        size = stat_info.st_size
        filename = os.path.basename(filepath)
        extension = os.path.splitext(filepath)[1].lower()
        is_empty = size == 0

        file_info = {
            'name': filename,
            'path': filepath,
            'size': size,
            'creation_date': datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
            'last_modified': last_modified.isoformat(),
            'extension': extension,
            'hash': None,
            'type': 'file',
            'id': node_id_counter[0],  # Assign unique ID
            # Analysis flags
            'is_duplicate': False,
            'is_old': (datetime.now() - last_modified).days > 5 * 365,
            'is_large': size > 100 * 1024 * 1024,
            'is_empty': is_empty
        }
        node_id_counter[0] += 1
        return file_info
    except PermissionError:
        print(f"Permission denied: {filepath}")
        return None
    except Exception as e:
        print(f"Error accessing {filepath}: {e}")
        return None

def get_file_hashes(filepaths):
    hashes = {}
    for filepath in filepaths:
        hash_md5 = hashlib.md5()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            hashes[filepath] = hash_md5.hexdigest()
        except PermissionError:
            print(f"Permission denied: {filepath}")
            hashes[filepath] = None
        except Exception as e:
            print(f"Error hashing {filepath}: {e}")
            hashes[filepath] = None
    return hashes

# ------------------------------
# Part 2: Build Dash Application
# ------------------------------

# Legend of the App
def create_legend():
    legend_items = [
        {'color': '#58a6ff', 'label': 'Directory'},
        {'color': 'green', 'label': 'Regular File'},
        {'color': 'red', 'label': 'Duplicate File'},
        {'color': 'orange', 'label': 'Old File (>5 years)'},
        {'color': 'purple', 'label': 'Large File (>100 MB)'},
        {'color': 'grey', 'label': 'Empty File'}
    ]

    legend = html.Div(
        [
            html.Div(
                [
                    html.Div(style={
                        'background-color': item['color'],
                        'width': '20px',
                        'height': '20px',
                        'display': 'inline-block',
                        'margin-right': '10px',
                        'border': '1px solid #000'
                    }),
                    html.Span(item['label'])
                ],
                style={'display': 'flex', 'align-items': 'center', 'margin-bottom': '5px'}
            )
            for item in legend_items
        ],
        style={'border': '1px solid #000', 'padding': '10px', 'margin-top': '20px'}
    )
    return legend

# Function to convert the file tree into a format suitable for Dash Cytoscape
def build_elements(node, parent_id=None, elements=None):
    if elements is None:
        elements = []
    current_id = node['id']
    node['id'] = str(current_id)
    color = '#58a6ff'  # Default color for directories

    if node['type'] == 'file':
        # Set color based on analysis flags
        if node.get('is_duplicate'):
            color = 'red'
        elif node.get('is_empty'):
            color = 'grey'
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
            'is_empty': node.get('is_empty', False),
            'background_color': color  # Pass the color to use in styling
        },
        'classes': node['type'],
    })

    # Add the edge from parent to current node
    if parent_id is not None:
        elements.append({'data': {'source': str(parent_id), 'target': node['id']}})

    # Recursively add children
    if 'children' in node:
        for child in node['children']:
            elements = build_elements(child, current_id, elements)

    return elements

# Function to build the file hierarchy for display
def build_file_hierarchy(node, level=0):
    items = []

    # Determine if node is a directory or file
    is_directory = node['type'] == 'directory'
    name = node['name']
    node_id = node['id']  # Use the unique ID assigned earlier

    # Style for the item
    item_style = {
        'display': 'flex',
        'alignItems': 'center',
        'marginLeft': f'{20 * level}px'
    }

    # Style for folder and file names
    name_style = {
        'display': 'inline-block',
        'cursor': 'pointer' if is_directory else 'default',
        'color': '#58a6ff' if is_directory else 'black'
    }

    # Icon for expanding/collapsing
    icon = html.Span('📁 ', style={'cursor': 'pointer'}) if is_directory else html.Span('📄 ')

    # Visualize button for directories
    visualize_button = dbc.Button(
        'Visualize',
        id={'type': 'visualize-button', 'node_id': node_id},
        size='sm',
        color='secondary',
        style={'marginLeft': '10px'}
    ) if is_directory else None

    # Main item (folder or file)
    item_children = []

    # Add icon with toggle functionality if directory
    if is_directory:
        item_children.append(
            html.Span(
                icon,
                id={'type': 'toggle-icon', 'node_id': node_id},
                className='toggle-icon'
            )
        )
    else:
        item_children.append(icon)

    # Add name
    item_children.append(
        html.Span(
            name,
            style=name_style,
            id={'type': 'item-name', 'node_id': node_id}
        )
    )

    # Add visualize button if directory
    if visualize_button:
        item_children.append(visualize_button)

    # Create the item div
    item = html.Div(
        item_children,
        style=item_style
    )

    items.append(item)

    # If the node is a directory, recursively build its children (initially hidden)
    if is_directory:
        child_items = []
        for child in node.get('children', []):
            child_items.extend(build_file_hierarchy(child, level + 1))  # Flatten the list

        children_div = html.Div(
            child_items,
            id={'type': 'children-div', 'node_id': node_id},
            className='children-div',
            style={'display': 'none'}  # Initially hidden
        )
        items.append(children_div)

    return items

# Function to format file sizes
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

# Initialize Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], long_callback_manager=long_callback_manager)
server = app.server  # Expose the server variable for deployments

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
            html.Div(id='loading-text', children=""),
            html.Div(id='scan-stats', children="")  # Element to display scan time and file count
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.H3("File Hierarchy"),
            html.Div([
                dbc.Button('Expand All', id='expand-all-button', n_clicks=0, style={'margin-right': '10px'}),
                dbc.Button('Collapse All', id='collapse-all-button', n_clicks=0),
            ], style={'margin-bottom': '10px'}),
            html.Div(id='file-hierarchy'),
            html.Div(id='dummy-output', style={'display': 'none'})  # Dummy output for clientside callback
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            dcc.Loading(
                id="loading-cytoscape",
                type="default",
                children=[
                    # Include the cytoscape component in the initial layout
                    cyto.Cytoscape(
                        id='cytoscape',
                        layout={'name': 'dagre'},
                        style={'width': '100%', 'height': '600px'},
                        elements=[],  # Start with empty elements
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
            create_legend()
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.Div(id='node-data')
        ], width=12)
    ]),
    dcc.Store(id='file-tree-store')  # Store the file tree data
])

# Callback to start scanning and update the graph using Dash Long Callback
@app.long_callback(
    output=[
        Output('loading-text', 'children'),
        Output('scan-stats', 'children'),
        Output('file-tree-store', 'data')
    ],
    inputs=[Input('scan-button', 'n_clicks')],
    state=[State('directory-input', 'value')],
    running=[
        (Output('scan-button', 'disabled'), True, False),
        (Output('directory-input', 'disabled'), True, False),
        (Output('loading-text', 'children'), 'Scanning in progress...', '')
    ],
)
def start_scan(n_clicks, directory):
    if n_clicks > 0 and directory:
        if not os.path.exists(directory):
            return "Directory does not exist.", "", None
        else:
            # Measure the scan time
            start_time = time.time()

            # Perform the scanning
            file_tree = get_file_tree(directory)

            # Measure the end time
            end_time = time.time()
            scan_time = end_time - start_time

            # Prepare the scan statistics
            total_files = count_files(file_tree)
            stats_message = f"Scan completed in {scan_time:.2f} seconds. Total files displayed: {total_files}"

            return "Scanning complete.", stats_message, file_tree
    else:
        return "", "", None

# Function to count total files
def count_files(node):
    count = 0
    if node['type'] == 'file':
        return 1
    elif node['type'] == 'directory':
        for child in node.get('children', []):
            count += count_files(child)
    return count

# Callback to build the file hierarchy after scanning
@app.callback(
    Output('file-hierarchy', 'children'),
    Input('file-tree-store', 'data')
)
def update_file_hierarchy(file_tree):
    if file_tree:
        hierarchy = build_file_hierarchy(file_tree)
        return hierarchy
    else:
        return ""

# Callback to handle expanding/collapsing folders
@app.callback(
    Output({'type': 'children-div', 'node_id': MATCH}, 'style'),
    Input({'type': 'toggle-icon', 'node_id': MATCH}, 'n_clicks'),
    State({'type': 'children-div', 'node_id': MATCH}, 'style'),
    prevent_initial_call=True
)
def toggle_folder(n_clicks, style):
    if n_clicks:
        if style and style.get('display') == 'none':
            style['display'] = 'block'
        else:
            style['display'] = 'none'
        return style
    else:
        raise PreventUpdate

# Clientside callback for "Expand All" and "Collapse All"
app.clientside_callback(
    """
    function(n_clicks_expand, n_clicks_collapse) {
        // Determine which button was clicked
        const ctx = dash_clientside.callback_context;
        if (!ctx.triggered.length) {
            return window.dash_clientside.no_update;
        }
        const triggered_id = ctx.triggered[0]['prop_id'].split('.')[0];
        const elements = document.getElementsByClassName('children-div');
        if (triggered_id === 'expand-all-button') {
            for (let i = 0; i < elements.length; i++) {
                elements[i].style.display = 'block';
            }
        } else if (triggered_id === 'collapse-all-button') {
            for (let i = 0; i < elements.length; i++) {
                elements[i].style.display = 'none';
            }
        }
        return null;
    }
    """,
    Output('dummy-output', 'children'),
    Input('expand-all-button', 'n_clicks'),
    Input('collapse-all-button', 'n_clicks')
)

# Callback to handle visualization of specific folders
@app.callback(
    Output('cytoscape', 'elements'),
    Input({'type': 'visualize-button', 'node_id': ALL}, 'n_clicks'),
    State('file-tree-store', 'data'),
    prevent_initial_call=True
)
def visualize_folder(n_clicks_list, file_tree):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate
    else:
        # Get the triggered ID directly as a dictionary
        button_id = ctx.triggered_id
        node_id = button_id['node_id']

        # Find the node corresponding to the node_id
        folder_node = find_node_by_id(file_tree, node_id)
        if folder_node:
            elements = build_elements(folder_node)
            return elements  # Return the elements to update the cytoscape graph
        else:
            return []

# Helper function to find a node by ID
def find_node_by_id(node, node_id):
    if node['id'] == node_id:
        return node
    elif node['type'] == 'directory':
        for child in node.get('children', []):
            result = find_node_by_id(child, node_id)
            if result:
                return result
    return None

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

# ------------------------------
# Run the Dash App
# ------------------------------
if __name__ == '__main__':
    app.run_server(debug=True)
