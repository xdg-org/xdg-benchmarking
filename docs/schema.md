# XDG Benchmarking Data Schema

This document describes the JSON schema for the XDG (Accelerated Discretized Geometry) benchmarking data structure.

## Overview

The benchmarking data is organized in a hierarchical structure where each benchmark run contains configuration and results for multiple models and executables. The system uses dynamic discovery to automatically find and load new datasets.

## Directory Structure

```
results/
├── runs/                    # Auto-discovered benchmark runs
│   ├── {run_id}/           # Unique run identifier (typically timestamp)
│   │   ├── config.json     # Run configuration and metadata
│   │   ├── results.json    # Benchmark results data
│   │   └── raw/           # Original CSV files (optional, for traceability)
│   └── ...
```

## Schema Definitions

### 1. Config Schema (`config.json`)

**Purpose**: Defines the configuration and metadata for a benchmark run.

**File Location**: `results/runs/{run_id}/config.json`

**Schema**:
```json
{
  "run_id": "string",           // Unique identifier for this run
  "date": "string",             // ISO 8601 timestamp (e.g., "2025-07-15T17:10:58Z")
  "config_file": "string",      // Path to configuration file used
  "models": ["string"],         // Array of model identifiers
  "executables": ["string"],    // Array of executable identifiers
  "particles_per_thread": "number",  // Number of particles per thread
  "max_threads": "number",      // Maximum number of threads tested
  "n_repeats": "number",        // Number of repeat runs
  "architecture": {             // Host machine metadata
    "machine": "string",        // e.g., "x86_64"
    "processor": "string",      // CPU identifier
    "cpu_count": "number",      // Logical CPU count
    "os": "string",             // OS name and version
    "python_version": "string"  // Interpreter version
  },
  "software_versions": {        // Optional; component -> version/commit map
    "{component}": "string"
  }
}
```

**Example**:
```json
{
  "run_id": "20250715_171058",
  "date": "2025-07-15T17:10:58Z",
  "config_file": "scaling_config.i",
  "models": ["tokamak", "atr", "msre"],
  "executables": ["xdg"],
  "particles_per_thread": 1000,
  "max_threads": 20,
  "n_repeats": 1,
  "architecture": {
    "machine": "x86_64",
    "processor": "Intel(R) Xeon(R)",
    "cpu_count": 64,
    "os": "Linux 6.8.0",
    "python_version": "3.11.7"
  },
  "software_versions": {
    "OpenMC": "0.13.4",
    "XDG": "c0ffee42"
  }
}
```

### 2. Results Schema (`results.json`)

**Purpose**: Contains the actual benchmark performance data.

**File Location**: `results/runs/{run_id}/results.json`

**Schema**:
```json
{
  "run_id": "string",           // Must match config.json run_id
  "date": "string",             // Must match config.json date
  "software_versions": {        // Optional mirror of config metadata
    "{component}": "string"
  },
  "results": {
    "{model_id}": {             // Model identifier (e.g., "tokamak")
      "{executable_id}": {      // Executable identifier (e.g., "moab")
        "scaling": [
          {
            "threads": "number",        // Number of threads (1, 5, 10, 15, etc.)
            "active_rate": "number|null",   // Active particles per second
            "inactive_rate": "number|null"  // Inactive particles per second
          }
        ],
        "max_performance": {
          "threads": "number",          // Thread count for max performance
          "active_rate": "number|null", // Maximum active rate achieved
          "inactive_rate": "number|null" // Maximum inactive rate achieved
        }
      }
    }
  }
}
```

**Example**:
```json
{
  "run_id": "20250715_171058",
  "date": "2025-07-15T17:10:58Z",
  "software_versions": {
    "OpenMC": "0.13.4",
    "XDG": "c0ffee42"
  },
  "results": {
    "atr": {
      "moab": {
        "scaling": [
          {"threads": 1, "inactive_rate": 345.05, "active_rate": 325.54},
          {"threads": 5, "inactive_rate": 561.29, "active_rate": 556.03},
          {"threads": 10, "inactive_rate": 687.74, "active_rate": 713.93},
          {"threads": 15, "inactive_rate": 762.14, "active_rate": 762.76}
        ],
        "max_performance": {
          "threads": 15,
          "active_rate": 762.76,
          "inactive_rate": 762.14
        }
      },
      "xdg": {
        "scaling": [
          {"threads": 1, "inactive_rate": 699.70, "active_rate": 645.56},
          {"threads": 5, "inactive_rate": 2358.76, "active_rate": 2229.78},
          {"threads": 10, "inactive_rate": 4362.48, "active_rate": 4201.33},
          {"threads": 15, "inactive_rate": 6251.09, "active_rate": 5938.64}
        ],
        "max_performance": {
          "threads": 15,
          "active_rate": 5938.64,
          "inactive_rate": 6251.09
        }
      }
    }
  }
}
```

## Data Types and Constraints

### Identifiers
- **run_id**: String, typically timestamp format (e.g., "20250715_171058")
- **model_id**: String, lowercase, no spaces (e.g., "tokamak", "atr", "msre")
- **executable_id**: String, lowercase, no spaces (e.g., "moab", "xdg", "double-down")

### Performance Metrics
- **active_rate**: Number or null, particles per second during active simulation
- **inactive_rate**: Number or null, particles per second during inactive/burnup cycles
- **threads**: Integer, number of CPU threads used

### Timestamps
- **date**: ISO 8601 format (e.g., "2025-07-15T17:10:58Z")

## Validation Rules

1. **Consistency**: `run_id` and `date` must match between `config.json` and `results.json`
2. **Completeness**: All models and executables listed in `config.json` must have corresponding data in `results.json`
3. **Thread Counts**: Thread counts in scaling data should be consistent across all models/executables
4. **Data Types**: All numeric values should be numbers (not strings), null values are allowed for missing data
5. **Performance**: Active and inactive rates should be positive numbers when not null (values that are non-positive/NaN/inf are converted to null during generation)

## Dynamic Discovery

The dashboard automatically discovers new datasets by:

1. Scanning `results/runs/` for directories
2. Looking for `config.json` and `results.json` files in each directory
3. Validating the schema of both files
4. Loading the data into the dashboard

### Adding New Datasets

To add a new benchmark run:

1. Create directory: `results/runs/{new_run_id}/`
2. Add `config.json` following the schema above
3. Add `results.json` following the schema above
4. (Optional) Add `raw/` directory with original CSV files
5. Restart the dashboard to auto-discover the new data

### Adding New Models/Executables

New models and executables are automatically discovered when they appear in new benchmark runs. No additional configuration is required.

## Schema Versioning

The current schema is version 1.0. Future schema changes will be documented with version numbers and migration guides.

## Error Handling

- Invalid JSON files are skipped with warnings
- Missing required files cause the run to be excluded
- Schema validation errors are logged for debugging
- The dashboard continues to function with partial data

## Examples

See the `results/runs/` directory for complete examples of valid schema files.
