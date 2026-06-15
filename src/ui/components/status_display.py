from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Iterable

import streamlit as st

from src.ui.components.help_dock import help_term_html


@dataclass(frozen=True)
class StatusItem:
    label: str
    value: object
    tone: str = "neutral"
    help_key: object | None = None
    help_text: str | None = None


def _clean_text(value: object) -> str:
    text = "无" if value is None else str(value)
    return text if text.strip() else "无"


def build_status_grid_html(items: Iterable[StatusItem], *, dense: bool = False) -> str:
    cards = []
    for item in items:
        tone = str(item.tone or "neutral").strip().lower()
        if tone not in {"neutral", "green", "yellow", "red", "blue"}:
            tone = "neutral"
        label_html = help_term_html(
            _clean_text(item.label),
            key=item.help_key,
            help_text=item.help_text,
        )
        cards.append(
            "<div class=\"hmm-status-card hmm-status-card--{tone}\">"
            "<div class=\"hmm-status-card__label\">{label}</div>"
            "<div class=\"hmm-status-card__value\">{value}</div>"
            "</div>".format(
                tone=escape(tone),
                label=label_html,
                value=escape(_clean_text(item.value)),
            )
        )
    if not cards:
        return ""
    dense_class = " hmm-status-grid--dense" if dense else ""
    return f"<div class=\"hmm-status-grid{dense_class}\">{''.join(cards)}</div>"


def render_status_grid(items: Iterable[StatusItem], *, dense: bool = False) -> None:
    html = build_status_grid_html(items, dense=dense)
    if not html:
        return
    st.markdown(
        html,
        unsafe_allow_html=True,
    )
