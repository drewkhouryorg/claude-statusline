Recorded from an Alpine 3.20 container on an arm64 Linux VM (kernel 6.x):
`stat-idle.txt` (first line of /proc/stat), `meminfo-roomy.txt` and `psi-calm.txt`.

Made from those by hand, to stand for a machine under memory pressure:
`meminfo-tight.txt` (4% available, 1.3G in zswap, 1.2G of 2G swap used),
`psi-stalling.txt` (tasks stalled on memory 23.5% of the last 10s) and
`vmstat-swapping.txt` (2.8G swapped out since boot).
