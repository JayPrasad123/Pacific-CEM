import pandas as pd
import pypsa
from pypsa.optimization.compat import define_constraints, get_var, linexpr
from datetime import datetime
import numpy as np
import os
import ast
import sys
import shutil
import re 
import calendar 
import plotly.graph_objects as go 
import plotly.express as px
import colorsys

# --------------------------
# Helper functions
# --------------------------
def calculate_annuity(capital_cost, interest_rate, lifetime):
    """Convert CAPEX to annuitized annualized cost."""
    if lifetime <= 0:  # Robustness check
        return capital_cost
    if interest_rate == 0:
        return capital_cost / lifetime
    return (capital_cost * interest_rate) / (1 - (1 + interest_rate) ** -lifetime)

def apply_cost_multiplier(carrier, base_capex, multipliers):
    """
    Scale the base CAPEX (from Excel) with tech-specific multipliers.
    Fallback to 1.0 if carrier not in multipliers.
    """
    key = carrier.lower()
    factor = multipliers.get(key, 1.0)
    return base_capex * factor


def get_renewable_carriers():
    """Define which carriers are considered renewable energy sources"""
    return ["Solar", "Solar Rooftop", "Wind", "Geothermal", "CNO", "Hydro", "Bio Power- CNO"]

# --- START OF FIX: Add get_dispatchable_carriers function ---
def get_dispatchable_carriers():
    """Define which carriers are considered dispatchable sources (firm capacity).
    These can provide power on demand: Hydro, BESS (battery_link), Diesel, Gas"""
    # Note: 'battery_link' is a PyPSA Link carrier, so its power contribution is retrieved from links_t.p
    # The actual carriers providing generation that could be dispatchable are listed here.
    return ["Hydro", "Diesel", "Gas", "Bio Power- CNO", "Geothermal"] # Added Bio Power- CNO, Geothermal as they can be firm
# --- END OF FIX ---

def safe_add_carrier(n, name, **kw):
    """Adds a carrier if it doesn't already exist."""
    if name not in n.carriers.index:
        n.add("Carrier", name, **kw)

# --- START OF FIX: Define color utilities locally within model_runner.py ---
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

# This is the master color map for all HTML outputs
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

def generate_input_summary(project_data, data_mapping_mode, mapped_data, output_path):
    """Generates a markdown summary of all simulation inputs."""
    scenario_name = project_data.get('scenario_name', 'Unnamed_Scenario')
    content = []

    # --- Header ---
    content.append("# PacCEM Simulation Input Summary")
    content.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    content.append("---")

    # --- Project Tab ---
    content.append("\n## 1. Project Tab Inputs\n")
    content.append(f"- **Project Name:** {project_data.get('project_name', 'N/A')}")
    content.append(f"- **Results Directory:** `{project_data.get('results_dir', 'N/A')}`")
    content.append(f"- **Scenario Name:** {scenario_name}")
    content.append(f"- **Scenario Number:** {project_data.get('scenario_number', 'N/A')}")
    content.append(f"- **Solver:** {project_data.get('solver', 'N/A')}")
    content.append(f"- **Discount Rate:** {project_data.get('discount_rate_display', 0.0)}%")
    content.append(f"- **Slack Cost:** {project_data.get('slack_cost', 0.0)} USD/MWh")
    content.append(f"- **CO2 Cap:** {project_data.get('co2_cap_display', 0.0)} tons/year")
    content.append(f"- **RE Share Target:** {project_data.get('re_share_display', 0.0)}%")
    content.append(f"- **Scenario Year:** {project_data.get('scenario_year', 'N/A')}")
    content.append(f"- **Reserve Margin:** {project_data.get('reserve_margin_display', 0.0)}%")
    content.append(f"- **Minimum Dispatchable Generation Share:** {project_data.get('dispatchable_share_display', 0.0)}%")
    content.append(f"- **Minimum Battery SOC:** {project_data.get('minimum_soc_display', 0.0)}%")

    demand_method = project_data.get('demand_projection_method', 'N/A')
    content.append(f"- **Demand Scaling Method:** {demand_method}")
    if demand_method == "Target Peak Demand":
        content.append(f"  - **Target Peak Demand:** {project_data.get('target_peak_demand', 'N/A')} MW")
    else:  # Percentage Growth
        content.append(f"  - **Annual Demand Growth (%):** {project_data.get('demand_growth_percentage', 'N/A')}")

    content.append(f"- **Enable Line Expansion:** {project_data.get('line_expansion', False)}")
    content.append(
        f"- **Default: New Generators are Extendable:** {project_data.get('default_new_gen_extendable', False)}")

    enabled_techs_data = project_data.get('enabled_techs', {})
    enabled_list = [tech for tech, is_enabled in enabled_techs_data.items() if is_enabled]
    disabled_list = [tech for tech, is_enabled in enabled_techs_data.items() if not is_enabled]
    content.append("- **Enabled Technologies:**")
    content.append(f"  - Enabled: {', '.join(enabled_list) if enabled_list else 'None'}")
    content.append(f"  - Disabled: {', '.join(disabled_list) if disabled_list else 'None'}")

    multipliers = project_data.get('tech_cost_multipliers', {})
    content.append("- **Technology Cost Multipliers:**")
    for tech, mult in multipliers.items():
        content.append(f"  - {tech.title()}: {mult:.2f}")

    content.append("\n---")

    # --- Data Mapping Tab ---
    content.append("\n## 2. Data Mapping Tab Inputs\n")

    component_types = [
        "buses", "demand", "generators", "transmission_lines",
        "transformers", "storage", "generation_profiles"
    ]

    for comp_type in component_types:
        comp_title = comp_type.replace('_', ' ').title()
        # Fix 2: Rename Load Data
        if comp_type == "demand": comp_title = "Load Data" 
        content.append(f"### {comp_title}\n")

        mode = data_mapping_mode.get(comp_type, "N/A")
        content.append(f"- **Input Mode:** {mode}")

        if mode == "Excel Mapping":
            comp_map_data = mapped_data.get(comp_type, {})
            sheet_name = comp_map_data.get('sheet_name', 'Not Selected')
            content.append(f"- **Selected Sheet:** `{sheet_name}`")
            content.append("- **Column Mappings:**")

            if comp_type == "demand":
                content.append(
                    "  - (All numeric columns in the sheet are treated as load profiles for different buses)")
            else:
                mappings_found = False
                for pac_col, excel_col in comp_map_data.items():
                    if pac_col not in ['sheet_name', 'df_content']:
                        content.append(f"  - `{pac_col}` mapped to `{excel_col}`")
                        mappings_found = True
                if not mappings_found:
                    content.append("  - (No columns mapped)")
        content.append("")  # Add a blank line for spacing

    # --- Write to file ---
    full_path = os.path.join(output_path, f"input_summary_{scenario_name}.md")
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))

    return f"Input summary saved to {full_path}"


# --------------------------
# Comparison Tab Helper Functions
# --------------------------

def load_network_from_nc(file_path):
    """Loads a PyPSA network from a NetCDF file."""
    try:
        n = pypsa.Network(file_path)
        return n
    except Exception as e:
        raise ValueError(f"Failed to load network from {file_path}: {e}")


def extract_key_metrics(n, scenario_name):
    """Extracts a predefined set of key scalar metrics from a PyPSA network."""
    
    # Fix 4: Thresholds for filtering slack in numerical results
    NEGLIGIBLE_SLACK_GENERATION_MWh = 0.001 # If total slack generation is less than 1 Wh, it's negligible
    NEGLIGIBLE_SLACK_CAPACITY_MW = 0.01 # If total slack capacity is less than 10 kW, it's negligible
    NEGLIGIBLE_SLACK_COST_USD = 1.0 # If total slack cost is less than 1 USD, it's negligible

    metrics = {
        'Scenario': scenario_name,
        'Total System Cost (USD)': n.objective if n.objective is not None else np.nan,
    }

    # Determine if slack is contributing (based on total generation)
    total_slack_gen_mwh = n.generators_t.p['slack'].sum() if 'slack' in n.generators.index and 'slack' in n.generators_t.p.columns and not n.generators_t.p.empty else 0
    is_slack_contributing = abs(total_slack_gen_mwh) > NEGLIGIBLE_SLACK_GENERATION_MWh

    # Installed Capacity (filter slack based on contributing flag)
    total_gen_cap = n.generators.p_nom_opt.sum() if not n.generators.empty else 0
    if 'slack' in n.generators.index and not is_slack_contributing: # Only subtract if slack exists but doesn't contribute
        total_gen_cap -= n.generators.loc['slack', 'p_nom_opt'] 
    metrics['Total Generation Capacity (MW)'] = total_gen_cap
    
    metrics['Total Storage Capacity (MWh)'] = n.stores.e_nom_opt.sum() if not n.stores.empty else 0
    metrics['Total Line Capacity (MVA)'] = n.lines.s_nom_opt.sum() if not n.lines.empty else 0

    # Annual Generation (filter slack based on contributing flag)
    total_annual_gen_mwh = n.generators_t.p.sum().sum() if not n.generators_t.p.empty else 0
    if 'slack' in n.generators.index and not n.generators_t.p.empty and 'slack' in n.generators_t.p.columns and not is_slack_contributing:
        total_annual_gen_mwh -= n.generators_t.p['slack'].sum()
    metrics['Total Annual Generation (GWh)'] = total_annual_gen_mwh / 1e3


    metrics['Total Annual Renewable Generation (GWh)'] = n.generators_t.p.loc[:, n.generators.carrier.isin(
        get_renewable_carriers())].sum().sum() / 1e3 if not n.generators_t.p.empty else 0
    metrics['Total Annual Demand (GWh)'] = n.loads_t.p_set.sum().sum() / 1e3 if not n.loads_t.p_set.empty else 0

    # Emissions & RE Share
    total_co2_emissions_tons = (n.generators_t.p.sum().groupby(
        n.generators.carrier).sum() * n.carriers.co2_emissions).sum() if not n.generators_t.p.empty and 'co2_emissions' in n.carriers.columns else 0
    metrics['Total Annual CO2 Emissions (tons)'] = total_co2_emissions_tons
    
    # Calculate RE Share
    if metrics['Total Annual Demand (GWh)'] > 0:
        metrics['Achieved RE Share (%)'] = (metrics['Total Annual Renewable Generation (GWh)'] / metrics[
            'Total Annual Demand (GWh)']) * 100
    else:
        metrics['Achieved RE Share (%)'] = 0

    # Calculate LCOE
    LCOE = np.nan
    if not np.isnan(metrics['Total System Cost (USD)']) and metrics['Total Annual Generation (GWh)'] > 0:
        LCOE = (metrics['Total System Cost (USD)'] / (metrics['Total Annual Generation (GWh)'] * 1000))
    metrics['LCOE (USD/MWh)'] = LCOE

    # Add capacity by carrier breakdown (filter slack)
    if not n.generators.empty:
        cap_by_carrier = n.generators.groupby('carrier').p_nom_opt.sum()
        for carrier, capacity in cap_by_carrier.items():
            if carrier == 'slack' and not is_slack_contributing: continue # Skip if slack not contributing
            metrics[f'Capacity {carrier.title()} (MW)'] = capacity

    # Add generation by carrier breakdown (filter slack)
    if not n.generators_t.p.empty:
        gen_by_carrier = n.generators_t.p.sum().groupby(n.generators.carrier).sum() / 1e3
        for carrier, generation in gen_by_carrier.items():
            if carrier == 'slack' and not is_slack_contributing: continue # Skip if slack not contributing
            metrics[f'Generation {carrier.title()} (GWh)'] = generation

    return metrics


# --------------------------
# Plotting Function (Replicates GUI Visuals for HTML Export)
# --------------------------
def create_plots(n, run_folder, scenario_name, scenario_year): 
    """
    Create HTML plots from the network `n`, matching GUI visuals.
    Saves HTML files to run_folder / "plots".
    """
    plot_folder = os.path.join(run_folder, "plots")
    os.makedirs(plot_folder, exist_ok=True)
    safe_scenario_name = re.sub(r'[^\w\-_\.]', '_', scenario_name)

    # Fix 4: Thresholds for filtering slack in plots
    NEGLIGIBLE_HOURLY_DISPATCH_MW = 0.001 # If hourly slack generation is less than 1W, it's negligible for plot traces
    NEGLIGIBLE_SLACK_GENERATION_MWh_TOTAL = 0.001 # For sum checks
    NEGLIGIBLE_SLACK_CAPACITY_MW = 0.01 
    NEGLIGIBLE_SLACK_COST_USD = 1.0 

    # 1. Color Map (Matches GUI)
    colours = {
        'diesel': 'brown',
        'solar': 'yellow',
        'wind': 'green',
        'hydro': 'blue',
        'slack': 'grey',
        'gas': 'orange',
        'charge': 'pink',      
        'discharge': '#5d4e29',
        'cno': '#6A3D9A',
        'solar rooftop': 'lightgoldenrodyellow',
        'geothermal': '#CAB2D6',
        'bio power- cno': '#6A3D9A',
        'battery storage': 'purple'
    }
    def get_col(c): return colours.get(str(c).lower(), 'grey')

    # Determine if slack is contributing (based on total generation)
    total_slack_gen_mwh_total = n.generators_t.p['slack'].sum() if 'slack' in n.generators.index and 'slack' in n.generators_t.p.columns and not n.generators_t.p.empty else 0
    is_slack_contributing_for_plots = abs(total_slack_gen_mwh_total) > NEGLIGIBLE_SLACK_GENERATION_MWh_TOTAL

    # Data for plots (recalculated to filter slack based on contributing flag)
    # ----------------------------------------------------------------------
    installed_capacity_base = n.generators.groupby('carrier').p_nom_opt.sum() if not n.generators.empty else pd.Series()
    if 'slack' in installed_capacity_base.index and not is_slack_contributing_for_plots:
        installed_capacity_filtered = installed_capacity_base.drop('slack')
    else:
        installed_capacity_filtered = installed_capacity_base.copy()

    total_generation_base_GWh = n.generators_t.p.sum().groupby(n.generators.carrier).sum() / 1e3 if not n.generators_t.p.empty else pd.Series()
    if 'slack' in total_generation_base_GWh.index and not is_slack_contributing_for_plots:
        total_generation_filtered_GWh = total_generation_base_GWh.drop('slack')
    else:
        total_generation_filtered_GWh = total_generation_base_GWh.copy()

    total_annual_demand_MWh = n.loads_t.p_set.sum().sum() if not n.loads_t.p_set.empty else 0
    renewable_generation_MWh = n.generators_t.p.loc[:, n.generators.carrier.isin(get_renewable_carriers())].sum().sum() if not n.generators_t.p.empty else 0

    # 1. Optimal Generation Capacity (Bar Chart)
    try:
        if not installed_capacity_filtered.empty:
            df_capacity_plot = installed_capacity_filtered.reset_index(name='Capacity (MW)')

            # Add Storage Capacity to this plot for consistency with GUI (if available)
            if not n.stores.empty:
                store_cap = n.stores.e_nom_opt.sum()
                if store_cap > 0:
                    df_capacity_plot = pd.concat(
                        [df_capacity_plot, pd.DataFrame([{'carrier': 'Battery Storage', 'Capacity (MW)': store_cap}])],
                        ignore_index=True)

            # --- START OF FIX: Rename capacity column and update plot labels ---
            df_capacity_plot['carrier'] = df_capacity_plot[
                'carrier'].str.lower()  # Ensure lowercase for color matching

            fig = px.bar(df_capacity_plot, x='carrier', y='Capacity (MW)', # Keep y-field as 'Capacity (MW)'
                         title=f'Optimal Installed Capacity by Carrier - {scenario_name}',
                         labels={'carrier': 'Carrier', 'Capacity (MW)': 'Capacity (MW for Gen. / MWh for Storage)'}, # Updated label
                         color='carrier',
                         color_discrete_map=colours)
            fig.update_layout(xaxis_title='Carrier', yaxis_title='Capacity (MW for Gen. / MWh for Storage)', template='simple_white') # Updated axis title
            # --- END OF FIX ---
            fig.write_html(os.path.join(plot_folder, f"1_Optimal_Capacity_Scenario_{safe_scenario_name}.html"))
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Saved '1_Optimal_Capacity_Scenario_{safe_scenario_name}.html'")
    except Exception as e:
        print(f"Optimal Capacity plot failed: {e}")

    # 2a. Capacity Mix (Pie Chart)
    try:
        if not installed_capacity_filtered.empty:
            df_capacity_mix = installed_capacity_filtered.reset_index(name='Capacity (MW)')
            # Add Storage Capacity for pie chart
            if not n.stores.empty:
                store_cap = n.stores.e_nom_opt.sum()
                if store_cap > 0:
                    df_capacity_mix = pd.concat([df_capacity_mix, pd.DataFrame(
                        [{'carrier': 'Battery Storage', 'Capacity (MW)': store_cap}])], ignore_index=True)

            # --- START OF FIX: Rename capacity column and update plot labels ---
            # For pie chart, the 'values' field does not have an explicit unit label on the chart itself,
            # but the numerical values represent MW or MWh depending on the carrier.
            fig_cap_mix = px.pie(df_capacity_mix, values='Capacity (MW)', names='carrier', # Keep values field as 'Capacity (MW)'
                                 title=f'Optimized Capacity Mix (MW for Gen. / MWh for Storage) - {scenario_name}', hole=0.3, # Update title for clarity
                                 color='carrier',
                                 color_discrete_map=colours)
            # --- END OF FIX ---
            fig_cap_mix.update_layout(template='simple_white')
            fig_cap_mix.write_html(os.path.join(plot_folder, f"2a_Capacity_Mix_Scenario_{safe_scenario_name}.html"))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved '2a_Capacity_Mix_Scenario_{safe_scenario_name}.html'")
    except Exception as e:
        print(f"Capacity Mix plot failed: {e}")

    # 2b. Annual Generation Share (Pie Chart)
    try:
        if not total_generation_filtered_GWh.empty:
            df_generation_mix = total_generation_filtered_GWh.reset_index(name='Generation (GWh/year)')

            # --- START OF FIX: Ensure carrier names are lowercase for matching with 'colours' dict ---
            df_generation_mix['carrier'] = df_generation_mix['carrier'].str.lower()
            # --- END OF FIX ---

            fig_gen_mix = px.pie(df_generation_mix, values='Generation (GWh/year)', names='carrier',
                                         title=f'Annual Generation Share - {scenario_name}', hole=0.3,
                                         color='carrier',
                                         color_discrete_map=colours)
            fig_gen_mix.update_layout(template='simple_white')
            fig_gen_mix.write_html(
                os.path.join(plot_folder, f"2b_Generation_Mix_Scenario_{safe_scenario_name}.html"))
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Saved '2b_Generation_Mix_Scenario_{safe_scenario_name}.html'")
    except Exception as e:
        print(f"Generation Mix plot failed: {e}")


    # 3a. Annual System Cost Breakdown - By Cost Type (Bar Chart)
    try:
        # Calculate cost components (similar to simulation_tab.py logic)
        gen_capital_cost = (n.generators.capital_cost * n.generators.p_nom_opt).sum() if not n.generators.empty else 0
        gen_fixed_operation_cost = (n.generators.fixed_cost * n.generators.p_nom_opt).sum() if not n.generators.empty and 'fixed_cost' in n.generators.columns else 0
        total_marginal_cost_sum = (n.generators_t.p.sum() * n.generators.marginal_cost).sum() if not n.generators_t.p.empty else 0 # sum of hourly dispatch * marginal_cost

        store_capital_cost = (n.stores.capital_cost * n.stores.e_nom_opt).sum() if not n.stores.empty else 0
        link_capital_cost = (n.links.capital_cost * n.links.p_nom_opt).sum() if not n.links.empty else 0
        line_capital_cost = (n.lines.capital_cost * n.lines.s_nom_opt).sum() if not n.lines.empty else 0
        transformer_capital_cost = (n.transformers.capital_cost * n.transformers.s_nom).sum() if not n.transformers.empty else 0
        
        slack_cost_value = 0
        if 'slack' in n.generators.index and not n.generators_t.p.empty and 'slack' in n.generators_t.p.columns:
            slack_cost_value = (n.generators_t.p['slack'] * n.generators.loc['slack', 'marginal_cost']).sum()

        calculated_costs = {
            'Generator Capital (USD/year)': gen_capital_cost,
            'Generator Fixed O&M (USD/year)': gen_fixed_operation_cost,
            'Generator Variable (USD/year)': total_marginal_cost_sum,
            'Storage Capital (USD/year)': store_capital_cost,
            'Link Capital (USD/year)': link_capital_cost,
            'Line Capital (USD/year)': line_capital_cost,
            'Transformer Capital (USD/year)': transformer_capital_cost,
            'Slack Cost (USD/year)': slack_cost_value
        }
        
        df_costs_breakdown = pd.DataFrame(list(calculated_costs.items()), columns=['Cost Type', 'Amount (USD/year)'])
        df_costs_breakdown = df_costs_breakdown[df_costs_breakdown['Amount (USD/year)'] > 0] # Filter rows where amount is 0

        # Fix 4: Filter Slack Cost if negligible (based on total cost contribution)
        if 'Slack Cost (USD/year)' in df_costs_breakdown['Cost Type'].values and not is_slack_contributing_for_plots:
            df_costs_breakdown = df_costs_breakdown[df_costs_breakdown['Cost Type'] != 'Slack Cost (USD/year)']


        if not df_costs_breakdown.empty:
            fig_costs = px.bar(df_costs_breakdown, x='Cost Type', y='Amount (USD/year)',
                               title=f'Annual System Cost Breakdown - By Cost Type - {scenario_name}', 
                               labels={'Amount (USD/year)': 'Amount (USD/year)', 'Cost Type': 'Cost Category'},
                               color='Cost Type',
                               color_discrete_map={ # Specific colors from GUI for consistency
                                          'Generator Capital (USD/year)': '#ADD8E6', 
                                          'Generator Fixed O&M (USD/year)': '#90EE90', 
                                          'Generator Variable (USD/year)': '#FFB6C1', 
                                          'Storage Capital (USD/year)': 'purple',
                                          'Link Capital (USD/year)': 'darkmagenta',
                                          'Line Capital (USD/year)': 'darkgray',
                                          'Transformer Capital (USD/year)': 'dimgray',
                                          'Slack Cost (USD/year)': 'red' 
                                      })
            fig_costs.update_layout(xaxis_title='Cost Category', yaxis_title='Annual Cost (USD/year)', template='simple_white')
            fig_costs.write_html(os.path.join(plot_folder, f"3a_System_Costs_By_Type_Scenario_{safe_scenario_name}.html"))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved '3a_System_Costs_By_Type_Scenario_{safe_scenario_name}.html'")
        else:
            print("System cost by type plot skipped: No significant cost components found.")
    except Exception as e:
        print(f"System cost by type plot failed: {e}")

    # 3b. Annual System Cost Breakdown - By Generator Carrier (Stacked CAPEX/OPEX Bar Chart & CSV)
    try:
        if not n.generators.empty and not n.generators_t.p.empty:
            df_gen_costs = n.generators.copy()
            df_gen_costs['annual_capital_cost'] = df_gen_costs['capital_cost'] * df_gen_costs['p_nom_opt']
            df_gen_costs['annual_fixed_om_cost'] = df_gen_costs.get('fixed_cost', 0) * df_gen_costs['p_nom_opt']

            gen_annual_dispatch_MWh_sum = n.generators_t.p.sum()  # Total MWh dispatched per generator
            df_gen_costs['annual_variable_cost'] = gen_annual_dispatch_MWh_sum * df_gen_costs['marginal_cost']

            # Calculate total annual O&M cost for stacking
            df_gen_costs['annual_om_cost'] = df_gen_costs['annual_fixed_om_cost'] + df_gen_costs['annual_variable_cost']

            # Aggregate CAPEX and OPEX by carrier
            df_costs_by_carrier_aggregated = df_gen_costs.groupby('carrier')[
                ['annual_capital_cost', 'annual_om_cost']].sum().reset_index()

            # Fix 4: Hide slack if cost is negligible (based on total cost contribution)
            if 'slack' in df_costs_by_carrier_aggregated['carrier'].values and not is_slack_contributing_for_plots:
                df_costs_by_carrier_aggregated = df_costs_by_carrier_aggregated[
                    df_costs_by_carrier_aggregated['carrier'] != 'slack']

            # Filter out any carriers with negligible CAPEX and OPEX (after potential slack removal)
            df_costs_by_carrier_aggregated = df_costs_by_carrier_aggregated[
                (df_costs_by_carrier_aggregated['annual_capital_cost'].abs() > NEGLIGIBLE_SLACK_COST_USD) |
                (df_costs_by_carrier_aggregated['annual_om_cost'].abs() > NEGLIGIBLE_SLACK_COST_USD)
                ].copy()

            # --- Data for Stacked Plot ---
            df_costs_melted = df_costs_by_carrier_aggregated.melt(id_vars='carrier',
                                                                  value_vars=['annual_capital_cost', 'annual_om_cost'],
                                                                  var_name='Cost Type',
                                                                  value_name='Amount (USD/year)')

            # Ensure carrier names are lowercase for matching with 'colours' dict
            df_costs_melted['carrier_lower'] = df_costs_melted['carrier'].str.lower()

            # Create a custom color map for stacking
            stacked_colors_map = {}
            for carr_name in df_costs_by_carrier_aggregated['carrier'].unique():
                carr_name_lower = carr_name.lower()
                base_color = colours.get(carr_name_lower, 'grey')  # Get base color

                # Define colors for CAPEX and OPEX for this carrier
                stacked_colors_map[f'annual_capital_cost_{carr_name_lower}'] = lighten_color(base_color,
                                                                                             factor=0.6)  # Lighter for CAPEX
                stacked_colors_map[f'annual_om_cost_{carr_name_lower}'] = base_color  # Original for O&M

            # Assign a 'color_group' for Plotly to use for color mapping
            df_costs_melted['color_group'] = df_costs_melted['Cost Type'] + '_' + df_costs_melted['carrier_lower']

            fig3_carrier = px.bar(df_costs_melted,
                                  x='carrier',
                                  y='Amount (USD/year)',
                                  color='color_group',  # Use the combined key for coloring
                                  color_discrete_map=stacked_colors_map,  # Apply the custom map
                                  title=f'Annual System Cost by Generator Carrier (CAPEX vs OPEX) - {scenario_name}',
                                  labels={'carrier': 'Carrier', 'Amount (USD/year)': 'Amount (USD/year)',
                                          'Cost Type': 'Cost Category'},
                                  category_orders={'Cost Type': ['annual_capital_cost', 'annual_om_cost']},
                                  # Ensure consistent stacking order
                                  barmode='stack')
            fig3_carrier.update_layout(xaxis_title='Carrier', yaxis_title='Annual Cost (USD/year)',
                                       template='simple_white')
            fig3_carrier.write_html(
                os.path.join(plot_folder, f"3b_System_Costs_By_Carrier_Scenario_{safe_scenario_name}.html"))
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Saved '3b_System_Costs_By_Carrier_Scenario_{safe_scenario_name}.html'")

        else:
            print("System cost by carrier plot skipped: No generator carrier costs found for plotting.")
    except Exception as e:
        print(f"System cost by carrier plot failed: {e}")

    # --- START OF FIX: Calculate LCOE by Carrier and save to CSV (moved here for plotting) ---
    # Fix: LCOE by Carrier Calculation
    NEGLIGIBLE_SLACK_GENERATION_MWh_TOTAL = 0.001
    NEGLIGIBLE_SLACK_CAPACITY_MW = 0.01
    NEGLIGIBLE_SLACK_COST_USD = 1.0
    NEGLIGIBLE_GENERATION_MWh_FOR_LCOE = 0.001  # If total generation is less than 1 Wh, LCOE is not meaningful

    lcoe_by_carrier_data = []

    # Get CAPEX and OPEX using PyPSA's statistics functions for all components
    all_capex_stats = n.statistics.capex()
    all_opex_stats = n.statistics.opex()

    if not n.generators.empty:
        all_gen_carriers = n.generators.carrier.fillna('unknown').unique()

        for carrier in all_gen_carriers:
            if carrier == 'slack' and not is_slack_contributing_for_plots:
                continue

            carrier_generator_indices = n.generators[n.generators.carrier == carrier].index
            total_carrier_gen_mwh = 0.0
            if not n.generators_t.p.empty and not carrier_generator_indices.empty:
                relevant_dispatch_columns = carrier_generator_indices.intersection(n.generators_t.p.columns)
                if not relevant_dispatch_columns.empty:
                    total_carrier_gen_mwh = n.generators_t.p[relevant_dispatch_columns].sum().sum()

            carrier_capex_sum = all_capex_stats.get(('Generator', carrier), 0.0)
            carrier_opex_sum = all_opex_stats.get(('Generator', carrier), 0.0)

            # --- Calculate Levelized CAPEX and Levelized OPEX ---
            levelized_capex_value = 0.0
            levelized_opex_value = 0.0
            lcoe_value = 0.0

            if abs(total_carrier_gen_mwh) > NEGLIGIBLE_GENERATION_MWh_FOR_LCOE:
                levelized_capex_value = carrier_capex_sum / total_carrier_gen_mwh
                levelized_opex_value = carrier_opex_sum / total_carrier_gen_mwh
                lcoe_value = levelized_capex_value + levelized_opex_value

            # Filter out entries where LCOE is 0 due to 0 costs and 0 generation,
            # but keep if there's generation with 0 cost (e.g., existing hydro with no remaining capital)
            if abs(lcoe_value) > 1e-6 or (abs(carrier_capex_sum) > 1e-6 or abs(carrier_opex_sum) > 1e-6) or abs(total_carrier_gen_mwh) > 1e-6:
                lcoe_by_carrier_data.append({
                    'Carrier': carrier,
                    'Levelized CAPEX (USD/MWh)': levelized_capex_value, # New column for stacked plot
                    'Levelized OPEX (USD/MWh)': levelized_opex_value,   # New column for stacked plot
                    'Total Annual CAPEX (USD/year)': carrier_capex_sum, # Keep for context in CSV
                    'Total Annual OPEX (USD/year)': carrier_opex_sum,   # Keep for context in CSV
                    'Generation (MWh/year)': total_carrier_gen_mwh,
                    'LCOE (USD/MWh)': lcoe_value # Total LCOE per carrier
                })

    df_lcoe_by_carrier = pd.DataFrame(lcoe_by_carrier_data)
    # --- END OF FIX ---

    # Save LCOE by Carrier data to CSV
    if not df_lcoe_by_carrier.empty:
        lcoe_csv_path = os.path.join(run_folder, "csv_outputs", f"lcoe_by_carrier_{safe_scenario_name}.csv")
        df_lcoe_by_carrier.to_csv(lcoe_csv_path, index=False)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Saved 'lcoe_by_carrier_{safe_scenario_name}.csv' to csv_outputs folder.")
    else:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] LCOE by carrier CSV skipped: No significant LCOE data to save.")
    # --- END OF FIX: Calculate LCOE by Carrier and save to CSV ---

    # 4. LCOE by Carrier Plot (Bar Chart)
    try:
        if not df_lcoe_by_carrier.empty:
            df_lcoe_plot_data = df_lcoe_by_carrier.copy()
            # Ensure carrier names are lowercase for matching with 'colours' dict
            df_lcoe_plot_data['Carrier'] = df_lcoe_plot_data['Carrier'].str.lower()

            # --- START OF FIX: Prepare data for single stacked LCOE bar chart ---
            # Sort by LCOE value (descending) to get largest at bottom for stacking
            df_lcoe_plot_data = df_lcoe_plot_data.sort_values(by='LCOE (USD/MWh)', ascending=False).copy()

            # Filter out entries where LCOE is zero/negligible to avoid flat segments
            df_lcoe_plot_data = df_lcoe_plot_data[df_lcoe_plot_data['LCOE (USD/MWh)'].abs() > 1e-6].copy()

            # Add a common category for the x-axis to create a single stacked bar
            df_lcoe_plot_data['X-axis Category'] = 'Total LCOE (USD/MWh)' # Common category for the x-axis

            fig_lcoe = px.bar(df_lcoe_plot_data,
                              x='X-axis Category', # Use the new common category for X-axis
                              y='LCOE (USD/MWh)',      # Y-axis is the individual LCOE
                              color='Carrier',          # Color by Carrier
                              color_discrete_map=colours, # Apply the base colors
                              title=f'Sum of Individual LCOEs by Technology Type - {scenario_name}',
                              labels={'X-axis Category': 'LCOE (USD/MWh)', 'LCOE (USD/MWh)': 'LCOE (USD/MWh)'}, # Clearer labels
                              barmode='stack') # Crucial for stacked bar chart

            # Add Total Sum of Individual LCOEs as text label on top of the bar
            total_sum_individual_lcoes = df_lcoe_plot_data['LCOE (USD/MWh)'].sum()
            if total_sum_individual_lcoes > 0:
                fig_lcoe.add_trace(go.Scatter(
                    x=['Total LCOE (USD/MWh)'], y=[total_sum_individual_lcoes], # Position at top of stack
                    mode='text',
                    text=[f"{total_sum_individual_lcoes:.2f} $/MWh"], # Display the total sum
                    textposition='top center',
                    showlegend=False,
                    textfont=dict(color="white", size=10) # Adjust text color/size as needed
                ))
            # --- END OF FIX ---

            fig_lcoe.update_layout(xaxis_title='', yaxis_title='LCOE (USD/MWh)', template='simple_white')
            fig_lcoe.write_html(os.path.join(plot_folder, f"4_LCOE_By_Carrier_Scenario_{safe_scenario_name}.html"))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved '4_LCOE_By_Carrier_Scenario_{safe_scenario_name}.html'")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] LCOE by Carrier plot skipped: No significant LCOE data to plot.")
    except Exception as e:
        print(f"LCOE by Carrier plot failed: {e}")
    # --- END OF FIX ---

    # --- START OF FIX: Capacity Factor Plot (Bar Chart) ---
    # 5. Capacity Factor Plot (Bar Chart)
    try:
        if not n.generators.empty:
            # Calculate capacity factor
            df_cf = n.statistics.capacity_factor()

            # Convert series to DataFrame and process (Component, Carrier)
            df_cf = df_cf.reset_index()
            df_cf.columns = ['Component', 'Carrier', 'Capacity Factor']

            # Filter only generators and drop slack if not contributing
            df_cf_generators = df_cf[df_cf['Component'] == 'Generator'].copy()

            # Fix 4: Filter slack from Capacity Factor plot if not contributing
            # Use the already determined 'is_slack_contributing_for_plots' from above
            if 'slack' in df_cf_generators['Carrier'].values and not is_slack_contributing_for_plots:
                df_cf_generators = df_cf_generators[df_cf_generators['Carrier'] != 'slack']

            # Ensure carrier names are lowercase for matching with 'colours' dict
            df_cf_generators['Carrier'] = df_cf_generators['Carrier'].str.lower()

            # Save Capacity Factor data to CSV
            cf_csv_path = os.path.join(run_folder, "csv_outputs",
                                       f"capacity_factor_by_carrier_{safe_scenario_name}.csv")
            df_cf_generators[['Carrier', 'Capacity Factor']].to_csv(cf_csv_path, index=False)
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Saved 'capacity_factor_by_carrier_{safe_scenario_name}.csv' to csv_outputs folder.")

            fig_cf = px.bar(df_cf_generators, x='Carrier', y='Capacity Factor',
                            title=f'Capacity Factor by Generator Carrier - {scenario_name}',
                            labels={'Carrier': 'Carrier', 'Capacity Factor': 'Capacity Factor (0-1)'},
                            color='Carrier',  # Color by carrier
                            color_discrete_map=colours,  # Use the general colours
                            range_y=[0, 1])  # Capacity factor is between 0 and 1
            fig_cf.update_layout(template='simple_white')
            fig_cf.write_html(os.path.join(plot_folder, f"5_Capacity_Factor_Scenario_{safe_scenario_name}.html"))
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Saved '5_Capacity_Factor_Scenario_{safe_scenario_name}.html'")
        else:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Capacity Factor plot skipped: No generator data available.")
    except Exception as e:
        print(f"Capacity Factor plot failed: {e}")
    # --- END OF FIX ---

    # 6a. Storage State of Charge (Line Chart)
    try:
        if not n.stores.empty:
            total_soc_t = n.stores_t.e.sum(axis=1) / 1000  # Convert to GWh
            fig_soc = px.line(total_soc_t, title=f'Total System Storage State of Charge (GWh) - {scenario_name}',
                              labels={'value': 'Total SOC (GWh)', 'index': 'Time'})
            fig_soc.update_traces(line=dict(color=get_col('battery storage')))  # Explicitly set line color
            fig_soc.update_layout(template='simple_white')
            fig_soc.write_html(os.path.join(plot_folder, f"6a_Storage_SOC_Scenario_{safe_scenario_name}.html"))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved '6a_Storage_SOC_Scenario_{safe_scenario_name}.html'")
    except Exception as e:
        print(f"Storage SOC plot failed: {e}")

    # 6b. Storage Charging/Discharging Power (Stacked Area Chart) (FIX: New plot for HTML output)
    try:
        # Re-use link_flow_data from the dispatch plot's calculation block if available, or calculate anew
        link_flow_data = None
        if not n.links.empty and hasattr(n.links_t, 'p0'):
            battery_links = n.links[n.links.carrier == 'battery_link'].index
            if not battery_links.empty:
                link_flow_data = n.links_t.p0[battery_links].sum(axis=1)

        if link_flow_data is not None and (
                link_flow_data.sum() > 0 or link_flow_data.sum() < 0):  # Only plot if there's any flow
            # Create a DataFrame for Plotly, ensuring column names match 'charge' and 'discharge' keys in colours
            df_charge_discharge = pd.DataFrame({
                'charge': link_flow_data.where(link_flow_data < 0, 0),  # Negative values for charging
                'discharge': link_flow_data.where(link_flow_data > 0, 0)  # Positive values for discharging
            }, index=n.snapshots)

            # Filter out if all values are zero (e.g., if no storage activity)
            if not df_charge_discharge.empty and (
                    df_charge_discharge['charge'].abs().sum() > 0 or df_charge_discharge['discharge'].sum() > 0):
                fig_power = go.Figure()

                # Add discharge (positive stackgroup)
                fig_power.add_trace(
                    go.Scatter(x=n.snapshots, y=df_charge_discharge['discharge'], stackgroup='2', name='Discharge',
                               mode='none',
                               line=dict(width=0.5, color=get_col('discharge')), fillcolor=get_col('discharge')))
                # Add charge (negative stackgroup)
                fig_power.add_trace(
                    go.Scatter(x=n.snapshots, y=df_charge_discharge['charge'], stackgroup='1', name='Charge',
                               mode='none',
                               line=dict(width=0.5, color=get_col('charge')), fillcolor=get_col('charge')))

                fig_power.update_layout(title=f'Total System Storage Charging/Discharging Power (MW) - {scenario_name}',
                                        xaxis_title='Time', yaxis_title='Power (MW)', template='simple_white',
                                        hovermode='x unified')
                fig_power.write_html(
                    os.path.join(plot_folder, f"6b_Storage_Charge_Discharge_Scenario_{safe_scenario_name}.html"))
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Saved '6b_Storage_Charge_Discharge_Scenario_{safe_scenario_name}.html'")
            else:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Storage Charge/Discharge plot skipped: No significant storage flow data.")
        else:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Storage Charge/Discharge plot skipped: No storage link flow data available.")
    except Exception as e:
        print(f"Storage Charge/Discharge plot failed: {e}")

        # 7. Hourly Generation Dispatch (Stacked Area Chart)
        # (Rest of this block remains largely unchanged, just renumbered and ensures link_flow_data is accessible or recalculated)
    try:
        fig_dispatch = go.Figure()
        # Fix 7: Order: Diesel > Gas > Hydro > Discharge > Wind > Solar > Others (from bottom to top)
        desired_order_bottom_up = ['Diesel', 'Gas', 'Hydro', 'Wind', 'Solar']
        available_gen_carriers = n.generators.carrier.unique()

        gen_traces_to_add = []
        NEGLIGIBLE_HOURLY_DISPATCH_MW = 0.001  # 1 kW
        for c in available_gen_carriers:
            if c != 'slack':  # Always filter slack from plots
                gens_carr_idx = n.generators[n.generators.carrier == c].index
                if not gens_carr_idx.empty and not n.generators_t.p.empty:
                    valid_cols = gens_carr_idx.intersection(n.generators_t.p.columns)
                    if not valid_cols.empty:
                        y = n.generators_t.p[valid_cols].sum(axis=1)
                        # Fix 4: Filter out generators with negligible total contribution for dispatch plot
                        if y.abs().sum() > NEGLIGIBLE_HOURLY_DISPATCH_MW * len(n.snapshots):  # Check total sum for year
                            gen_traces_to_add.append({'name': c, 'y': y, 'color': get_col(c)})

        # Recalculate link_flow_data if it wasn't already for 6b or ensure it's still available
        link_flow_data = None
        if not n.links.empty and hasattr(n.links_t, 'p0'):
            battery_links = n.links[n.links.carrier == 'battery_link'].index
            if not battery_links.empty:
                link_flow_data = n.links_t.p0[battery_links].sum(axis=1)

        discharge_trace_data = None
        if link_flow_data is not None:
            y_dis = link_flow_data.where(link_flow_data > 0, 0)
            if y_dis.sum() > 0:  # Only add if there is actual discharge
                discharge_trace_data = {'name': 'discharge', 'y': y_dis, 'color': get_col('discharge')}

        final_stacked_traces = []
        for c in ['Diesel', 'Gas', 'Hydro']:
            for trace in gen_traces_to_add:
                if trace['name'] == c:
                    final_stacked_traces.append(trace)
                    break

        if discharge_trace_data:
            final_stacked_traces.append(discharge_trace_data)

        for c in ['Wind', 'Solar']:
            for trace in gen_traces_to_add:
                if trace['name'] == c:
                    final_stacked_traces.append(trace)
                    break

        for trace in gen_traces_to_add:
            if trace['name'] not in desired_order_bottom_up and trace['name'] not in [t['name'] for t in
                                                                                      final_stacked_traces]:  # Avoid duplicates
                final_stacked_traces.append(trace)

        for trace_data in final_stacked_traces:
            fig_dispatch.add_trace(
                go.Scatter(x=n.snapshots, y=trace_data['y'], stackgroup='2', name=trace_data['name'], mode='none',
                           line=dict(width=0.5, color=trace_data['color']), fillcolor=trace_data['color']))

        if link_flow_data is not None:
            y_charge = link_flow_data.where(link_flow_data < 0, 0)
            if y_charge.sum() < 0:  # Only add if there is actual charging
                fig_dispatch.add_trace(go.Scatter(x=n.snapshots, y=y_charge, stackgroup='1', name='charge', mode='none',
                                                  line=dict(width=0.5, color=get_col('charge')),
                                                  fillcolor=get_col('charge')))

        if not n.loads_t.p_set.empty:
            fig_dispatch.add_trace(go.Scatter(x=n.snapshots, y=n.loads_t.p_set.sum(axis=1), name='Demand', mode='lines',
                                              line=dict(color='black', width=2, dash='dot')))

        fig_dispatch.update_layout(title=f'Hourly Generation Dispatch - {scenario_name}', xaxis_title='Time',
                                   yaxis_title='MW', template='simple_white')
        fig_dispatch.write_html(os.path.join(plot_folder, f"7_Generation_Dispatch_Scenario_{safe_scenario_name}.html"))
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Saved '7_Generation_Dispatch_Scenario_{safe_scenario_name}.html'")
    except Exception as e:
        print(f"Dispatch plot failed: {e}")

    print(f"All plots created (if data available) in {plot_folder}")


# --- START OF FIX: Add constraint-related helper functions ---

def add_dispatchable_constraint(n, snapshots, dispatchable_share):
    """
    Add hourly dispatchable generation constraint.
    Ensures minimum percentage of demand comes from dispatchable sources at each hour.
    """
    if dispatchable_share is None or dispatchable_share <= 0:
        return

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Adding dispatchable generation constraint: {dispatchable_share * 100:.1f}% from Hydro/BESS/Diesel/Gas at each hour"
    dispatchable_carriers = get_dispatchable_carriers()

    # Get dispatchable generators
    dispatchable_gens = n.generators[n.generators.carrier.isin(dispatchable_carriers)].index

    # Get battery links (for discharge tracking)
    battery_links = n.links[n.links.carrier == 'battery_link'].index

    if len(dispatchable_gens) == 0 and len(battery_links) == 0:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: No dispatchable generators or batteries found. Skipping dispatchable generation constraint."
        return

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(dispatchable_gens)} dispatchable generators and {len(battery_links)} battery links."

    # Get total demand per snapshot (sum across all loads)
    total_demand_per_snapshot = n.loads_t.p_set.sum(axis=1)

    # Get generator power variables for dispatchable generators only
    gen_p = get_var(n, "Generator", "p")
    dispatchable_gen_p = gen_p.loc[:, dispatchable_gens]

    # Sum dispatchable generation per snapshot
    dispatchable_expr = linexpr((1, dispatchable_gen_p)).sum(dims='Generator')

    # Add battery discharge if batteries exist
    if len(battery_links) > 0:
        link_p = get_var(n, "Link", "p")
        battery_p = link_p.loc[:, battery_links]
        # Only positive link_p (discharge) contributes to meeting demand
        battery_discharge_expr = linexpr((1, battery_p.where(battery_p > 0, 0))).sum(dims='Link')

        # Total dispatchable = generators + batteries
        total_dispatchable_expression = dispatchable_expr + battery_discharge_expr
    else:
        total_dispatchable_expression = dispatchable_expr

    # RHS: minimum dispatchable requirement per snapshot
    min_dispatchable = dispatchable_share * total_demand_per_snapshot

    # Add constraints: one per snapshot
    define_constraints(
        n,
        total_dispatchable_expression,
        ">=",
        min_dispatchable,
        "GlobalConstraint",
        "dispatchable_minimum"
    )

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Added dispatchable generation constraints for {len(snapshots)} hours."


def add_minimum_soc_constraint(n, snapshots, minimum_soc):
    """
    Add minimum State of Charge (SOC) constraint for battery storage.
    Ensures battery SOC never drops below specified percentage of capacity.
    """
    if minimum_soc is None or minimum_soc <= 0:
        return

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Adding minimum SOC constraint: {minimum_soc * 100:.1f}% of battery capacity."

    # Check if there are any stores (batteries) in the network
    if len(n.stores) == 0:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: No stores/batteries found. Skipping minimum SOC constraint."
        return

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(n.stores)} battery stores."

    # Get store state_of_charge (energy) variables
    soc_vars = get_var(n, "Store", "e")

    # For each store, create minimum SOC constraint
    # SOC must be >= minimum_soc * capacity at all times
    for store in n.stores.index:
        # Get SOC variable for this store across all snapshots
        store_soc = soc_vars.loc[:, store]

        # Check if store capacity is extendable
        if n.stores.at[store, 'e_nom_extendable']:
            # For extendable stores, use the capacity VARIABLE (not fixed value)
            store_capacity_var = get_var(n, "Store", "e_nom").loc[store]

            # Create constraint: SOC >= minimum_soc * e_nom (capacity variable)
            # This ensures the constraint scales with optimized capacity
            soc_expr = linexpr((1, store_soc), (-minimum_soc, store_capacity_var))

            define_constraints(
                n,
                soc_expr,
                ">=",
                0,  # LHS - RHS >= 0, which means: SOC >= minimum_soc * capacity
                "Store",
                f"min_soc_{store}"
            )
        else:
            # For fixed capacity stores, use the fixed e_nom value
            store_capacity = n.stores.at[store, 'e_nom']
            min_energy = minimum_soc * store_capacity

            # Create linear expression
            soc_expr = linexpr((1, store_soc))

            # Add constraint: SOC >= minimum_soc * capacity (fixed)
            define_constraints(
                n,
                soc_expr,
                ">=",
                min_energy,
                "Store",
                f"min_soc_{store}"
            )

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Added minimum SOC constraints for {len(n.stores)} batteries across {len(snapshots)} hours."


# Define extra_functionality for renewable-only battery charging (from main.py)
def add_renewable_charging_constraint(n, snapshots):
    """
    Constrain battery charging to only use Solar and Wind energy sources.
    Prevents expensive fossil fuel generators (diesel, gas) and other sources from charging batteries.
    Only excess Solar and Wind can charge batteries.
    """
    # Check if there are any stores (batteries) in the network
    if len(n.stores) == 0:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: No stores/batteries found. Skipping renewable charging constraint."
        return

    # Check if there are battery links
    battery_links = n.links[n.links.carrier == 'battery_link'].index
    if len(battery_links) == 0:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: No battery links found. Skipping renewable charging constraint."
        return

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Adding Solar and Wind-only charging constraint for {len(battery_links)} battery links."

    # Get only Solar and Wind carriers (Solar Rooftop is a type of Solar)
    solar_wind_carriers = ['Solar', 'Solar Rooftop', 'Wind']

    # Get Solar and Wind generators only
    renewable_gens = n.generators[n.generators.carrier.isin(solar_wind_carriers)].index

    if len(renewable_gens) == 0:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: No Solar or Wind generators found. Skipping renewable charging constraint."
        return

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(renewable_gens)} Solar and Wind generators for charging constraint."

    # Get generator and link power variables
    gen_p = get_var(n, "Generator", "p")
    link_p = get_var(n, "Link", "p")

    # Filter to only renewable generators and battery links
    renewable_gen_p = gen_p.loc[:, renewable_gens]
    battery_link_p = link_p.loc[:, battery_links]

    # Sum Solar and Wind generation per snapshot (across all Solar and Wind generators)
    renewable_gen_sum = linexpr((1, renewable_gen_p)).sum(dim='Generator')

    # Sum battery link power per snapshot (across all battery links)
    # For battery links: positive p = discharge, negative p = charge
    # We want to constrain charging: -link_p <= solar_wind_gen
    # Which means (renewable_gen_sum + link_p) should be >= 0 when link_p is negative (charging)
    battery_link_sum = linexpr((1, battery_link_p)).sum(dim='Link')

    # Combine expressions using arithmetic: solar_wind_gen + link_p >= 0
    # This ensures that when link_p is negative (charging),
    # the charging magnitude does not exceed the available Solar and Wind generation
    constraint_expr = renewable_gen_sum + battery_link_sum

    define_constraints(
        n,
        constraint_expr,
        ">=",
        0,
        "GlobalConstraint",
        "renewable_charge"
    )

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Added Solar and Wind-only charging constraint for {len(snapshots)} hours."


def combined_extra_functionality(n, snapshots, dispatchable_share, minimum_soc):
    """Wrapper to call multiple extra functionality functions"""
    # The yield statements from add_..._constraint functions are propagated
    # by the generator that calls combined_extra_functionality.
    # Pass along the parameters.
    for log_msg in add_dispatchable_constraint(n, snapshots, dispatchable_share):
        yield log_msg
    for log_msg in add_minimum_soc_constraint(n, snapshots, minimum_soc):
        yield log_msg
    # if add_renewable_charging_constraint is ever made active, it would be called here:
    for log_msg in add_renewable_charging_constraint(n, snapshots):
        yield log_msg


# --------------------------
# Core model runner
# --------------------------
def run_model(
        data_file,
        results_dir,
        solver,
        co2_cap,
        re_share,
        slack_cost,
        discount_rate,
        tech_cost_multipliers,
        scenario_name,
        scenario_number,
        line_expansion,
        enabled_techs,
        default_new_gen_extendable,
        scenario_year,
        target_peak_demand,
        demand_projection_method,
        demand_growth_percentage,
        reserve_margin,
        dispatchable_share,
        minimum_soc,
        df_buses,
        df_generators,
        df_load,
        df_transmission_lines,
        df_transformers,
        df_storage,
        df_generation_profiles,
        df_scenario_year # This parameter is currently not used but kept for backward compatibility if needed
):
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Starting simulation for scenario: {scenario_name}"

    current_datetime = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_folder_name = f"{scenario_name}_{current_datetime}"
    full_results_path_prefix = os.path.join(results_dir, run_folder_name)
    os.makedirs(full_results_path_prefix, exist_ok=True)

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Results will be saved to: {full_results_path_prefix}"

    if solver.lower() == 'highs' and os.environ.get('PYPSA_SOLVER_HIGHSPY_PATH_SET') == 'true':
        yield f"[{datetime.now().strftime('%H:%M:%S')}] HiGHS executable path was successfully added to environment PATH by app startup."
    elif solver.lower() == 'highs':
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Attempting to find HiGHS using system PATH (automatic detection in app.py failed)."

    # --------------------------
    # Scenario Year and Demand Scaling
    # --------------------------
    target_year = scenario_year
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Target Year for simulation: {target_year}"

    # Fix 1: Calculate peak from passed df_load, not file
    if not df_load.empty:
        current_peak_MW = df_load.sum(axis=1).max()
    else:
        current_peak_MW = 0
        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: No load data provided, base load peak assumed zero."

    scale_factor = 1.0
    if demand_projection_method == "Target Peak Demand":
        target_peak_MW_input = target_peak_demand
        scale_factor = target_peak_MW_input / current_peak_MW if current_peak_MW > 0 else 1.0
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Demand Scaling Method: Target Peak. Base Load Peak: {current_peak_MW:.2f} MW, Target Peak: {target_peak_MW_input:.2f} MW. Scale Factor: {scale_factor:.2f}"
    else:  # Percentage Growth
        growth_factor_percentage = demand_growth_percentage / 100.0
        scale_factor = (1 + growth_factor_percentage)
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Demand Scaling Method: Percentage Growth. Percentage Growth: {demand_growth_percentage:.1f}%. Scale Factor: {scale_factor:.2f}"

    if current_peak_MW == 0 and (demand_projection_method == "Target Peak Demand" and target_peak_demand > 0 or demand_projection_method == "Percentage Growth" and demand_growth_percentage > 0):
        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Base load peak is zero, but target/growth specified. Demand may be scaled from zero."

    # --- START OF FIX: Apply Reserve Margin Multiplier ---
    reserve_margin_multiplier = 1.0 + reserve_margin
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Applying reserve margin: {reserve_margin * 100:.1f}%. Total load scaled by an additional factor of {reserve_margin_multiplier:.2f}."
    # --- END OF FIX ---

    # --------------------------
    # Network build
    # --------------------------
    n = pypsa.Network()

    timestamps = pd.date_range(start=f'{target_year}-01-01', end=f'{target_year}-12-31 23:00', freq='h')
    if calendar.isleap(target_year):
        # Remove Feb 29 hours to have exactly 8760 hours for consistent profiles
        feb29_start = pd.Timestamp(f'{target_year}-02-29 00:00')
        feb29_end = pd.Timestamp(f'{target_year}-02-29 23:00')
        timestamps = timestamps[~((timestamps >= feb29_start) & (timestamps <= feb29_end))]
    elif len(timestamps) > 8760: # If it's not a leap year but has more than 8760, truncate
        timestamps = timestamps[:8760]
    elif len(timestamps) < 8760: # If for some reason less than 8760, warn
        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Snapshots generated fewer than 8760 hours ({len(timestamps)}). This may affect results."

    n.snapshots = timestamps
    n.snapshot_weightings['objective'] = n.snapshot_weightings['objective'] * (8760 / len(timestamps))
    yield f"[{datetime.now().strftime('%H:%M:%S')}] PyPSA Network initialized with {len(timestamps)} snapshots (leap year adjusted to 8760 hours)."

    # Buses
    if not df_buses.empty:
        df_buses_processed = df_buses.set_index('Bus name', drop=False).copy()
        for bus_name, row in df_buses_processed.iterrows():
            n.add("Bus",
                  bus_name,
                  x=row.get("x"),
                  y=row.get("y"),
                  v_nom=row.get("v_nom"),
                  carrier=row.get("carrier"),
                  unit=row.get("unit"))
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Added {len(df_buses_processed)} buses with extended attributes."
    else:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] No bus data provided."
        raise ValueError("No bus data provided to build the network.")

    # Carriers
    all_carriers_from_generators = df_generators['Carrier'].dropna().astype(str).unique() if not df_generators.empty else []
    all_carriers_from_storage = df_storage['Carrier'].dropna().astype(str).unique() if not df_storage.empty else []
    all_carriers_from_buses = df_buses['carrier'].dropna().astype(str).unique() if not df_buses.empty else []
    all_carriers_from_data = set(all_carriers_from_generators).union(set(all_carriers_from_storage)).union(
        set(all_carriers_from_buses))

    standard_carriers = {"electricity", "backup", "AC", "storage_charge", "storage_discharge", "slack", "battery_link"}
    all_carriers_to_add = all_carriers_from_data.union(standard_carriers)

    for c in all_carriers_to_add:
        carrier_name_lower = str(c).lower()
        if carrier_name_lower == "diesel":
            safe_add_carrier(n, c, co2_emissions=0.267)
        elif carrier_name_lower == "gas":
            safe_add_carrier(n, c, co2_emissions=0.202)
        elif carrier_name_lower == "bio power- cno":
            safe_add_carrier(n, c, co2_emissions=0.1) # Assuming a value for Bio Power- CNO
        else:
            safe_add_carrier(n, c, co2_emissions=0.0)
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Defined {len(n.carriers)} energy carriers."

    # Loads (Fix 1: Uses df_load directly)
    if not df_load.empty:
        df_load_processed = df_load.copy()

        # Ensure index is datetime for reindexing
        if not isinstance(df_load_processed.index, pd.DatetimeIndex):
            # If the index is not datetime but matches snapshots length, assume alignment
            if len(df_load_processed) == len(n.snapshots):
                df_load_processed.index = n.snapshots
            else:
                yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Load data rows ({len(df_load_processed)}) do not match snapshot count ({len(n.snapshots)}). Reindexing will occur, potentially with NaNs."
                df_load_processed = df_load_processed.reindex(n.snapshots)
        else:
            df_load_processed = df_load_processed.reindex(n.snapshots) # Reindex to network snapshots

        df_load_processed = df_load_processed.fillna(0) # Fill any NaNs from reindexing or original data

        numeric_cols = df_load_processed.select_dtypes(include=np.number).columns
        df_load_processed = df_load_processed[numeric_cols]
        df_load_processed.dropna(axis=1, how='all', inplace=True) # Drop columns that are all NaN after processing

        if df_load_processed.empty:
            yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Processed load data is empty or non-numeric. No loads added to network."
        else:
            for load_centre in df_load_processed.columns:
                if load_centre in n.buses.index:
                    load_fix = pd.Series(df_load_processed[load_centre] * scale_factor * reserve_margin_multiplier, index=n.snapshots, name=load_centre)
                    n.add("Load", load_centre, bus=load_centre, p_set=load_fix)
                else:
                    yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Load center '{load_centre}' does not have a corresponding bus. Skipping."
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Added {len(n.loads)} load components, scaled by {scale_factor:.2f}."
    else:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] No load data provided."

    # Generation Profiles
    # --- START OF FIX: Robust processing of df_generation_profiles for site-specific profiles ---
    df_prof = pd.DataFrame(index=n.snapshots)  # Initialize empty DataFrame for processed profiles

    if not df_generation_profiles.empty:
        # Check if df_generation_profiles is a dictionary (from Excel mapping) or a DataFrame (from manual entry)
        if isinstance(df_generation_profiles, dict) and 'df_content' in df_generation_profiles:
            # Handle case where df_generation_profiles is a dict from mapped_data (Excel)
            df_profiles_content_dict = df_generation_profiles['df_content']

            if df_profiles_content_dict:  # Check if the dictionary itself is not empty
                # Create a temporary dict for profiles ensuring all are lists
                processed_profiles_for_df = {}
                for k, v in df_profiles_content_dict.items():
                    if isinstance(v, list):
                        processed_profiles_for_df[k] = v
                    else:
                        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Profile '{k}' has unexpected format. Skipping."

                if processed_profiles_for_df:  # Check if any valid profiles were found
                    # Ensure all profiles have the same length as snapshots
                    for col_name, profile_values in processed_profiles_for_df.items():
                        if len(profile_values) < len(n.snapshots):
                            processed_profiles_for_df[col_name] = profile_values + [0.0] * (
                                        len(n.snapshots) - len(profile_values))
                        elif len(profile_values) > len(n.snapshots):
                            processed_profiles_for_df[col_name] = profile_values[:len(n.snapshots)]

                    df_prof = pd.DataFrame(processed_profiles_for_df, index=n.snapshots).fillna(0.0)
                else:
                    yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: No valid generation profiles content found in mapped data (Excel). Generators requiring profiles will produce 0 power."
            else:
                yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Mapped generation profiles (Excel) are empty. Generators requiring profiles will produce 0 power."

        else:  # Handle case where df_generation_profiles is already a DataFrame (e.g., from manual entry)
            df_prof = df_generation_profiles.copy()
            if not isinstance(df_prof.index, pd.DatetimeIndex):
                if len(df_prof) == len(n.snapshots):
                    df_prof.index = n.snapshots
                else:
                    yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Manual generation profile rows ({len(df_prof)}) do not match snapshot count ({len(n.snapshots)}). Reindexing will occur, potentially with NaNs."
                    df_prof = df_prof.reindex(n.snapshots).fillna(0.0)
            else:
                df_prof = df_prof.reindex(n.snapshots).fillna(0.0).copy()

        # Log available profiles for user debugging
        if not df_prof.empty:
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Loaded generation profiles sheet. Available columns: {', '.join(df_prof.columns.tolist())}"
        else:
            yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Processed generation profiles DataFrame is empty. Generators requiring profiles will produce 0 power."
    else:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] No generation profile data provided. Intermittent generators requiring profiles will produce 0 power."
    # --- END OF FIX ---

    # --------------------------
    # Generators
    # --------------------------
    if not df_generators.empty:
        df_gen_processed = df_generators.set_index('Generator name', drop=True).copy()

        if 'Scenario' in df_gen_processed.columns:
            # FIX: Robust scenario filtering to handle both lists and scalars
            def check_scen_membership(scenario_col_value):
                try: 
                    # Attempt to evaluate as a literal (list) if it's a string
                    evaluated_value = ast.literal_eval(str(scenario_col_value)) if isinstance(scenario_col_value, str) else scenario_col_value
                except (ValueError, SyntaxError):
                    # If evaluation fails, treat as scalar
                    evaluated_value = scenario_col_value

                if isinstance(evaluated_value, (list, tuple)):
                    return scenario_number in evaluated_value
                else:
                    # Direct comparison for scalar values
                    return scenario_number == evaluated_value

            df_gen_processed = df_gen_processed[df_gen_processed['Scenario'].apply(check_scen_membership)].copy()
        
        added_generators_count = 0
        for gen_i, row in df_gen_processed.iterrows():
            carrier = row['Carrier']
            if not enabled_techs.get(carrier, True):
                yield f"[{datetime.now().strftime('%H:%M:%M')}] Skipping generator '{gen_i}' (Carrier: {carrier}) as its technology is disabled."
                continue

            bus = row['Bus']
            if bus not in n.buses.index:
                yield f"[{datetime.now().strftime('%H:%M:%M')}] WARNING: Generator '{gen_i}' refers to non-existent bus '{bus}'. Skipping."
                continue

            status = int(float(row.get('Status', 0)))  # 0 for existing, 1 for new

            # --- Robust Quantity Logic ---
            qty = 1
            if 'Quantity' in row and pd.notna(row['Quantity']):
                qty = int(float(row['Quantity']))

            p_nom_initial_total = float(row.get('Capacity(MW)', 0.0))
            size_mw = float(row.get('Size (MW)', 0.0))

            p_nom_instance_val = p_nom_initial_total # Default to total, then refine
            if size_mw > 0:
                p_nom_instance_val = size_mw # Use explicit size per unit if given
            elif qty > 1 and p_nom_initial_total > 0:
                p_nom_instance_val = p_nom_initial_total / qty # Distribute total capacity among quantity if no size given

            # Parameter extraction
            input_p_nom_extendable_raw = row.get('p_nom_extendable')
            p_nom_extendable = False # Default
            if pd.notna(input_p_nom_extendable_raw):
                if isinstance(input_p_nom_extendable_raw, (bool, np.bool_)):
                    p_nom_extendable = bool(input_p_nom_extendable_raw)
                elif isinstance(input_p_nom_extendable_raw, (int, float)):
                    p_nom_extendable = bool(int(input_p_nom_extendable_raw)) # 0 -> False, 1 -> True
                elif isinstance(input_p_nom_extendable_raw, str):
                    val_str = input_p_nom_extendable_raw.lower().strip()
                    p_nom_extendable = (val_str == 'true' or val_str == '1')
            elif status == 1: # For new generators, default to project setting
                p_nom_extendable = default_new_gen_extendable

            lifetime = int(float(row.get('lifetime', 25))) if pd.notna(row.get('lifetime', 25)) else 25
            raw_capex_per_MW = float(row.get('Capital_cost (USD/MW)', 0.0))
            # --- START OF FIX: Read fixed_O&M and add to annuitized_capex ---
            fixed_OM_per_MW_year = float(row.get('fixed_O&M (USD/MW/year)', 0.0)) # Read the fixed O&M cost
            marginal_cost_per_MWh = float(row.get('Marginal cost (USD/MWh)', 0.0))

            efficiency = float(row.get('efficiency', 1.0))
            committable_raw = row.get('committable', False)
            committable = bool(committable_raw) if pd.notna(committable_raw) else False

            # Apply Cost Multipliers to CAPEX first
            scaled_capex = apply_cost_multiplier(carrier, raw_capex_per_MW, tech_cost_multipliers)
            annuitized_capex = calculate_annuity(scaled_capex, discount_rate, lifetime)

            # Add fixed O&M (USD/MW/year) directly to annuitized CAPEX (USD/MW/year) as per main.py
            total_annual_fixed_cost_per_MW = annuitized_capex + fixed_OM_per_MW_year
            # --- END OF FIX ---
            p_min_pu = float(row.get('p_min_pu', 0.0))
            p_nom_min_gen = float(row.get('P_nom_min', 0.0))
            p_nom_max_gen = float(row.get('P_nom_max', np.inf))

            # --- START OF FIX: Site-specific profile lookup for p_max_pu and Hydro p_min_pu ---
            p_max_pu_value = 1.0 # Default for dispatchable or if profile not found
            p_min_pu_value = float(row.get('p_min_pu', 0.0)) # Default p_min_pu

            profile_col_name = row.get('Profile Column')
            profile_data_found = None

            if carrier in get_renewable_carriers():
                actual_profile_col_to_use = None
                
                # Check if specific profile column is provided and exists
                if isinstance(profile_col_name, str) and profile_col_name.strip() and profile_col_name.strip() in df_prof.columns:
                    actual_profile_col_to_use = profile_col_name.strip()
                # Otherwise try to find a generic fallback profile
                else:
                    fallback_name = f"{carrier} profile"
                    if fallback_name in df_prof.columns:
                        actual_profile_col_to_use = fallback_name
                    elif carrier in df_prof.columns:
                        actual_profile_col_to_use = carrier
                    else:
                        for col in df_prof.columns:
                            if col.lower() == fallback_name.lower():
                                actual_profile_col_to_use = col
                                break
                
                if actual_profile_col_to_use:
                    profile_data_found = pd.to_numeric(df_prof[actual_profile_col_to_use], errors='coerce').fillna(0.0)
                    if profile_data_found.empty or profile_data_found.sum() == 0:
                        yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Generator '{gen_i}' ({carrier}) using profile '{actual_profile_col_to_use}' but data is empty or zeros. It will produce 0 power."
                        p_max_pu_value = 0.0
                        if carrier == 'Hydro': p_min_pu_value = 0.0
                    else:
                        p_max_pu_value = profile_data_found.values
                        if carrier == 'Hydro': p_min_pu_value = profile_data_found.values
                    yield f"[{datetime.now().strftime('%H:%M:%S')}] Generator '{gen_i}' ({carrier}) using profile: '{actual_profile_col_to_use}'."
                else:
                    yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Generator '{gen_i}' ({carrier}) is renewable but no valid profile found (tried '{profile_col_name}' and generic '{carrier} profile'). It will produce 0 power."
                    p_max_pu_value = 0.0
                    if carrier == 'Hydro': p_min_pu_value = 0.0

            p_nom_min_gen = float(row.get('P_nom_min', 0.0))
            p_nom_max_gen = float(row.get('P_nom_max', np.inf))

            # --- Instantiation Loop for multiple units if Quantity > 1 ---
            count_to_add = qty if qty > 0 else 1
            
            for i in range(1, count_to_add + 1):
                gen_name_instance = gen_i # Default name for single units
                if count_to_add > 1:
                    # Naming convention matches reference concept: {GenID}_{CarrierCode}{Index}
                    # Example: `Gen1_DI1`, `Gen1_DI2` for Diesel, `Gen2_HY1` for Hydro
                    carrier_code = carrier.replace(" ", "").upper()[:2] # e.g., "DI", "HY", "SO", "WI"
                    gen_name_instance = f"{gen_i}_{carrier_code}{i}"
                    
                    # Ensure absolute uniqueness in case of name collision
                    original_name = gen_name_instance
                    counter = 0
                    while gen_name_instance in n.generators.index:
                        gen_name_instance = f"{original_name}_{counter}"
                        counter += 1

                # p_nom setting: 0 for new builds, existing for existing units
                p_nom_set_for_add = 0.0
                if status == 0: # Existing generator
                    p_nom_set_for_add = p_nom_instance_val
                
                n.add("Generator",
                      gen_name_instance,
                      bus=bus,
                      p_nom=p_nom_set_for_add,
                      p_nom_min=p_nom_min_gen,
                      p_nom_max=p_nom_max_gen,
                      p_min_pu=p_min_pu_value, # Use determined p_min_pu_value
                      p_max_pu=p_max_pu_value, # Use determined p_max_pu_value
                      carrier=carrier,
                      efficiency=efficiency,
                      marginal_cost=marginal_cost_per_MWh,
                      capital_cost=total_annual_fixed_cost_per_MW,  # Now includes annuitized CAPEX + fixed O&M
                      fixed_cost=0.0,  # Explicitly set to 0.0 to avoid double-counting
                      p_nom_extendable=p_nom_extendable,
                      committable=committable,
                      ramp_limit_down=1, ramp_limit_up=1
                      )
                added_generators_count += 1
                
                status_str = "New Build" if status == 1 else "Existing"
                extendable_str = "extendable" if p_nom_extendable else "fixed"
                yield f"[{datetime.now().strftime('%H:%M:%S')}] Added {status_str} Gen '{gen_name_instance}' ({carrier}) at {bus}, initial p_nom={p_nom_set_for_add:.2f}, {extendable_str}."

        # Fix 5: Slack Cost configuration from Project Tab (marginal cost)
        slack_bus = list(n.buses.index)[0] if not n.buses.empty else "DummyBusForSlack"
        if slack_bus not in n.buses.index:
            n.add("Bus", slack_bus) # Ensure a bus exists for slack

        n.add("Generator",
              'slack',
              bus=slack_bus,
              p_nom=1e6, # Large nominal capacity to cover any shortage
              p_max_pu=1,
              marginal_cost=slack_cost,
              carrier='slack')
        added_generators_count += 1
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Added slack generator at bus '{slack_bus}' with marginal_cost={slack_cost:.2f} USD/MWh."
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Total {added_generators_count} generators processed."
    else:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] No generator data provided. Only slack generator will be present if buses exist."
        # Add slack even if no other generators exist, if there's at least one bus
        if not n.buses.empty:
            slack_bus = list(n.buses.index)[0]
            n.add("Generator", 'slack', bus=slack_bus, p_nom=1e6, marginal_cost=slack_cost, carrier='slack')
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Added slack generator at bus '{slack_bus}'."


    # --------------------------
    # Transmission Lines
    # --------------------------
    if not df_transmission_lines.empty:
        df_lines_processed = df_transmission_lines.copy()

        # --- START OF FIX: Scenario filtering for Transmission Lines ---
        if 'Scenario' in df_lines_processed.columns:
            def check_scen_membership(scenario_col_value):
                try:
                    evaluated_value = ast.literal_eval(str(scenario_col_value)) if isinstance(scenario_col_value,
                                                                                              str) else scenario_col_value
                except (ValueError, SyntaxError):
                    evaluated_value = scenario_col_value

                if isinstance(evaluated_value, (list, tuple)):
                    return scenario_number in evaluated_value
                else:
                    return scenario_number == evaluated_value

            df_lines_processed = df_lines_processed[df_lines_processed['Scenario'].apply(check_scen_membership)].copy()
        # --- END OF FIX ---
        
        lines_added_count = 0
        for i, row in df_lines_processed.iterrows():
            from_bus = str(row.get('From')).strip()
            to_bus = str(row.get('To')).strip()
            if from_bus not in n.buses.index or to_bus not in n.buses.index:
                yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Transmission line '{i}' between '{from_bus}' and '{to_bus}' refers to non-existent bus(es). Skipping."
                continue

            name = f"Line_{from_bus}_{to_bus}_{i}"
            
            s_nom_extendable = bool(row.get('s_nom_extendable', line_expansion)) # Use project-level line_expansion if not specified

            line_lifetime = int(float(row.get('lifetime', 25))) if pd.notna(row.get('lifetime', 25)) else 25
            line_capital_cost_raw = float(row.get('Capital_cost (USD/MVA)', 0.0))
            annuitized_line_capex = calculate_annuity(line_capital_cost_raw, discount_rate, line_lifetime)

            n.add("Line",
                  name,
                  bus0=from_bus,
                  bus1=to_bus,
                  type=row.get('type', None),
                  s_nom=float(row.get('s_nom', 0.0)) if not s_nom_extendable else 0.0, # Initial s_nom is 0 if extendable
                  s_nom_extendable=s_nom_extendable,
                  capital_cost=annuitized_line_capex,
                  length=float(row.get('Length (kM)', 1.0)))
            lines_added_count += 1
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Added Line '{name}': {from_bus} <-> {to_bus}, s_nom={row.get('s_nom', 0.0):.2f}, extendable={s_nom_extendable}."
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Total {lines_added_count} transmission lines added."
    else:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] No transmission line data provided."

    # --------------------------
    # Transformers
    # --------------------------
    if not df_transformers.empty:
        df_transformers_processed = df_transformers.copy()

        # --- START OF FIX: Scenario filtering for Transformers ---
        if 'Scenario' in df_transformers_processed.columns:
            def check_scen_membership(scenario_col_value):
                try:
                    evaluated_value = ast.literal_eval(str(scenario_col_value)) if isinstance(scenario_col_value,
                                                                                              str) else scenario_col_value
                except (ValueError, SyntaxError):
                    evaluated_value = scenario_col_value

                if isinstance(evaluated_value, (list, tuple)):
                    return scenario_number in evaluated_value
                else:
                    return scenario_number == evaluated_value

            df_transformers_processed = df_transformers_processed[
                df_transformers_processed['Scenario'].apply(check_scen_membership)].copy()
        # --- END OF FIX ---
        
        transformers_added_count = 0
        for i, row in df_transformers_processed.iterrows():
            bus0 = str(row.get('bus0')).strip()
            bus1 = str(row.get('bus1')).strip()
            if bus0 not in n.buses.index or bus1 not in n.buses.index:
                yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Transformer '{row.get('name', f'Trans_{i}')}' between '{bus0}' and '{bus1}' refers to non-existent bus(es). Skipping."
                continue

            name = str(row.get('name', f"Transformer_{i}")).strip()

            transformer_lifetime = int(float(row.get('lifetime', 25))) if pd.notna(row.get('lifetime', 25)) else 25
            transformer_capital_cost_raw = float(row.get('Capital_cost (USD/MW)', 0.0))
            annuitized_transformer_capex = calculate_annuity(transformer_capital_cost_raw, discount_rate,
                                                             transformer_lifetime)

            # --- START OF FIX: Incorporate num_parallel logic ---
            num_parallel = int(float(row.get('num_parallel', 1))) if pd.notna(row.get('num_parallel', 1)) else 1
            s_nom_single_unit = float(row.get('s_nom', 0.0))
            s_nom_total = s_nom_single_unit * num_parallel  # Calculate total capacity
            # --- END OF FIX ---

            n.add("Transformer",
                  name,
                  bus0=bus0,
                  bus1=bus1,
                  s_nom=s_nom_total,
                  v_nom0=float(row.get('v_nom0', 0.0)),
                  v_nom1=float(row.get('v_nom1', 0.0)),
                  x=float(row.get('x', 0.0)),
                  r=float(row.get('r', 0.0)),
                  capital_cost=annuitized_transformer_capex)
            transformers_added_count += 1
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Added Transformer '{name}': {bus0} <-> {bus1}, s_nom_total={s_nom_total:.2f} MVA ({num_parallel}x{s_nom_single_unit:.2f} MVA), extendable={False}."
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Total {transformers_added_count} transformers added."
    else:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] No transformer data provided."

    # --------------------------
    # Storage construction (Revised to single bidirectional link model)
    # --------------------------
    if not df_storage.empty:
        df_storage_processed = df_storage.set_index('name', drop=True).copy()
        if 'Scenario' in df_storage_processed.columns:
            # FIX: Robust scenario filtering for storage
            def check_scen_membership(scenario_col_value):
                try: 
                    evaluated_value = ast.literal_eval(str(scenario_col_value)) if isinstance(scenario_col_value, str) else scenario_col_value
                except (ValueError, SyntaxError):
                    evaluated_value = scenario_col_value

                if isinstance(evaluated_value, (list, tuple)):
                    return scenario_number in evaluated_value
                else:
                    return scenario_number == evaluated_value

            df_storage_processed = df_storage_processed[df_storage_processed['Scenario'].apply(check_scen_membership)].copy()

        storage_count = 0
        for sto_i, row in df_storage_processed.iterrows():
            bus_parent = str(row.get('Bus')).strip()
            if bus_parent not in n.buses.index:
                yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Storage '{sto_i}' refers to non-existent parent bus '{bus_parent}'. Skipping."
                continue

            carrier = str(row.get('Carrier', 'Battery Storage')).strip()
            if not enabled_techs.get(carrier, True):
                yield f"[{datetime.now().strftime('%H:%M:%S')}] Skipping storage '{sto_i}' (Carrier: {carrier}) as its technology is disabled."
                continue

            store_internal_bus_name = f"{sto_i}_internal_bus"
            if store_internal_bus_name not in n.buses.index:
                n.add("Bus", store_internal_bus_name)

            p_nom_converter = float(row.get('p_nom (MW)', 0.0))
            e_nom_storage = float(row.get('e_nom (MWh)', 0.0))
            status = float(row.get('Status', 0.0)) # 0 for existing, 1 for new

            e_nom_initial = e_nom_storage if status == 0 else 0.0 # Initial capacity is 0 for new builds

            e_nom_extendable = bool(row.get('e_nom_extendable', False))
            lifetime = int(float(row.get('lifetime', 20.0))) if pd.notna(row.get('lifetime', 20.0)) else 20

            marginal_cost_storage = float(row.get('Marginal cost (USD/MWh)', 0.0))
            # The user explicitly requested to enter storage capital cost in USD/MW (power capacity)
            # Therefore, we apply this cost to the Link component (inverter/converter) and set the Store (energy) cost to 0.
            raw_capex_per_MWh = 0.0
            annuitized_e_capex = calculate_annuity(raw_capex_per_MWh, discount_rate, lifetime)

            # Storage Defaults (Matching Reference implementation for marginal_cost)
            link_efficiency = float(row.get('link_efficiency', 0.95))
            
            # Fix: Link marginal cost - 10.0 for existing, 1.0 for new
            default_link_mc = 10.0 if status == 0 else 1.0
            link_marginal_cost = float(row.get('link_marginal_cost', default_link_mc))

            # Read the user-provided USD/MW cost
            link_capital_cost_raw_per_MW = float(row.get('Capital_cost (USD/MW)', 0.0))
            annuitized_link_capex = calculate_annuity(link_capital_cost_raw_per_MW, discount_rate, lifetime)

            e_max_pu = float(row.get('e_max_pu', 0.9))

            n.add(
                "Link", f"{sto_i}_link",
                bus0=store_internal_bus_name,
                bus1=bus_parent,
                p_nom=p_nom_converter,
                p_min_pu=-1.0, # Allows bidirectional flow (charging)
                carrier='battery_link',
                efficiency=link_efficiency,
                marginal_cost=link_marginal_cost,
                p_nom_extendable=e_nom_extendable, # Link p_nom is extendable, tied to e_nom_extendable from store data
                capital_cost=annuitized_link_capex
            )

            n.add("Store", sto_i,
                  bus=store_internal_bus_name,
                  e_nom=e_nom_initial,
                  e_nom_extendable=e_nom_extendable,
                  e_cyclic=True, # Allows energy to be stored and retrieved
                  e_max_pu=e_max_pu,
                  marginal_cost=marginal_cost_storage,
                  capital_cost=annuitized_e_capex,
                  lifetime=lifetime,
                  carrier=carrier)

            storage_count += 1
            status_str = "New Build" if status == 1 else "Existing"
            extendable_str = "extendable" if e_nom_extendable else "fixed"
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Added {status_str} Storage '{sto_i}' ({carrier}) at {bus_parent}, initial e_nom={e_nom_initial:.2f} MWh, p_nom_converter={p_nom_converter:.2f} MW, {extendable_str}."
    else:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] No storage data provided."

    # --------------------------
    # Constraints
    # --------------------------
    renewable_carriers = get_renewable_carriers()
    for carrier_name in renewable_carriers:
        if carrier_name in n.carriers.index:
            n.carriers.loc[carrier_name, 'renewable'] = 1.0
        else:
            yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Renewable carrier '{carrier_name}' not found in network carriers defined in this scenario. Ensure all carriers are added to PyPSA network."

    if co2_cap is not None and co2_cap > 0:
        n.add("GlobalConstraint", "CO2_CAP",
              carrier_attribute="co2_emissions",
              sense="<=",
              constant=float(co2_cap))
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Added CO2 emissions cap: {co2_cap:.2f} tons/year."

    if re_share is not None and re_share > 0:
        total_annual_demand = n.loads_t.p_set.sum().sum()
        if total_annual_demand == 0:
            yield f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Cannot apply RE share constraint as total annual demand is zero."
        else:
            min_re_generation = re_share * total_annual_demand
            n.add("GlobalConstraint", "RE_SHARE", # Changed from RE_SHARE_MIN for consistency, PyPSA will use "name"
                  carrier_attribute="renewable",
                  sense=">=",
                  constant=float(min_re_generation))
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Added RE share target: {re_share * 100:.1f}% of total annual demand."

    # --------------------------
    # Optimization
    # --------------------------
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Starting optimization with solver: {solver}..."
    # --- START OF FIX: Pass dispatchable_share and minimum_soc to extra_functionality ---
    # Only use extra_functionality if at least one constraint is active
    if (dispatchable_share is not None and dispatchable_share > 0) or \
       (minimum_soc is not None and minimum_soc > 0):
        # Pass parameters to the combined_extra_functionality wrapper
        n.optimize(solver_name=solver,
                   extra_functionality=lambda n_net, snapshots: combined_extra_functionality(n_net, snapshots, dispatchable_share, minimum_soc))
    else:
        n.optimize(solver_name=solver)
    # --- END OF FIX ---
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Optimization finished."

    # --- DIAGNOSTICS ---
    yield f"[{datetime.now().strftime('%H:%M:%S')}] --- OPTIMIZATION DIAGNOSTICS ---"
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Objective: {n.objective:.2f}" if n.objective is not None else "[Not Available]"
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Generators_t.p is empty: {n.generators_t.p.empty}"
    if not n.generators_t.p.empty:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Dispatch nonzero: {n.generators_t.p.sum().sum() > 0}"
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Dispatch shape: {n.generators_t.p.shape}"
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Loads_t.p_set is empty: {n.loads_t.p_set.empty}"
    if not n.loads_t.p_set.empty:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Loads nonzero: {n.loads_t.p_set.sum().sum() > 0}"
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Loads shape: {n.loads_t.p_set.shape}"
    yield f"[{datetime.now().strftime('%H:%M:%S')}] --- END DIAGNOSTICS ---"

    # --------------------------
    # Save outputs
    # --------------------------
    n.export_to_netcdf(os.path.join(full_results_path_prefix, f"{scenario_name}.nc"))
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Network results saved to {os.path.join(full_results_path_prefix, f'{scenario_name}.nc')}"

    csv_sub_folder_path = os.path.join(full_results_path_prefix, "csv_outputs")
    os.makedirs(csv_sub_folder_path, exist_ok=True)
    n.export_to_csv_folder(csv_sub_folder_path)  # Export all standard PyPSA CSVs first

    # --- Export generators_t.p (dispatch) to CSV ---
    if not n.generators_t.p.empty:
        dispatch_csv_path = os.path.join(csv_sub_folder_path, f"generators-dispatch_{scenario_name}.csv")
        n.generators_t.p.to_csv(dispatch_csv_path)
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Hourly dispatch data saved to {dispatch_csv_path}"
    else:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] No hourly dispatch data to save."

    # --- CSV RENAMING LOGIC (for standard PyPSA CSVs) ---
    for filename in os.listdir(csv_sub_folder_path):
        if filename.endswith(".csv"):
            base_name = os.path.splitext(filename)[0]
            if not base_name.endswith(f"_{scenario_name}"):
                new_filename = f"{base_name}_{scenario_name}.csv"
                old_path = os.path.join(csv_sub_folder_path, filename)
                new_path = os.path.join(csv_sub_folder_path, new_filename)
                # Only rename if file exists and new name is different
                if os.path.exists(old_path) and os.path.basename(old_path) != new_filename:
                    os.rename(old_path, new_path)
    yield f"[{datetime.now().strftime('%H:%M:%S')}] Detailed CSV results saved and renamed with scenario tag to {csv_sub_folder_path}"

    # --- START OF FIX: Save CAPEX and OPEX to CSV in csv_outputs folder ---
    try:
        # Re-calculate costs for CSV export (ensures consistency)
        NEGLIGIBLE_SLACK_GENERATION_MWh = 0.001
        NEGLIGIBLE_SLACK_COST_USD = 1.0
        total_slack_gen_mwh_for_csv = n.generators_t.p[
            'slack'].sum() if 'slack' in n.generators.index and 'slack' in n.generators_t.p.columns and not n.generators_t.p.empty else 0
        is_slack_contributing_for_csv = abs(total_slack_gen_mwh_for_csv) > NEGLIGIBLE_SLACK_GENERATION_MWh

        if not n.generators.empty and not n.generators_t.p.empty:
            df_gen_costs_for_csv = n.generators.copy()
            df_gen_costs_for_csv['annual_capital_cost'] = df_gen_costs_for_csv['capital_cost'] * df_gen_costs_for_csv[
                'p_nom_opt']
            df_gen_costs_for_csv['annual_fixed_om_cost'] = df_gen_costs_for_csv.get('fixed_cost', 0) * \
                                                           df_gen_costs_for_csv['p_nom_opt']

            gen_annual_dispatch_MWh_sum_for_csv = n.generators_t.p.sum()
            df_gen_costs_for_csv['annual_variable_cost'] = gen_annual_dispatch_MWh_sum_for_csv * df_gen_costs_for_csv[
                'marginal_cost']

            df_gen_costs_for_csv['annual_om_cost'] = df_gen_costs_for_csv['annual_fixed_om_cost'] + \
                                                     df_gen_costs_for_csv['annual_variable_cost']

            df_costs_by_carrier_aggregated_for_csv = df_gen_costs_for_csv.groupby('carrier')[
                ['annual_capital_cost', 'annual_om_cost']].sum().reset_index()

            if 'slack' in df_costs_by_carrier_aggregated_for_csv[
                'carrier'].values and not is_slack_contributing_for_csv:
                df_costs_by_carrier_aggregated_for_csv = df_costs_by_carrier_aggregated_for_csv[
                    df_costs_by_carrier_aggregated_for_csv['carrier'] != 'slack']

            df_costs_by_carrier_aggregated_for_csv = df_costs_by_carrier_aggregated_for_csv[
                (df_costs_by_carrier_aggregated_for_csv['annual_capital_cost'].abs() > NEGLIGIBLE_SLACK_COST_USD) |
                (df_costs_by_carrier_aggregated_for_csv['annual_om_cost'].abs() > NEGLIGIBLE_SLACK_COST_USD)
                ].copy()

            # Prepare CAPEX data for saving
            df_capex_to_save = df_costs_by_carrier_aggregated_for_csv[['carrier', 'annual_capital_cost']].rename(
                columns={'annual_capital_cost': 'Annual Capital Cost (USD/year)'})
            capex_csv_path = os.path.join(csv_sub_folder_path, f"generator_capex_by_carrier_{scenario_name}.csv")
            df_capex_to_save.to_csv(capex_csv_path, index=False)
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Saved 'generator_capex_by_carrier_{scenario_name}.csv' to {csv_sub_folder_path}"

            # Prepare OPEX data for saving
            df_opex_to_save = df_costs_by_carrier_aggregated_for_csv[['carrier', 'annual_om_cost']].rename(
                columns={'annual_om_cost': 'Annual O&M Cost (USD/year)'})
            opex_csv_path = os.path.join(csv_sub_folder_path, f"generator_opex_by_carrier_{scenario_name}.csv")
            df_opex_to_save.to_csv(opex_csv_path, index=False)
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Saved 'generator_opex_by_carrier_{scenario_name}.csv' to {csv_sub_folder_path}"
        else:
            yield f"[{datetime.now().strftime('%H:%M:%S')}] No generator data available to save CAPEX/OPEX CSVs."
    except Exception as e:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Error saving CAPEX/OPEX CSVs: {e}"
    # --- END OF FIX ---

    # --- Generate capacity_location.csv ---
    try:
        if not n.buses.empty and not n.generators.empty:
            buses_for_loc = n.buses[['x', 'y']].rename(columns={'x': 'lon', 'y': 'lat'})

            generators_for_loc = n.generators[['carrier', 'p_nom_opt', 'bus']].copy()
            
            # Fix 4: Filter slack from capacity_location.csv if negligible
            NEGLIGIBLE_SLACK_CAPACITY_MW = 0.01
            generators_for_loc = generators_for_loc[~((generators_for_loc['carrier'] == 'slack') & (generators_for_loc['p_nom_opt'] < NEGLIGIBLE_SLACK_CAPACITY_MW))]

            grouped_generators_for_loc = generators_for_loc.groupby(['bus', 'carrier']).sum('p_nom_opt').reset_index()

            merged_capacity_location_df = pd.merge(buses_for_loc, grouped_generators_for_loc, left_index=True,
                                                   right_on='bus', how='left')
            merged_capacity_location_df.rename(columns={'bus': 'Bus name'}, inplace=True)

            # Handle potential duplicate lat/lon columns from merge if 'bus' was also in original bus data
            if 'lon_x' in merged_capacity_location_df.columns:
                merged_capacity_location_df['lon'] = merged_capacity_location_df['lon_x'].fillna(
                    merged_capacity_location_df['lon_y'])
                merged_capacity_location_df['lat'] = merged_capacity_location_df['lat_x'].fillna(
                    merged_capacity_location_df['lat_y'])
                merged_capacity_location_df.drop(columns=['lon_x', 'lat_x', 'lon_y', 'lat_y'], inplace=True)

            if 'bus' in merged_capacity_location_df.columns:
                merged_capacity_location_df.drop(columns=['bus'], inplace=True)

            capacity_location_csv_path = os.path.join(full_results_path_prefix,
                                                      f"capacity_location_{scenario_name}.csv")
            merged_capacity_location_df.to_csv(capacity_location_csv_path, index=False)
            yield f"[{datetime.now().strftime('%H:%M:%S')}] Capacity location data saved to {capacity_location_csv_path}"
        else:
            yield f"[{datetime.now().strftime('%H:%M:%S')}] No bus or generator data to create capacity_location.csv."
    except Exception as e:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Error generating capacity_location.csv: {e}"

    # --- NEW: Call create_plots for HTML outputs (Fix 8: All GUI plots) ---
    try:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Generating HTML plots..."
        create_plots(n, full_results_path_prefix, scenario_name, scenario_year)
        yield f"[{datetime.now().strftime('%H:%M:%S')}] HTML plots generated in plots/ subfolder."
    except Exception as e:
        yield f"[{datetime.now().strftime('%H:%M:%S')}] Error generating HTML plots: {e}"

    yield f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {scenario_name} finished. All results saved."

    yield (n, full_results_path_prefix)