"""Small local TA compatibility layer used by Quant Bot.
Implements only the indicator classes required by this repository, avoiding a
runtime dependency on the external `ta` package.
"""
from . import trend, volatility, momentum
