"""Hardware detection -> local-model recommendation.

The UI lets every user pick a local model appropriate to THEIR machine; this
module powers the default recommendation and the per-tier 'fits' hints.
"""

from __future__ import annotations

from ..config import LOCAL_MODEL_TIERS, get_settings
from ..models.schemas import HardwareInfo, LocalModelOption


def _ram_gb() -> tuple[float, float, int]:
    try:
        import psutil

        vm = psutil.virtual_memory()
        return (round(vm.total / 1e9, 1), round(vm.available / 1e9, 1), psutil.cpu_count() or 1)
    except Exception:
        import os

        return (8.0, 4.0, os.cpu_count() or 1)


def recommend_local_model(total_ram_gb: float | None = None) -> str:
    if total_ram_gb is None:
        total_ram_gb, _, _ = _ram_gb()
    # leave headroom: require the tier to fit in ~70% of total RAM
    budget = total_ram_gb * 0.7
    chosen = LOCAL_MODEL_TIERS[0]["model"]
    for tier in LOCAL_MODEL_TIERS:
        if budget >= tier["min_ram_gb"]:
            chosen = tier["model"]
    return chosen


def hardware_info() -> HardwareInfo:
    total, avail, cpus = _ram_gb()
    settings = get_settings()
    recommended = settings.local_model or recommend_local_model(total)
    budget = total * 0.7
    options = [
        LocalModelOption(
            model=t["model"], label=t["label"], min_ram_gb=t["min_ram_gb"],
            fits=budget >= t["min_ram_gb"],
        )
        for t in LOCAL_MODEL_TIERS
    ]
    return HardwareInfo(
        total_ram_gb=total,
        available_ram_gb=avail,
        cpu_count=cpus,
        recommended_local_model=recommended,
        options=options,
    )
