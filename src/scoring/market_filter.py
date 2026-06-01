from __future__ import annotations


def market_regime_risk_message(state_label: str | None) -> str:
    label = str(state_label or "Neutral")
    if label == "RiskOn":
        return "当前大盘状态为风险偏好，板块趋势信号可按正常权重观察。"
    if label == "RiskOff":
        return "当前大盘状态为风险回避，板块相对强势可能只是抗跌，信号应降权看待。"
    return "当前大盘状态为中性震荡，建议减少候选数量，优先观察最强且数据质量较好的板块。"
