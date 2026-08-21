import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime # Import datetime for current year default

def show_tab():
    st.title("Project Setup & Scenario Configuration")

    def render_status(value, default_value, is_mandatory=False):
        is_missing = value is None or str(value).strip() == ""
        if is_missing:
            if is_mandatory:
                st.error("❌ Required - Missing value.")
            else:
                st.warning("⚠️ Optional - Using default.")
        else:
            if not is_mandatory and value == default_value:
                st.warning("⚠️ Optional - Default set.")
            else:
                st.success("✅ Set")

    st.subheader("Project Details")
    st.session_state.project_data['project_name'] = st.text_input(
        "Project Name",
        value=st.session_state.project_data.get('project_name', "My_PacCEM_Project"),
        help="A name for your current project."
    )

    st.session_state.project_data['results_dir'] = st.text_input(
        "Results Directory (Full Path)",
        value=st.session_state.project_data.get('results_dir', os.path.join(os.getcwd(), "results")),
        help="Enter the full path where results will be saved. E.g., C:/Users/YourName/Documents/PacCEM_Results"
    )
    if st.session_state.project_data['results_dir']:
        if not os.path.exists(st.session_state.project_data['results_dir']):
            st.warning(f"The specified results directory '{st.session_state.project_data['results_dir']}' does not exist. It will be created if a simulation is run.")
        else:
            st.success("Results directory exists.")
    else:
        st.error("Results Directory is mandatory.")


    st.subheader("Scenario Parameters")
    st.session_state.project_data['scenario_name'] = st.text_input(
        "Scenario Name",
        value=st.session_state.project_data.get('scenario_name', "Default_Scenario_1"),
        help="A unique name for this simulation scenario."
    )
    
    st.session_state.project_data['scenario_number'] = st.number_input(
        "Scenario Number",
        value=st.session_state.project_data.get('scenario_number', 1),
        min_value=1,
        step=1,
        help="A numerical identifier for the scenario."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        solver_options = ["highs", "cbc", "glpk", "gurobi"]
        st.session_state.project_data['solver'] = st.selectbox(
            "Solver",
            options=solver_options,
            index=solver_options.index(st.session_state.project_data.get('solver', "highs").lower()) if st.session_state.project_data.get('solver', "highs").lower() in solver_options else 0,
            help="Select the optimization solver to use. (Note: Solvers must be installed separately)."
        )
    with col2:
        st.session_state.project_data['discount_rate_display'] = st.number_input(
            "Discount Rate (%)",
            value=st.session_state.project_data.get('discount_rate_display', 5.0),
            min_value=0.0, max_value=100.0, step=0.1, format="%.1f",
            help="Annual discount rate for annuitizing capital costs."
        )
        st.session_state.project_data['discount_rate'] = st.session_state.project_data['discount_rate_display'] / 100.0

    with col3:
        # Fix 5: Slack Cost configuration with specific label and default
        st.session_state.project_data['slack_cost'] = st.number_input(
            "Value of Lost Load / Slack Cost (USD/MWh)",
            value=st.session_state.project_data.get('slack_cost', 10000.0), # Default to 10000.0 as requested
            min_value=0.0, step=100.0, format="%.1f",
            help="Value of Lost Load (Marginal cost of unmet demand). Set high to avoid unserved energy."
        )

    col4, col5, col6 = st.columns(3)
    with col4:
        co2_cap_display_value = st.session_state.project_data.get('co2_cap_display', 0.0)
        st.session_state.project_data['co2_cap_display'] = st.number_input(
            "CO2 Cap (tons/year, set 0 for none)",
            value=co2_cap_display_value,
            min_value=0.0, step=1000.0, format="%.1f",
            help="Maximum allowed annual CO2 emissions. Set to 0 for no cap."
        )
        if st.session_state.project_data['co2_cap_display'] == 0.0:
            st.session_state.project_data['co2_cap'] = None
        else:
            st.session_state.project_data['co2_cap'] = st.session_state.project_data['co2_cap_display']

    with col5:
        re_share_display_value = st.session_state.project_data.get('re_share_display', 0.0)
        st.session_state.project_data['re_share_display'] = st.number_input(
            "RE Share Target (0-100%, set 0 for none)",
            value=re_share_display_value,
            min_value=0.0, max_value=100.0, step=1.0, format="%.1f",
            help="Minimum percentage of annual electricity demand to be met by renewables. Set to 0 for no target."
        )
        if st.session_state.project_data['re_share_display'] == 0.0:
            st.session_state.project_data['re_share'] = None
        else:
            st.session_state.project_data['re_share'] = st.session_state.project_data['re_share_display'] / 100.0

    with col6:
        st.session_state.project_data['scenario_year'] = st.number_input(
            "Scenario Year",
            value=st.session_state.project_data.get('scenario_year', datetime.now().year),
            min_value=1900, max_value=2100, step=1,
            help="The target year for the simulation scenario. Used for demand scaling and snapshots."
        )
        # --- Add Reserve Margin Input ---
        st.session_state.project_data['reserve_margin_display'] = st.number_input(
            "Reserve Margin (%)",
            value=st.session_state.project_data.get('reserve_margin_display', 15.0),  # Default to 15%
            min_value=0.0, max_value=100.0, step=0.1, format="%.1f",
            help="Percentage of peak demand added as reserve capacity for reliability."
        )
        st.session_state.project_data['reserve_margin'] = st.session_state.project_data['reserve_margin_display'] / 100.0

    # New row for Dispatchable Share and Minimum SOC
    col7, col8 = st.columns(2)
    with col7:
        st.session_state.project_data['dispatchable_share_display'] = st.number_input(
            "Minimum Dispatchable Generation Share (%)",
            value=st.session_state.project_data.get('dispatchable_share_display', 0.0), # Default to 0%
            min_value=0.0, max_value=100.0, step=0.1, format="%.1f",
            help="Minimum percentage of hourly electricity demand that *must* be met by dispatchable generators (e.g., Hydro, Diesel, Gas) or battery discharge."
        )
        # Convert to decimal for backend
        st.session_state.project_data['dispatchable_share'] = st.session_state.project_data['dispatchable_share_display'] / 100.0

    with col8:
        st.session_state.project_data['minimum_soc_display'] = st.number_input(
            "Minimum Battery State of Charge (SOC) (%)",
            value=st.session_state.project_data.get('minimum_soc_display', 0.0), # Default to 0%
            min_value=0.0, max_value=100.0, step=0.1, format="%.1f",
            help="Minimum State of Charge (SOC) that battery energy storage systems (BESS) must maintain (e.g., 10% prevents deep discharge)."
        )
        # Convert to decimal for backend
        st.session_state.project_data['minimum_soc'] = st.session_state.project_data['minimum_soc_display'] / 100.0

        demand_projection_method = st.radio(
            "Choose Demand Projection Method:",
            ("Target Peak Demand", "Percentage Growth"),
            key="demand_projection_method",
            index=0 if st.session_state.project_data.get('demand_projection_method', "Target Peak Demand") == "Target Peak Demand" else 1
        )
        st.session_state.project_data['demand_projection_method'] = demand_projection_method

        if demand_projection_method == "Target Peak Demand":
            st.session_state.project_data['target_peak_demand'] = st.number_input(
                "Target Peak Demand (MW)",
                value=st.session_state.project_data.get('target_peak_demand', 100.0),
                min_value=0.0, step=1.0, format="%.1f",
                help="The peak demand in MW for the scenario year. The base load profile will be scaled to match this peak."
            )
            st.session_state.project_data['demand_growth_percentage'] = None 
        else: # Percentage Growth
            st.session_state.project_data['demand_growth_percentage'] = st.number_input(
                "Annual Demand Growth (%)",
                value=st.session_state.project_data.get('demand_growth_percentage', 2.0),
                min_value=-100.0, step=0.1, format="%.1f",
                help="Annual percentage growth in electricity demand from base year."
            )
            st.session_state.project_data['target_peak_demand'] = None
    
    st.session_state.project_data['line_expansion'] = st.checkbox(
        "Enable Line Expansion",
        value=st.session_state.project_data.get('line_expansion', False),
        help="Allow transmission lines to be expanded in capacity."
    )

    st.session_state.project_data['default_new_gen_extendable'] = st.checkbox(
        "Default: New Generators are Extendable (if not specified in data)",
        value=st.session_state.project_data.get('default_new_gen_extendable', True),
        help="If 'p_nom_extendable' is not specified in the input data for NEW generators (Status = 1), this value will be used."
    )

    st.subheader("Renewable Technologies & Cost Multipliers")
    available_techs = ["Solar", "Wind", "Hydro", "Geothermal", "CNO", "Diesel", "Gas", "Solar Rooftop", "Battery Storage"]
    if 'enabled_techs' not in st.session_state.project_data:
        st.session_state.project_data['enabled_techs'] = {tech: True for tech in available_techs}
        # Ensure newly added tech also has an entry if it wasn't there before
    for tech in available_techs:
        if tech not in st.session_state.project_data['enabled_techs']:
            st.session_state.project_data['enabled_techs'][tech] = True

    cols = st.columns(len(available_techs))
    for i, tech in enumerate(available_techs):
        with cols[i]:
            st.session_state.project_data['enabled_techs'][tech] = st.checkbox(
                tech,
                value=st.session_state.project_data['enabled_techs'].get(tech, True),
                help=f"Enable/Disable {tech} technology for this scenario."
            )

    st.markdown("---")
    st.markdown("Enter cost multipliers for each technology (e.g., 1.0 for no change, 1.2 for 20% increase):")
    if 'tech_cost_multipliers' not in st.session_state.project_data:
        st.session_state.project_data['tech_cost_multipliers'] = {tech.lower(): 1.0 for tech in available_techs}
    # Ensure newly added tech also has a multiplier entry if it wasn't there before
    for tech in available_techs:
        if tech.lower() not in st.session_state.project_data['tech_cost_multipliers']:
            st.session_state.project_data['tech_cost_multipliers'][tech.lower()] = 1.0

    multiplier_cols = st.columns(3)
    for i, tech in enumerate(available_techs):
        with multiplier_cols[i % 3]:
            st.session_state.project_data['tech_cost_multipliers'][tech.lower()] = st.number_input(
                f"{tech} Multiplier",
                value=st.session_state.project_data['tech_cost_multipliers'].get(tech.lower(), 1.0),
                min_value=0.0, step=0.01, format="%.2f",
                key=f"multiplier_{tech}"
            )

    st.subheader("Upload Main Excel Data File")
    uploaded_file = st.file_uploader(
        "Upload your Excel file (e.g., Data.xlsx) containing all network data.",
        type=["xlsx"],
        help="This file should contain separate sheets for buses, generators, loads, etc., as specified in the documentation."
    )

    if uploaded_file is not None:
        try:
            st.session_state.excel_file_buffer = uploaded_file.getvalue()
            st.success("Excel file uploaded successfully.")

            xls = pd.ExcelFile(io.BytesIO(st.session_state.excel_file_buffer))
            st.session_state.excel_sheet_names = xls.sheet_names
            st.info(f"Sheets found: {', '.join(st.session_state.excel_sheet_names)}")

        except Exception as e:
            st.error(f"Error reading Excel file: {e}")
            st.session_state.excel_file_buffer = None
            st.session_state.excel_sheet_names = []
    else:
        st.session_state.excel_file_buffer = None
        st.session_state.excel_sheet_names = []