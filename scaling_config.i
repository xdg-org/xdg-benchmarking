[executables]
double-down = /home/pshriwise/internal/xdg/soft/rt-double-down/opt/bin/openmc
xdg = /home/pshriwise/internal/xdg/soft/rt-xdg/opt/bin/openmc
moab = /home/pshriwise/internal/xdg/soft/rt-moab/opt/bin/openmc

# Optional limit on number of threads for some of the executables
[exec_max_threads]
moab = 30

[models]
Tokamak = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/tokamak
ATR = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/atr
MSRE = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/msre
# REGRESSION_TEST = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/regression_test
# SIMPLE_TOKAMAK = /home/pshriwise/internal/xdg/benchmarking/xdg-benchmark-models/simple_tokamak

[options]
output = True
particles_per_thread = 500
max_threads = 80
n_repeats = 1
