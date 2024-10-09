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

# Load extra layouts for Cytoscape
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
    all_files = []  # Collect all files for analysis

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
                        process_file_batch(files_to_hash, node, file_hashes, duplicate_files, node_id_counter, all_files)
                        files_to_hash = []  # Reset the batch list

            if files_to_hash:
                process_file_batch(files_to_hash, node, file_hashes, duplicate_files, node_id_counter, all_files)

        except PermissionError:
            print(f"Permission denied: {node['path']}")
        except Exception as e:
            print(f"Error accessing {node['path']}: {e}")

    add_nodes(tree)
    return tree, all_files

def process_file_batch(filepaths, node, file_hashes, duplicate_files, node_id_counter, all_files):
    batch_hashes = get_file_hashes(filepaths)

    for filepath, file_hash in batch_hashes.items():
        file_info = get_file_info(filepath, node_id_counter)
        if file_info:
            all_files.append(file_info)  # Add to all_files list for analysis
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

    # Checkbox for selection
    checkbox = dcc.Checklist(
        options=[{'label': '', 'value': node_id}],
        value=[],
        id={'type': 'checkbox', 'node_id': node_id},
        inputStyle={'margin-right': '5px'},
        style={'margin-right': '10px'}
    )

    # Main item (folder or file)
    item_children = []

    # Add checkbox
    item_children.append(checkbox)

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

# Initialize Dash app with suppress_callback_exceptions=True
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP],
                long_callback_manager=long_callback_manager,
                suppress_callback_exceptions=True)
server = app.server  # Expose the server variable for deployments

# Layout of the app
app.layout = dbc.Container([
    dcc.Store(id='analysis-complete', data=False),  # Store to track if analysis is complete
    dcc.Store(id='selected-section', data='Analysis'),  # Store to track selected section
    dcc.Store(id='file-tree-store'),  # Store the file tree data
    dcc.Store(id='all-files-store'),  # Store all files data for analysis
    dcc.Store(id='selected-items-store', data=[]),  # Store selected items from checkboxes
    dbc.Row([
        dbc.Col(html.H1("Allianz File System Analyzer"), width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.Div("Enter the root directory to analyze:"),
            dcc.Input(id='directory-input', type='text', value='', style={'width': '100%'}),
            html.Button('Initiate Directory Analysis', id='scan-button', n_clicks=0, style={'margin-top': '10px'}),
            html.Div(id='loading-text', children="")
        ], width=12)
    ]),
    # Div to show after analysis is complete
    html.Div(id='post-analysis-content', children=[
        html.Div(id='scan-stats', children=""),  # Element to display scan time and file count
        # Navigation bubbles
        html.Div([
            dbc.Button('Analysis', id='analysis-button', n_clicks=0, className='nav-bubble', color='primary'),
            dbc.Button('Directory Overview', id='directory-overview-button', n_clicks=0, className='nav-bubble', color='secondary'),
            dbc.Button('Builder', id='builder-button', n_clicks=0, className='nav-bubble', color='secondary')
        ], style={'margin-top': '20px', 'display': 'flex', 'gap': '10px', 'justify-content': 'center'}),
        html.Hr(),
        # Sections
        html.Div(id='section-content')
    ], style={'display': 'none'})  # Initially hidden
])

# Callback to start scanning and update the graph using Dash Long Callback
@app.long_callback(
    output=[
        Output('loading-text', 'children'),
        Output('scan-stats', 'children'),
        Output('file-tree-store', 'data'),
        Output('all-files-store', 'data'),
        Output('analysis-complete', 'data')
    ],
    inputs=[Input('scan-button', 'n_clicks')],
    state=[State('directory-input', 'value')],
    running=[
        (Output('scan-button', 'disabled'), True, False),
        (Output('directory-input', 'disabled'), True, False),
        (Output('loading-text', 'children'), 'Analysis in progress...', '')
    ],
)
def start_scan(n_clicks, directory):
    if n_clicks > 0 and directory:
        if not os.path.exists(directory):
            return "Directory does not exist.", "", None, None, False
        else:
            # Measure the scan time
            start_time = time.time()

            # Perform the scanning
            file_tree, all_files = get_file_tree(directory)

            # Measure the end time
            end_time = time.time()
            scan_time = end_time - start_time

            # Prepare the scan statistics
            total_files = count_files(file_tree)
            stats_message = f"Analysis completed in {scan_time:.2f} seconds. Total files displayed: {total_files}"

            return "Analysis complete.", stats_message, file_tree, all_files, True
    else:
        return "", "", None, None, False

# Function to count total files
def count_files(node):
    count = 0
    if node['type'] == 'file':
        return 1
    elif node['type'] == 'directory':
        for child in node.get('children', []):
            count += count_files(child)
    return count

# Callback to show post-analysis content
@app.callback(
    Output('post-analysis-content', 'style'),
    Input('analysis-complete', 'data')
)
def show_post_analysis_content(analysis_complete):
    if analysis_complete:
        return {'display': 'block'}
    else:
        return {'display': 'none'}

# Callback to update the section content based on selected section
@app.callback(
    Output('section-content', 'children'),
    [
        Input('analysis-button', 'n_clicks'),
        Input('directory-overview-button', 'n_clicks'),
        Input('builder-button', 'n_clicks'),
        Input('analysis-complete', 'data')  # Add this back as an Input
    ],
    [
        State('analysis-complete', 'data'),
        State('file-tree-store', 'data'),
        State('all-files-store', 'data'),
        State('selected-items-store', 'data')
    ],
    prevent_initial_call=False  # Allow initial call to set default content
)
def update_section_content(n_clicks_analysis, n_clicks_overview, n_clicks_builder, analysis_complete_input,
                           analysis_complete_state, file_tree, all_files, selected_items):
    if not analysis_complete_state:
        raise PreventUpdate

    # Determine which input triggered the callback
    ctx = dash.callback_context
    if not ctx.triggered:
        # Default to 'Analysis' tab when the app loads
        selected_section = 'Analysis'
    else:
        triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
        if triggered_id == 'analysis-button':
            selected_section = 'Analysis'
        elif triggered_id == 'directory-overview-button':
            selected_section = 'Directory Overview'
        elif triggered_id == 'builder-button':
            selected_section = 'Builder'
        elif triggered_id == 'analysis-complete' and analysis_complete_input:
            selected_section = 'Analysis'
        else:
            raise PreventUpdate  # Ignore other triggers

    # Update the section content
    if selected_section == 'Analysis':
        # Build the summary metrics
        content = build_analysis_content(all_files)
    elif selected_section == 'Directory Overview':
        content = html.Div([
            html.H3("Directory Overview"),
            html.Div([
                dbc.Button('Expand All', id='expand-all-button', n_clicks=0, style={'margin-right': '10px'}),
                dbc.Button('Collapse All', id='collapse-all-button', n_clicks=0),
                # Add Copy Selected to Builder button
                dbc.Button('Copy Selected to Builder', id='copy-to-builder-button', n_clicks=0, style={'margin-left': '30px'}),
            ], style={'margin-bottom': '10px'}),
            html.Div(id='file-hierarchy'),
            html.Div(id='visualization-content'),  # Placeholder for visualization
            html.Div(id='dummy-output', style={'display': 'none'})  # Dummy output for clientside callback
        ])
        # Update file hierarchy
        if file_tree:
            hierarchy = build_file_hierarchy(file_tree)
            content.children[2].children = hierarchy  # Corrected index to 2
    elif selected_section == 'Builder':
        content = build_builder_content(selected_items)
    else:
        content = html.Div()

    return content

def build_analysis_content(all_files):
    # Calculate metrics
    total_files = len(all_files)
    duplicate_files = [f for f in all_files if f.get('is_duplicate')]
    old_files = [f for f in all_files if f.get('is_old')]
    large_files = [f for f in all_files if f.get('is_large')]
    empty_files = [f for f in all_files if f.get('is_empty')]

    # Create collapsible items for each metric
    metrics = [
        {
            'title': f"Total Files Scanned: {total_files}",
            'id': 'total-files',
            'count': total_files,
            'files': all_files
        },
        {
            'title': f"Duplicate Files: {len(duplicate_files)}",
            'id': 'duplicate-files',
            'count': len(duplicate_files),
            'files': duplicate_files
        },
        {
            'title': f"Old Files (>5 years): {len(old_files)}",
            'id': 'old-files',
            'count': len(old_files),
            'files': old_files
        },
        {
            'title': f"Large Files (>100 MB): {len(large_files)}",
            'id': 'large-files',
            'count': len(large_files),
            'files': large_files
        },
        {
            'title': f"Empty Files: {len(empty_files)}",
            'id': 'empty-files',
            'count': len(empty_files),
            'files': empty_files
        }
    ]

    collapsibles = []
    for metric in metrics:
        collapsibles.append(
            dbc.Card([
                dbc.CardHeader(
                    html.H2(
                        dbc.Button(
                            metric['title'],
                            color='link',
                            id=f"group-{metric['id']}-toggle",
                        )
                    )
                ),
                dbc.Collapse(
                    dbc.CardBody(build_file_table(metric['files'])),
                    id=f"collapse-{metric['id']}",
                ),
            ], className='mb-3')
        )

    content = html.Div([
        html.H3("Analysis"),
        html.Div(collapsibles)
    ])

    return content

def build_file_table(files):
    if not files:
        return html.P("No files found in this category.")

    table_header = [
        html.Thead(html.Tr([
            html.Th("File Name"),
            html.Th("Path"),
            html.Th("Size"),
            html.Th("Last Modified")
        ]))
    ]

    rows = []
    for file in files:
        rows.append(html.Tr([
            html.Td(file.get('name')),
            html.Td(file.get('path')),
            html.Td(format_size(file.get('size'))),
            html.Td(file.get('last_modified'))
        ]))

    table_body = [html.Tbody(rows)]

    table = dbc.Table(table_header + table_body, bordered=True, hover=True, responsive=True, striped=True)

    return table

def build_builder_content(selected_items):
    if not selected_items:
        return html.Div([
            html.H3("Builder"),
            html.P("No items have been copied from the Directory Overview yet.")
        ])
    else:
        # Display the list of copied items
        items = []
        for item in selected_items:
            items.append(html.Li(f"{item['type'].capitalize()}: {item['path']}"))
        content = html.Div([
            html.H3("Builder"),
            html.P("List of copied items:"),
            html.Ul(items)
        ])
        return content

# Callback to toggle collapsibles in Analysis tab
@app.callback(
    [Output(f"collapse-{metric_id}", "is_open") for metric_id in ['total-files', 'duplicate-files', 'old-files', 'large-files', 'empty-files']],
    [Input(f"group-{metric_id}-toggle", "n_clicks") for metric_id in ['total-files', 'duplicate-files', 'old-files', 'large-files', 'empty-files']],
    [State(f"collapse-{metric_id}", "is_open") for metric_id in ['total-files', 'duplicate-files', 'old-files', 'large-files', 'empty-files']],
    prevent_initial_call=True
)
def toggle_collapses(*args):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    # Initialize all collapsibles to their current state
    states = list(args[-5:])
    # Get the index of the button that triggered the callback
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    index = ['group-total-files-toggle', 'group-duplicate-files-toggle', 'group-old-files-toggle', 'group-large-files-toggle', 'group-empty-files-toggle'].index(button_id)

    # Toggle the state of the triggered collapsible
    states[index] = not states[index]

    return states

# Callback to update the button colors
@app.callback(
    [
        Output('analysis-button', 'color'),
        Output('directory-overview-button', 'color'),
        Output('builder-button', 'color')
    ],
    [
        Input('analysis-button', 'n_clicks'),
        Input('directory-overview-button', 'n_clicks'),
        Input('builder-button', 'n_clicks')
    ]
)
def update_button_colors(n_clicks_analysis, n_clicks_overview, n_clicks_builder):
    ctx = dash.callback_context
    if not ctx.triggered:
        triggered_id = 'analysis-button'
    else:
        triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]

    colors = {
        'analysis-button': 'secondary',
        'directory-overview-button': 'secondary',
        'builder-button': 'secondary'
    }
    colors[triggered_id] = 'primary'

    return colors['analysis-button'], colors['directory-overview-button'], colors['builder-button']

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

# Callback to collect selected items from checkboxes
@app.callback(
    Output('selected-items-store', 'data'),
    Input('copy-to-builder-button', 'n_clicks'),
    State({'type': 'checkbox', 'node_id': ALL}, 'value'),
    State({'type': 'checkbox', 'node_id': ALL}, 'id'),
    State('file-tree-store', 'data'),
    prevent_initial_call=True
)
def copy_selected_to_builder(n_clicks, checkbox_values_list, checkbox_ids_list, file_tree):
    if n_clicks:
        selected_node_ids = []
        for value_list in checkbox_values_list:
            if value_list:
                selected_node_ids.extend(value_list)

        selected_items = []
        for node_id in selected_node_ids:
            node = find_node_by_id(file_tree, int(node_id))
            if node:
                selected_items.append({
                    'id': node['id'],
                    'name': node['name'],
                    'path': node['path'],
                    'type': node['type']
                })
        return selected_items
    else:
        raise PreventUpdate

# Callback to handle visualization of specific folders
@app.callback(
    Output('visualization-content', 'children'),
    Input({'type': 'visualize-button', 'node_id': ALL}, 'n_clicks'),
    State('file-tree-store', 'data'),
    prevent_initial_call=True
)
def visualize_folder(n_clicks_list, file_tree):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate
    else:
        # Get the triggered ID and the value of n_clicks for the triggered input
        button_id = ctx.triggered_id
        triggered_value = ctx.triggered[0]['value']

        # Check if the n_clicks of the triggered button is greater than 0
        if not triggered_value or triggered_value <= 0:
            raise PreventUpdate

        if 'node_id' not in button_id:
            raise PreventUpdate
        node_id = button_id['node_id']

        # Proceed to visualize
        folder_node = find_node_by_id(file_tree, node_id)
        if folder_node:
            elements = build_elements(folder_node)
            # Build the visualization content
            visualization_content = html.Div([
                html.Hr(),
                html.H3("Directory Visualization"),
                dcc.Loading(
                    id="loading-cytoscape",
                    type="default",
                    children=[
                        cyto.Cytoscape(
                            id='cytoscape',
                            layout={'name': 'dagre'},
                            style={'width': '100%', 'height': '600px'},
                            elements=elements,  # Update elements
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
                ),
                create_legend(),
                html.Div(id='node-data')
            ])
            return visualization_content
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
    Input('cytoscape', 'tapNodeData'),
    prevent_initial_call=True
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