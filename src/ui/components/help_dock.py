from __future__ import annotations

from html import escape
from typing import Iterable, Mapping

import streamlit as st

from src.ui.help_texts import explain_term


DEFAULT_HELP_TEXT = "当前页面的关键指标会在这里显示说明。"


def help_term_html(label: object, *, key: object | None = None, help_text: str | None = None) -> str:
    text = "无" if label is None else str(label)
    explanation = help_text or explain_term(key if key is not None else text) or explain_term(text)
    if not explanation:
        return escape(text)
    return (
        "<span class=\"hmm-help-term\" tabindex=\"0\" data-help=\"{help_text}\" title=\"{help_text}\">{label}</span>"
    ).format(
        label=escape(text),
        help_text=escape(str(explanation), quote=True),
    )


def render_help_dock() -> None:
    st.markdown(
        "<div class=\"hmm-help-dock\">"
        "<span class=\"hmm-help-dock__label\">指标解释</span>"
        f"<span class=\"hmm-help-dock__text\">{escape(DEFAULT_HELP_TEXT)}</span>"
        "</div>",
        unsafe_allow_html=True,
    )


def build_help_chip_row_html(keys: Iterable[object], *, labels: Mapping[object, str] | None = None) -> str:
    chips: list[str] = []
    for key in keys:
        label = labels.get(key, str(key)) if labels else str(key)
        explanation = explain_term(key) or explain_term(label)
        if not explanation:
            continue
        chips.append(
            "<span class=\"hmm-help-chip\">{term}</span>".format(
                term=help_term_html(label, key=key, help_text=explanation)
            )
        )
    if not chips:
        return ""
    return "<div class=\"hmm-help-chip-row\">{}</div>".format("".join(chips))


def render_help_chip_row(keys: Iterable[object], *, labels: Mapping[object, str] | None = None) -> None:
    html = build_help_chip_row_html(keys, labels=labels)
    if html:
        st.markdown(html, unsafe_allow_html=True)
