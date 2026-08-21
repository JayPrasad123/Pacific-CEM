import streamlit as st
import pandas as pd
import os
import io
import plotly.express as px
import plotly.graph_objects as go
from backend.model_runner import load_network_from_nc, extract_key_metrics, get_renewable_carriers


def show_tab():
    st.title("Compare Simulation Scenarios (.nc Files)")

    st.sidebar.header("Comparison Controls")

    # Initialize session state for loaded networks
    if 'comparison_networks' not in st.session_state:
        st.session_state.comparison_networks = {}  # Stores {scenario_name: pypsa.Network object}
    if 'comparison_uploaded_file_info' not in st.session_state:
        # Stores {original_filename: {'scenario_name': user_given_name, 'file_hash': hash_of_content}}
        st.session_state.comparison_uploaded_file_info = {}

    # --- File Upload Section ---
    st.subheader("Upload NetCDF (.nc) Result Files")
    current_uploaded_files = st.file_uploader(
        "Upload one or more PyPSA NetCDF result files (.nc) to compare.",
        type=["nc"],
        accept_multiple_files=True,
        key="nc_file_uploader",
        help="These files are generated after a successful simulation run."
    )

    current_uploader_file_map = {f.name: f for f in current_uploaded_files}

    files_removed_from_uploader = [
        filename for filename in st.session_state.comparison_uploaded_file_info.keys()
        if filename not in current_uploader_file_map
    ]
    for filename in files_removed_from_uploader:
        scenario_name_to_remove = st.session_state.comparison_uploaded_file_info[filename]['scenario_name']
        if scenario_name_to_remove in st.session_state.comparison_networks:
            del st.session_state.comparison_networks[scenario_name_to_remove]
        del st.session_state.comparison_uploaded_file_info[filename]
        if f"scenario_name_input_{filename}" in st.session_state:
            del st.session_state[f"scenario_name_input_{filename}"]
        st.info(f"Removed '{scenario_name_to_remove}' (original: {filename}) from loaded networks.")

    for uploaded_file in current_uploaded_files:
        original_filename = uploaded_file.name
        file_name_base = os.path.splitext(original_filename)[0]
        file_content = uploaded_file.getvalue()
        file_hash = hash(file_content)

        existing_file_info = st.session_state.comparison_uploaded_file_info.get(original_filename)

        scenario_input_key = f"scenario_name_input_{original_filename}"

        if scenario_input_key not in st.session_state:
            st.session_state[scenario_input_key] = existing_file_info[
                'scenario_name'] if existing_file_info else file_name_base

        scenario_name_from_input = st.text_input(
            f"Scenario Name for '{original_filename}'",
            value=st.session_state[scenario_input_key],
            key=scenario_input_key
        )

        needs_reloading = True
        if existing_file_info and existing_file_info['file_hash'] == file_hash and \
                existing_file_info['scenario_name'] == scenario_name_from_input:
            needs_reloading = False
            # Check if name was changed without file content change (rerun to update dict key)
            if existing_file_info['scenario_name'] != scenario_name_from_input:
                st.rerun()

        if not needs_reloading:
            old_scenario_name = existing_file_info['scenario_name']
            if scenario_name_from_input != old_scenario_name:
                if old_scenario_name in st.session_state.comparison_networks:
                    net_obj = st.session_state.comparison_networks.pop(old_scenario_name)
                    st.session_state.comparison_networks[scenario_name_from_input] = net_obj
                st.session_state.comparison_uploaded_file_info[original_filename][
                    'scenario_name'] = scenario_name_from_input
                st.info(f"Scenario name for '{original_filename}' updated to '{scenario_name_from_input}'.")
                st.rerun()
            continue

        name_collision_detected = False
        for s_name_in_state, n_obj_in_state in st.session_state.comparison_networks.items():
            if s_name_in_state == scenario_name_from_input:
                original_file_for_colliding_name = None
                for k, v in st.session_state.comparison_uploaded_file_info.items():
                    if v['scenario_name'] == s_name_in_state:
                        original_file_for_colliding_name = k
                        break

                if original_file_for_colliding_name != original_filename:
                    name_collision_detected = True
                    st.warning(
                        f"Scenario name '{scenario_name_from_input}' is already used by '{original_file_for_colliding_name}'. Please choose a unique name for '{original_filename}'.")
                    break

        if name_collision_detected:
            continue

        try:
            # Using cache for temp file
            temp_nc_path = os.path.join("cache", f"temp_{original_filename}")
            with open(temp_nc_path, "wb") as f:
                f.write(file_content)

            n = load_network_from_nc(temp_nc_path)
            st.session_state.comparison_networks[scenario_name_from_input] = n
            st.session_state.comparison_uploaded_file_info[original_filename] = {
                'scenario_name': scenario_name_from_input,
                'file_hash': file_hash
            }
            st.success(f"Loaded '{scenario_name_from_input}' from '{original_filename}' successfully.")
            os.remove(temp_nc_path)
            st.rerun()

        except ValueError as e:
            st.error(f"Error loading '{original_filename}': {e}. Please ensure it's a valid PyPSA NetCDF file.")
        except Exception as e:
            st.error(f"An unexpected error occurred loading '{original_filename}': {e}")

    if st.session_state.comparison_networks:
        if st.button("Clear All Loaded Networks", key="clear_networks"):
            st.session_state.comparison_networks = {}
            st.session_state.comparison_uploaded_file_info = {}
            for key in list(st.session_state.keys()):
                if key.startswith("scenario_name_input_"):
                    del st.session_state[key]
            st.success("All loaded networks cleared.")
            st.rerun()

    if not st.session_state.comparison_networks:
        st.info("Please upload NetCDF files to start comparison.")
        return

    st.subheader("Select Scenarios for Comparison")
    all_scenario_names_in_state = list(st.session_state.comparison_networks.keys())

    selected_scenarios = st.sidebar.multiselect(
        "Choose scenarios to compare:",
        options=all_scenario_names_in_state,
        default=all_scenario_names_in_state,
        key="comparison_scenario_selector"
    )

    if not selected_scenarios:
        st.warning("Please select at least one scenario to compare.")
        return

    networks_to_compare = {s_name: st.session_state.comparison_networks[s_name] for s_name in selected_scenarios}

    # --- Numerical Comparison ---
    st.subheader("Numerical Comparison of Key Metrics")

    all_metrics_data = []
    for s_name, n_obj in networks_to_compare.items():
        metrics = extract_key_metrics(n_obj, s_name)
        all_metrics_data.append(metrics)

    df_metrics_raw = pd.DataFrame(all_metrics_data).set_index('Scenario')

    available_scalar_metrics = [col for col in df_metrics_raw.columns if col not in ['Scenario']]
    if available_scalar_metrics:
        selected_scalar_metrics = st.sidebar.multiselect(
            "Select scalar metrics to display:",
            options=available_scalar_metrics,
            default=available_scalar_metrics[:min(5, len(available_scalar_metrics))],
            key="scalar_metric_selector"
        )
        if selected_scalar_metrics:
            st.dataframe(df_metrics_raw[selected_scalar_metrics].T.round(2))
        else:
            st.info("No scalar metrics selected for display.")
    else:
        st.info("No scalar metrics available for comparison.")

    st.markdown("---")