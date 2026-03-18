"""
Internal App Marketplace — sidebar catalog + preview pane (like Streamlit's template gallery).
Run: streamlit run marketplace_app.py
"""
from pathlib import Path

import streamlit as st
import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "marketplace_config.yaml"


def load_config():
    if not CONFIG_PATH.exists():
        return {
            "title": "Our apps",
            "subtitle": "Add marketplace_config.yaml to list your apps.",
            "categories": [
                {
                    "name": "Data apps",
                    "apps": [
                        {
                            "name": "KSA Kitchen Tracker",
                            "description": "Master Kitchens, Dashboard, and Discussions.",
                            "url": "https://ksa-kitchenp-tracker-dcl4vvscpgpgeamjbmpnyj.streamlit.app/",
                            "owner": "Operations",
                        }
                    ],
                }
            ],
        }
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Support legacy flat "apps" list as a single category
    if data.get("apps") and not data.get("categories"):
        data["categories"] = [{"name": "Apps", "apps": data["apps"]}]
    return data


def main():
    st.set_page_config(page_title="App marketplace", layout="wide", initial_sidebar_state="expanded")
    config = load_config()
    title = config.get("title") or "Our apps"
    subtitle = config.get("subtitle") or "Internal tools and dashboards."
    categories = config.get("categories") or []

    # Build flat list of all apps with (category_name, app)
    all_apps = []
    for cat in categories:
        cat_name = cat.get("name") or "Apps"
        for app in cat.get("apps") or []:
            all_apps.append((cat_name, app))

    if not all_apps:
        st.info("No apps in config yet. Edit **marketplace_config.yaml** to add entries.")
        return

    # Sidebar: categories and app names (like the template gallery)
    st.sidebar.markdown(f"**{title}**")
    st.sidebar.caption(subtitle)
    st.sidebar.divider()

    # Which app is selected (stored when user clicks a sidebar button)
    selected_app = st.session_state.get("marketplace_selected_app_data")
    if selected_app is None and all_apps:
        selected_app = all_apps[0][1]
        st.session_state["marketplace_selected_app_data"] = selected_app

    for cat_name, apps_in_cat in [(c.get("name"), c.get("apps") or []) for c in categories]:
        if not apps_in_cat:
            continue
        st.sidebar.markdown(f"**{cat_name}**")
        for app in apps_in_cat:
            name = app.get("name") or "App"
            app_key = f"mp_{cat_name}_{name}_{app.get('url', '')}".replace(" ", "_").replace("/", "_").replace(":", "_")[:80]
            if st.sidebar.button(name, key=app_key, use_container_width=True):
                st.session_state["marketplace_selected_app_data"] = app
                st.rerun()
        st.sidebar.markdown("")

    # Main area: preview pane (like "My new app" + description + View demo)
    st.markdown(f"## {selected_app.get('name') or 'App'}")
    if selected_app.get("owner"):
        st.caption(selected_app.get("owner"))
    st.markdown(selected_app.get("description") or "No description.")
    url = (selected_app.get("url") or "").strip()
    if url:
        st.link_button("View demo →", url=url, type="primary")
    else:
        st.caption("(URL not set in config)")
    st.divider()
    st.caption("Edit **marketplace_config.yaml** to add or change apps. Redeploy to refresh.")


if __name__ == "__main__":
    main()
