#!/usr/bin/env python3
"""
satisfactory_clusters.py

K-means factory cluster optimiser for Satisfactory.

Clusters resource nodes using geography + production-chain affinity, assigns
production targets to each cluster proportionally, determines inter-cluster
shipping, then writes:
  clusters.md          – markdown table
  map-annotated.png    – world map with cluster centroids and node dots

Usage
-----
    python satisfactory_clusters.py nodes.json [--bases 6] [--affinity 2.0]
                                               [--map map.png] [--seed 42]
                                               [--threshold 0.05]

Requires: Pillow  (pip install Pillow)
"""

import json, math, argparse, random, textwrap, os, re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# Output rate table  (Mk.3 miner / Oil Extractor / Resource Well at 250 %)
# ═══════════════════════════════════════════════════════════════════════════════
OUTPUT_RATES: Dict[str, Dict[str, float]] = {
    "Solid":  {"Pure": 1200, "Normal": 600,  "Impure": 300},
    "Liquid": {"Pure":  600, "Normal": 300,  "Impure": 150},
    "Gas":    {"Pure":  300, "Normal": 150,  "Impure":  75},
}

# Raw resources recognised by the tool (nodes of any other type are skipped)
RESOURCE_CHAINS: set = {
    "Iron Ore", "Copper Ore", "Coal", "Limestone", "Crude Oil",
    "Bauxite", "Raw Quartz", "SAM", "Caterium Ore", "Nitrogen Gas", "Sulfur",
}

# Resources to skip entirely (nuclear already implemented, water unlimited)
SKIP_RESOURCES = {"Uranium", "Water"}

# ═══════════════════════════════════════════════════════════════════════════════
# Recipes
#   primary  – raw resource that "owns" this recipe for assignment
#   chain    – chain index
#   also     – optional secondary raw resource (soft co-location pull)
# ═══════════════════════════════════════════════════════════════════════════════
RECIPES: Dict[str, Dict] = {
    # Heavy Industry ──────────────────────────────────────────────────────────
    "Iron Ingot":               dict(primary="Iron Ore",     chain=0),
    "Copper Ingot":             dict(primary="Copper Ore",   chain=0),
    "Steel Ingot":              dict(primary="Iron Ore",     chain=0, also="Coal"),
    "Iron Plate":               dict(primary="Iron Ore",     chain=0),
    "Reinforced Iron Plate":    dict(primary="Iron Ore",     chain=0),
    "Steel Pipe":               dict(primary="Iron Ore",     chain=0, also="Coal"),
    "Steel Beam":               dict(primary="Iron Ore",     chain=0, also="Coal"),
    "Encased Industrial Beam":  dict(primary="Iron Ore",     chain=0, also="Coal"),
    "Modular Frame":            dict(primary="Iron Ore",     chain=0),
    "Heavy Modular Frame":      dict(primary="Iron Ore",     chain=0),
    "Versatile Framework":      dict(primary="Iron Ore",     chain=0),
    "Copper Powder":            dict(primary="Copper Ore",   chain=0),
    "Copper Sheet":             dict(primary="Copper Ore",   chain=0),
    "Wire":                     dict(primary="Iron Ore",     chain=0),
    "Cable":                    dict(primary="Iron Ore",     chain=1),  # Cable (Coated) uses oil
    "Concrete":                 dict(primary="Limestone",    chain=0),
    "Smart Plating":            dict(primary="Iron Ore",     chain=0),
    "EMCR":                     dict(primary="Iron Ore",     chain=6, also="Caterium Ore"),
    # Oil & Plastics ──────────────────────────────────────────────────────────
    "Plastic":                  dict(primary="Crude Oil",    chain=1),
    "Rubber":                   dict(primary="Crude Oil",    chain=1),
    "Heavy Oil Residue":        dict(primary="Crude Oil",    chain=1),
    "Petroleum Coke":           dict(primary="Crude Oil",    chain=1),
    "Fuel (Diluted)":           dict(primary="Crude Oil",    chain=1),
    # Aluminum ────────────────────────────────────────────────────────────────
    "Alumina Solution":         dict(primary="Bauxite",      chain=2),
    "Aluminum Scrap":           dict(primary="Bauxite",      chain=2, also="Coal"),
    "Aluminum Ingot":           dict(primary="Bauxite",      chain=2),
    "Aluminum Casing":          dict(primary="Bauxite",      chain=2),
    "Alclad Sheet":             dict(primary="Bauxite",      chain=2, also="Copper Ore"),
    "Heat Sink":                dict(primary="Bauxite",      chain=2, also="Crude Oil"),
    "Empty Fluid Tank":         dict(primary="Bauxite",      chain=2),
    # Quantum / SAM ───────────────────────────────────────────────────────────
    "Quartz Crystal":           dict(primary="Raw Quartz",   chain=3),
    "Silica":                   dict(primary="Raw Quartz",   chain=3),
    "Crystal Oscillator":       dict(primary="Raw Quartz",   chain=3, also="Crude Oil"),
    "Reanimated SAM":           dict(primary="SAM",          chain=3),
    "Ficsite Ingot":            dict(primary="SAM",          chain=3, also="Caterium Ore"),
    "Ficsite Trigon":           dict(primary="SAM",          chain=3),
    "Dark Matter Crystal":      dict(primary="SAM",          chain=3),
    "Time Crystal":             dict(primary="Raw Quartz",   chain=3),
    "Diamonds (Cloudy)":        dict(primary="Raw Quartz",   chain=3, also="Limestone"),
    "Excited Photonic Matter":  dict(primary="SAM",          chain=3),
    "Superposition Oscillator": dict(primary="Raw Quartz",   chain=3, also="SAM"),
    "Neural-Quantum Processor": dict(primary="SAM",          chain=3, also="Raw Quartz"),
    "Singularity Cell":         dict(primary="SAM",          chain=3, also="Copper Ore"),
    # Electronics ─────────────────────────────────────────────────────────────
    "Caterium Ingot":           dict(primary="Caterium Ore", chain=4),
    "Quickwire":                dict(primary="Caterium Ore", chain=4, also="Copper Ore"),
    "AI Limiter":               dict(primary="Caterium Ore", chain=4),
    "Circuit Board":            dict(primary="Crude Oil",    chain=4, also="Caterium Ore"),
    "High-Speed Connector":     dict(primary="Caterium Ore", chain=4, also="Raw Quartz"),
    "Computer":                 dict(primary="Caterium Ore", chain=4, also="Crude Oil"),
    "Supercomputer":            dict(primary="Caterium Ore", chain=4, also="Crude Oil"),
    "Automated Wiring":         dict(primary="Caterium Ore", chain=4, also="Iron Ore"),
    "Adaptive Control Unit":    dict(primary="Caterium Ore", chain=4),
    # Nitrogen ────────────────────────────────────────────────────────────────
    "Nitric Acid":              dict(primary="Nitrogen Gas", chain=5, also="Iron Ore"),
    "Packaged Nitrogen Gas":    dict(primary="Nitrogen Gas", chain=5),
    # Motors / Cooling ────────────────────────────────────────────────────────
    "Stator":                   dict(primary="Iron Ore",     chain=6),
    "Rotor":                    dict(primary="Iron Ore",     chain=6),
    "Motor":                    dict(primary="Iron Ore",     chain=6),
    "Cooling System":           dict(primary="Nitrogen Gas", chain=6, also="Bauxite"),
    "Turbo Motor":              dict(primary="Iron Ore",     chain=6, also="Nitrogen Gas"),
    "Fused Modular Frame":      dict(primary="Iron Ore",     chain=6, also="Nitrogen Gas"),
    "Modular Engine":           dict(primary="Iron Ore",     chain=6, also="Crude Oil"),
    "Radio Control Unit":       dict(primary="Raw Quartz",   chain=4, also="Bauxite"),
    "Pressure Conversion Cube": dict(primary="Iron Ore",     chain=6),
    # Space Elevator final assembly ───────────────────────────────────────────
    "Thermal Propulsion Rocket": dict(primary="Iron Ore",     chain=6),
    "Magnetic Field Generator":  dict(primary="Iron Ore",     chain=0),
    "Nuclear Pasta":             dict(primary="Copper Ore",   chain=0),
    "Assembly Director System":  dict(primary="Caterium Ore", chain=4),
    "AI Expansion Server":       dict(primary="SAM",          chain=3),
    "Ballistic Warp Drive":      dict(primary="SAM",          chain=3),
    "Biochemical Sculptor":      dict(primary="SAM",          chain=3),
}

# Final SE items are forced to the cluster nearest the Space Elevator (origin)
FINAL_ASSEMBLY = {
    "Thermal Propulsion Rocket", "Magnetic Field Generator", "Nuclear Pasta",
    "Assembly Director System", "AI Expansion Server", "Ballistic Warp Drive",
    "Biochemical Sculptor",
}

# product → products that consume it (for shipping determination)
CONSUMERS: Dict[str, List[str]] = {
    "Iron Ingot":            ["Iron Plate", "Reinforced Iron Plate", "Steel Ingot",
                              "Steel Pipe", "Steel Beam", "Modular Frame",
                              "Heavy Modular Frame", "Versatile Framework", "Wire",
                              "Stator", "Rotor", "Motor", "Fused Modular Frame",
                              "Smart Plating", "Ficsite Ingot", "EMCR"],
    "Copper Ingot":          ["Alclad Sheet", "Automated Wiring", "Quickwire",
                              "Copper Powder", "Copper Sheet"],
    "Steel Ingot":           ["Steel Pipe", "Steel Beam", "Encased Industrial Beam",
                              "Heavy Modular Frame", "Versatile Framework", "Rotor"],
    "Iron Plate":            ["Reinforced Iron Plate", "Nitric Acid"],
    "Reinforced Iron Plate": ["Modular Frame", "Smart Plating"],
    "Steel Pipe":            ["Encased Industrial Beam", "Stator"],
    "Steel Beam":            ["Encased Industrial Beam", "Versatile Framework"],
    "Encased Industrial Beam": ["Heavy Modular Frame"],
    "Modular Frame":         ["Heavy Modular Frame", "Modular Engine"],
    "Heavy Modular Frame":   ["Fused Modular Frame", "Adaptive Control Unit",
                              "Pressure Conversion Cube"],
    "Versatile Framework":   ["Magnetic Field Generator"],
    "Copper Powder":         ["Nuclear Pasta"],
    "Copper Sheet":          ["AI Limiter", "Circuit Board"],
    "Wire":                  ["Cable", "Stator", "Automated Wiring"],
    "Cable":                 ["Automated Wiring"],
    "Smart Plating":         ["Thermal Propulsion Rocket"],
    "Plastic":               ["Circuit Board", "Computer"],
    "Rubber":                ["Heat Sink", "Crystal Oscillator", "Modular Engine",
                              "Cable", "Radio Control Unit"],
    "Fuel (Diluted)":        ["Fused Modular Frame"],
    "Alumina Solution":      ["Aluminum Scrap"],
    "Aluminum Scrap":        ["Aluminum Ingot"],
    "Aluminum Ingot":        ["Alclad Sheet", "Aluminum Casing", "Heat Sink",
                              "Empty Fluid Tank"],
    "Alclad Sheet":          ["Heat Sink", "Superposition Oscillator"],
    "Aluminum Casing":       ["Radio Control Unit"],
    "Heat Sink":             ["Cooling System"],
    "Empty Fluid Tank":      ["Packaged Nitrogen Gas"],
    "Quartz Crystal":        ["Crystal Oscillator", "High-Speed Connector"],
    "Silica":                ["Crystal Oscillator", "Circuit Board",
                              "High-Speed Connector"],
    "Crystal Oscillator":    ["Computer", "Superposition Oscillator",
                              "Radio Control Unit"],
    "Reanimated SAM":        ["Ficsite Ingot", "Dark Matter Crystal",
                              "Excited Photonic Matter"],
    "Ficsite Ingot":         ["Ficsite Trigon"],
    "Ficsite Trigon":        ["Neural-Quantum Processor", "Biochemical Sculptor"],
    "Dark Matter Crystal":   ["Superposition Oscillator", "Singularity Cell"],
    "Time Crystal":          ["Neural-Quantum Processor"],
    "Excited Photonic Matter": ["Neural-Quantum Processor", "Superposition Oscillator"],
    "Superposition Oscillator": ["Ballistic Warp Drive"],
    "Neural-Quantum Processor": ["AI Expansion Server"],
    "Singularity Cell":      ["Pressure Conversion Cube"],
    "Caterium Ingot":        ["Quickwire"],
    "Quickwire":             ["AI Limiter", "Circuit Board", "High-Speed Connector",
                              "Supercomputer"],
    "AI Limiter":            ["Adaptive Control Unit"],
    "Circuit Board":         ["Computer", "Adaptive Control Unit",
                              "Radio Control Unit"],
    "High-Speed Connector":  ["Assembly Director System", "EMCR"],
    "Computer":              ["Supercomputer"],
    "Supercomputer":         ["Neural-Quantum Processor", "Assembly Director System"],
    "Adaptive Control Unit": ["Assembly Director System"],
    "EMCR":                  ["Magnetic Field Generator"],
    "Nitric Acid":           ["Fused Modular Frame"],
    "Packaged Nitrogen Gas": ["Turbo Motor"],
    "Stator":                ["Motor", "EMCR"],
    "Rotor":                 ["Turbo Motor", "Motor"],
    "Motor":                 ["Turbo Motor", "Cooling System", "Modular Engine"],
    "Cooling System":        ["Turbo Motor"],
    "Turbo Motor":           ["Thermal Propulsion Rocket"],
    "Fused Modular Frame":   ["Thermal Propulsion Rocket", "Pressure Conversion Cube"],
    "Modular Engine":        ["Thermal Propulsion Rocket"],
    "Pressure Conversion Cube": ["Ballistic Warp Drive"],
    "Radio Control Unit":    ["Pressure Conversion Cube"],
    "Diamonds (Cloudy)":     ["Time Crystal"],
}

# Production targets (units/min) from factory.csv – non-zero active recipes only
PRODUCTION_TARGETS: Dict[str, float] = {
    # Space Elevator
    "AI Expansion Server":          20,
    "Biochemical Sculptor":         10,
    "Ballistic Warp Drive":          3,
    "Nuclear Pasta":                25,
    "Assembly Director System":     51.25,
    "Magnetic Field Generator":     70,
    "Thermal Propulsion Rocket":    51.5,
    # Tier 9 intermediates
    "Neural-Quantum Processor":     20,
    "Superposition Oscillator":     23,
    "Singularity Cell":              7.5,
    "Dark Matter Crystal":         153,
    "Ficsite Trigon":              400,
    "Ficsite Ingot":               133.33,
    "Time Crystal":                100,
    "Diamonds (Cloudy)":           200,
    "Reanimated SAM":              400,
    "Excited Photonic Matter":    1575,
    # High-level parts
    "Cooling System":              154.5,
    "Pressure Conversion Cube":     50.75,
    "Turbo Motor":                  51.5,
    "Fused Modular Frame":         102.25,
    "Radio Control Unit":          101.5,
    "Heat Sink":                   309,
    "Aluminum Casing":            2030,
    "Alclad Sheet":               1089.86,
    "Aluminum Ingot":             9865.36,
    "Aluminum Scrap":            19730.71,
    "Alumina Solution":          11838.43,
    "Empty Fluid Tank":            618,
    # Electronic parts
    "Supercomputer":                71.25,
    "EMCR":                         70,
    "Computer":                    490,
    "Crystal Oscillator":          546.83,
    "AI Limiter":                  689.33,
    "High-Speed Connector":        248.75,
    "Circuit Board":              2406.25,
    "Quickwire":                 21249.17,
    "Caterium Ingot":             2304.10,
    "Adaptive Control Unit":       102.5,
    # Oil parts
    "Petroleum Coke":             3946.14,
    "Plastic":                    1995,
    "Rubber":                     6674.08,
    "Cable":                     10250,
    "Fuel (Diluted)":             1022.5,
    "Heavy Oil Residue":           317.88,
    # Iron and steel
    "Heavy Modular Frame":         204.75,
    "Motor":                       437.75,
    "Stator":                     1664,
    "Rotor":                      1133,
    "Modular Frame":               670,
    "Reinforced Iron Plate":       704.17,
    "Encased Industrial Beam":     728,
    "Iron Plate":                 2694.89,
    "Wire":                      30498.89,
    "Steel Pipe":                17208.13,
    "Steel Beam":                 1050,
    "Steel Ingot":               30012.2,
    "Iron Ingot":                40994.29,
    "Smart Plating":               257.5,
    "Versatile Framework":         175,
    "Modular Engine":              128.75,
    "Automated Wiring":            512.5,
    # Copper parts
    "Copper Ingot":              49281.81,
    "Copper Powder":              5000,
    "Copper Sheet":              10064.70,
    # Quartz / SAM parts
    "Quartz Crystal":             5468.33,
    "Silica":                     8403.13,
    # Misc
    "Concrete":                   5391.6,
    "Nitric Acid":                 818,
    "Packaged Nitrogen Gas":       618,
}

# Products that may be produced at every cluster holding the primary resource.
# Derived automatically: anything in PRODUCTION_TARGETS that is never consumed
# as an input by a downstream recipe in CONSUMERS.
# Steel Ingot is also directly smelted from Iron Ore, so it stays multi-site.
MULTI_SITE_PRODUCTS: set = (
    {p for p in PRODUCTION_TARGETS
     if p not in {c for consumers in CONSUMERS.values() for c in consumers}}
    | {"Steel Ingot"}
)

# World coordinate bounds – fixed from wiki: NW corner (-3246, -3750), SE corner (4253, 3750)
# Wiki format is (north-south, east-west): first coord = latitude, second = longitude.
#   N-S axis (+Y = South):  -3246 north … 4253 south  →  less north than south
#   E-W axis (+X = East):   -3750 west  … 3750 east   →  symmetric
# Multiply by 100 (wiki metres → Unreal cm = game units).
WORLD_MIN_X: float = -375_000   # 3750 units west  (symmetric)
WORLD_MAX_X: float =  375_000   # 3750 units east  (symmetric)
WORLD_MIN_Y: float = -324_600   # 3246 units north (less than south)
WORLD_MAX_Y: float =  425_300   # 4253 units south (more than north)


def print_world_bounds() -> None:
    print(f"  World bounds  X: [{WORLD_MIN_X:,.0f}, {WORLD_MAX_X:,.0f}]  (E-W symmetric)"
          f"   Y: [{WORLD_MIN_Y:,.0f}, {WORLD_MAX_Y:,.0f}]  (less north, more south)")

# ═══════════════════════════════════════════════════════════════════════════════
# Icon mappings
# ═══════════════════════════════════════════════════════════════════════════════
# Raw resource name → icon stem (icons/<stem>.webp)
RESOURCE_ICONS: Dict[str, str] = {
    "Iron Ore":     "Iron_Ore",
    "Copper Ore":   "Copper_Ore",
    "Coal":         "Coal",
    "Limestone":    "Limestone",
    "Crude Oil":    "Crude_Oil",
    "Bauxite":      "Bauxite",
    "Raw Quartz":   "Raw_Quartz",
    "SAM":          "SAM",
    "Caterium Ore": "Caterium_Ore",
    "Sulfur":       "Sulfur",
    # Nitrogen Gas – no icon available
}


# Cluster colours for map annotation (R, G, B)
CLUSTER_COLORS = [
    (220,  60,  60),   # red
    ( 60, 140, 220),   # blue
    ( 60, 200,  80),   # green
    (220, 160,  40),   # orange
    (180,  60, 220),   # purple
    ( 60, 200, 200),   # cyan
    (220, 220,  60),   # yellow
    (200, 100, 160),   # pink
    (100, 160, 100),   # sage
    (160, 120,  60),   # brown
]

# ═══════════════════════════════════════════════════════════════════════════════
# K-means
# ═══════════════════════════════════════════════════════════════════════════════
def euclidean(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def kmeans(points: List[List[float]], k: int,
           weights: Optional[List[float]] = None,
           max_iter: int = 300, seed: int = 42) -> Tuple[List[List[float]], List[int]]:
    """
    Rate-weighted k-means++.  Returns (centroids, per-point assignments).

    weights : per-point positive scalars (e.g. extraction rate).
              A pure node counts 4× an impure one, so dense high-value
              resource pockets pull bases toward them.  Uniform if None.
    """
    n = len(points)
    if n < k:
        raise ValueError(f"Need >= {k} points for {k} clusters (have {n}).")

    w = weights if weights is not None else [1.0] * n

    rng = random.Random(seed)
    # Weighted k-means++ initialisation: prob ∝ weight × dist²
    centroids: List[List[float]] = [list(points[rng.randrange(n)])]
    for _ in range(k - 1):
        dists = [w[i] * min(euclidean(p, c) ** 2 for c in centroids)
                 for i, p in enumerate(points)]
        total = sum(dists)
        r = rng.random() * total if total > 0 else 0.0
        cum = 0.0
        chosen = points[-1]
        for i, d in enumerate(dists):
            cum += d
            if cum >= r:
                chosen = points[i]
                break
        centroids.append(list(chosen))

    assignments = [0] * n
    for _ in range(max_iter):
        new_asgn = [min(range(k), key=lambda c: euclidean(p, centroids[c]))
                    for p in points]
        if new_asgn == assignments:
            break
        assignments = new_asgn
        dim = len(points[0])
        new_c = []
        for c in range(k):
            idxs = [i for i, a in enumerate(assignments) if a == c]
            if idxs:
                tw = sum(w[i] for i in idxs)
                new_c.append([
                    sum(w[i] * points[i][j] for i in idxs) / tw
                    for j in range(dim)
                ])
            else:
                new_c.append(centroids[c])
        centroids = new_c

    return centroids, assignments


# ═══════════════════════════════════════════════════════════════════════════════
# Node loading
# ═══════════════════════════════════════════════════════════════════════════════
def load_nodes(path: str, include_exploited_nodes: bool = False) -> List[Dict]:
    """Parse nodes.json; skip exploited nodes and non-production resources.

    include_exploited_nodes : when True, nodes with Exploited=true are included
                              alongside unexploited ones.  Use this to plan a
                              full-map layout that accounts for nodes already
                              in service in your current save.
    """
    with open(path, "rb") as raw:
        bom = raw.read(2)
    encoding = "utf-16" if bom in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    with open(path, encoding=encoding) as f:
        data = json.load(f)

    entries = data.get("value", data) if isinstance(data, dict) else data
    nodes = []
    for n in entries:
        if n.get("Exploited", False) and not include_exploited_nodes:
            continue
        resource = n.get("Name", "")
        if resource in SKIP_RESOURCES or resource not in RESOURCE_CHAINS:
            continue
        form   = n.get("ResourceForm", "Solid")
        purity = n.get("Purity", "Normal")
        rate   = OUTPUT_RATES.get(form, {}).get(purity, 0)
        if rate == 0:
            continue
        loc = n.get("location", {})
        nodes.append({
            "id":       n.get("ID", ""),
            "resource": resource,
            "form":     form,
            "purity":   purity,
            "rate":     rate,
            "x":        float(loc.get("x", 0)),
            "y":        float(loc.get("y", 0)),
        })
    return nodes


# ═══════════════════════════════════════════════════════════════════════════════
# Feature engineering
# ═══════════════════════════════════════════════════════════════════════════════
def make_features(nodes: List[Dict]) -> List[List[float]]:
    """
    Geographic feature vector per node: [x_norm, y_norm]
    Normalised to [0, 1] using world bounds.
    Production-chain affinity is removed; geographic spread is driven
    entirely by rate-weighted centroid updates in kmeans().
    """
    x_range = WORLD_MAX_X - WORLD_MIN_X
    y_range = WORLD_MAX_Y - WORLD_MIN_Y
    return [
        [(n["x"] - WORLD_MIN_X) / x_range,
         (n["y"] - WORLD_MIN_Y) / y_range]
        for n in nodes
    ]



# ═══════════════════════════════════════════════════════════════════════════════
# Section-based cluster naming
# Maps each produced part to the factory section it belongs to.
# Used by assign_section_names() to score clusters against sections.
# ═══════════════════════════════════════════════════════════════════════════════
PART_TO_SECTION: Dict[str, str] = {
    # SPACE ELEVATOR
    "AI Expansion Server":       "SPACE ELEVATOR",
    "Adaptive Control Unit":     "SPACE ELEVATOR",
    "Assembly Director System":  "SPACE ELEVATOR",
    "Automated Wiring":          "SPACE ELEVATOR",
    "Ballistic Warp Drive":      "SPACE ELEVATOR",
    "Biochemical Sculptor":      "SPACE ELEVATOR",
    "Cable":                     "SPACE ELEVATOR",
    "Dark Matter Crystal":       "SPACE ELEVATOR",
    "Diamonds (Cloudy)":         "SPACE ELEVATOR",
    "Excited Photonic Matter":   "SPACE ELEVATOR",
    "Ficsite Ingot":             "SPACE ELEVATOR",
    "Ficsite Trigon":            "SPACE ELEVATOR",
    "Magnetic Field Generator":  "SPACE ELEVATOR",
    "Modular Engine":            "SPACE ELEVATOR",
    "Neural-Quantum Processor":  "SPACE ELEVATOR",
    "Nuclear Pasta":             "SPACE ELEVATOR",
    "Reanimated SAM":            "SPACE ELEVATOR",
    "Singularity Cell":          "SPACE ELEVATOR",
    "Smart Plating":             "SPACE ELEVATOR",
    "Superposition Oscillator":  "SPACE ELEVATOR",
    "Thermal Propulsion Rocket": "SPACE ELEVATOR",
    "Time Crystal":              "SPACE ELEVATOR",
    "Versatile Framework":       "SPACE ELEVATOR",
    # HIGH LEVEL PARTS
    "Cooling System":            "HIGH LEVEL PARTS",
    "Fused Modular Frame":       "HIGH LEVEL PARTS",
    "Heavy Modular Frame":       "HIGH LEVEL PARTS",
    "Pressure Conversion Cube":  "HIGH LEVEL PARTS",
    "Radio Control Unit":        "HIGH LEVEL PARTS",
    "Turbo Motor":               "HIGH LEVEL PARTS",
    # ALUMINUM PARTS
    "Alumina Solution":          "ALUMINUM PARTS",
    "Aluminum Casing":           "ALUMINUM PARTS",
    "Aluminum Ingot":            "ALUMINUM PARTS",
    "Aluminum Scrap":            "ALUMINUM PARTS",
    "Heat Sink":                 "ALUMINUM PARTS",
    # ELECTRONIC PARTS
    "AI Limiter":                "ELECTRONIC PARTS",
    "Circuit Board":             "ELECTRONIC PARTS",
    "Computer":                  "ELECTRONIC PARTS",
    "Copper Sheet":              "ELECTRONIC PARTS",
    "Crystal Oscillator":        "ELECTRONIC PARTS",
    "EMCR":                      "ELECTRONIC PARTS",
    "High-Speed Connector":      "ELECTRONIC PARTS",
    "Quickwire":                 "ELECTRONIC PARTS",
    "Silica":                    "ELECTRONIC PARTS",
    "Supercomputer":             "ELECTRONIC PARTS",
    # OIL PARTS
    "Fuel (Diluted)":            "OIL PARTS",
    "Heavy Oil Residue":         "OIL PARTS",
    "Petroleum Coke":            "OIL PARTS",
    "Plastic":                   "OIL PARTS",
    "Rubber":                    "OIL PARTS",
    # IRON AND STEEL
    "Encased Industrial Beam":   "IRON AND STEEL",
    "Iron Ingot":                "IRON AND STEEL",
    "Modular Frame":             "IRON AND STEEL",
    "Motor":                     "IRON AND STEEL",
    "Reinforced Iron Plate":     "IRON AND STEEL",
    "Rotor":                     "IRON AND STEEL",
    "Stator":                    "IRON AND STEEL",
    "Steel Beam":                "IRON AND STEEL",
    "Steel Ingot":               "IRON AND STEEL",
    "Steel Pipe":                "IRON AND STEEL",
    "Wire":                      "IRON AND STEEL",
    # COPPER PARTS
    "Copper Ingot":              "COPPER PARTS",
    "Copper Powder":             "COPPER PARTS",
    # LIQUIDS AND GASES
    "Empty Fluid Tank":          "LIQUIDS AND GASES",
    "Iron Plate":                "LIQUIDS AND GASES",
    "Nitric Acid":               "LIQUIDS AND GASES",
    "Packaged Nitrogen Gas":     "LIQUIDS AND GASES",
    # OTHER
    "Caterium Ingot":            "OTHER",
    "Concrete":                  "OTHER",
    "Quartz Crystal":            "OTHER",
}

# Total raw resource consumption rates (units/min) for the full factory plan.
# Used to determine node utilization and colour-code resource dots on the map.
RESOURCE_REQUIREMENTS: Dict[str, float] = {
    "Iron Ore":     55385.0,
    "Copper Ore":   26326.0,
    "Coal":         24209.0,
    "Raw Quartz":   12209.0,
    "Caterium Ore": 12351.0,
    "Bauxite":      10000.0,
    "Limestone":    32057.0,
    "Uranium":       1800.0,
    "Sulfur":          900.0,
    "Crude Oil":    13243.0,
    "Nitrogen Gas":  9758.0,
    "SAM":           2600.0,
}


def assign_section_names(all_cluster_prods: List[Dict[str, float]],
                          part_to_section: Dict[str, str]) -> List[str]:
    """
    Assign each cluster a unique section name.  Each section can only win once:
    whichever cluster produces the highest fraction of that section's total
    map-wide output gets the name.

    Algorithm: build a (cluster × section) score matrix, then greedily pick
    the highest-scoring pair, assign it, and remove both from contention.
    Clusters left over after all sections are taken get numbered fallback names.
    """
    section_targets: Dict[str, float] = defaultdict(float)
    for part, sec in part_to_section.items():
        section_targets[sec] += PRODUCTION_TARGETS.get(part, 0.0)

    k = len(all_cluster_prods)
    scores: List[Dict[str, float]] = []
    for prod in all_cluster_prods:
        cluster_sec: Dict[str, float] = defaultdict(float)
        for part, qty in prod.items():
            sec = part_to_section.get(part)
            if sec:
                cluster_sec[sec] += qty
        scores.append({sec: cluster_sec[sec] / (section_targets[sec] or 1.0)
                        for sec in cluster_sec})

    assigned: List[Optional[str]] = [None] * k
    used_clusters: set = set()
    used_sections: set = set()

    all_scores = sorted(
        ((sc, c, sec) for c, row in enumerate(scores) for sec, sc in row.items()),
        reverse=True
    )
    for sc, c, sec in all_scores:
        if c in used_clusters or sec in used_sections:
            continue
        assigned[c] = sec
        used_clusters.add(c)
        used_sections.add(sec)
        if len(used_clusters) == k:
            break

    fallback = 1
    for c in range(k):
        if assigned[c] is None:
            assigned[c] = f"Cluster {fallback}"
            fallback += 1

    return assigned


# ═══════════════════════════════════════════════════════════════════════════════
# Production assignment
# ═══════════════════════════════════════════════════════════════════════════════
def assign_production(nodes: List[Dict], assignments: List[int],
                      k: int, centroids: List[List[float]],
                      threshold: float = 0.05) -> List[Dict[str, float]]:
    """
    For each product in PRODUCTION_TARGETS, split production across clusters
    proportionally to their share of the product's primary raw resource.
    Final assembly items go to the cluster nearest the world origin (0, 0).
    Returns list of {product: qty} dicts, one per cluster.
    """
    # Sum available resource rate per cluster
    cluster_res: List[Dict[str, float]] = [defaultdict(float) for _ in range(k)]
    for node, asgn in zip(nodes, assignments):
        cluster_res[asgn][node["resource"]] += node["rate"]

    # Find cluster nearest origin (Space Elevator site)
    x_range = WORLD_MAX_X - WORLD_MIN_X
    y_range = WORLD_MAX_Y - WORLD_MIN_Y
    ox = (0 - WORLD_MIN_X) / x_range
    oy = (0 - WORLD_MIN_Y) / y_range
    fa_cluster = min(range(k), key=lambda c: euclidean(centroids[c][:2], [ox, oy]))

    cluster_prod: List[Dict[str, float]] = [defaultdict(float) for _ in range(k)]

    for product, target in PRODUCTION_TARGETS.items():
        if target <= 0:
            continue
        recipe = RECIPES.get(product)
        if not recipe:
            continue

        if product in FINAL_ASSEMBLY:
            cluster_prod[fa_cluster][product] += target
            continue

        primary = recipe["primary"]
        supply = [cluster_res[c].get(primary, 0.0) for c in range(k)]
        total_supply = sum(supply)

        if total_supply == 0:
            # Fall back: put it all in the final-assembly cluster
            cluster_prod[fa_cluster][product] += target
            continue

        fractions = [s / total_supply for s in supply]
        # Apply threshold: zero out small fractions and renormalise
        fractions = [f if f >= threshold else 0.0 for f in fractions]
        fsum = sum(fractions)
        if fsum == 0:
            fractions = [1.0 / k] * k
        else:
            fractions = [f / fsum for f in fractions]

        if product in MULTI_SITE_PRODUCTS:
            # First-level product: split proportionally across all clusters
            # that hold the primary resource
            for c in range(k):
                qty = target * fractions[c]
                if qty > 0.5:
                    cluster_prod[c][product] += qty
        else:
            # Downstream part: winner-takes-all — assign to the single cluster
            # with the largest share of the primary resource
            best = max(range(k), key=lambda c: fractions[c])
            cluster_prod[best][product] += target

    return cluster_prod


# ═══════════════════════════════════════════════════════════════════════════════
# Shipping determination
# ═══════════════════════════════════════════════════════════════════════════════
def find_shipping(cluster_prod: List[Dict[str, float]],
                  k: int) -> List[List[str]]:
    """
    Return per-cluster list of items that need to be shipped out.
    A product is shipped out of cluster A if it is produced at A and
    consumed by another product that is produced at cluster B ≠ A.
    """
    # product → set of clusters that produce it
    prod_clusters: Dict[str, set] = defaultdict(set)
    for c in range(k):
        for product in cluster_prod[c]:
            prod_clusters[product].add(c)

    ships_out: List[set] = [set() for _ in range(k)]
    for product, consumers in CONSUMERS.items():
        src_clusters = prod_clusters.get(product, set())
        for consumer in consumers:
            dst_clusters = prod_clusters.get(consumer, set())
            for src in src_clusters:
                for dst in dst_clusters:
                    if src != dst:
                        ships_out[src].add(product)

    return [sorted(s) for s in ships_out]


# ═══════════════════════════════════════════════════════════════════════════════
# Markdown output
# ═══════════════════════════════════════════════════════════════════════════════
def fmt_qty(qty: float) -> str:
    return f"{qty:,.0f}" if qty >= 10 else f"{qty:.1f}"


def write_markdown(clusters: List[Dict], path: str = "clusters.md") -> None:
    lines = ["# Satisfactory Factory Clusters\n"]
    lines.append("| # | Name | Coords (x, y) | Produces | Ships Out |")
    lines.append("|---|------|--------------|---------|-----------|")

    # Find products made in >1 cluster
    multi: Dict[str, List[int]] = defaultdict(list)
    for c in clusters:
        for p in c["production"]:
            multi[p].append(c["index"])
    multi = {p: idxs for p, idxs in multi.items() if len(idxs) > 1}

    for c in clusters:
        idx  = c["index"] + 1
        name = c["name"]
        x, y = c["cx"], c["cy"]
        coord = f"({x:,.0f}, {y:,.0f})"

        prod_parts = []
        for p, qty in sorted(c["production"].items(), key=lambda kv: -kv[1]):
            label = p
            if p in multi:
                label += f" ({fmt_qty(qty)}/min)"
            else:
                label += f" ({fmt_qty(qty)}/min)"
            prod_parts.append(label)
        produces = "<br>".join(prod_parts) if prod_parts else "—"

        ship_parts = []
        for p in c["ships_out"]:
            qty = c["production"].get(p, 0)
            ship_parts.append(f"{p} ({fmt_qty(qty)}/min)" if qty else p)
        ships = "<br>".join(ship_parts) if ship_parts else "*(terminus)*"

        lines.append(f"| {idx} | {name} | {coord} | {produces} | {ships} |")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  -> {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Map annotation
# ═══════════════════════════════════════════════════════════════════════════════
def convex_hull(points: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Andrew's monotone-chain convex hull. Returns vertices in CCW order."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(O: Tuple, A: Tuple, B: Tuple) -> float:
        return (A[0] - O[0]) * (B[1] - O[1]) - (A[1] - O[1]) * (B[0] - O[0])

    lower: List[Tuple[int, int]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: List[Tuple[int, int]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def world_to_pixel(wx: float, wy: float,
                   img_w: int, img_h: int) -> Tuple[int, int]:
    px = int((wx - WORLD_MIN_X) / (WORLD_MAX_X - WORLD_MIN_X) * img_w)
    py = int((wy - WORLD_MIN_Y) / (WORLD_MAX_Y - WORLD_MIN_Y) * img_h)  # +Y = South = down
    return px, py


def write_map(nodes: List[Dict], assignments: List[int],
              clusters: List[Dict], src_map: str, out_map: str,
              cluster_alpha: float = 0.4,
              shift_x: int = 0, shift_y: int = 0,
              resource_requirements: Optional[Dict[str, float]] = None,
              icons_dir: str = "icons") -> None:
    """
    cluster_alpha : opacity of the cluster hull fill (0.0 = fully transparent,
                    1.0 = fully opaque).  Default 0.4 = 60 % transparent.
    shift_x / shift_y : pixel offset applied to every drawn element, letting
                    you nudge node positions to align with the map image.
    icons_dir : directory containing <Name>.webp icon files (default: icons/).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  ⚠  Pillow not installed – skipping map annotation.")
        print("     Run:  pip install Pillow")
        return


    # ── Icon helpers ──────────────────────────────────────────────────────────
    _icon_cache: Dict[str, object] = {}

    def get_icon(stem: str, size: int):
        key = f"{stem}_{size}"
        if key not in _icon_cache:
            path = os.path.join(icons_dir, f"{stem}.webp")
            if not os.path.isfile(path):
                path = os.path.join(icons_dir, f"Packaged_{stem}.webp")
            try:
                ico = Image.open(path).convert("RGBA")
                ico = ico.resize((size, size), Image.LANCZOS)
                _icon_cache[key] = ico
            except Exception:
                _icon_cache[key] = None
        return _icon_cache[key]

    def paste_icon(base_img, ico, cx: int, cy: int) -> None:
        """Paste icon centred at (cx, cy), clipping to image bounds."""
        if ico is None:
            return
        iw, ih = ico.size
        x0, y0 = cx - iw // 2, cy - ih // 2
        src_x = max(0, -x0);  src_y = max(0, -y0)
        dst_x = max(0,  x0);  dst_y = max(0,  y0)
        cw = min(iw - src_x, base_img.width  - dst_x)
        ch = min(ih - src_y, base_img.height - dst_y)
        if cw <= 0 or ch <= 0:
            return
        region = ico.crop((src_x, src_y, src_x + cw, src_y + ch))
        base_img.paste(region, (dst_x, dst_y), region)

    img = Image.open(src_map).convert("RGBA")
    W, H = img.size
    scale = W / 1280   # all pixel sizes were tuned at 1280px; scale linearly

    # ── Cluster convex-hull fills (drawn first, behind everything else) ────────
    hull_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    hull_draw = ImageDraw.Draw(hull_overlay)

    # Bucket node pixel positions by cluster index
    cluster_pixels: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    for node, asgn in zip(nodes, assignments):
        px, py = world_to_pixel(node["x"], node["y"], W, H)
        cluster_pixels[asgn].append((px + shift_x, py + shift_y))

    fill_alpha    = int(cluster_alpha * 255)
    outline_alpha = min(255, fill_alpha + 80)
    for c in clusters:
        idx  = c["index"]
        pts  = cluster_pixels.get(idx, [])
        if len(pts) < 3:
            continue
        hull = convex_hull(pts)
        if len(hull) < 3:
            continue
        col = CLUSTER_COLORS[idx % len(CLUSTER_COLORS)]
        hull_draw.polygon(hull,
                          fill=(*col, fill_alpha),
                          outline=(*col, outline_alpha))

    img = Image.alpha_composite(img, hull_overlay)

    # All subsequent drawing goes on the composited image
    draw = ImageDraw.Draw(img, "RGBA")

    # Try to load a font; fall back to default
    fsize    = max(8,  int(14 * scale))
    fsize_sm = max(6,  int(11 * scale))
    try:
        font    = ImageFont.truetype("arial.ttf", fsize)
        font_sm = ImageFont.truetype("arial.ttf", fsize_sm)
    except Exception:
        font    = ImageFont.load_default()
        font_sm = font

    k = len(clusters)

    resource_requirements = resource_requirements or {}

    # ── Determine which nodes are actually consumed ───────────────────────────
    # For each (cluster, resource): proportion the map-wide requirement by this
    # cluster's share of total supply, then mark the highest-rate nodes as used
    # until that quota is filled.  Nodes beyond the quota are marked gray.
    total_supply: Dict[str, float] = defaultdict(float)
    for node in nodes:
        total_supply[node["resource"]] += node["rate"]

    # Collect node indices per cluster per resource, sorted rate-desc
    cluster_res_nodes: Dict[int, Dict[str, List]] = defaultdict(lambda: defaultdict(list))
    for idx, (node, asgn) in enumerate(zip(nodes, assignments)):
        cluster_res_nodes[asgn][node["resource"]].append((node["rate"], idx))
    for c_nodes in cluster_res_nodes.values():
        for lst in c_nodes.values():
            lst.sort(reverse=True)

    fully_used:   set = set()
    partial_used: set = set()
    for c in clusters:
        cidx = c["index"]
        for resource, node_list in cluster_res_nodes[cidx].items():
            tot_supply  = total_supply.get(resource, 1.0) or 1.0
            tot_needed  = resource_requirements.get(resource, 0.0)
            c_supply    = sum(rate for rate, _ in node_list)
            needed_here = tot_needed * (c_supply / tot_supply)
            cumulative  = 0.0
            for rate, node_idx in node_list:
                if cumulative >= needed_here:
                    break
                remaining = needed_here - cumulative
                if rate <= remaining:
                    fully_used.add(node_idx)   # entire output spoken for
                else:
                    partial_used.add(node_idx) # only partially consumed
                cumulative += rate

    # Draw individual node dots (small, semi-transparent)
    # black = fully used, pale yellow = partially used, white = unused
    icon_node_sz = max(10, int(12 * scale))
    for idx, (node, asgn) in enumerate(zip(nodes, assignments)):
        px, py = world_to_pixel(node["x"], node["y"], W, H)
        px += shift_x; py += shift_y
        col = CLUSTER_COLORS[asgn % len(CLUSTER_COLORS)]
        r = max(int(2 * scale), int(node["rate"] / 600 * scale))
        if idx in fully_used:
            ring = ( 20,  20,  20, 230)
        elif idx in partial_used:
            ring = (255, 210,  80, 200)
        else:
            ring = (255, 255, 255, 200)
        draw.ellipse([px - r, py - r, px + r, py + r],
                     fill=(*col, 160), outline=ring, width=max(1, int(2 * scale)))
        # Resource icon centred above the dot (only for used/partially-used nodes)
        if idx in fully_used or idx in partial_used:
            ico_stem = RESOURCE_ICONS.get(node["resource"])
            if ico_stem:
                ico = get_icon(ico_stem, icon_node_sz)
                paste_icon(img, ico, px, py - r - icon_node_sz // 2 - max(1, int(scale)))

    # Draw cluster centroid circles and labels
    for c in clusters:
        px, py = world_to_pixel(c["cx"], c["cy"], W, H)
        px += shift_x; py += shift_y
        col = CLUSTER_COLORS[c["index"] % len(CLUSTER_COLORS)]
        R      = int(18 * scale)
        inset  = max(1, int(3 * scale))
        shadow = max(1, int(scale))
        # Outer ring
        draw.ellipse([px - R, py - R, px + R, py + R],
                     outline=(*col, 255), width=max(1, int(3 * scale)))
        # Inner fill (semi-transparent)
        draw.ellipse([px - R + inset, py - R + inset,
                      px + R - inset, py + R - inset],
                     fill=(*col, 180))
        # Index number
        label = str(c["index"] + 1)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((px - tw // 2, py - th // 2), label,
                  font=font, fill=(255, 255, 255, 255))
        # Name label below circle
        name_label = c["name"]
        bbox2 = draw.textbbox((0, 0), name_label, font=font_sm)
        nw = bbox2[2] - bbox2[0]
        draw.text((px - nw // 2 + shadow, py + R + shadow), name_label,
                  font=font_sm, fill=(0, 0, 0, 200))
        draw.text((px - nw // 2, py + R), name_label,
                  font=font_sm, fill=(*col, 255))

    # ── Prepare product icons for legend ──────────────────────────────────────
    def _part_stem(name: str) -> str:
        """'Fuel (Diluted)' → 'Fuel_Diluted',  'Iron Ingot' → 'Iron_Ingot'"""
        name = re.sub(r'\s*\([^)]*\)', '', name)
        name = re.sub(r'[^A-Za-z0-9 ]', '', name)
        return '_'.join(name.split())

    icon_leg_sz  = max(8,  int(10 * scale))
    icon_leg_gap = max(1,  int(2  * scale))
    icon_row_h   = icon_leg_sz + 2 * icon_leg_gap

    # For each cluster: list of loaded icons, sorted by qty desc
    cluster_prod_icons: List[List] = []
    for c in clusters:
        icos = []
        for part, qty in sorted(c["production"].items(), key=lambda kv: -kv[1]):
            ico = get_icon(_part_stem(part), icon_leg_sz)
            if ico is not None:
                icos.append(ico)
        cluster_prod_icons.append(icos)

    # Legend box (top-left corner)
    legend_x   = int(8  * scale)
    legend_y   = int(8  * scale)
    legend_pad = int(4  * scale)
    line_h     = int(18 * scale)
    swatch_h1  = int(3  * scale)
    swatch_h2  = int(13 * scale)
    swatch_w   = int(12 * scale)
    text_gap   = int(16 * scale)
    legend_lines = [f"{c['index']+1}. {c['name']}" for c in clusters]

    text_max_w = max(draw.textbbox((0, 0), l, font=font_sm)[2] for l in legend_lines)
    icon_max_w = max(
        (len(icos) * (icon_leg_sz + icon_leg_gap) - icon_leg_gap) if icos else 0
        for icos in cluster_prod_icons
    )
    content_w = max(text_max_w, icon_max_w + swatch_w + icon_leg_gap)
    box_w = content_w + 2 * legend_pad + text_gap
    entry_h = line_h + icon_row_h + icon_leg_gap
    box_h = len(legend_lines) * entry_h + 2 * legend_pad

    draw.rectangle([legend_x, legend_y,
                    legend_x + box_w, legend_y + box_h],
                   fill=(0, 0, 0, 160), outline=(180, 180, 180, 200))
    for i, (line, prod_icos) in enumerate(zip(legend_lines, cluster_prod_icons)):
        col = CLUSTER_COLORS[i % len(CLUSTER_COLORS)]
        entry_y = legend_y + legend_pad + i * entry_h
        # Color swatch
        draw.rectangle([legend_x + legend_pad,
                        entry_y + swatch_h1,
                        legend_x + legend_pad + swatch_w,
                        entry_y + swatch_h2],
                       fill=(*col, 220))
        # Name text
        draw.text((legend_x + legend_pad + text_gap, entry_y),
                  line, font=font_sm, fill=(240, 240, 240, 255))
        # Icon row
        ix = legend_x + legend_pad + text_gap
        iy = entry_y + line_h + icon_leg_gap
        for ico in prod_icos:
            paste_icon(img, ico, ix + icon_leg_sz // 2, iy + icon_leg_sz // 2)
            ix += icon_leg_sz + icon_leg_gap

    img.save(out_map)
    print(f"  -> {out_map}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(
        description="K-means factory cluster optimiser for Satisfactory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
              python satisfactory_clusters.py nodes.json
              python satisfactory_clusters.py nodes.json --bases 8
            """))
    parser.add_argument("nodes",      help="Path to nodes.json")
    parser.add_argument("--bases",    type=int,   default=6,   metavar="N",
                        help="Number of factory clusters (default: 6)")
    parser.add_argument("--seed",     type=int,   default=42,  metavar="S",
                        help="Random seed for k-means++ (default: 42)")
    parser.add_argument("--threshold",type=float, default=0.05, metavar="T",
                        help="Min resource fraction for cluster assignment (default: 0.05)")
    parser.add_argument("--map",      default="map.png", metavar="FILE",
                        help="Source map image (default: map.png)")
    parser.add_argument("--out-map",  default="map-annotated.png", metavar="FILE",
                        help="Output annotated map (default: map-annotated.png)")
    parser.add_argument("--out-md",   default="clusters.md", metavar="FILE",
                        help="Output markdown file (default: clusters.md)")
    parser.add_argument("--cluster-alpha", type=float, default=0.4, metavar="A",
                        help="Opacity of cluster hull fill 0.0–1.0 (default: 0.4 = 60%% transparent)")
    parser.add_argument("--shift-x", type=int, default=-332, metavar="PX",
                        help="Pixel offset applied to all drawn elements horizontally (default: -85)")
    parser.add_argument("--shift-y", type=int, default=332, metavar="PX",
                        help="Pixel offset applied to all drawn elements vertically (default: 85)")
    parser.add_argument("--include-exploited-nodes", action="store_true", default=False,
                        help="Include nodes marked Exploited=true in nodes.json (default: skip them)")
    parser.add_argument("--icons-dir", default="icons", metavar="DIR",
                        help="Directory containing <Name>.webp icon files (default: icons)")
    args = parser.parse_args()

    part_to_section = PART_TO_SECTION
    res_req         = RESOURCE_REQUIREMENTS

    print("Loading nodes…")
    nodes = load_nodes(args.nodes, include_exploited_nodes=args.include_exploited_nodes)
    exploited_note = " (including exploited)" if args.include_exploited_nodes else ""
    print(f"  {len(nodes)} nodes loaded{exploited_note}.")

    # Resource summary
    res_count: Dict[str, int] = defaultdict(int)
    for n in nodes:
        res_count[n["resource"]] += 1
    for r, cnt in sorted(res_count.items()):
        print(f"    {r:20s}  {cnt:3d} nodes")

    print_world_bounds()

    print(f"\nRunning k-means  (k={args.bases}, rate-weighted, seed={args.seed})…")
    features = make_features(nodes)

    # Weight each node by rate × utilization so barely-needed resources
    # (e.g. Sulfur at 12 %) exert proportionally less pull on cluster centroids
    # than fully-needed ones (e.g. Crude Oil at ~100 %).
    total_supply: Dict[str, float] = defaultdict(float)
    for n in nodes:
        total_supply[n["resource"]] += n["rate"]
    utilization = {
        r: min(1.0, res_req.get(r, 0.0) / max(total_supply[r], 1.0))
        for r in total_supply
    }
    weights = [n["rate"] * utilization.get(n["resource"], 1.0) for n in nodes]

    centroids, assignments = kmeans(features, args.bases,
                                    weights=weights, seed=args.seed)

    # Convert feature-space centroids back to world coords
    x_range = WORLD_MAX_X - WORLD_MIN_X
    y_range = WORLD_MAX_Y - WORLD_MIN_Y
    world_cx = [c[0] * x_range + WORLD_MIN_X for c in centroids]
    world_cy = [c[1] * y_range + WORLD_MIN_Y for c in centroids]

    print("\nAssigning production…")
    cluster_prod = assign_production(nodes, assignments, args.bases,
                                     centroids, threshold=args.threshold)
    ships_out    = find_shipping(cluster_prod, args.bases)

    # Assign section names globally (each section wins at most once)
    section_names = assign_section_names(
        [dict(cluster_prod[c]) for c in range(args.bases)], part_to_section)

    # Build cluster dicts
    clusters = []
    for c in range(args.bases):
        node_count = sum(1 for a in assignments if a == c)
        res_in_cluster = defaultdict(float)
        for node, asgn in zip(nodes, assignments):
            if asgn == c:
                res_in_cluster[node["resource"]] += node["rate"]

        name = section_names[c]
        clusters.append({
            "index":      c,
            "name":       name,
            "cx":         world_cx[c],
            "cy":         world_cy[c],
            "node_count": node_count,
            "resources":  dict(res_in_cluster),
            "production": dict(cluster_prod[c]),
            "ships_out":  ships_out[c],
        })

    # Print summary to stdout
    print()
    for c in clusters:
        res_str = ", ".join(
            f"{r} ({v:,.0f}/min)"
            for r, v in sorted(c["resources"].items(), key=lambda kv: -kv[1])
        )
        print(f"  Cluster {c['index']+1}: {c['name']}")
        print(f"    Centre: ({c['cx']:,.0f}, {c['cy']:,.0f})   Nodes: {c['node_count']}")
        print(f"    Resources: {res_str}")
        top_prod = sorted(c["production"].items(), key=lambda kv: -kv[1])[:5]
        print(f"    Top products: {', '.join(f'{p} ({fmt_qty(q)}/min)' for p, q in top_prod)}")
        print()

    print("Writing outputs…")
    write_markdown(clusters, path=args.out_md)
    write_map(nodes, assignments, clusters,
              src_map=args.map, out_map=args.out_map,
              cluster_alpha=args.cluster_alpha,
              shift_x=args.shift_x, shift_y=args.shift_y,
              resource_requirements=res_req,
              icons_dir=args.icons_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
