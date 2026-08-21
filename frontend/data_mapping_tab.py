import streamlit as st
import pandas as pd
import io
import ast # For literal_eval
import difflib
import streamlit.components.v1 as components

def inject_nav_buttons():
    st.markdown("<div id='data-mapping-marker' style='position:absolute; width:0; height:0; overflow:hidden;'></div>", unsafe_allow_html=True)
    html_code = """
    <script>
    const parentDoc = window.parent.document;
    
    if (!parentDoc.getElementById('nav-left-btn')) {
        const style = parentDoc.createElement('style');
        style.innerHTML = `
        .nav-btn {
            position: fixed;
            top: 50%;
            transform: translateY(-50%);
            font-size: 60px;
            background: transparent;
            color: rgba(128, 128, 128, 0.2);
            border: none;
            cursor: pointer;
            z-index: 99999;
            padding: 20px;
            transition: color 0.3s;
            user-select: none;
        }
        .nav-btn:hover {
            color: rgba(128, 128, 128, 0.8);
        }
        #nav-left-btn { left: 10px; }
        #nav-right-btn { right: 10px; }
        `;
        parentDoc.head.appendChild(style);

        const btnLeft = parentDoc.createElement('button');
        btnLeft.id = 'nav-left-btn';
        btnLeft.className = 'nav-btn';
        btnLeft.innerHTML = '&#10094;';
        btnLeft.onclick = function() {
            const allTabs = parentDoc.querySelectorAll('div[role="tabpanel"] div[data-testid="stTabs"] button[role="tab"]');
            const tabs = Array.from(allTabs).filter(tab => tab.offsetParent !== null);
            let activeIndex = -1;
            for(let i=0; i<tabs.length; i++) {
                if(tabs[i].getAttribute('aria-selected') === 'true') { activeIndex = i; break; }
            }
            if(activeIndex > 0) tabs[activeIndex - 1].click();
        };
        parentDoc.body.appendChild(btnLeft);

        const btnRight = parentDoc.createElement('button');
        btnRight.id = 'nav-right-btn';
        btnRight.className = 'nav-btn';
        btnRight.innerHTML = '&#10095;';
        btnRight.onclick = function() {
            const allTabs = parentDoc.querySelectorAll('div[role="tabpanel"] div[data-testid="stTabs"] button[role="tab"]');
            const tabs = Array.from(allTabs).filter(tab => tab.offsetParent !== null);
            let activeIndex = -1;
            for(let i=0; i<tabs.length; i++) {
                if(tabs[i].getAttribute('aria-selected') === 'true') { activeIndex = i; break; }
            }
            if(activeIndex !== -1 && activeIndex < tabs.length - 1) tabs[activeIndex + 1].click();
        };
        parentDoc.body.appendChild(btnRight);

        const script = parentDoc.createElement('script');
        script.innerHTML = `
            setInterval(function() {
                const marker = document.getElementById('data-mapping-marker');
                const btnL = document.getElementById('nav-left-btn');
                const btnR = document.getElementById('nav-right-btn');
                if (btnL && btnR) {
                    if (marker && marker.offsetParent !== null) {
                        btnL.style.display = 'block';
                        btnR.style.display = 'block';
                        const allTabs = document.querySelectorAll('div[role="tabpanel"] div[data-testid="stTabs"] button[role="tab"]');
                        const tabs = Array.from(allTabs).filter(tab => tab.offsetParent !== null);
                        if(tabs.length > 0) {
                            if(tabs[0].getAttribute('aria-selected') === 'true') btnL.style.visibility = 'hidden';
                            else btnL.style.visibility = 'visible';
                            
                            if(tabs[tabs.length-1].getAttribute('aria-selected') === 'true') btnR.style.visibility = 'hidden';
                            else btnR.style.visibility = 'visible';
                        }
                    } else {
                        btnL.style.display = 'none';
                        btnR.style.display = 'none';
                    }
                }
            }, 200);
        `;
        parentDoc.body.appendChild(script);
    }
    </script>
    """
    components.html(html_code, height=0, width=0)

def get_best_match(target, choices, cutoff=0.9):
    if not choices: return None
    if target in choices: return target
    
    lower_choices = {str(c).lower(): c for c in choices}
    target_lower = str(target).lower()
    if target_lower in lower_choices:
        return lower_choices[target_lower]
        
    best_ratio = 0
    best_choice = None
    for choice in choices:
        choice_lower = str(choice).lower()
        ratio = difflib.SequenceMatcher(None, target_lower, choice_lower).ratio()
        if ratio > best_ratio and ratio >= cutoff:
            best_ratio = ratio
            best_choice = choice
    return best_choice

TOOLTIP_MAPPING = {
    'Bus name': 'Unique identifier for the bus node. Mandatory for connecting components. Unmapped: causes error.',
    'v_nom': 'Nominal voltage of the bus in kV. Unmapped: defaults to standard or ignores if single-voltage.',
    'x': 'Longitude coordinate for mapping. Unmapped: bus will not display on geographic plots.',
    'y': 'Latitude coordinate for mapping. Unmapped: bus will not display on geographic plots.',
    'carrier': 'Energy carrier type (e.g. AC, DC). Unmapped: defaults to AC in most PyPSA setups.',
    'unit': 'Optional unit description. Unmapped: ignored.',
    'Generator name': 'Unique identifier for the generator. Unmapped: autogenerated or errors.',
    'Bus': 'Bus node where the generator is connected. Must match a Bus name. Unmapped: errors.',
    'Capacity(MW)': 'Nominal capacity (p_nom) in MW. Base size of the unit. Unmapped: defaults to 0 MW.',
    'Size (MW)': 'Explicit unit size in MW, overriding Capacity if Quantity > 1. Unmapped: Capacity is distributed by Quantity.',
    'Quantity': 'Number of identical units to build. Unmapped: defaults to 1.',
    'Build Year': 'Year the generator was built. Unmapped: ignored unless multi-period optimization is used.',
    'P_nom_min': 'Minimum capacity limit for expansion. Unmapped: defaults to 0 MW.',
    'P_nom_max': 'Maximum capacity limit for expansion. Unmapped: defaults to infinity.',
    'Carrier': 'Primary energy carrier (e.g. Solar, Wind, Gas). Drives physics, costs, and emissions. Unmapped: defaults to generic generation.',
    'Scenario': 'Specific scenario this component belongs to. Unmapped: component applies to all scenarios.',
    'p_nom_extendable': 'Boolean (True/False) indicating if the solver can expand the capacity optimally. Unmapped: defaults to project settings (usually False).',
    'Marginal cost (USD/MWh)': 'Variable operation cost (fuel + variable O&M). Unmapped: defaults to 0.',
    'Capital_cost (USD/MW)': 'Overnight investment cost per MW (CAPEX). Will be annuitized over lifetime. Unmapped: defaults to 0.',
    'fixed_O&M (USD/MW/year)': 'Fixed annual operation and maintenance cost per MW. Unmapped: defaults to 0.',
    'lifetime': 'Expected operational lifetime in years. Used to calculate annualized CAPEX. Unmapped: defaults to 25 years.',
    'Status': '0 for Existing, 1 for New Build. Determines if initial capacity is forced or optimized. Unmapped: defaults to Existing.',
    'efficiency': 'Conversion efficiency (electrical output / thermal input). Unmapped: defaults to 1.0 (100%).',
    'p_min_pu': 'Minimum dispatch limit (per unit of nominal capacity). Unmapped: defaults to 0.0.',
    'Profile Column': 'Column name in Generation Profiles containing the hourly dispatch profile (p_max_pu). Unmapped: falls back to generic carrier profile (e.g. "Solar profile") or 0.0 power.',
    'From': 'Starting bus node. Must match a Bus name. Unmapped: errors.',
    'To': 'Ending bus node. Must match a Bus name. Unmapped: errors.',
    'type': 'Standard type of the line (e.g. for automatic impedance calculation). Unmapped: uses explicit x, r, b parameters if provided.',
    's_nom_extendable': 'Boolean (True/False) if the line capacity can be expanded optimally. Unmapped: defaults to project line expansion setting.',
    's_nom': 'Nominal apparent power capacity in MVA. Unmapped: defaults to 0 MVA.',
    'Capital_cost (USD/MVA)': 'Investment cost per MVA of line capacity. Unmapped: defaults to 0.',
    'Length (kM)': 'Length of the line in kilometers. Unmapped: defaults to 1.0 km.',
    'name': 'Unique identifier for the component. Unmapped: auto-generated or errors.',
    'bus0': 'Starting bus node. Unmapped: errors.',
    'bus1': 'Ending bus node. Unmapped: errors.',
    'v_nom0': 'Nominal voltage at bus0. Unmapped: defaults to bus0 voltage.',
    'v_nom1': 'Nominal voltage at bus1. Unmapped: defaults to bus1 voltage.',
    'r': 'Series resistance. Unmapped: defaults to 0.0.',
    'num_parallel': 'Number of parallel identical transformers. Unmapped: defaults to 1.',
    'p_nom (MW)': 'Charge/discharge capacity of the storage in MW. Unmapped: defaults to 0.',
    'e_nom (MWh)': 'Energy capacity of the storage in MWh. Unmapped: defaults to 0.',
    'Year': 'Installation year. Unmapped: ignored.',
    'e_nom_extendable': 'Boolean (True/False) if energy capacity can be optimized. Unmapped: defaults to False.',
    'Capital_cost (USD/MW)': 'Investment cost per MW of storage power capacity. Unmapped: defaults to 0.'
}

MANDATORY_FIELDS = {
    "buses": ['Bus name'],
    "generators": ['Generator name', 'Bus'],
    "transmission_lines": ['From', 'To'],
    "transformers": ['name', 'bus0', 'bus1'],
    "storage": ['name', 'Bus']
}

# Helper function to read a sheet and populate dropdowns
def get_sheet_and_columns(sheet_name, excel_file_buffer):
    if not excel_file_buffer or not sheet_name:
        return None, []
    try:
        df = pd.read_excel(io.BytesIO(excel_file_buffer), sheet_name=sheet_name)
        return df, df.columns.tolist()
    except Exception as e:
        st.error(f"Error reading sheet '{sheet_name}': {e}")
        return None, []


# Helper to render dropdown for column selection
def column_selector(component_type, attribute_name, columns, default_value=None, auto_selected_value=None):
    key = f"{component_type}_{attribute_name}_col"
    st.session_state.mapped_data[component_type] = st.session_state.mapped_data.get(component_type, {})

    # 1. Prioritize user's saved value
    current_value = st.session_state.mapped_data[component_type].get(attribute_name, None)

    # 2. If no user saved value, use auto_selected_value
    if current_value is None:
        current_value = auto_selected_value

    # 3. If still no value, use hardcoded default_value
    if current_value is None:
        current_value = default_value

    options = ["-- Select --"] + columns

    # Determine the correct index for the selectbox
    selected_index = 0
    if current_value in columns:
        selected_index = columns.index(current_value) + 1
    elif default_value in columns: # Fallback to hardcoded default if current_value not in options
        selected_index = columns.index(default_value) + 1

    tooltip_text = TOOLTIP_MAPPING.get(attribute_name, f"Select the column from the Excel sheet that contains {attribute_name}.")
    
    is_mandatory = attribute_name in MANDATORY_FIELDS.get(component_type, [])
    
    col1, col2, _ = st.columns(3)
    with col1:
        selected_col = st.selectbox(
            f'"{attribute_name}" Column',
            options=options,
            index=selected_index,
            key=key,
            help=tooltip_text
        )
    
    with col2:
        st.write("") # Spacer to align with selectbox vertically
        st.write("")
        if selected_col != "-- Select --":
            import difflib
            similarity = difflib.SequenceMatcher(None, str(attribute_name).lower(), str(selected_col).lower()).ratio()
            if similarity < 0.4 and str(selected_col).lower() not in str(attribute_name).lower() and str(attribute_name).lower() not in str(selected_col).lower():
                st.warning(f"⚠️ Mapped '{selected_col}', but expected '{attribute_name}'")
            else:
                st.success(f"✅ Mapped to '{selected_col}'")
        else:
            if is_mandatory:
                st.error("❌ Required - Missing mapping will cause errors.")
            else:
                st.warning("⚠️ Optional - Will use default or fallback behavior.")

    if selected_col != "-- Select --":
        st.session_state.mapped_data[component_type][attribute_name] = selected_col
        return selected_col
    else:
        st.session_state.mapped_data[component_type].pop(attribute_name, None)
        return None

# Helper to render data editor for manual entry
def manual_data_editor(component_type, default_cols):
    # Fix 2: UI renaming for Load Data
    display_name = "Load Data" if component_type == "demand" else component_type.replace('_', ' ').title()
    st.markdown(f"**Manually Enter {display_name}**")
    
    # Initialize DataFrame in session_state if not present or columns changed
    if component_type not in st.session_state.manual_data or \
       list(st.session_state.manual_data[component_type].columns) != default_cols:
        st.session_state.manual_data[component_type] = pd.DataFrame(columns=default_cols)

    edited_df = st.data_editor(
        st.session_state.manual_data[component_type],
        num_rows="dynamic",
        key=f"manual_{component_type}_editor"
    )
    st.session_state.manual_data[component_type] = edited_df
    

def show_tab():
    st.title("Data Mapping & Manual Entry")
    
    inject_nav_buttons()

    if not st.session_state.get('excel_file_buffer'):
        st.warning("Please upload an Excel file in the 'Project' tab to enable Excel mapping.")
        return

    excel_sheet_names = st.session_state.get('excel_sheet_names', [])
    if not excel_sheet_names:
        st.warning("No sheets found in the uploaded Excel file. Please check the file.")
        return

    if 'data_mapping_mode' not in st.session_state:
        st.session_state.data_mapping_mode = {}

    component_types_spec = {
        "buses": ['Bus name', 'v_nom', 'x', 'y', 'carrier', 'unit'],
        "demand": [], # Special handling for demand (all columns are data)
        "generators": ['Generator name', 'Bus', 'Capacity(MW)', 'Size (MW)', 'Quantity', 'Build Year', 'P_nom_min', 'P_nom_max', 'Carrier', 'Scenario', 'p_nom_extendable', 'Marginal cost (USD/MWh)', 'Capital_cost (USD/MW)', 'fixed_O&M (USD/MW/year)', 'lifetime', 'Status', 'efficiency', 'p_min_pu', 'Profile Column'],
        "transmission_lines": ['From', 'To', 'type', 's_nom_extendable', 's_nom', 'Capital_cost (USD/MVA)', 'Length (kM)', 'Scenario'],
        "transformers": ['name', 'bus0', 'bus1', 's_nom', 'v_nom0', 'v_nom1', 'x', 'r', 'Capital_cost (USD/MW)', 'Scenario', 'num_parallel'],
        'storage': ['name', 'p_nom (MW)', 'e_nom (MWh)', 'Year', 'Carrier', 'Bus', 'Scenario', 'e_nom_extendable', 'Marginal cost (USD/MWh)', 'Capital_cost (USD/MW)', 'lifetime', 'Status'],
        "generation_profiles": []
    }

    sub_tab_names = list(component_types_spec.keys())
    
    # Fix 2: Renaming tab title for Demand -> Load Data
    tab_titles = [name.replace('_', ' ').title() if name != "demand" else "Load Data" for name in sub_tab_names]

    # Calculate status colors for tabs and inject CSS
    css_string = "<style>\n"
    for i, component_type in enumerate(sub_tab_names):
        has_error = False
        if st.session_state.data_mapping_mode.get(component_type, "Excel Mapping") == "Excel Mapping":
            if component_type in MANDATORY_FIELDS:
                for attr in MANDATORY_FIELDS[component_type]:
                    mapped_val = st.session_state.mapped_data.get(component_type, {}).get(attr)
                    if not mapped_val or mapped_val == "-- Select --":
                        has_error = True
        
        is_saved = st.session_state.get(f"is_saved_{component_type}", False)
        
        if has_error:
            color = "#ff6666" # light red
        elif not is_saved:
            color = "#ffcc00" # light yellow
        else:
            color = "#99ff99" # light green
            
        # Target the p element inside the sub-tabs only (tabs inside a tabpanel)
        css_string += f'div[role="tabpanel"] div[data-testid="stTabs"] button[role="tab"]:nth-child({i+1}) p {{ border-bottom: 3px solid {color} !important; }}\n'
    
    css_string += "</style>"
    st.markdown(css_string, unsafe_allow_html=True)

    sub_tabs = st.tabs(tab_titles)

    for i, component_type in enumerate(sub_tab_names):
        with sub_tabs[i]:
            # Fix 2: UI renaming
            display_name = "Load Data" if component_type == "demand" else component_type.replace('_', ' ').title()
            
            st.subheader(f"{display_name}")
            
            st.session_state.data_mapping_mode[component_type] = st.radio(
                f"Select data input mode for {display_name}",
                ("Excel Mapping", "Manual Entry"),
                key=f"{component_type}_mode_radio",
                index=0 if st.session_state.data_mapping_mode.get(component_type, "Excel Mapping") == "Excel Mapping" else 1,
            )

            if st.session_state.data_mapping_mode[component_type] == "Excel Mapping":
                st.session_state.mapped_data[component_type] = st.session_state.mapped_data.get(component_type, {})
                selected_sheet_key = f"{component_type}_sheet_selector"
                
                saved_sheet = st.session_state.mapped_data[component_type].get('sheet_name')
                if saved_sheet in excel_sheet_names:
                    default_sheet_index = excel_sheet_names.index(saved_sheet) + 1
                else:
                    auto_sheet = get_best_match(component_type, excel_sheet_names, cutoff=0.9)
                    if not auto_sheet:
                        auto_sheet = get_best_match(display_name, excel_sheet_names, cutoff=0.9)
                    if auto_sheet:
                        default_sheet_index = excel_sheet_names.index(auto_sheet) + 1
                    else:
                        default_sheet_index = 0

                col_sheet, _ = st.columns([1, 2])
                with col_sheet:
                    selected_sheet = st.selectbox(
                        f"Select Excel Sheet for {display_name}",
                        options=["-- Select --"] + excel_sheet_names,
                        index=default_sheet_index,
                        key=selected_sheet_key
                    )
                
                if selected_sheet != "-- Select --":
                    st.session_state.mapped_data[component_type]['sheet_name'] = selected_sheet
                    df_current_sheet, current_sheet_cols = get_sheet_and_columns(selected_sheet, st.session_state.excel_file_buffer)
                    if df_current_sheet is None:
                        continue

                    if component_type == "demand":
                        st.info("For Load Data, all columns except the index column (if any) will be considered load profiles for different buses.")
                        if df_current_sheet is not None:
                            st.dataframe(df_current_sheet.head())
                            st.session_state.mapped_data[component_type]['df_content'] = df_current_sheet.to_dict('list')
                    elif component_type == "generation_profiles":
                        # --- START OF FIX: Simplified Generation Profiles tab for site-specific mapping ---
                        st.info("For Generation Profiles, this sheet contains all hourly profiles. Individual generator profiles are mapped via 'Profile Column' in the Generators tab.")

                        if df_current_sheet is not None:
                            st.dataframe(df_current_sheet.head()) # Show preview of the raw profiles sheet
                            st.session_state.mapped_data[component_type]['df_content'] = df_current_sheet.to_dict('list')
                            st.session_state.mapped_data[component_type]['columns'] = df_current_sheet.columns.tolist() # Save columns for backend reference
                        else:
                            st.session_state.mapped_data[component_type].pop('df_content', None)
                            st.session_state.mapped_data[component_type].pop('columns', None)
                            st.warning("No data found in the selected generation profiles sheet.")
                        # --- END OF FIX ---
                    else:   # <--- THIS IS THE RESTORED 'ELSE' BLOCK FOR ALL OTHER COMPONENTS
                        # --- START OF FIX: Restored display and mapping for other components ---
                        if df_current_sheet is not None:
                            st.dataframe(df_current_sheet.head()) # Show preview

                            # Dictionary to store auto-matched column names
                            auto_matches = {}
                            for required_col_name in component_types_spec[component_type]:
                                best_match = get_best_match(required_col_name, current_sheet_cols, cutoff=0.9)
                                if best_match:
                                    auto_matches[required_col_name] = best_match
                                elif component_type == 'generators' and required_col_name == 'Profile Column':
                                    pass # Don't auto-match generic profiles here, rely on user to map specific ones

                            for col_name_spec in component_types_spec[component_type]:
                                auto_value_for_selector = auto_matches.get(col_name_spec, None)
                                # Pass the auto_value to the column_selector
                                column_selector(component_type, col_name_spec, current_sheet_cols,
                                                auto_selected_value=auto_value_for_selector)

                            st.session_state.mapped_data[component_type]['df_content'] = df_current_sheet.to_dict('list')
                        else:
                            st.session_state.mapped_data[component_type].pop('df_content', None)
                            st.warning("Please select a sheet and map its columns to proceed.")
                        # --- END OF FIX ---

            else: # Manual Entry
                manual_data_editor(component_type, component_types_spec[component_type] if component_type != "demand" else ['Bus'] + [f'Time_{i}' for i in range(8760)])
                if component_type == "generation_profiles":
                    st.warning("For manual generation profiles, ensure you enter 8760 hourly values for each enabled technology (values between 0 and 1). If a profile is missing for an enabled technology, it will generate 0 power.")


            if st.button(f"Save {display_name}", key=f"save_data_{component_type}"):
                st.session_state[f"is_saved_{component_type}"] = True
                st.success(f"{display_name} saved for current session.")
                st.rerun()