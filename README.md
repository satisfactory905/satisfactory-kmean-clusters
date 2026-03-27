# Satisfactory Factory Cluster Optimizer

---

## Overview

Planning a late-game Satisfactory factory means deciding which resources to co-locate, which parts to centralize, and how to minimize inter-base shipping. This tool automates that analysis using rate-weighted k-means clustering on resource node geography, then distributes production targets across clusters based on resource availability and a dependency-aware assignment model.

**Outputs:**
- `clusters.md` — Markdown table listing each cluster's name, coordinates, production targets, and outbound shipping
- `map-annotated.png` — Annotated world map with cluster hulls, centroid markers, resource node dots, icons, and a production legend

![Annotated map example](map-annotated.png)

---

## Getting Started

### 1. Install Python

Download and install Python 3.8 or later from [python.org](https://www.python.org/downloads/). During installation on Windows, check **"Add Python to PATH"**.

To verify your installation, open a terminal and run:

```bash
python --version
```

### 2. Install Dependencies

```bash
pip install Pillow
```

### 3. Run the Script

```bash
python satisfactory_clusters.py nodes.json
```

Output files (`clusters.md` and `map-annotated.png`) are written to the same folder.

---

## Input Files

### `nodes.json`
Resource node data exported from the game using the [Ficsit Remote Monitoring](https://docs.ficsit.app/ficsitremotemonitoring/latest/json/Read/getResourceNode.html) mod (`getResourceNode` endpoint). Expected structure:

```json
{
  "value": [
    {
      "Name": "Iron Ore",
      "Purity": "Pure",
      "ResourceForm": "Solid",
      "Exploited": false,
      "location": { "x": 12345.0, "y": -67890.0, "z": 0.0 }
    }
  ]
}
```

- `Purity`: `Pure`, `Normal`, or `Impure`
- `ResourceForm`: `Solid`, `Liquid`, or `Gas`
- `Exploited`: nodes marked `true` are skipped by default. Pass `--include-exploited-nodes` to include them. This is useful for planning a full-map layout that accounts for nodes already tapped in your current save — the clustering will treat them identically to unexploited nodes. Note that `nodes.json` is read fresh on every run and never modified; the `Exploited` field only changes if you re-export via the mod.
- Coordinates are in Unreal Engine units (centimetres)
- The file may be UTF-8 or UTF-16; the script detects the encoding automatically based on the BOM

Supported resources: Iron Ore, Copper Ore, Coal, Limestone, Crude Oil, Bauxite, Raw Quartz, SAM, Caterium Ore, Nitrogen Gas, Sulfur. Water and Uranium are skipped.

### `factory.csv`
A production plan spreadsheet. The tool reads two sections:

| Rows | Content | Purpose |
|------|---------|---------|
| 24–38 | **Resources Required** — resource name and total consumption rate | Used to determine node utilization |
| 62–434 | **Named sections** — part names grouped under section headers | Used to name clusters |

Valid section headers: `SPACE ELEVATOR`, `HIGH LEVEL PARTS`, `ALUMINUM PARTS`, `ELECTRONIC PARTS`, `OIL PARTS`, `IRON AND STEEL`, `COPPER PARTS`, `LIQUIDS AND GASES`, `OTHER`.

### `map.png`
A world map image. Works at any resolution; all drawing sizes scale proportionally relative to a 1280×1280 reference. A 5000×5000 map is recommended for readability at full zoom.

### `icons/` *(optional)*
A folder of `.webp` icon files named in `Title_Snake_Case` (e.g. `Iron_Ingot.webp`, `Crude_Oil.webp`). Icons are shown above resource nodes on the map and in the legend alongside each cluster's produced parts. If the folder or a specific icon is missing, that element is silently skipped.

For liquid/gas resources whose packaged form is named differently (e.g. `Packaged_Oil`), the icon loader automatically tries `Packaged_{stem}.webp` as a fallback.

---

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--bases N` | `6` | Number of factory clusters |
| `--seed S` | `42` | Random seed for k-means++ initialisation |
| `--threshold T` | `0.05` | Minimum resource fraction for a cluster to receive a production assignment |
| `--map FILE` | `map.png` | Source map image |
| `--out-map FILE` | `map-annotated.png` | Output annotated map |
| `--out-md FILE` | `clusters.md` | Output Markdown table |
| `--cluster-alpha A` | `0.4` | Opacity of cluster hull fill (0.0–1.0) |
| `--factory FILE` | `factory.csv` | Factory plan CSV for section-based cluster naming |
| `--include-exploited-nodes` | off | Include nodes marked `Exploited: true` in the analysis (see below) |

### Examples

```bash
# Basic run with 6 clusters
python satisfactory_clusters.py nodes.json

# 9 clusters, higher-resolution map
python satisfactory_clusters.py nodes.json --bases 9 --map map5000.png
```

---

## Customizing the Script

The following values are hardcoded near the top of `satisfactory_clusters.py` and are the most likely things you'll want to change for your own playthrough.

### Production Targets — `PRODUCTION_TARGETS`

This is the most important dict to update. It maps every product name to the rate (units/min) you want to produce globally. The values here represent one specific factory plan and almost certainly won't match yours:

```python
PRODUCTION_TARGETS: Dict[str, float] = {
    "Iron Ingot": 40994.29,
    "Plastic":     1995,
    # ...
}
```

Change any value to match your own targets. Products set to `0` are ignored. Products not listed here won't be assigned to any cluster.

Note: `factory.csv` is read at runtime for cluster *naming* and node *utilization coloring*, but the production targets themselves are read from this dict, not the CSV. If your factory plan changes, update `PRODUCTION_TARGETS` to match.

### Miner Output Rates — `OUTPUT_RATES`

Rates are calculated assuming **Mk.3 miners / Oil Extractors / Resource Wells overclocked to 250%**. If you're running a different setup, update these values:

```python
OUTPUT_RATES = {
    "Solid":  {"Pure": 1200, "Normal": 600,  "Impure": 300},
    "Liquid": {"Pure":  600, "Normal": 300,  "Impure": 150},
    "Gas":    {"Pure":  300, "Normal": 150,  "Impure":  75},
}
```

### Skipped Resources — `SKIP_RESOURCES`

Water and Uranium are excluded from clustering by default. Water is unlimited (pipes) and Uranium requires separate nuclear handling. If you want Uranium nodes to appear on the map and influence clustering, remove it from this set:

```python
SKIP_RESOURCES = {"Uranium", "Water"}
```

### Cluster Colors — `CLUSTER_COLORS`

A list of `(R, G, B)` tuples, one per cluster. Extend or reorder to match your preferred color scheme:

```python
CLUSTER_COLORS = [
    (220,  60,  60),   # red
    ( 60, 140, 220),   # blue
    # ...
]
```

### Final Assembly Items — `FINAL_ASSEMBLY`

These products are always assigned to the cluster geographically nearest the Space Elevator (world origin), regardless of where their resources are. Update this if your Space Elevator deliverables change between game phases:

```python
FINAL_ASSEMBLY = {
    "Thermal Propulsion Rocket",
    "Magnetic Field Generator",
    # ...
}
```

---

## How It Works

### 1. Node Extraction Rate

Each node's output rate is derived from its purity and resource form using Mk.3 miners / Oil Extractors / Resource Wells overclocked to 250%:

| Form \ Purity | Pure | Normal | Impure |
|--------------|------|--------|--------|
| Solid | 1200/min | 600/min | 300/min |
| Liquid | 600/min | 300/min | 150/min |
| Gas | 300/min | 150/min | 75/min |

### 2. Utilization-Weighted K-Means Clustering

Clusters are determined by **rate-weighted geographic k-means++** on the 2D world coordinates of all nodes. The feature vector is purely geographic — no production-chain affinity dimensions — so bases spread across the map driven by where resources physically are.

Each node's influence on centroid placement is scaled by:

```
weight = node_rate × min(1.0, factory_need / total_map_supply)
```

This means barely-needed resources (e.g. Sulfur at ~12% utilization) exert proportionally less pull than fully-needed ones (e.g. Crude Oil at ~100%). A cluster of unused sulfur nodes won't drag a base out of position.

### 3. Production Assignment

For each product in the production plan, the tool decides how to split output across clusters based on which cluster holds the most of the product's **primary raw resource**.

#### Multi-Site Products (first-level refining)
Products whose only inputs come directly from raw resource extractors are **split proportionally** across all clusters that hold the relevant resource. This allows Iron Ingots or Plastic to be produced wherever Iron Ore or Crude Oil exists.

Multi-site products are derived automatically from the production dependency graph: any product that does not appear as a consumed input anywhere in the dependency chain is classified as first-level. Steel Ingot is explicitly included because it can be smelted directly from Iron Ore even though an alloy recipe also consumes Iron Ingots.

**Current multi-site set:** Iron Ingot, Steel Ingot, Copper Ingot, Caterium Ingot, Alumina Solution, Plastic, Rubber, Fuel (Diluted), Heavy Oil Residue, Petroleum Coke, Concrete, Quartz Crystal, Silica, Reanimated SAM, Diamonds (Cloudy)

#### Single-Site Parts (downstream assembly)
Everything that consumes at least one manufactured intermediate (Circuit Boards need Plastic + Copper Sheet, Motors need Rotors + Stators, etc.) is assigned **winner-takes-all** to the single cluster with the largest share of the product's primary resource. This prevents the same complex part from being split across two bases that would then both need to import sub-components from different places.

The dependency graph (`CONSUMERS`) is the source of truth for this classification. Any product that appears as a consumed input in `CONSUMERS` is single-site.

#### Final Assembly
Space Elevator deliverables (Thermal Propulsion Rocket, Magnetic Field Generator, etc.) are always assigned to the cluster geographically nearest the world origin, which is where the Space Elevator sits.

### 4. Cluster Naming

Each cluster is named after the factory section it most strongly represents. The score for a (cluster, section) pair is:

```
score = cluster's production of section's parts / total map-wide target for that section
```

A global greedy assignment then picks the highest-scoring (cluster, section) pair, assigns it, and removes both from contention. This ensures every section name is used at most once and each cluster gets the name of the section it dominates most relative to that section's full map-wide scale — not just raw volume.

Clusters beyond the number of sections fall back to numbered names.

### 5. Node Usage Visualization

For each resource, the tool calculates how much of the map-wide factory requirement falls on each cluster (proportional to that cluster's share of total supply). Nodes within each cluster are then sorted by rate descending and marked off until the quota is filled:

| Ring color | Meaning |
|-----------|---------|
| Dark gray | Node's full output is consumed |
| Pale yellow | Node is partially consumed |
| White | Node is not needed |

The dot size scales with the node's extraction rate.

### 6. Map Annotation

All visual dimensions are defined relative to a 1280px reference and multiplied by `scale = image_width / 1280`, so the same code produces readable output at any resolution.

**Drawn elements (back to front):**
1. Convex hull fills — one per cluster, color-coded with configurable alpha transparency
2. Resource node dots — sized by rate, ring color by usage state, resource icon above used nodes
3. Cluster centroid circles — numbered, color-matched to their hull
4. Cluster name labels — below the centroid circle
5. Legend — top-left box listing each cluster with a color swatch, name, and a row of icons for everything produced there

---

## Coordinate System

The game world uses Unreal Engine coordinates (centimetres):

| Axis | Range | Direction |
|------|-------|-----------|
| X | −375,000 to +375,000 | West → East |
| Y | −324,600 to +425,300 | North → South (+Y is south) |

The map image maps linearly onto this range. The `--shift-x` / `--shift-y` parameters apply a pixel offset to every drawn element, allowing you to correct for any padding or offset in the map image itself. The defaults (`-332`, `332`) are calibrated for a 5000×5000 map; for a 1280×1280 map use `-85`, `85`.

---

## Output: `clusters.md`

A Markdown table with one row per cluster:

| Column | Content |
|--------|---------|
| # | Cluster index |
| Name | Section name (or fallback) |
| Coords | World coordinates of the centroid |
| Produces | All assigned products with rates |
| Ships Out | Products produced here that are consumed at a different cluster |

---

## File Structure

```
SatFac/
├── satisfactory_clusters.py   # Main script
├── nodes.json                 # Resource node export
├── factory.csv                # Production plan
├── map.png                    # Source world map
├── icons/                     # Item/resource icons (.webp)
│   ├── Iron_Ingot.webp
│   ├── Crude_Oil.webp
│   └── ...
├── clusters.md                # Generated cluster table
└── map-annotated.png          # Generated annotated map
```

---

## Third-Party Assets

The item and resource icons in `icons/` are property of **Coffee Stain Studios** and are sourced from the [Satisfactory Wiki](https://satisfactory.wiki.gg). They are not created by or claimed by this project. This project is a non-commercial fan tool; no ownership or endorsement is implied.

If you redistribute this project, do not include the icon files. Users should source them independently from the wiki or their own game installation.
