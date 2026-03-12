"""
Minimal test: AgGrid with getRowStyle (row colors).
Run: streamlit run app/test_aggrid_colors.py
If you see one green row and one red row, AgGrid row styling works in your environment.
"""
import streamlit as st
import pandas as pd

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
    HAS_AGGRI = True
except ImportError:
    HAS_AGGRI = False

st.set_page_config(page_title="AgGrid color test", layout="centered")

st.title("AgGrid row color test")
st.caption("If you see one row green and one row red, getRowStyle works. If both rows are plain, it does not.")

if not HAS_AGGRI:
    st.error("streamlit-aggrid not installed. Run: pip install streamlit-aggrid")
    st.stop()

# Tiny dataframe: 2 rows, Status = Vacant / Occupied
df = pd.DataFrame([
    {"Name": "Kitchen A", "Status": "Vacant"},
    {"Name": "Kitchen B", "Status": "Occupied"},
])

# getRowStyle: green for Vacant, red for Occupied
get_row_style = JsCode("""
function(params) {
    if (!params || !params.data) return null;
    var s = (params.data.Status || '').toString().toLowerCase();
    if (s === 'vacant') return { backgroundColor: '#D1FAE5' };
    if (s === 'occupied') return { backgroundColor: '#FEE2E2' };
    return null;
}
""")

gb = GridOptionsBuilder.from_dataframe(df)
gb.configure_default_column(filter=True, sortable=True)
go = gb.build()
go["getRowStyle"] = get_row_style

AgGrid(
    df,
    gridOptions=go,
    height=150,
    allow_unsafe_jscode=True,
)

st.success("Table above. If row 1 is green and row 2 is red, styling works.")
