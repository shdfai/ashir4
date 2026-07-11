# ai/

The previous 5-model machine-learning ensemble (`ensemble.py` — LSTM +
XGBoost + Random Forest + Gradient Boosting + a PPO reinforcement-learning
agent) has been removed.

The bot's strategy is now 100% rule-based: **SuperTrend + Price Action
(BOS/CHoCH + candlestick patterns) + a simplified Elliott Wave filter**.
See `strategies/engine.py` for the full, explainable logic and
`core/indicators.py` for how each signal is computed.

This folder is kept (currently empty) in case a future rule-based scoring
module is added here again.
