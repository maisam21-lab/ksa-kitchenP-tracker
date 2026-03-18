"""
Internal App Marketplace — one place to find and open your org's Streamlit apps.
Run: streamlit run marketplace_app.py
Deploy on Streamlit Cloud with this file as the main script.
"""
import os
from pathlib import Path

import streamlit as st
import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "marketplace_config.yaml"


def load_config():
    if not CONFIG_PATH.exists():
        return {
            "title": "Our apps",
            "subtitle": "Add marketplace_config.yaml to list your apps.",
            "apps": [
                {
                    "name": "KSA Kitchen Tracker",
                    "description": "Master Kitchens, Dashboard, and Discussions.",
                    "url": "https://ksa-kitchenp-tracker-dcl4vvscpgpgeamjbmpnyj.streamlit.app/",
                    "owner": "Operations",
                }
            ],
        }
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    st.set_page_config(page_title="App marketplace", layout="wide", initial_sidebar_state="collapsed")
    config = load_config()
    title = config.get("title") or "Our apps"
    subtitle = config.get("subtitle") or "Internal tools and dashboards."
    apps = config.get("apps") or []

    st.markdown(f"## {title}")
    st.caption(subtitle)
    st.divider()

    if not apps:
        st.info("No apps in config yet. Edit **marketplace_config.yaml** to add entries.")
        return

    # Cards in a responsive grid (3 per row)
    n_cols = 3
    for row_start in range(0, len(apps), n_cols):
        row_apps = apps[row_start : row_start + n_cols]
        cols = st.columns(n_cols)
        for j, app in enumerate(row_apps):
            with cols[j]:
                name = app.get("name") or "App"
                description = app.get("description") or ""
                url = (app.get("url") or "").strip()
                owner = app.get("owner") or ""
                st.markdown(f"### {name}")
                if owner:
                    st.caption(owner)
                st.markdown(description)
                if url:
                    st.link_button("Open app →", url=url, type="primary", use_container_width=True)
                else:
                    st.caption("(URL not set)")
                st.divider()

    st.caption("Edit **marketplace_config.yaml** in the repo to add or change apps. Redeploy to refresh.")


if __name__ == "__main__":
    main()
