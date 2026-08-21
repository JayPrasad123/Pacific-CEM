import streamlit as st
import pandas as pd
import folium
from folium import plugins
from streamlit_folium import folium_static
import io
import time
from backend.model_runner import run_model, get_renewable_carriers, generate_input_summary  # Only import core backend functions
import os
from datetime import datetime
import shutil
import linopy  # For checking available solvers
import plotly.express as px  # For plotting results
import plotly.graph_objects as go  # For more custom plots


# --- Helper Function: Determine Generator Status ---
def get_generator_status(row):
    """Determines the investment status of a generator based on initial and optimized capacity."""
    # Use a small epsilon for float comparison to avoid precision errors
    epsilon = 0.01
    p_init = row.get('p_nom', 0.0)
    p_opt = row.get('p_nom_opt', 0.0)

    if p_init < epsilon and p_opt > epsilon:
        return "New Build"
    elif p_init > epsilon and p_opt > p_init + epsilon:
        return "Expanded"
    elif p_init > epsilon and p_opt < epsilon:
        return "Decommissioned"
    elif p_init > epsilon and p_opt >= epsilon:
        return "Existing"
    else:
        return "Not Built"

def get_storage_status(row):
    """Determines the investment status of a storage unit based on initial and optimized energy capacity."""
    epsilon = 0.01
    e_init = row.get('e_nom', 0.0) # For stores, this is initial energy capacity
    e_opt = row.get('e_nom_opt', 0.0)

    if e_init < epsilon and e_opt > epsilon:
        return "New Build"
    elif e_init > epsilon and e_opt > e_init + epsilon:
        return "Expanded"
    elif e_init > epsilon and e_opt < epsilon:
        return "Decommissioned"
    elif e_init > epsilon and e_opt >= epsilon:
        return "Existing"
    else:
        return "Not Built"

# --- START OF FIX: Define color utilities locally within simulation_tab.py ---
def lighten_color(hex_color, factor=0.4):
    """Lightens a hex color by blending it with white."""
    if not isinstance(hex_color, str) or not hex_color.startswith('#') or len(hex_color) != 7:
        return '#CCCCCC'  # Default to light grey for invalid hex

    hex_color = hex_color.lstrip('#')

    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    r_light = int(r + (255 - r) * factor)
    g_light = int(g + (255 - g) * factor)
    b_light = int(b + (255 - b) * factor)

    r_light = max(0, min(255, r_light))
    g_light = max(0, min(255, g_light))
    b_light = max(0, min(255, b_light))

    return '#%02x%02x%02x' % (r_light, g_light, b_light)


# This is the master color map for all GUI plots
PLOT_COLOR_MAP = {
    'Diesel': 'brown',
    'Solar': 'yellow',
    'Wind': 'green',
    'Hydro': 'blue',
    'Slack': 'grey',
    'Gas': 'orange',
    'charge': 'pink',
    'discharge': '#5d4e29',
    'CNO': '#6A3D9A',
    'Solar Rooftop': 'lightgoldenrodyellow',
    'Geothermal': '#CAB2D6',
    'Bio Power- CNO': '#6A3D9A',
    'Battery Storage': 'purple'
}


def get_plot_color(carrier_name):
    """Helper to get color from PLOT_COLOR_MAP, case-insensitive."""
    color = PLOT_COLOR_MAP.get(carrier_name)
    if color: return color
    color = PLOT_COLOR_MAP.get(str(carrier_name).lower())
    if color: return color
    color = PLOT_COLOR_MAP.get(str(carrier_name).title())  # For 'Battery Storage'
    if color: return color
    return 'grey'  # Default if no match found
# --- END OF FIX ---

# --- Helper Function: Create Interactive Network Map ---
def create_network_map(n_results, df_buses, view_mode="Active Fleet"):
    if df_buses.empty:
        return None

    valid_buses = df_buses.dropna(subset=['lat', 'lon'])
    if valid_buses.empty:
        return folium.Map(location=[0, 0], zoom_start=2)

    map_center = [valid_buses['lat'].mean(), valid_buses['lon'].mean()]
    m = folium.Map(location=map_center, zoom_start=5, height=700, control_scale=True)

    # Dictionary to quickly look up bus coordinates by name
    bus_coords = {row['name']: (row['lat'], row['lon']) for idx, row in valid_buses.iterrows()}

    # --- Layer Groups ---
    fg_buses = folium.FeatureGroup(name="Buses", show=True)
    fg_lines = folium.FeatureGroup(name="Transmission Lines", show=True)
    fg_transformers = folium.FeatureGroup(name="Transformers", show=True)

    # --- START OF FIX: Renamed and added dedicated BESS layer ---
    fg_other_links = folium.FeatureGroup(name="Other Network Links", show=True) # For non-battery links
    fg_bess_storage = plugins.MarkerCluster(name="Battery Energy Storage", show=True) # Dedicated layer for BESS
    # --- END OF FIX ---

    # Use MarkerCluster for generators to handle density (remains the same)
    fg_generators = plugins.MarkerCluster(name="Generators", show=True)

    # --- 1. Draw Buses --- (No change)
    for idx, row in valid_buses.iterrows():
        bus_name = row['name']
        popup_html = f"""
        <div style="font-family: sans-serif; width: 150px;">
            <b>Bus:</b> {bus_name}<br>
            <b>Voltage:</b> {row.get('v_nom', 'N/A')} kV<br>
            <b>Carrier:</b> {row.get('carrier', 'N/A')}
        </div>
        """
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=3,
            color='black',
            fill=True,
            fill_color='white',
            fill_opacity=1.0,
            popup=folium.Popup(popup_html, max_width=200),
            tooltip=bus_name
        ).add_to(fg_buses)

    # --- 2. Draw Lines --- (No change)
    if hasattr(n_results, 'lines') and not n_results.lines.empty:
        max_s_nom_line = n_results.lines.s_nom_opt.max() if not n_results.lines.s_nom_opt.empty else 0
        if max_s_nom_line == 0: max_s_nom_line = 100  # Prevent division by zero

        for idx, line in n_results.lines.iterrows():
            bus0_name = line['bus0']
            bus1_name = line['bus1']
            if bus0_name in bus_coords and bus1_name in bus_coords:
                points = [bus_coords[bus0_name], bus_coords[bus1_name]]

                cap = line.get('s_nom_opt', line.get('s_nom', 0))
                weight = 2 + (cap / max_s_nom_line * 4)

                popup_html = f"""
                <div style="font-family: sans-serif;">
                    <b>Line:</b> {idx}<br>
                    <b>Flow:</b> {bus0_name} ↔ {bus1_name}<br>
                    <b>Capacity:</b> {cap:.2f} MVA
                </div>
                """
                folium.PolyLine(
                    locations=points,
                    color='#555',  # Dark grey for transmission
                    weight=weight,
                    opacity=0.6,
                    popup=folium.Popup(popup_html, max_width=200),
                    tooltip=f"Line: {idx}"
                ).add_to(fg_lines)

    # --- 3. Draw Transformers --- (No change)
    if hasattr(n_results, 'transformers') and not n_results.transformers.empty:
        for idx, trafo in n_results.transformers.iterrows():
            bus0_name = trafo['bus0']
            bus1_name = trafo['bus1']
            if bus0_name in bus_coords and bus1_name in bus_coords:
                points = [bus_coords[bus0_name], bus_coords[bus1_name]]
                popup_html = f"<b>Transformer:</b> {idx}<br>S_nom: {trafo.get('s_nom', 'N/A')} MVA"
                folium.PolyLine(
                    locations=points,
                    color='orange',
                    weight=3,
                    opacity=0.8,
                    popup=folium.Popup(popup_html, max_width=200)
                ).add_to(fg_transformers)

    # --- 4. Draw Generators (Dynamic Filtering) --- (Existing logic, no change)
    if not n_results.generators.empty:
        df_gens = n_results.generators.copy()

        NEGLIGIBLE_SLACK_GENERATION_MWh = 0.001
        total_slack_gen_mwh = n_results.generators_t.p[
            'slack'].sum() if 'slack' in n_results.generators.index and 'slack' in n_results.generators_t.p.columns and not n_results.generators_t.p.empty else 0
        is_slack_contributing_for_map = abs(total_slack_gen_mwh) > NEGLIGIBLE_SLACK_GENERATION_MWh

        if 'slack' in df_gens.index and not is_slack_contributing_for_map:
            df_gens = df_gens.drop('slack')

        df_gens['status'] = df_gens.apply(get_generator_status, axis=1)

        if view_mode == "Active Fleet":
            df_gens = df_gens[df_gens['p_nom_opt'] > 0.01]
        elif view_mode == "New Investments":
            df_gens = df_gens[df_gens['status'].isin(["New Build", "Expanded"])]
        elif view_mode == "All Assets": # If "All Assets", don't filter by p_nom > 0.01
            pass # No additional filtering based on p_nom_opt
        elif view_mode == "Existing Fleet":
            df_gens = df_gens[df_gens['p_nom'] > 0.01] # Filter for initial capacity

        df_gens_map = df_gens.merge(
            valid_buses[['name', 'lat', 'lon']],
            left_on='bus',
            right_on='name',
            how='inner'
        )

        max_gen_cap = df_gens_map['p_nom_opt'].max() if not df_gens_map.empty else 0
        if max_gen_cap == 0: max_gen_cap = 100  # Prevent division by zero

        for i, row in df_gens_map.iterrows():
            status = row['status']
            p_opt = row['p_nom_opt']
            p_init = row['p_nom']
            carrier = row['carrier']

            if status == "New Build":
                marker_color = "green"
            elif status == "Expanded":
                marker_color = "orange"
            elif status == "Decommissioned":
                marker_color = "red"
            elif status == "Existing":
                marker_color = "blue"
            else:
                marker_color = "gray"

            radius = 5
            if p_opt > 0 and max_gen_cap > 0:
                radius = 5 + (p_opt / max_gen_cap) * 15

            popup_content = f"""
            <div style="font-family: sans-serif; width: 200px;">
                <h5 style="margin-bottom:5px; color:{marker_color};">{row['Generator name'] if 'Generator name' in row else row.name}</h5>
                <b>Carrier:</b> {carrier}<br>
                <b>Status:</b> <b>{status}</b><br>
                <hr style="margin: 5px 0;">
                <b>Capacity (Optimized):</b> {p_opt:.2f} MW<br>
                <b>Capacity (Initial):</b> {p_init:.2f} MW<br>
                <br>
                <b>Marginal Cost:</b> {row.get('marginal_cost', 0):.2f} $/MWh<br>
                <b>Capital Cost:</b> {row.get('capital_cost', 0):.0f} $/MW
            </div>
            """

            folium.CircleMarker(
                location=[row['lat'], row['lon']],
                radius=radius,
                color=marker_color,
                fill=True,
                fill_color=marker_color,
                fill_opacity=0.7,
                popup=folium.Popup(popup_content, max_width=250),
                tooltip=f"{carrier}: {p_opt:.1f} MW"
            ).add_to(fg_generators)

    # --- 5. Draw Other Network Links (not batteries) ---
    if hasattr(n_results, 'links') and not n_results.links.empty:
        for idx, link in n_results.links.iterrows():
            # --- START OF FIX: Plot only non-battery links here ---
            if link['carrier'] != 'battery_link':
                bus0 = link['bus0']
                bus1 = link['bus1']
                if bus0 in bus_coords and bus1 in bus_coords:
                     folium.PolyLine(
                        locations=[bus_coords[bus0], bus_coords[bus1]],
                        color='green',
                        weight=2,
                        dash_array='5, 5',
                        popup=f"Link: {idx} ({link['carrier']})" # Added carrier info to popup
                    ).add_to(fg_other_links) # Add to the renamed layer
            # --- END OF FIX ---

    # --- START OF FIX: Draw Battery Energy Storage (BESS) ---
    if hasattr(n_results, 'stores') and not n_results.stores.empty:
        # Create a working copy of stores data and add initial e_nom
        df_stores_working = n_results.stores.copy()
        df_stores_working['e_nom_initial'] = n_results.stores.e_nom

        # --- Robustly identify battery stores ---
        # A store is a battery if its carrier contains 'battery'
        # OR if its name (which is the parent bus of the internal_bus) is linked to a battery_link

        # Get store names that are linked to a battery_link (by finding their internal bus names)
        stores_from_links_internal_bus_names = n_results.links[n_results.links.carrier == 'battery_link']['bus0'].str.replace('_internal_bus', '')
        # Get the actual store names from the parent bus side of the link
        stores_from_links_parent_bus_names = n_results.links[n_results.links.carrier == 'battery_link']['bus1']

        # Filter stores where their carrier contains 'battery' OR their name matches a parent bus of a battery link
        # Use store_name (index) to filter, not the 'bus' column directly for initial filter
        battery_store_names = df_stores_working[
            (df_stores_working['carrier'].str.contains('battery', case=False, na=False, regex=False)) |
            (df_stores_working['bus'].isin(stores_from_links_parent_bus_names)) # Match store's 'bus' (parent bus) to link's 'bus1'
        ].index

        df_batteries = df_stores_working.loc[battery_store_names].copy() # Filter the stores identified as batteries

        if not df_batteries.empty:
            # Determine BESS status based on initial vs optimized energy capacity
            def get_bess_status(row):
                epsilon = 0.01
                e_init = row.get('e_nom_initial', 0.0)
                e_opt = row.get('e_nom_opt', 0.0)

                if e_init < epsilon and e_opt > epsilon: return "New Build"
                elif e_init > epsilon and e_opt > e_init + epsilon: return "Expanded"
                elif e_init > epsilon and e_opt < epsilon: return "Decommissioned"
                elif e_init > epsilon and e_opt >= epsilon: return "Existing"
                else: return "Not Built"

            df_batteries['status'] = df_batteries.apply(get_bess_status, axis=1)

            df_batteries_to_plot = df_batteries.copy()

            # Apply view_mode filtering to batteries
            if view_mode == "Active Fleet":
                df_batteries_to_plot = df_batteries_to_plot[df_batteries_to_plot['e_nom_opt'] > 0.01]
            elif view_mode == "New Investments":
                df_batteries_to_plot = df_batteries_to_plot[df_batteries_to_plot['status'].isin(["New Build", "Expanded"])]
            elif view_mode == "Existing Fleet":
                df_batteries_to_plot = df_batteries_to_plot[df_batteries_to_plot['e_nom_initial'] > 0.01]
            elif view_mode == "All Assets":
                pass # No additional filtering

            # Merge with bus coordinates using the 'bus' column of the store (which is its parent bus)
            df_batteries_map = df_batteries_to_plot.merge(
                valid_buses[['name', 'lat', 'lon']],
                left_on='bus', # Match store's 'bus' (parent bus)
                right_on='name',
                how='inner'
            )

            if not df_batteries_map.empty:
                max_bess_cap = df_batteries_map['e_nom_opt'].max() if not df_batteries_map.empty else 100
                if max_bess_cap == 0: max_bess_cap = 100

                for i, row in df_batteries_map.iterrows():
                    status = row['status']
                    e_opt = row['e_nom_opt']
                    e_init = row['e_nom_initial']
                    carrier = row['carrier']
                    store_name = row.name # The index is the store name

                    if status == "New Build": marker_color = "darkgreen"
                    elif status == "Expanded": marker_color = "darkorange"
                    elif status == "Decommissioned": marker_color = "darkred"
                    elif status == "Existing": marker_color = "darkblue"
                    else: marker_color = "grey"

                    radius = 5
                    if e_opt > 0 and max_bess_cap > 0:
                        radius = 5 + (e_opt / max_bess_cap) * 15
                    else:
                        radius = 5

                    # Find the associated link's p_nom_opt based on the store's internal bus name
                    associated_link_p_nom = 0.0 # Default to 0.0 if not found
                    internal_bus_name_for_store = f"{store_name}_internal_bus"
                    matching_links = n_results.links[n_results.links['bus0'] == internal_bus_name_for_store]
                    if not matching_links.empty:
                        associated_link_p_nom = matching_links.iloc[0]['p_nom_opt']

                    popup_content = f"""
                    <div style="font-family: sans-serif; width: 200px;">
                        <h5 style="margin-bottom:5px; color:{marker_color};">Battery: {store_name}</h5>
                        <b>Carrier:</b> {carrier}<br>
                        <b>Status:</b> <b>{status}</b><br>
                        <hr style="margin: 5px 0;">
                        <b>Energy Capacity (Optimized):</b> {e_opt:.2f} MWh<br>
                        <b>Energy Capacity (Initial):</b> {e_init:.2f} MWh<br>
                        <b>Power Rating (Optimized):</b> {associated_link_p_nom:.2f} MW<br>
                    </div>
                    """
                    folium.CircleMarker(
                        location=[row['lat'], row['lon']],
                        radius=radius,
                        color=marker_color,
                        fill=True,
                        fill_color=marker_color,
                        fill_opacity=0.8,
                        popup=folium.Popup(popup_content, max_width=250),
                        tooltip=f"BESS ({carrier}): {e_opt:.1f} MWh"
                    ).add_to(fg_bess_storage)
            else:
                st.info(f"No significant battery storage assets to display in '{view_mode}' view on map.")
        else:
            st.info("No battery storage (Store components with battery links) found in network results to display on map.")
    else:
        st.info("No battery storage data found in network results.")
    # --- END OF FIX: Draw Battery Energy Storage (BESS) - Further Enhanced Logic ---

    # Add all layers to map
    fg_buses.add_to(m)
    fg_lines.add_to(m)
    fg_transformers.add_to(m)
    fg_generators.add_to(m)

    # --- START OF FIX: Add new BESS and renamed Other Links layers ---
    fg_bess_storage.add_to(m) # Add the dedicated BESS layer
    fg_other_links.add_to(m) # Add the renamed non-battery links layer
    # --- END OF FIX ---

    # Add Layer Control to toggle these
    folium.LayerControl(collapsed=False).add_to(m)

    return m

def show_tab():
    st.title("Run Simulation & View Outputs")

    if st.session_state.highs_path_set_status:
        st.info("HiGHS solver path successfully configured at application startup.")
    else:
        st.warning(
            "HiGHS solver path might not be automatically configured. Ensure 'highs' is in system PATH if using HiGHS.")

    try:
        if hasattr(linopy, 'available_solvers'):
            st.info(f"Available solvers detected by Linopy: {', '.join(linopy.available_solvers)}")
        else:
            st.warning("Could not determine available solvers from Linopy.")
    except Exception as e:
        st.warning(f"Error checking Linopy available solvers: {e}")

    st.subheader("Simulation Control")

    if st.button("Run Simulation", key="run_simulation_button", help="Click to start the PyPSA optimization."):
        if not all([st.session_state.project_data.get('project_name'),
                    st.session_state.project_data.get('results_dir'),
                    st.session_state.project_data.get('scenario_name'),
                    st.session_state.project_data.get('solver'),
                    st.session_state.project_data.get('scenario_year') is not None,
                    (st.session_state.project_data.get(
                        'demand_projection_method') == "Target Peak Demand" and st.session_state.project_data.get(
                        'target_peak_demand') is not None) or \
                    (st.session_state.project_data.get(
                        'demand_projection_method') == "Percentage Growth" and st.session_state.project_data.get(
                        'demand_growth_percentage') is not None)
                    ]):
            st.error(
                "Missing mandatory project or scenario details (Project Name, Results Dir, Scenario Name, Solver, Scenario Year, Demand Projection). Please complete the 'Project' tab.")
            return

        has_bus_data = False
        if st.session_state.data_mapping_mode.get('buses') == "Excel Mapping":
            if st.session_state.mapped_data.get('buses', {}).get('df_content'): has_bus_data = True
        elif st.session_state.data_mapping_mode.get('buses') == "Manual Entry":
            if not st.session_state.manual_data.get('buses', pd.DataFrame()).empty: has_bus_data = True

        has_load_data = False  # Fix 2: Renamed variable for Load Data
        if st.session_state.data_mapping_mode.get('demand') == "Excel Mapping":  # Internal key is still 'demand'
            if st.session_state.mapped_data.get('demand', {}).get('df_content'): has_load_data = True
        elif st.session_state.data_mapping_mode.get('demand') == "Manual Entry":
            if not st.session_state.manual_data.get('demand', pd.DataFrame()).empty: has_load_data = True

        if not has_bus_data:
            st.error("No bus data found. Please provide bus data in the 'Data Mapping' tab.")
            return
        if not has_load_data:  # Fix 2: Renamed message for Load Data
            st.error("No load data found. Please provide load data in the 'Data Mapping' tab.")
            return

        st.info("Validation passed. Starting simulation...")

        st.session_state.log_output = ""
        log_placeholder = st.empty()

        final_n_results = None
        final_results_prefix = None

        try:
            data_for_model = {}
            component_to_df_map = {
                "buses": "df_buses",
                "generators": "df_generators",
                "demand": "df_load",  # Internal key is still 'demand'
                "transmission_lines": "df_transmission_lines",
                "transformers": "df_transformers",
                "storage": "df_storage",
                "generation_profiles": "df_generation_profiles"
            }

            for comp_type, df_key in component_to_df_map.items():
                if comp_type == "demand" or comp_type == "generation_profiles":
                    if st.session_state.data_mapping_mode.get(comp_type) == "Excel Mapping":
                        mapped = st.session_state.mapped_data.get(comp_type, {})
                        data_for_model[df_key] = pd.DataFrame(mapped['df_content']) if mapped.get(
                            'df_content') else pd.DataFrame()
                        if mapped.get('sheet_name'):
                            data_for_model[f'{df_key}_mapping'] = mapped
                    else:
                        data_for_model[df_key] = st.session_state.manual_data.get(comp_type, pd.DataFrame())
                        data_for_model[f'{df_key}_mapping'] = {}
                else:
                    if st.session_state.data_mapping_mode.get(comp_type) == "Excel Mapping":
                        mapped = st.session_state.mapped_data.get(comp_type, {})
                        if mapped.get('df_content'):
                            df_raw = pd.DataFrame(mapped['df_content'])
                            rename_dict = {
                                mapped_col: default_col
                                for default_col, mapped_col in mapped.items()
                                if
                                default_col != 'sheet_name' and default_col != 'df_content' and mapped_col in df_raw.columns
                            }
                            data_for_model[df_key] = df_raw.rename(columns=rename_dict).copy()
                        else:
                            data_for_model[df_key] = pd.DataFrame()
                    else:
                        data_for_model[df_key] = st.session_state.manual_data.get(comp_type, pd.DataFrame()).copy()

            data_for_model['df_scenario_year'] = pd.DataFrame(
                {'Scenario': [st.session_state.project_data['scenario_number']],
                 'Year': [st.session_state.project_data['scenario_year']]})

            for item in run_model(
                    data_file=io.BytesIO(st.session_state.excel_file_buffer),
                    results_dir=st.session_state.project_data['results_dir'],
                    solver=st.session_state.project_data['solver'],
                    co2_cap=st.session_state.project_data['co2_cap'],
                    re_share=st.session_state.project_data['re_share'],
                    slack_cost=st.session_state.project_data['slack_cost'],
                    discount_rate=st.session_state.project_data['discount_rate'],
                    tech_cost_multipliers=st.session_state.project_data['tech_cost_multipliers'],
                    scenario_name=st.session_state.project_data['scenario_name'],
                    scenario_number=st.session_state.project_data['scenario_number'],
                    line_expansion=st.session_state.project_data['line_expansion'],
                    enabled_techs=st.session_state.project_data['enabled_techs'],
                    default_new_gen_extendable=st.session_state.project_data['default_new_gen_extendable'],
                    scenario_year=st.session_state.project_data['scenario_year'],
                    target_peak_demand=st.session_state.project_data['target_peak_demand'],
                    demand_projection_method=st.session_state.project_data['demand_projection_method'],
                    demand_growth_percentage=st.session_state.project_data['demand_growth_percentage'],
                    reserve_margin=st.session_state.project_data['reserve_margin'],
                    dispatchable_share=st.session_state.project_data['dispatchable_share'],
                    minimum_soc=st.session_state.project_data['minimum_soc'],
                    df_buses=data_for_model.get('df_buses', pd.DataFrame()),
                    df_generators=data_for_model.get('df_generators', pd.DataFrame()),
                    df_load=data_for_model.get('df_load', pd.DataFrame()),
                    df_transmission_lines=data_for_model.get('df_transmission_lines', pd.DataFrame()),
                    df_transformers=data_for_model.get('df_transformers', pd.DataFrame()),
                    df_storage=data_for_model.get('df_storage', pd.DataFrame()),
                    df_generation_profiles=data_for_model.get('df_generation_profiles', pd.DataFrame()),
                    df_scenario_year=data_for_model.get('df_scenario_year', pd.DataFrame())
            ):
                if isinstance(item, tuple) and len(item) == 2:
                    final_n_results, final_results_prefix = item
                    st.session_state.log_output += f"[{datetime.now().strftime('%H:%M:%S')}] Final results object received from model.\n"
                else:
                    st.session_state.log_output += str(item) + "\n"
                log_placeholder.code(st.session_state.log_output, language="text")
                time.sleep(0.01)

            if final_n_results is not None and final_results_prefix is not None:
                st.success("Simulation completed successfully! Results are saved to disk.")
                st.session_state.simulation_results = {
                    'network_object': final_n_results,
                    'results_path_prefix': final_results_prefix,
                    'initial_bus_data': data_for_model.get('df_buses', pd.DataFrame())
                }

                # Generate summary file AFTER getting the results path
                try:
                    summary_log = generate_input_summary(
                        project_data=st.session_state.project_data,
                        data_mapping_mode=st.session_state.data_mapping_mode,
                        mapped_data=st.session_state.mapped_data,
                        output_path=final_results_prefix
                    )
                    st.session_state.log_output += f"[{datetime.now().strftime('%H:%M:%S')}] {summary_log}\n"
                    log_placeholder.code(st.session_state.log_output, language="text")
                except Exception as e:
                    st.warning(f"Could not generate input summary file. Error: {e}")

            else:
                st.error("Simulation failed: Could not retrieve final results object from the model.")
                st.session_state.simulation_results = None

        except Exception as e:
            st.error(f"Simulation failed: {e}")
            st.exception(e)
            st.session_state.log_output += f"\nERROR: {e}\n"
            log_placeholder.code(st.session_state.log_output, language="text")

    st.subheader("Live Simulation Log")

    if st.session_state.simulation_results and st.session_state.simulation_results.get('network_object'):
        n_results = st.session_state.simulation_results['network_object']
        original_df_buses = st.session_state.simulation_results['initial_bus_data']
        results_path_prefix = st.session_state.simulation_results['results_path_prefix']

        tab_map, tab_plots = st.tabs(["Network Overview (Map)", "Simulation Results (Plots)"])

        with tab_map:
            st.subheader("Network Overview (Map)")

            # Map Controls
            col_map_ctrl, col_map_dummy = st.columns([2, 4])
            with col_map_ctrl:
                view_mode = st.radio(
                    "Select Generator View:",
                    ("Active Fleet", "New Investments", "Existing Fleet", "All Assets"),
                    help="Filter which generators are displayed on the map."
                )

            bus_df_for_map = original_df_buses.copy()
            bus_df_for_map = bus_df_for_map.rename(columns={'Bus name': 'name', 'x': 'lon', 'y': 'lat'})
            bus_df_for_map = bus_df_for_map.dropna(subset=['lon', 'lat'])

            map_object = create_network_map(n_results, bus_df_for_map, view_mode=view_mode)
            if map_object:
                folium_static(map_object)
            else:
                st.info("No valid bus coordinates to display the network map.")

        with tab_plots:
            st.subheader("Simulation Results (Plots)")

            # Fix 4: Thresholds for filtering slack
            NEGLIGIBLE_SLACK_GENERATION_MWh = 0.001
            NEGLIGIBLE_SLACK_CAPACITY_MW = 0.01
            NEGLIGIBLE_SLACK_COST_USD = 1.0

            # Determine if slack is contributing (for GUI plots and tables)
            total_slack_gen_mwh_gui = n_results.generators_t.p[
                'slack'].sum() if 'slack' in n_results.generators.index and 'slack' in n_results.generators_t.p.columns and not n_results.generators_t.p.empty else 0
            is_slack_contributing_gui = abs(total_slack_gen_mwh_gui) > NEGLIGIBLE_SLACK_GENERATION_MWh

            total_annual_demand_MWh = n_results.loads_t.p_set.sum().sum() if not n_results.loads_t.p_set.empty else 0
            renewable_generation_MWh = n_results.generators_t.p.loc[:, n_results.generators.carrier.isin(
                get_renewable_carriers())].sum().sum() if not n_results.generators_t.p.empty else 0
            total_co2_emissions_tons = (n_results.generators_t.p.sum().groupby(
                n_results.generators.carrier).sum() * n_results.carriers.co2_emissions).sum() if not n_results.generators_t.p.empty and 'co2_emissions' in n_results.carriers.columns else 0
            total_marginal_cost = (
                    n_results.generators_t.p * n_results.generators.marginal_cost).sum().sum() if not n_results.generators_t.p.empty else 0

            # --- Key Metrics Summary Table (Fix 4: Hide Slack if 0) ---
            installed_capacity_for_summary = n_results.generators.groupby(
                'carrier').p_nom_opt.sum() if not n_results.generators.empty else pd.Series()
            if 'slack' in installed_capacity_for_summary.index and not is_slack_contributing_gui:
                installed_capacity_for_summary = installed_capacity_for_summary.drop('slack')

            total_generation_for_summary_GWh = n_results.generators_t.p.sum().groupby(
                n_results.generators.carrier).sum() / 1e3 if not n_results.generators_t.p.empty else pd.Series()
            if 'slack' in total_generation_for_summary_GWh.index and not is_slack_contributing_gui:
                total_generation_for_summary_GWh = total_generation_for_summary_GWh.drop('slack')

            st.markdown("### Key Metrics Summary")
            metrics_data = {
                "Metric": [],
                "Value": [],
                "Unit": []
            }

            if n_results.objective is not None:
                metrics_data["Metric"].append("Total System Cost")
                metrics_data["Value"].append(f"{n_results.objective:.2f}")
                metrics_data["Unit"].append("USD")

            if not installed_capacity_for_summary.empty:
                metrics_data["Metric"].append("Total Installed Generation Capacity")
                metrics_data["Value"].append(f"{installed_capacity_for_summary.sum():.2f}")
                metrics_data["Unit"].append("MW")

            if not total_generation_for_summary_GWh.empty:
                metrics_data["Metric"].append("Total Annual Generation")
                metrics_data["Value"].append(f"{total_generation_for_summary_GWh.sum():.2f}")
                metrics_data["Unit"].append("GWh/year")

            if total_annual_demand_MWh > 0:
                achieved_re_share = (renewable_generation_MWh / total_annual_demand_MWh) * 100
                metrics_data["Metric"].append("Achieved RE Share")
                metrics_data["Value"].append(f"{achieved_re_share:.2f}")
                metrics_data["Unit"].append("%")

            metrics_data["Metric"].append("Total Annual CO₂ Emissions")
            metrics_data["Value"].append(f"{total_co2_emissions_tons:.2f}")
            metrics_data["Unit"].append("tons/year")

            df_key_metrics = pd.DataFrame(metrics_data)
            # --- START OF FIX: Round 'Value' column to 2 decimal places ---
            # Ensure 'Value' is numeric before rounding, then convert back to string with formatting
            df_key_metrics['Value'] = pd.to_numeric(df_key_metrics['Value'], errors='coerce').round(2).astype(str)
            # For values like costs, ensure they still have .00 if they are integers after rounding
            df_key_metrics['Value'] = df_key_metrics['Value'].apply(
                lambda x: f"{float(x):.2f}" if pd.notna(x) else "N/A")
            # --- END OF FIX ---
            st.dataframe(df_key_metrics, hide_index=True, use_container_width=True)

            st.markdown("---")

            # --- Data for Plots (Fix 4: Hide Slack if 0) ---
            installed_capacity_for_plots = n_results.generators.groupby(
                'carrier').p_nom_opt.sum() if not n_results.generators.empty else pd.Series()
            if 'slack' in installed_capacity_for_plots.index and not is_slack_contributing_gui:
                installed_capacity_for_plots = installed_capacity_for_plots.drop('slack')

            total_generation_for_plots_GWh = n_results.generators_t.p.sum().groupby(
                n_results.generators.carrier).sum() / 1e3 if not n_results.generators_t.p.empty else pd.Series()
            if 'slack' in total_generation_for_plots_GWh.index and not is_slack_contributing_gui:
                total_generation_for_plots_GWh = total_generation_for_plots_GWh.drop('slack')

            # --- Plot 1: Optimal Generation Capacity & Investment Decisions ---
            st.markdown("### 1. Optimal Generation Capacity & Investment Decisions")
            if not installed_capacity_for_plots.empty:
                df_capacity_plot = installed_capacity_for_plots.reset_index(name='Capacity (MW)')
                # Include storage in this plot too (total capacity)
                if not n_results.stores.empty:
                    store_capacity_mwh = n_results.stores.e_nom_opt.sum()
                    if store_capacity_mwh > 0:
                        df_capacity_plot = pd.concat([df_capacity_plot, pd.DataFrame(
                            [{'carrier': 'Battery Storage', 'Capacity (MW)': store_capacity_mwh}])], ignore_index=True)

                fig1 = px.bar(df_capacity_plot, x='carrier', y='Capacity (MW)',     # Keep y-field as 'Capacity (MW)'
                              title='Optimized Total Installed Capacity by Carrier',
                              labels={'carrier': 'Carrier', 'Capacity (MW)': 'Capacity (MW for Gen. / MWh for Storage)'}, # Updated label
                              color='carrier',
                              color_discrete_map=PLOT_COLOR_MAP)
                fig1.update_layout(xaxis_title='Carrier', yaxis_title='Capacity (MW for Gen. / MWh for Storage)', template='simple_white') # Updated axis title
                # --- END OF FIX ---
                st.plotly_chart(fig1, use_container_width=True)

                st.markdown("#### Investment Decisions Table")
                # --- START OF FIX: Comprehensive Investment Decisions Table ---
                investment_records = []

                # 1. Process Generators for New Investments/Expansions
                if not n_results.generators.empty:
                    # Filter for extendable generators that either grew or are new (p_nom_opt > 0)
                    df_invested_gens = n_results.generators[
                        (n_results.generators.p_nom_extendable == True) &
                        (n_results.generators.p_nom_opt > 0)
                    ].copy()

                    # Fix 4: Filter slack from investment decisions table
                    if 'slack' in df_invested_gens['carrier'].values and not is_slack_contributing_gui:
                        df_invested_gens = df_invested_gens[df_invested_gens['carrier'] != 'slack']

                    for gen_name, gen_row in df_invested_gens.iterrows():
                        p_init = gen_row.get('p_nom', 0.0)
                        p_opt = gen_row.get('p_nom_opt', 0.0)
                        new_capacity = p_opt - p_init

                        # Only include if actual new capacity was built or expanded
                        if new_capacity > 0.01: # Use a small threshold for floating point comparison
                            annual_investment_cost = new_capacity * gen_row.get('capital_cost', 0.0) # capital_cost already includes fixed O&M and annuitization

                            investment_records.append({
                                'Component Type': 'Generator',
                                'Name': gen_name,
                                'Bus': gen_row.get('bus', 'N/A'),
                                'Carrier': gen_row.get('carrier', 'N/A'),
                                'Initial Capacity': f"{p_init:.2f} MW",
                                'Optimized Capacity': f"{p_opt:.2f} MW",
                                'New Capacity Built': f"{new_capacity:.2f} MW",
                                'Annual Investment Cost': f"{annual_investment_cost:.2f} USD/year"
                            })

                # 2. Process Storage (BESS) for New Investments/Expansions
                if hasattr(n_results, 'stores') and not n_results.stores.empty:
                    df_invested_stores = n_results.stores[
                        (n_results.stores.e_nom_extendable == True) &
                        (n_results.stores.e_nom_opt > 0)
                    ].copy()

                    for store_name, store_row in df_invested_stores.iterrows():
                        e_init = store_row.get('e_nom', 0.0)
                        e_opt = store_row.get('e_nom_opt', 0.0)
                        new_energy_capacity = e_opt - e_init

                        if new_energy_capacity > 0.01: # Use a small threshold
                            annual_investment_cost_store = new_energy_capacity * store_row.get('capital_cost', 0.0) # For MWh capacity

                            # Also get associated Link's optimized power capacity (MW)
                            associated_link_name = f"{store_name}_link"
                            link_p_nom_opt = n_results.links.loc[associated_link_name, 'p_nom_opt'] if associated_link_name in n_results.links.index else 0.0
                            link_p_nom_initial = n_results.links.loc[associated_link_name, 'p_nom'] if associated_link_name in n_results.links.index else 0.0
                            new_power_capacity = link_p_nom_opt - link_p_nom_initial

                            # Annual cost for link power capacity (if extendable and new capacity built)
                            annual_investment_cost_link = 0.0
                            if new_power_capacity > 0.01 and associated_link_name in n_results.links.index and n_results.links.loc[associated_link_name, 'p_nom_extendable']:
                                annual_investment_cost_link = new_power_capacity * n_results.links.loc[associated_link_name, 'capital_cost']


                            investment_records.append({
                                'Component Type': 'Battery Storage',
                                'Name': store_name,
                                'Bus': store_row.get('bus', 'N/A'),
                                'Carrier': store_row.get('carrier', 'N/A'),
                                'Initial Capacity': f"{e_init:.2f} MWh",
                                'Optimized Capacity': f"{e_opt:.2f} MWh / {link_p_nom_opt:.2f} MW",
                                'New Capacity Built': f"{new_energy_capacity:.2f} MWh / {new_power_capacity:.2f} MW",
                                'Annual Investment Cost': f"{annual_investment_cost_store + annual_investment_cost_link:.2f} USD/year"
                            })

                if investment_records:
                    df_investment_decisions = pd.DataFrame(investment_records)
                    # No explicit rounding needed here as we are formatting as strings
                    st.dataframe(df_investment_decisions, hide_index=True, use_container_width=True)
                else:
                    st.info("No new generation or storage capacity investments were made in this scenario.")
                # --- END OF FIX: Comprehensive Investment Decisions Table ---

            # --- Plot 2: Technology Mix (Capacity & Generation Shares) ---
            st.markdown("### 2. Technology Mix (Capacity & Generation Shares)")
            col_cap_mix, col_gen_mix = st.columns(2)

            with col_cap_mix:
                st.markdown("#### Capacity Mix (MW)")
                if not installed_capacity_for_plots.empty:
                    df_capacity_mix = installed_capacity_for_plots.reset_index(name='Capacity (MW)')
                    # Include storage in pie chart
                    if not n_results.stores.empty:
                        store_capacity_mwh = n_results.stores.e_nom_opt.sum()
                        if store_capacity_mwh > 0:
                            df_capacity_mix = pd.concat([df_capacity_mix, pd.DataFrame(
                                [{'carrier': 'Battery Storage', 'Capacity (MW)': store_capacity_mwh}])],
                                                        ignore_index=True)

                    fig2_cap = px.pie(df_capacity_mix, values='Capacity (MW)', names='carrier', # Keep values field as 'Capacity (MW)'
                                      title='Optimized Capacity Mix (MW for Gen. / MWh for Storage)', hole=0.3, # Updated title
                                      color='carrier',
                                      color_discrete_map=PLOT_COLOR_MAP)
                    # --- END OF FIX ---
                    st.plotly_chart(fig2_cap, use_container_width=True)
                else:
                    st.info("No capacity mix data available.")

            with col_gen_mix:
                st.markdown("#### Annual Generation Share (GWh/year)")
                if not total_generation_for_plots_GWh.empty:
                    df_generation_mix = total_generation_for_plots_GWh.reset_index(name='Generation (GWh/year)')

                    fig2_gen = px.pie(df_generation_mix, values='Generation (GWh/year)', names='carrier',
                                      title='Annual Generation Share', hole=0.3,
                                      color='carrier',
                                      color_discrete_map=PLOT_COLOR_MAP)  # Use PLOT_COLOR_MAP
                    st.plotly_chart(fig2_gen, use_container_width=True)
                else:
                    st.info("No generation mix data available.")

            # --- Plot 3: Cost Breakdown ---
            st.markdown("### 3. Cost Breakdown")

            # --- START OF FIX: Display "By Cost Type" plot unconditionally ---
            if n_results.objective is not None and not n_results.generators.empty:
                gen_capital_cost = (n_results.generators.capital_cost * n_results.generators.p_nom_opt).sum()
                gen_fixed_operation_cost = (
                            n_results.generators.fixed_cost * n_results.generators.p_nom_opt).sum() if 'fixed_cost' in n_results.generators.columns else 0

                store_capital_cost = (
                            n_results.stores.capital_cost * n_results.stores.e_nom_opt).sum() if not n_results.stores.empty else 0
                link_capital_cost = (
                            n_results.links.capital_cost * n_results.links.p_nom_opt).sum() if not n_results.links.empty else 0
                line_capital_cost = (
                            n_results.lines.capital_cost * n_results.lines.s_nom_opt).sum() if not n_results.lines.empty else 0
                transformer_capital_cost = (
                            n_results.transformers.capital_cost * n_results.transformers.s_nom).sum() if not n_results.transformers.empty else 0

                slack_cost_value = 0
                if 'slack' in n_results.generators.index and not n_results.generators_t.p.empty and 'slack' in n_results.generators_t.p.columns:
                    slack_cost_value = (n_results.generators_t.p['slack'] * n_results.generators.loc[
                        'slack', 'marginal_cost']).sum()

                calculated_costs = {
                    'Generator Capital (USD/year)': gen_capital_cost,
                    'Generator Fixed O&M (USD/year)': gen_fixed_operation_cost,
                    'Generator Variable (USD/year)': total_marginal_cost,
                    'Storage Capital (USD/year)': store_capital_cost,
                    'Link Capital (USD/year)': link_capital_cost,
                    'Line Capital (USD/year)': line_capital_cost,
                    'Transformer Capital (USD/year)': transformer_capital_cost,
                    'Slack Cost (USD/year)': slack_cost_value
                }

                df_costs_breakdown = pd.DataFrame(list(calculated_costs.items()),
                                                  columns=['Cost Type', 'Amount (USD/year)'])
                df_costs_breakdown = df_costs_breakdown[
                    df_costs_breakdown['Amount (USD/year)'] > 0]  # Filter rows where amount is 0

                # Fix 4: Filter Slack Cost if negligible
                if 'Slack Cost (USD/year)' in df_costs_breakdown['Cost Type'].values and not is_slack_contributing_gui:
                    df_costs_breakdown = df_costs_breakdown[df_costs_breakdown['Cost Type'] != 'Slack Cost (USD/year)']

                if not df_costs_breakdown.empty:
                    fig3_by_type = px.bar(df_costs_breakdown, x='Cost Type', y='Amount (USD/year)',
                                          title='Annual System Cost Breakdown - By Cost Type',
                                          labels={'Amount (USD/year)': 'Amount (USD/year)'},
                                          color='Cost Type',
                                          color_discrete_map={  # Define specific colors for cost types
                                              'Generator Capital (USD/year)': '#ADD8E6',
                                              'Generator Fixed O&M (USD/year)': '#90EE90',
                                              'Generator Variable (USD/year)': '#FFB6C1',
                                              'Storage Capital (USD/year)': 'purple',
                                              'Link Capital (USD/year)': 'darkmagenta',
                                              'Line Capital (USD/year)': 'darkgray',
                                              'Transformer Capital (USD/year)': 'dimgray',
                                              'Slack Cost (USD/year)': 'red'  # Explicit red for slack cost
                                          })
                    st.plotly_chart(fig3_by_type, use_container_width=True)
                else:
                    st.info("No significant cost components found for 'By Cost Type' plot.")
            else:
                st.info(
                    "Cost breakdown data for 'By Cost Type' is not available (optimization might not have run or failed).")
            # --- END OF FIX: Display "By Cost Type" plot unconditionally ---

            st.markdown("---")  # Separator between plots

            # --- START OF FIX: Display "By Carrier (Generators)" plot unconditionally ---
            st.markdown("#### Annual System Cost Breakdown - By Generator Carrier (CAPEX vs OPEX)")
            if not n_results.generators.empty and not n_results.generators_t.p.empty:
                df_gen_costs = n_results.generators.copy()
                df_gen_costs['annual_capital_cost'] = df_gen_costs['capital_cost'] * df_gen_costs['p_nom_opt']
                df_gen_costs['annual_fixed_om_cost'] = df_gen_costs.get('fixed_cost', 0) * df_gen_costs['p_nom_opt']

                gen_annual_dispatch_MWh = n_results.generators_t.p.sum()
                df_gen_costs['annual_variable_cost'] = gen_annual_dispatch_MWh * df_gen_costs['marginal_cost']

                # Calculate total annual O&M cost for stacking
                df_gen_costs['annual_om_cost'] = df_gen_costs['annual_fixed_om_cost'] + df_gen_costs[
                    'annual_variable_cost']

                df_costs_by_carrier_aggregated = df_gen_costs.groupby('carrier')[
                    ['annual_capital_cost', 'annual_om_cost']].sum().reset_index()

                # Fix 4: Hide slack if cost is negligible
                if 'slack' in df_costs_by_carrier_aggregated['carrier'].values and not is_slack_contributing_gui:
                    df_costs_by_carrier_aggregated = df_costs_by_carrier_aggregated[
                        df_costs_by_carrier_aggregated['carrier'] != 'slack']

                # Filter out any carriers with negligible CAPEX and OPEX
                df_costs_by_carrier_aggregated = df_costs_by_carrier_aggregated[
                    (df_costs_by_carrier_aggregated['annual_capital_cost'].abs() > NEGLIGIBLE_SLACK_COST_USD) |
                    (df_costs_by_carrier_aggregated['annual_om_cost'].abs() > NEGLIGIBLE_SLACK_COST_USD)
                    ].copy()

                df_costs_melted_gui = df_costs_by_carrier_aggregated.melt(id_vars='carrier',
                                                                          value_vars=['annual_capital_cost',
                                                                                      'annual_om_cost'],
                                                                          var_name='Cost Type',
                                                                          value_name='Amount (USD/year)')

                # Ensure carrier names are lowercase for matching with 'PLOT_COLOR_MAP' dict
                df_costs_melted_gui['carrier_lower'] = df_costs_melted_gui['carrier'].str.lower()

                # Create a custom color map for stacking using the frontend's PLOT_COLOR_MAP
                stacked_colors_map_gui = {}
                for carr_name in df_costs_by_carrier_aggregated['carrier'].unique():
                    carr_name_lower = carr_name.lower()
                    # Use the PLOT_COLOR_MAP defined in simulation_tab.py, and then lighten it
                    base_color = PLOT_COLOR_MAP.get(carr_name, PLOT_COLOR_MAP.get(carr_name_lower, 'grey'))
                    stacked_colors_map_gui[f'annual_capital_cost_{carr_name_lower}'] = lighten_color(base_color,
                                                                                                     factor=0.4)  # Lighter for CAPEX
                    stacked_colors_map_gui[f'annual_om_cost_{carr_name_lower}'] = base_color  # Original for O&M
                df_costs_melted_gui['color_group'] = df_costs_melted_gui['Cost Type'] + '_' + df_costs_melted_gui[
                    'carrier_lower']

                if not df_costs_melted_gui.empty:
                    fig3_carrier = px.bar(df_costs_melted_gui,
                                          x='carrier',
                                          y='Amount (USD/year)',
                                          color='color_group',  # Use the combined key for coloring
                                          color_discrete_map=stacked_colors_map_gui,  # Apply the custom map
                                          title='Annual System Cost by Generator Carrier (CAPEX vs OPEX)',
                                          labels={'carrier': 'Carrier', 'Amount (USD/year)': 'Amount (USD/year)',
                                                  'Cost Type': 'Cost Category'},
                                          category_orders={'Cost Type': ['annual_capital_cost', 'annual_om_cost']},
                                          # Consistent stacking order
                                          barmode='stack')
                    fig3_carrier.update_layout(xaxis_title='Carrier', yaxis_title='Annual Cost (USD/year)',
                                               template='simple_white')
                    st.plotly_chart(fig3_carrier, use_container_width=True)
                else:
                    st.info("No generator carrier costs found for 'By Carrier (Generators)' plot.")
            else:
                st.info("Generator data for 'By Carrier (Generators)' is not available for cost breakdown.")
            # --- END OF FIX: Display "By Carrier (Generators)" plot unconditionally ---

            # --- START OF FIX: Replace CO2 Emissions Plot with LCOE by Carrier Plot (GUI) ---
            st.markdown("### 4. LCOE by Carrier & CO₂ Emissions")  # Updated title
            col_lcoe, col_cf = st.columns(2)  # Renamed col_co2 to col_lcoe

            with col_lcoe:  # This column now holds LCOE plot and CO2 metric
                st.markdown("#### Levelized Cost of Electricity (LCOE) by Carrier")

                # --- START OF FIX: Use robust LCOE calculation for GUI plot and prepare for single stacked bar ---
                lcoe_by_carrier_data_gui = []

                NEGLIGIBLE_GENERATION_MWh_FOR_LCOE = 0.001

                if not n_results.generators.empty:
                    all_gen_carriers = n_results.generators.carrier.fillna('unknown').unique()

                    all_capex_stats = n_results.statistics.capex()
                    all_opex_stats = n_results.statistics.opex()

                    for carrier in all_gen_carriers:
                        if carrier == 'slack' and not is_slack_contributing_gui:
                            continue

                        carrier_generator_indices = n_results.generators[n_results.generators.carrier == carrier].index
                        total_carrier_gen_mwh = 0.0
                        if not n_results.generators_t.p.empty and not carrier_generator_indices.empty:
                            relevant_dispatch_columns = carrier_generator_indices.intersection(n_results.generators_t.p.columns)
                            if not relevant_dispatch_columns.empty:
                                total_carrier_gen_mwh = n_results.generators_t.p[relevant_dispatch_columns].sum().sum()

                        carrier_capex_sum = all_capex_stats.get(('Generator', carrier), 0.0)
                        carrier_opex_sum = all_opex_stats.get(('Generator', carrier), 0.0)

                        lcoe_value = 0.0
                        if abs(total_carrier_gen_mwh) > NEGLIGIBLE_GENERATION_MWh_FOR_LCOE:
                            lcoe_value = (carrier_capex_sum + carrier_opex_sum) / total_carrier_gen_mwh

                        # Filter out entries that have no costs and no generation
                        if abs(lcoe_value) > 1e-6 or (abs(carrier_capex_sum) > 1e-6 or abs(carrier_opex_sum) > 1e-6) or abs(total_carrier_gen_mwh) > 1e-6:
                            lcoe_by_carrier_data_gui.append({
                                'Carrier': carrier,
                                'LCOE (USD/MWh)': lcoe_value
                            })

                df_lcoe_by_carrier_gui = pd.DataFrame(lcoe_by_carrier_data_gui)

                if not df_lcoe_by_carrier_gui.empty:
                    # Sort by LCOE value (descending) to get largest at bottom for stacking
                    df_lcoe_plot_data_gui = df_lcoe_by_carrier_gui.sort_values(by='LCOE (USD/MWh)', ascending=False).copy()

                    # Filter out entries where LCOE is zero/negligible
                    df_lcoe_plot_data_gui = df_lcoe_plot_data_gui[df_lcoe_plot_data_gui['LCOE (USD/MWh)'].abs() > 1e-6].copy()

                    # Add a common category for the x-axis to create a single stacked bar
                    df_lcoe_plot_data_gui['X-axis Category'] = 'Total LCOE (USD/MWh)' # Common category for the x-axis

                    fig_lcoe_gui = px.bar(df_lcoe_plot_data_gui,
                                          x='X-axis Category', # Use the new common category for X-axis
                                          y='LCOE (USD/MWh)',      # Y-axis is individual LCOE
                                          color='Carrier',          # Color by Carrier
                                          color_discrete_map=PLOT_COLOR_MAP, # Use the PLOT_COLOR_MAP
                                          title='Sum of Individual LCOEs by Technology Type',
                                          labels={'X-axis Category': 'LCOE (USD/MWh)', 'LCOE (USD/MWh)': 'LCOE (USD/MWh)'}, # Clearer labels
                                          barmode='stack') # Crucial for stacked bar chart

                    # Add Total Sum of Individual LCOEs as text label on top of the bar
                    total_sum_individual_lcoes_gui = df_lcoe_plot_data_gui['LCOE (USD/MWh)'].sum()
                    if total_sum_individual_lcoes_gui > 0:
                        fig_lcoe_gui.add_trace(go.Scatter(
                            x=['Total LCOE (USD/MWh)'], y=[total_sum_individual_lcoes_gui], # Position at top of stack
                            mode='text',
                            text=[f"Total: {total_sum_individual_lcoes_gui:.2f} $/MWh"], # Display the total sum
                            textposition='top center',
                            showlegend=False,
                            textfont=dict(color="white", size=10) # Adjust text color/size as needed
                        ))

                    fig_lcoe_gui.update_layout(xaxis_title='LCOE (USD/MWh)', yaxis_title='LCOE (USD/MWh)', template='simple_white')
                    st.plotly_chart(fig_lcoe_gui, use_container_width=True)
                else:
                    st.info("No LCOE by carrier data available for plotting.")
                # --- END OF FIX ---

                st.markdown("#### Annual CO₂ Emissions") # Keep metric display
                st.metric(label="Total Annual CO₂ Emissions", value=f"{total_co2_emissions_tons:.2f} tons")

            with col_cf:
                st.markdown("#### Capacity Factor by Carrier")
                if not n_results.generators.empty:
                    # Calculate capacity factor for GUI display
                    df_cf_gui = n_results.statistics.capacity_factor()
                    df_cf_gui = df_cf_gui.reset_index()
                    df_cf_gui.columns = ['Component', 'Carrier', 'Capacity Factor']

                    # Filter only generators and drop slack if not contributing
                    df_cf_generators_gui = df_cf_gui[df_cf_gui['Component'] == 'Generator'].copy()

                    if 'slack' in df_cf_generators_gui['Carrier'].values and not is_slack_contributing_gui:
                        df_cf_generators_gui = df_cf_generators_gui[df_cf_generators_gui['Carrier'] != 'slack']

                    # Filter out any carriers with zero capacity factor (after slack removal)
                    df_cf_generators_gui = df_cf_generators_gui[df_cf_generators_gui['Capacity Factor'] > 0]

                    if not df_cf_generators_gui.empty:
                        fig_cf_gui = px.bar(df_cf_generators_gui, x='Carrier', y='Capacity Factor',
                                            title='Capacity Factor by Generator Carrier',
                                            labels={'Carrier': 'Carrier', 'Capacity Factor': 'Capacity Factor (0-1)'},
                                            color='Carrier',
                                            color_discrete_map=PLOT_COLOR_MAP,  # Use PLOT_COLOR_MAP
                                            range_y=[0, 1])
                        st.plotly_chart(fig_cf_gui, use_container_width=True)
                    else:
                        st.info("No generator capacity factor data available for plotting.")
                else:
                    st.info("No generator data available to calculate capacity factor.")

            # --- Plot 5: Storage Behaviour ---
            st.markdown("### 5. Storage Behaviour")
            if not n_results.stores.empty:
                st.markdown("#### Total Storage State of Charge (SOC) over time")
                total_soc_t = n_results.stores_t.e.sum(axis=1) / 1000  # Convert to GWh for better scale
                fig5_soc = px.line(total_soc_t, title='Total System Storage State of Charge (GWh)',
                                   labels={'value': 'Total SOC (GWh)', 'index': 'Time'})
                fig5_soc.update_traces(
                    line=dict(color=get_plot_color('Battery Storage')))  # Ensure color consistency
                st.plotly_chart(fig5_soc, use_container_width=True)

                st.markdown("#### Total Storage Charging/Discharging Power over time")
                link_flow_data = None
                if not n_results.links.empty and hasattr(n_results.links_t, 'p0'):
                    battery_links = n_results.links[n_results.links.carrier == 'battery_link'].index
                    if not battery_links.empty:
                        link_flow_data = n_results.links_t.p0[battery_links].sum(axis=1)

                if link_flow_data is not None and (link_flow_data.sum() > 0 or link_flow_data.sum() < 0):
                    df_charge_discharge_gui = pd.DataFrame({
                        'charge': link_flow_data.where(link_flow_data < 0, 0),  # Negative values for charging
                        'discharge': link_flow_data.where(link_flow_data > 0, 0)  # Positive values for discharging
                    }, index=n_results.snapshots)

                    if not df_charge_discharge_gui.empty and (
                            df_charge_discharge_gui['charge'].abs().sum() > 0 or df_charge_discharge_gui[
                        'discharge'].sum() > 0):
                        fig5_power = go.Figure()

                        # Add discharge (positive stackgroup)
                        fig5_power.add_trace(
                            go.Scatter(x=n_results.snapshots, y=df_charge_discharge_gui['discharge'], stackgroup='2',
                                       name='Discharge', mode='none',
                                       line=dict(width=0.5, color=get_plot_color('discharge')),
                                       fillcolor=get_plot_color('discharge')))
                        # Add charge (negative stackgroup)
                        fig5_power.add_trace(
                            go.Scatter(x=n_results.snapshots, y=df_charge_discharge_gui['charge'], stackgroup='1',
                                       name='Charge', mode='none',
                                       line=dict(width=0.5, color=get_plot_color('charge')),
                                       fillcolor=get_plot_color('charge')))

                        fig5_power.update_layout(title='Total System Storage Charging/Discharging Power (MW)',
                                                 xaxis_title='Time', yaxis_title='Power (MW)', template='simple_white',
                                                 hovermode='x unified')
                        st.plotly_chart(fig5_power, use_container_width=True)
                    else:
                        st.info("No significant storage charging/discharging power data available.")
                else:
                    st.info("No storage charging/discharging power data available.")

            else:
                st.info("No storage data available for plotting.")

            # --- Fix 7: Hourly Generation Dispatch (Strict Stack Order) ---
            st.markdown("### 6. Hourly Generation Dispatch")

            fig6_dispatch = go.Figure()

            # Order: Diesel > Gas > Hydro > Discharge > Wind > Solar > Others (from bottom to top)
            desired_order_bottom_up = ['Diesel', 'Gas', 'Hydro', 'Wind', 'Solar']
            available_gen_carriers = n_results.generators.carrier.unique()

            # Prepare generator traces to add, ensuring filtering of 0 contribution
            gen_traces_to_add = []
            NEGLIGIBLE_HOURLY_DISPATCH_MW = 0.001  # 1 kW
            for c in available_gen_carriers:
                if c != 'slack':  # Always filter slack from plots
                    gens_carr_idx = n_results.generators[n_results.generators.carrier == c].index
                    if not gens_carr_idx.empty and not n_results.generators_t.p.empty:
                        valid_cols = gens_carr_idx.intersection(n_results.generators_t.p.columns)
                        if not valid_cols.empty:
                            y = n_results.generators_t.p[valid_cols].sum(axis=1)
                            # Fix 4: Filter out generators with negligible total contribution for dispatch plot
                            if y.abs().sum() > NEGLIGIBLE_HOURLY_DISPATCH_MW * len(
                                    n_results.snapshots):  # Check total sum for year
                                gen_traces_to_add.append(
                                    {'name': c, 'y': y, 'color': get_plot_color(c)})  # Use get_plot_color

            # Prepare storage flows for stacking
            link_flow_data = None
            if not n_results.links.empty and hasattr(n_results.links_t, 'p0'):
                battery_links = n_results.links[n_results.links.carrier == 'battery_link'].index
                if not battery_links.empty:
                    link_flow_data = n_results.links_t.p0[battery_links].sum(axis=1)

            discharge_trace_data = None
            if link_flow_data is not None:
                y_dis = link_flow_data.where(link_flow_data > 0, 0)
                if y_dis.sum() > 0:  # Only add if there is actual discharge
                    discharge_trace_data = {'name': 'discharge', 'y': y_dis,
                                            'color': get_plot_color('discharge')}  # Use get_plot_color

            # Build final traces list in desired bottom-up order for Plotly stacking
            final_stacked_traces = []

            # 1. Add Diesel, Gas, Hydro (base of the stack)
            for c in ['Diesel', 'Gas', 'Hydro']:
                for trace in gen_traces_to_add:
                    if trace['name'] == c:
                        final_stacked_traces.append(trace)
                        break

            # 2. Add Discharge (BESS)
            if discharge_trace_data:
                final_stacked_traces.append(discharge_trace_data)

            # 3. Add Wind, Solar
            for c in ['Wind', 'Solar']:
                for trace in gen_traces_to_add:
                    if trace['name'] == c:
                        final_stacked_traces.append(trace)
                        break

            # 4. Add any other remaining generator types (not in desired_order_bottom_up)
            # Ensure unique addition to prevent duplicates if a carrier appeared earlier
            for trace in gen_traces_to_add:
                if trace['name'] not in desired_order_bottom_up and trace['name'] not in [t['name'] for t in
                                                                                          final_stacked_traces]:
                    final_stacked_traces.append(trace)

            # Add the stacked traces to the figure
            for trace_data in final_stacked_traces:
                fig6_dispatch.add_trace(go.Scatter(
                    x=n_results.snapshots, y=trace_data['y'],
                    name=trace_data['name'], stackgroup='2',
                    mode='none', line=dict(width=0.5, color=trace_data['color']), fillcolor=trace_data['color']
                ))

            # 5. Add Charge (as a separate, negative stackgroup)
            if link_flow_data is not None:
                y_charge = link_flow_data.where(link_flow_data < 0, 0)  # Negative values
                if y_charge.sum() < 0:  # Only add if there is actual charging
                    fig6_dispatch.add_trace(go.Scatter(
                        x=n_results.snapshots, y=y_charge,
                        name='charge', stackgroup='1',
                        mode='none', line=dict(width=0.5, color=get_plot_color('charge')),
                        fillcolor=get_plot_color('charge')  # Use get_plot_color
                    ))

            # 6. Demand Line
            if hasattr(n_results.loads_t, 'p_set'):
                total_demand = n_results.loads_t.p_set.sum(axis=1)
                fig6_dispatch.add_trace(go.Scatter(
                    x=n_results.snapshots, y=total_demand,
                    name='Demand', mode='lines', line=dict(color='black', width=1.5, dash='dot')
                ))

            fig6_dispatch.update_layout(
                title='Hourly Generation Dispatch',
                xaxis_title='Time', yaxis_title='Power (MW)',
                height=600,
                hovermode='x unified'
            )
            st.plotly_chart(fig6_dispatch, use_container_width=True)

    else:
        st.info("Run a simulation first to view results.")

    st.subheader("Download All Results")
    if st.session_state.simulation_results and st.session_state.simulation_results.get('results_path_prefix'):
        results_path_prefix = st.session_state.simulation_results['results_path_prefix']

        zip_base_name = os.path.basename(results_path_prefix)
        zip_archive_name = f"{results_path_prefix}_all_results"

        try:
            shutil.make_archive(zip_archive_name, 'zip', results_path_prefix)
            final_zip_file = f"{zip_archive_name}.zip"

            if os.path.exists(final_zip_file):
                with open(final_zip_file, "rb") as f:
                    st.download_button(
                        label="Download All Results (ZIP)",
                        data=f.read(),
                        file_name=f"{zip_base_name}_all_results.zip",
                        mime="application/zip"
                    )
                st.success("ZIP archive created and ready for download.")
            else:
                st.error(f"Failed to create ZIP archive at {final_zip_file}.")
        except Exception as e:
            st.error(f"Error creating ZIP archive: {e}")
            st.exception(e)

    else:
        st.info("Run a simulation first to enable result downloads.")