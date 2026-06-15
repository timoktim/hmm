from __future__ import annotations

import streamlit as st


def render_app_layout_css() -> None:
    st.markdown(
        """
<style>
div[data-testid="column"],
div[data-testid="stMetric"],
div[data-testid="stMetric"] > div {
  min-width: 0;
}

div[data-testid="stMetric"] [data-testid="stMetricLabel"],
div[data-testid="stMetric"] [data-testid="stMetricValue"],
div[data-testid="stCaptionContainer"],
div[data-testid="stCaptionContainer"] p,
div[data-testid="stMarkdownContainer"] p,
div[data-testid="stAlert"] p {
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}

div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
  line-height: 1.25;
}

div[data-testid="stMetric"] [data-testid="stMetricValue"] {
  line-height: 1.18;
}

section.main > div[data-testid="stMainBlockContainer"] {
  padding-bottom: 5.5rem;
}

.hmm-help-dock,
.hmm-help-term:hover::after,
.hmm-help-term:focus-visible::after,
.hmm-help-term:focus::after {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 999999;
  min-height: 3.25rem;
  padding: 0.65rem 1.1rem;
  border-top: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(12, 18, 30, 0.97);
  color: rgba(255, 255, 255, 0.94);
  box-shadow: 0 -8px 28px rgba(0, 0, 0, 0.24);
  font-size: 0.9rem;
  line-height: 1.45;
}

.hmm-help-term:hover::after,
.hmm-help-term:focus-visible::after,
.hmm-help-term:focus::after {
  content: attr(data-help);
  display: block;
  z-index: 1000001;
  pointer-events: none;
  white-space: normal;
  overflow-wrap: anywhere;
}

.hmm-help-dock {
  display: flex;
  gap: 0.7rem;
  align-items: center;
}

.hmm-help-dock__label {
  flex: 0 0 auto;
  color: rgba(255, 255, 255, 0.72);
  font-size: 0.78rem;
  letter-spacing: 0;
}

.hmm-help-dock__text {
  min-width: 0;
  overflow-wrap: anywhere;
}

.hmm-help-term {
  border-bottom: 1px dotted currentColor;
  cursor: help;
  outline: none;
}

.hmm-help-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.38rem;
  margin: 0.25rem 0 0.65rem;
}

.hmm-help-chip {
  border: 1px solid rgba(128, 128, 128, 0.24);
  border-radius: 999px;
  padding: 0.14rem 0.48rem 0.18rem;
  background: rgba(128, 128, 128, 0.08);
  font-size: 0.78rem;
  line-height: 1.35;
}

.hmm-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
  gap: 0.5rem;
  margin: 0.35rem 0 0.85rem;
}

.hmm-status-grid--dense {
  grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
}

.hmm-status-card {
  min-width: 0;
  border: 1px solid rgba(128, 128, 128, 0.24);
  border-left-width: 3px;
  border-radius: 6px;
  padding: 0.48rem 0.62rem;
  background: rgba(128, 128, 128, 0.06);
}

.hmm-status-card--green {
  border-left-color: #2e7d32;
}

.hmm-status-card--yellow {
  border-left-color: #b7791f;
}

.hmm-status-card--red {
  border-left-color: #c62828;
}

.hmm-status-card--blue {
  border-left-color: #2b6cb0;
}

.hmm-status-card--neutral {
  border-left-color: rgba(128, 128, 128, 0.52);
}

.hmm-status-card__label {
  color: rgba(128, 128, 128, 0.92);
  font-size: 0.78rem;
  line-height: 1.2;
  margin-bottom: 0.18rem;
  overflow-wrap: anywhere;
}

.hmm-status-card__value {
  font-size: 0.94rem;
  font-weight: 600;
  line-height: 1.25;
  overflow-wrap: anywhere;
  word-break: break-word;
}
</style>
        """,
        unsafe_allow_html=True,
    )
