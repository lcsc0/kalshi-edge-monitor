Vendored from https://github.com/shiyu-coder/Kronos (commit 67b630e, MIT, see LICENSE).
Copied: model/{__init__,kronos,module}.py. Only local change: `from model.module import *`
-> `from .module import *` in kronos.py. Weights are NOT vendored; they load from the
Hugging Face Hub (NeoQuasar/Kronos-*). Kronos forecasts OHLCV candlesticks.
