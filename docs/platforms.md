# macOS and Linux

Everything except the system column (CPU, memory and battery) is plain Python and git, so it's the same everywhere. The system column reads each OS's own measures. The status line was built on macOS, and the Linux readers were added to match it. The test suite runs on both in CI. `make test-linux` also runs it in Alpine and Debian containers, which you run by hand.

WSL counts as Linux. Windows outside WSL isn't supported: the wrapper and installer need bash, and the `project-info` helper uses Unix file locks.

## Where each reading comes from

| Reading | macOS | Linux | Why they differ |
| - | - | - | - |
| CPU busy % | `host_statistics` from the Mach kernel, via `ctypes` | `/proc/stat` | Each kernel's own tick counters. Both give busy time between two samples, kept in `cache/cpu-ticks.json`. |
| Load and cores | `sysctl vm.loadavg`, `hw.ncpu` | `/proc/loadavg`, `os.cpu_count()` | |
| Busiest process | `ps -Arco pcpu,comm` | `ps -eo pcpu,comm --sort=-pcpu` | BSD and GNU `ps` take different flags. Asked only when the CPU is saturated. |
| Memory pressure | `kern.memorystatus_vm_pressure_level` | `/proc/pressure/memory` (PSI) | See below. |
| How full memory is | `kern.memorystatus_level` | `MemAvailable` in `/proc/meminfo` | |
| Compressed memory (`comp`) | `vm_stat`, pages occupied by the compressor | `Zswap` in `/proc/meminfo` | macOS always compresses memory. Linux does only with zswap on, so `comp` is often missing on Linux. |
| Swap in use | `sysctl vm.swapusage` | `SwapTotal` minus `SwapFree` | |
| Swap moving (arrows) | `Swapins` and `Swapouts` in `vm_stat` | `pswpin` and `pswpout` in `/proc/vmstat` | |
| Biggest app | each process's footprint from `proc_pid_rusage`, the same number as Activity Monitor; resident memory for a VM | `VmRSS` in `/proc/<pid>/status` | See below. |
| Battery | `pmset -g batt` | `/sys/class/power_supply/*/capacity` and `status` | |

## Memory pressure

macOS publishes a pressure level (normal, warn or critical), the same one Activity Monitor graphs. The status line uses it as is.

Linux has no single level, so the status line makes one from pressure stall information (PSI). PSI reports the share of the last 10 seconds in which some task was stalled waiting on memory:

- under 10%: normal
- 10% to 40%: warn
- 40% and over: critical

The thresholds are `PSI_WARN` and `PSI_CRIT` in `statusline.py`. Kernels older than 4.20, or built without PSI, have no `/proc/pressure`. On those, it falls back to how much memory is available: under 10% is warn and under 5% is critical.

## Naming the biggest app

On a Mac, a process belongs to the outermost `.app` bundle it runs from, so Chrome's dozens of helper processes add up as "Chrome". A virtual machine runs as Apple's virtualization service, so it's named after the process that launched it. That name comes from a private but long-standing macOS call, `responsibility_get_pid_responsible_for_pid`. If that call ever goes away, the VM shows as "VM" and nothing breaks. Colima VMs are named "colima". OrbStack runs its VM inside its own helper app, so it shows as "OrbStack".

For a VM, the count is its resident memory, because footprint misleads both ways: a Linux guest that zeroes its memory at boot reads as its whole size, though macOS stores zeroed pages for almost nothing, and OrbStack's VM memory doesn't appear in its helper's footprint at all. Resident memory is closer for both, though it leaves out what macOS has compressed.

`sysctl` is called as `/usr/sbin/sysctl`, so the readings still work when Claude Code's `PATH` leaves out `/usr/sbin`.

On Linux, a process goes by its name in `/proc/<pid>/status`, and processes with the same name are added up. Resident memory (`VmRSS`) counts shared pages in each process that maps them, so a browser's total can read higher than on a Mac.

Only processes you can read are counted on both. Root's processes are left out, since they aren't yours to quit.

## Making it work somewhere else

All the platform code is in the gathering section of `statusline/statusline.py`, under `gather_system()`. A reader returns the same shapes the renderer already understands:

```python
{"battery": {"pct": 64, "ac": True},
 "cpu": {"usage": 41, "load": "3.10", "cores": 8, "top": "node"},
 "memory": {"pressure": 1, "used_pct": 58, "comp_mb": 4506, "swap_mb": 2848,
            "swapped_out_mb": 12.0, "swapped_in_mb": 3.0}}
```

Every key is optional. Leave out what a platform can't measure and that part of the column goes away.

To add a platform:

1. Write parsers that take the raw text, so they can be tested with recorded files. `parse_memory_linux` and `tests/test_linux.py` show the pattern.
2. Record the platform's files or command output into `tests/data/<platform>/`.
3. Add a branch in `gather_system()` and in `cpu_ticks()`.
4. Add a scenario showing a typical reading, and re-record the snapshots (see [testing](testing.md)).
