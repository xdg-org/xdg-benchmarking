[models]
Tokamak = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/tokamak
ATR = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/atr
MSRE = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/msre
# REGRESSION_TEST = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/regression_test
# SIMPLE_TOKAMAK = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/simple_tokamak

[options]
executable_label = xdg
executable_path = /home/pshriwise/internal/xdg/soft/rt-xdg/opt/bin/openmc
output = True
particles_per_thread = 500
max_threads = 80
n_repeats = 1
