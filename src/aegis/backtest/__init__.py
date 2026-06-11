"""Walk-forward backtesting + Monte Carlo calibration (P1.6, Concept §17).

The cardinal rule: the backtest calls THE SAME functions the live engine
will call - aegis.strategy.screening / kalman / zscore and aegis.risk.sizing
/ costs. There is no second implementation of any pillar here; a backtest of
different code would validate nothing.
"""
