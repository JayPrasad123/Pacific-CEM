import streamlit as st


def show_tab():
    st.title("About PacCEM")
    st.markdown("""
    Welcome to **PacCEM (Pacific Capacity Expansion Model)**, your user-friendly tool for understanding and planning future power systems, especially for small and island grids.

    PacCEM is designed to empower a wide range of users – from utility managers and regulators to researchers and students – to explore different energy scenarios without needing deep programming expertise. Our goal is to make power system analysis transparent, repeatable, and accessible, even when working offline.
    """)

    st.subheader("How to Use PacCEM")
    st.markdown("""
    PacCEM guides you through a clear, step-by-step process across its main tabs:

    1.  **Project Tab:** This is where you begin your analysis!
        *   **Project Details:** Name your project and choose where your simulation results will be saved on your computer.
        *   **Scenario Parameters:** Define the `Scenario Year` you're modeling, set `Load Data` growth, select an `Optimization Solver` (like HiGHS), and configure important policy targets such as `CO2 Caps` (to limit emissions) or `Renewable Energy Share` (to promote green energy).
        *   **Reliability & Storage Controls:** Enhance grid stability by setting a `Reserve Margin` (extra capacity for unexpected events), define a `Minimum Dispatchable Generation Share` (ensuring steady power from controllable sources), and specify a `Minimum Battery State of Charge (SOC)` to protect battery life.
        *   **Technology & Cost:** Enable or disable specific power generation and storage technologies (like Solar, Wind, Diesel, Battery Storage) and apply `Cost Multipliers` to model future price changes.
        *   **Data Upload:** Upload your main Excel file containing all your power system data (buses, generators, loads, etc.).

    2.  **Data Mapping Tab:** Once your Excel file is uploaded, this tab helps PacCEM understand your data.
        *   You can select the specific Excel `Sheet` for each power system component (like `Buses`, `Generators`, `Load Data`, `Storage`).
        *   **Auto-Matching:** The system will intelligently `auto-match` column names from your selected sheet to what PacCEM expects (e.g., 'Bus name', 'Capacity', 'Lifetime'), saving you time.
        *   **Profile Column:** For renewable `Generators`, you'll map a `Profile Column` from your generator data that points to specific hourly generation data in your `Generation Profiles` sheet.
        *   **Manual Entry:** If you prefer, you can `Manually Enter` data directly into interactive tables instead of using Excel.

    3.  **Simulation Tab:** Ready to run your analysis?
        *   After saving all your mapped data, click 'Run Simulation'. You'll see a live log tracking the model's progress.
        *   **Interactive Map:** Once complete, an interactive map will visualize your power grid, showing all assets including generators and newly built battery storage, with filter options.
        *   **Comprehensive Plots:** Explore the `7 detailed plots` generated to interpret your results:
            *   **Optimal Capacity:** Total installed capacity by technology.
            *   **Technology Mix:** Pie charts for capacity and generation shares.
            *   **Cost Breakdown:** Annual system costs by type (e.g., capital, variable) and by individual generator carrier (CAPEX vs OPEX).
            *   **LCOE by Carrier:** A stacked bar showing the Levelized Cost of Electricity for each technology.
            *   **Capacity Factor:** The average utilization of each generator technology.
            *   **Storage Behaviour:** Plots for battery State of Charge (SOC) and charging/discharging power over time.
            *   **Hourly Generation Dispatch:** A stacked area chart showing how each technology contributed to meeting demand hour-by-hour.
        *   **Download Results:** Download all raw data, plots (as HTML files), and model outputs in a comprehensive ZIP archive.

    4.  **Compare Tab:** If you've run multiple scenarios, this tab lets you compare their key numerical metrics side-by-side. Just upload the `.nc` (NetCDF) result files, and PacCEM will extract and display essential data for an easy comparison.
    """)

    st.subheader("Built with")
    st.markdown("""
    PacCEM is built on powerful, open-source tools, leveraging the best of Python for energy system modeling:

    *   **Frontend (User Interface):** [Streamlit](https://streamlit.io/) (a Python web framework for creating interactive web applications)
    *   **Backend (Power System Optimization):** [PyPSA](https://pypsa.org/) (Python for Power System Analysis, a framework for simulating and optimizing power systems)
    *   **Data Handling:** Pandas (for data manipulation), SQLite (for per-project data persistence), YAML (for scenario configuration), Excel/CSV (for flexible input data), and NetCDF/CSV/HTML (for rich outputs).
    *   **Solvers:** Compatible with leading optimization solvers such as HiGHS (default), CBC, GLPK, and Gurobi (user-selectable, requires separate installation and licensing for commercial solvers).
    """)

    st.subheader("Requirements")
    st.markdown("""
    To run PacCEM locally, you'll need:

    *   Python 3.8 or newer.
    *   All required Python packages listed in the `requirements.txt` file (these can be installed using `pip install -r requirements.txt`).
    *   At least one PyPSA-compatible optimization solver installed and accessible (e.g., HiGHS is generally included with PyPSA, but others like CBC or Gurobi may require separate installation).
    """)

    st.subheader("Builder Information")
    st.info("""
    *   Developed by a dedicated team to democratize access to power system modeling for sustainable energy planning in the Pacific region and beyond.
    """)