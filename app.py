import streamlit as st
import os
import pandas as pd
import sys # Added for sys.path and sys.platform

# --- START: HiGHS PATH Setup (MUST BE AT THE VERY TOP) ---
# This ensures the HiGHS executable is discoverable by Pyomo/Linopy
# as soon as PyPSA-related modules are imported.
_highs_exe_path_set = False
# Using a global flag to ensure this expensive PATH modification happens only once
if not _highs_exe_path_set:
    try:
        # Find the site-packages directory in the current virtual environment
        site_packages_path = None
        for p in sys.path:
            if 'site-packages' in p and os.path.isdir(os.path.join(p, 'highspy')):
                site_packages_path = p
                break
        
        if site_packages_path:
            highs_bin_path = os.path.join(site_packages_path, 'highspy', 'bin')
            
            highs_executable_name = 'highs'
            if sys.platform == 'win32':
                highs_executable_name = 'highs.exe'
            
            highs_exe_full_path = os.path.join(highs_bin_path, highs_executable_name)

            if os.path.exists(highs_exe_full_path) and os.access(highs_exe_full_path, os.X_OK):
                # Prepend the directory containing the executable to PATH
                os.environ['PATH'] = highs_bin_path + os.pathsep + os.environ.get('PATH', '')
                _highs_exe_path_set = True
    except Exception as e:
        # Silently handle, as Pyomo might still find it in default PATH or user config
        pass 

# Store the status in session_state for frontend messaging if needed
if 'highs_path_set_status' not in st.session_state:
    st.session_state.highs_path_set_status = _highs_exe_path_set
# --- END: HiGHS PATH Setup ---

# Now import other modules, including those that import pypsa/linopy
from frontend import about_tab, project_tab, data_mapping_tab, simulation_tab, compare_tab


# Set Streamlit page configuration
st.set_page_config(
    page_title="PacCEM - Pacific Capacity Expansion Model",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        'Get Help': 'mailto:support@example.com',
        'Report a bug': "mailto:bugs@example.com",
        'About': "# PacCEM - A PyPSA-based tool for capacity expansion modeling."
    }
)

# Initialize session state for navigation and data persistence
if 'current_tab_index' not in st.session_state:
    st.session_state.current_tab_index = 0 # Corresponds to "About" tab

if 'project_data' not in st.session_state:
    st.session_state.project_data = {}
if 'excel_file_buffer' not in st.session_state:
    st.session_state.excel_file_buffer = None
if 'excel_sheet_names' not in st.session_state:
    st.session_state.excel_sheet_names = []
if 'mapped_data' not in st.session_state:
    st.session_state.mapped_data = {}

# Initializing data_mapping_mode is crucial for the UI state of data_mapping_tab
if 'data_mapping_mode' not in st.session_state:
    st.session_state.data_mapping_mode = {
        "buses": "Excel Mapping",
        "demand": "Excel Mapping", # Fix 2: Internal key is still 'demand'
        "generators": "Excel Mapping",
        "transmission_lines": "Excel Mapping",
        "transformers": "Excel Mapping",
        "storage": "Excel Mapping",
        "generation_profiles": "Excel Mapping",
    }

# Initializing manual_data with correct columns after Fix 6 (removed fixed_O&M)
if 'manual_data' not in st.session_state:
    st.session_state.manual_data = {
        'buses': pd.DataFrame(columns=['Bus name', 'v_nom', 'x', 'y', 'carrier', 'unit']),
        'demand': pd.DataFrame(columns=['Bus'] + [f'Time_{i}' for i in range(8760)]),
        'generators': pd.DataFrame(
            columns=['Generator name', 'Bus', 'Capacity(MW)', 'Size (MW)', 'Quantity', 'Build Year', 'P_nom_min',
                     'P_nom_max', 'Carrier', 'Scenario', 'p_nom_extendable', 'Marginal cost (USD/MWh)',
                     'Capital_cost (USD/MW)', 'fixed_O&M (USD/MW/year)', 'lifetime', 'Status', 'efficiency', 'p_min_pu', 'Profile Column']),
        'transmission_lines': pd.DataFrame(columns=['From', 'To', 'type', 's_nom_extendable', 's_nom', 'Capital_cost (USD/MVA)', 'Length (kM)', 'Scenario']),
        'transformers': pd.DataFrame(columns=['name', 'bus0', 'bus1', 's_nom', 'v_nom0', 'v_nom1', 'x', 'r', 'Capital_cost (USD/MW)', 'Scenario', 'num_parallel']),
        'storage': pd.DataFrame(columns=['name', 'p_nom (MW)', 'e_nom (MWh)', 'Year', 'Carrier', 'Bus', 'Scenario', 'e_nom_extendable', 'Marginal cost (USD/MWh)', 'Capital_cost (USD/MW)', 'lifetime', 'Status' ]),
        'generation_profiles': pd.DataFrame(columns=['Solar profile', 'Solar Rooftop profile', 'Wind profile', 'Hydro profile']),
    }
if 'simulation_results' not in st.session_state:
    st.session_state.simulation_results = None
if 'log_output' not in st.session_state:
    st.session_state.log_output = ""


# Ensure results and cache directories exist
os.makedirs("results", exist_ok=True)
os.makedirs("cache", exist_ok=True)


# Horizontal navigation tabs
tab_names = ["About", "Project", "Data Mapping", "Simulation", "Compare"] 

tab_objects = st.tabs(tab_names)

with tab_objects[0]: # About Tab
    about_tab.show_tab()
with tab_objects[1]: # Project Tab
    project_tab.show_tab()
with tab_objects[2]: # Data Mapping Tab
    data_mapping_tab.show_tab()
with tab_objects[3]: # Simulation Tab
    simulation_tab.show_tab()
with tab_objects[4]: # Compare Tab
    compare_tab.show_tab()