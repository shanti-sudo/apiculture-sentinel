import sys
from pathlib import Path

import streamlit as st

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# Configure pages
home_page = st.Page("home_landing.py", title="Home", icon="🏠", default=True)
fleet_page = st.Page("pages/fleet_command.py", title="Fleet Dashboard", icon="📡")
triage_page = st.Page("pages/hive_triage.py", title="Hive Triage", icon="🔬")

# Define navigation
pg = st.navigation([home_page, fleet_page, triage_page])
pg.run()
