"""The Streamlit layer: everything that draws, and nothing that decides.

Every module here may import streamlit; nothing under amlcopilot/ may. That is
the whole split — the risk engine, the screening rules, the datasets and the
decision log can be tested and run from the command line with no UI at all.
"""
