"""Read-only hardware inventory with explicit unknowns and data provenance.

Only reports data returned by the host; never treats dedicated VRAM as system RAM.
No elevated privileges are required. Unsupported sensors are marked unavailable.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess


def run(argv, timeout=5):
    if not shutil.which(argv[0]):
        return ""
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def integer(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def meminfo():
    data = {}
    for line in read("/proc/meminfo").splitlines():
        m = re.match(r"^([A-Za-z_()]+):\s+(\d+)\s+kB", line)
        if m:
            data[m.group(1)] = int(m.group(2)) * 1024
    return data


def cpu():
    info = run(["lscpu", "-J"])
    parsed = {}
    if info:
        try:
            for item in json.loads(info)["lscpu"]:
                parsed[item["field"].rstrip(":")] = item["data"].strip()
        except (ValueError, KeyError, TypeError):
            pass
    raw = read("/proc/cpuinfo")
    flags = next(
        (
            x.split(":", 1)[1].strip().split()
            for x in raw.splitlines()
            if x.startswith(("flags\t", "Features\t"))
        ),
        [],
    )
    mhz = []
    for line in raw.splitlines():
        if line.startswith("cpu MHz"):
            try:
                mhz.append(round(float(line.split(":", 1)[1].strip()), 1))
            except ValueError:
                pass
    freqs = []
    for p in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/cpuinfo_max_freq"):
        v = integer(read(p))
        if v:
            freqs.append(v / 1000)
    sockets = integer(parsed.get("Socket(s)"))
    physical = integer(parsed.get("Core(s) per socket"))
    return {
        "architecture": parsed.get("Architecture") or platform.machine(),
        "vendor": parsed.get("Vendor ID"),
        "model": parsed.get("Model name"),
        "physical_cores": physical * sockets if physical and sockets else None,
        "logical_threads": integer(parsed.get("CPU(s)")) or os.cpu_count(),
        "current_clock_mhz_per_logical_cpu": mhz,
        "max_reported_clock_mhz": max(freqs) if freqs else parsed.get("CPU max MHz"),
        "base_clock_mhz": None,  # Not always exposed by the kernel; never infer from current speed.
        "cache": {
            k: parsed.get(k) for k in ("L1d cache", "L1i cache", "L2 cache", "L3 cache")
        },
        "supported_instruction_flags": flags,
        "source": ["lscpu", "/proc/cpuinfo", "sysfs cpufreq"],
    }


def gpu():
    cards = []
    nvidia = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,memory.total,memory.free,driver_version,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        8,
    )
    if nvidia:
        for row in nvidia.splitlines():
            fields = [x.strip() for x in row.split(",")]
            if len(fields) < 8:
                continue
            idx, name, uuid, total, free, driver, temp, util = fields[:8]
            tot = integer(total)
            avail = integer(free)
            item = {
                "index": integer(idx),
                "vendor": "NVIDIA",
                "name": name,
                "uuid": uuid,
                "driver": driver,
                "memory_kind": "dedicated_device_vram_reported_by_nvidia_smi",
                "dedicated_vram_mib": tot,
                "available_vram_mib": avail,
                "shared_system_ram_mib": None,
                "vram_bandwidth_gbps": None,
                "vram_memory_type": None,
                "temperature_c": integer(temp),
                "gpu_utilization_pct": integer(util),
                "compute_capability": None,
                "clocks_mhz": {},
                "backend_candidates": ["CUDA"],
                "source": "nvidia-smi",
            }
            for field, label in [
                ("compute_cap", "compute_capability"),
                ("clocks.current.graphics", "graphics_clock_mhz"),
                ("clocks.current.memory", "memory_clock_mhz"),
                ("memory.type", "vram_memory_type"),
            ]:
                result = run(
                    [
                        "nvidia-smi",
                        f"--query-gpu={field}",
                        "--format=csv,noheader,nounits",
                    ],
                    4,
                )
                if not result:
                    continue
                values = result.splitlines()
                n = item["index"]
                if n is None or n >= len(values):
                    continue
                v = values[n].strip()
                if not v or v == "[Not Supported]":
                    continue
                if label in ("graphics_clock_mhz", "memory_clock_mhz"):
                    item["clocks_mhz"][label] = integer(v)
                else:
                    item[label] = v
            cards.append(item)
    pci = run(["lspci", "-D", "-nn"], 8)
    for line in pci.splitlines():
        if not re.search(
            r"\b(VGA compatible controller|3D controller|Display controller):",
            line,
            re.I,
        ):
            continue
        if any(g["vendor"] == "NVIDIA" and "NVIDIA" in line for g in cards):
            continue
        vendor = (
            "NVIDIA"
            if "NVIDIA" in line
            else "AMD"
            if re.search("AMD|ATI", line, re.I)
            else "Intel"
            if "Intel" in line
            else "Other"
        )
        cards.append(
            {
                "vendor": vendor,
                "pci_device_description": line,
                "memory_kind": "unknown_pci_gpu",
                "dedicated_vram_mib": None,
                "available_vram_mib": None,
                "shared_system_ram_mib": None,
                "backend_candidates": [
                    "ROCm (compatibility unverified)",
                    "Vulkan (compatibility unverified)",
                ]
                if vendor == "AMD"
                else ["CUDA (driver unverified)"]
                if vendor == "NVIDIA"
                else ["CPU fallback"],
                "source": "lspci; GPU memory unverified",
            }
        )
    return cards


def disks():
    raw = run(
        [
            "lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,PATH,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL,TRAN,ROTA,UUID",
        ],
        8,
    )
    if raw:
        try:
            return json.loads(raw)["blockdevices"]
        except (ValueError, KeyError):
            pass
    return []


def storage_details():
    devices = disks()

    def decorate(dev):
        if dev.get("type") == "disk":
            dev["medium"] = (
                "nvme"
                if str(dev.get("tran", "")).lower() == "nvme"
                else "rotational_hdd"
                if str(dev.get("rota", "")).lower() in ("1", "true")
                else "solid_state_or_nonrotational"
                if str(dev.get("rota", "")).lower() in ("0", "false")
                else "unknown"
            )
        mounts = dev.get("mountpoints") or []
        if isinstance(mounts, str):
            mounts = [mounts]
        dev["mounted_free_bytes"] = {}
        for mp in mounts:
            if not mp:
                continue
            try:
                dev["mounted_free_bytes"][mp] = shutil.disk_usage(mp).free
            except OSError:
                pass
        for child in dev.get("children", []) or []:
            decorate(child)

    for dev in devices:
        decorate(dev)
    return devices


def ram_speed():
    if os.geteuid() != 0:
        return None
    output = run(["dmidecode", "-t", "memory"], timeout=8)
    speeds = []
    for match in re.finditer(
        r"^\s*Configured Memory Speed:\s*(\d+)\s*(?:MT/s|MHz)", output, re.M
    ):
        speeds.append(int(match.group(1)))
    return sorted(set(speeds)) if speeds else None


def desktop_details():
    labels = (
        "Operating System",
        "KDE Plasma Version",
        "KDE Frameworks Version",
        "Qt Version",
        "Kernel Version",
        "Graphics Platform",
        "Processors",
        "Memory",
    )
    details = {}
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    if "kde" in desktop or os.environ.get("KDE_FULL_SESSION") == "true":
        for line in run(["kinfo"], timeout=8).splitlines():
            label, _, value = line.partition(":")
            if value.strip() and (
                label in labels
                or re.fullmatch(r"Graphics Processor [1-9][0-9]?", label)
            ):
                details[label] = value.strip()
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session in ("wayland", "x11", "tty"):
        details.setdefault(
            "Graphics Platform",
            {"wayland": "Wayland", "x11": "X11", "tty": "Console"}[session],
        )
    for label, file in (
        ("Manufacturer", "sys_vendor"),
        ("Product Name", "product_name"),
        ("System Version", "product_version"),
    ):
        value = read(Path("/sys/class/dmi/id") / file)
        if value:
            details[label] = value
    return details


def inventory():
    m = meminfo()
    osrel = {}
    for line in read("/etc/os-release").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            osrel[k] = v.strip().strip('"')
    return {
        "schema": 1,
        "hostname": platform.node(),
        "system": {
            "os": osrel.get("PRETTY_NAME", platform.system()),
            "os_id": osrel.get("ID"),
            "kernel": platform.release(),
            "architecture": platform.machine(),
        },
        "cpu": cpu(),
        "gpus": gpu(),
        "ram": {
            "total_bytes": m.get("MemTotal"),
            "available_bytes": m.get("MemAvailable"),
            "swap_total_bytes": m.get("SwapTotal"),
            "speed_mt_s": ram_speed(),
            "speed_note": "Requires trustworthy DIMM SPD/firmware data; not guessed from CPU",
        },
        "storage": storage_details(),
        "accelerators": {
            "nvidia_smi_available": bool(run(["nvidia-smi", "-L"])),
            "vulkaninfo_available": bool(shutil.which("vulkaninfo")),
            "rocm_smi_available": bool(shutil.which("rocm-smi")),
        },
        "notes": [
            "Dedicated VRAM is separate from RAM; do not add them as a single GPU memory pool.",
            "Missing sensor values are null, not fabricated.",
            "Hardware presence does not certify a usable inference backend.",
        ],
    }


def profile(info):
    ram = info["ram"]["total_bytes"] or 0
    candidates = [
        g
        for g in info["gpus"]
        if g.get("vendor") == "NVIDIA" and g.get("dedicated_vram_mib")
    ]
    best = max(candidates, key=lambda g: g["dedicated_vram_mib"], default=None)
    vram = best["dedicated_vram_mib"] if best else 0
    if best and vram <= 6144:
        context = 2048
        recommended = ["qwen3:1.7b", "llama3.2:3b"]
        mode = "cuda (runtime validation required)"
    elif best and vram <= 12288:
        context = 4096
        recommended = ["llama3.2:3b"]
        mode = "cuda (runtime validation required)"
    elif best:
        context = 8192
        recommended = ["llama3.2:3b"]
        mode = "cuda (runtime validation required)"
    else:
        context = 2048 if ram < 16 * 1024**3 else 4096
        recommended = ["qwen3:1.7b"]
        mode = "cpu (GPU backend not verified)"
    threads = info["cpu"]["physical_cores"] or info["cpu"]["logical_threads"] or 1
    return {
        "mode": mode,
        "recommended_models": recommended,
        "default_model": recommended[0],
        "context": context,
        "parallel_requests": 1,
        "max_loaded_models": 1,
        "max_queue": 16,
        "cpu_threads_hint": threads,
        "memory_safety": "No forced GPU layers, clocks, or VRAM allocation",
        "reason": "Conservative inference defaults pending measurements on this host",
        "gpu_vram_mib": vram,
        "host_ram_gib": round(ram / 1024**3, 2),
    }
