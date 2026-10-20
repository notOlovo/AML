"""The sidebar: which dataset, which weights, where the review threshold sits."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from amlcopilot import validation
from amlcopilot.config import DEFAULT_WEIGHTS, REVIEW_AT
from amlcopilot.io import datasets

ADD_DATASET = "+ Add dataset"


@dataclass
class Settings:
    """What the sidebar decided this run."""
    folder: str
    weights: dict
    review_at: int
    ready: bool = True
    message: str = ""


def _set_weights(values: dict) -> None:
    # runs as a button callback, i.e. before the sliders are drawn again
    for key, value in values.items():
        st.session_state[f"w_{key}"] = float(value)


def _dataset_picker(root: Path, folders: list[str]) -> tuple[str, bool]:
    """Returns the chosen dataset and whether the run can go ahead."""
    default = os.environ.get("AML_DATA", "data/real")
    choice = st.selectbox("Dataset", folders + [ADD_DATASET],
                          index=folders.index(default) if default in folders else 0)
    if choice != ADD_DATASET:
        return choice, True

    st.caption("Upload the two CSV files required by the AML pipeline.")
    clients_file = st.file_uploader("clients.csv", type=["csv"], key="clients_upload")
    transactions_file = st.file_uploader("transactions.csv", type=["csv"], key="transactions_upload")
    if st.button("Add dataset", disabled=not clients_file or not transactions_file):
        folder = datasets.add(root, clients_file.name,
                              clients_file.getbuffer(), transactions_file.getbuffer())
        # a dataset that cannot be scored is removed again, so the selector never offers a broken one
        report = validation.check(folder)
        if not report.ok:
            datasets.remove(root, folder.name)
            st.error(report.summary())
            return (folders[0] if folders else ""), False
        for warning in report.warnings:
            st.warning(warning)
        st.success(f"Dataset '{folder.name}' added: {report.clients:,} clients, "
                   f"{report.transactions:,} transactions.")
        st.rerun()
    return (folders[0] if folders else ""), bool(clients_file and transactions_file)


def draw(root: Path, role: str) -> Settings:
    folders = datasets.available(root)
    with st.sidebar:
        st.markdown('<div class="aml-settings-label">Settings</div>', unsafe_allow_html=True)
        folder, ready = _dataset_picker(root, folders)
        for key, value in DEFAULT_WEIGHTS.items():
            st.session_state.setdefault(f"w_{key}", float(value))

        # Only a supervisor moves the weights; a user works the queue as configured.
        if role == "Supervisor":
            st.subheader("Stage 2 weights")
            weights = {k: st.slider(k.replace("_", " "), 0.0, 50.0, step=0.5, key=f"w_{k}")
                       for k in DEFAULT_WEIGHTS}
            review_at = st.slider("Send to human review from score", 10, 80,
                                  int(REVIEW_AT))
            st.button("Reset to default weights", on_click=_set_weights, args=(DEFAULT_WEIGHTS,))
            st.caption(f"Sum {sum(weights.values()):.1f}, rescaled to 100.")
            if sum(weights.values()) <= 0:
                st.warning("Every weight is zero: stage 2 scores nobody, only the hard rules decide.")
        else:
            weights = {k: st.session_state[f"w_{k}"] for k in DEFAULT_WEIGHTS}
            review_at = int(REVIEW_AT)
            st.markdown(
                '<div class="aml-user-hint">User mode · choose an existing dataset or add a new '
                'CSV dataset.</div>',
                unsafe_allow_html=True,
            )

    message = "" if ready else "Choose both clients.csv and transactions.csv in the sidebar to add a dataset."
    return Settings(folder=folder, weights=weights, review_at=review_at, ready=ready, message=message)