"""Canonical Streamlit entry point.

The dashboard contains the application UI and pipeline. Execute it as the
Streamlit script on every rerun (rather than importing a cached module).
"""

import runpy
from pathlib import Path


dashboard_path = Path(__file__).resolve().with_name("dashboard.py")
runpy.run_path(str(dashboard_path), run_name="__main__")
