# cloudfetch

Tired of endlessly clicking through portals to download LiDAR data? Is your area of interest always on intersection of 4 neighbouring tiles? **cloudfetch** is a library for downloading arbitrary polygons of large remote point cloud datasets. Designed for ease of use and automated processing, it leverages PDAL (Point Data Abstraction Library) and COPC under the hood to crop, merge, and filter point cloud tiles seamlessly.

## Features

* **Custom Areas of Interest (AOI):** Define arbitrary polygons to query specific geographic regions rather than downloading entire dataset tiles.
* **Interactive Polygon Drawing:** Includes an interactive map widget powered by `tkintermapview` allowing users to draw AOIs directly through a GUI.
* **Multiple Open Datasets:** Built-in support for multiple national remote point cloud datasets, including the Dutch AHN series, French IGN LiDAR HD, and Canadian CanElevation.
* **Extendible Architecture** Integrate new data sources by subclassing the abstract PointCloudProvider. Developers only need to implement a single get_index method to retrieve tile URLs, and the base class will automatically handle the heavy lifting of downloading, cropping, and merging via PDAL.
* **Provider Chaining:** Use `ProviderChain` to automatically attempt downloads across multiple datasets in sequence (e.g., trying AHN6, and falling back to AHN5 if data is unavailable).
* **Dynamic Resolution Control:** Control the output density via minimum point spacing (Poisson thinning) to keep file sizes manageable.

## Installation

**cloudfetch** requires Python 3.10 or higher. 

Because this library relies heavily on **PDAL** for its C++ point cloud processing capabilities, you must install the underlying PDAL binaries on your system *before* installing this package. Standard `pip` cannot build these C++ dependencies reliably.

### Step 1: Install PDAL (Prerequisite)
I strongly recommend using a package manager like `conda` or `pixi` to install the PDAL Python bindings and binaries:

**Using Conda/Mamba:**
```bash
conda install -c conda-forge python-pdal
```

**Using Pixi:**
```bash
pixi add pdal python-pdal
```

*(Note: Advanced users can also install PDAL via system package managers like `brew install pdal` or `apt-get install pdal`, but Conda/Pixi is the safest route).*

### Step 2: Install cloudfetch
Once PDAL is installed in your environment, you can safely install the library via PyPI:

```bash
pip install cloudfetch
```


## Quickstart

Below is a basic example demonstrating how to draw an AOI interactively, chain two AHN datasets together, and download the resulting point cloud. 

```python
import logging
from pathlib import Path

from cloudfetch import AHN5, AHN6
from cloudfetch.base import ProviderChain
from cloudfetch.utils import AOIPolygon

# Set up logging to track the download and PDAL processing
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] | %(name)s | %(message)s")


def main():
    # 1. Prompt the user to draw an Area of Interest on an interactive map
    aoi_rdnew = AOIPolygon.get_from_user("Draw AOI for AHN demo")

    # 2. Initialize the dataset providers
    ahn6 = AHN6(data_dir="./data")
    ahn5 = AHN5(data_dir="./data")

    # 3. Chain them: The library will try AHN6 first, then fallback to AHN5
    ahn_chain = ProviderChain(providers=[ahn6, ahn5])

    # 4. Fetch the data, which will be merged, cropped, and saved as COPC.LAZ
    result_path = ahn_chain.fetch(aoi=aoi_rdnew.polygon, aoi_crs=aoi_rdnew.crs, output_path="./data/my_output.copc.laz")


if __name__ == "__main__":
    main()
```

### Loading Geometries from Files
If you already have a predefined shape (such as a GeoJSON file), you can bypass the UI and load the polygon directly:

```python
aoi = AOIPolygon.get_from_file(Path("my_boundary.geojson"))
```

### Adjusting Resolution
You can dynamically thin the dataset to a specific minimum point spacing by supplying a `resolution` float (in coordinate units) to the `fetch()` method:

```python
# Apply a 2.0 coordinate unit radius for Poisson thinning
provider.fetch(aoi=aoi.polygon, resolution=2.0)
```


## Supported Datasets

The library currently supports the following dataset providers out of the box:

* **Netherlands:** `AHN1`, `AHN2`, `AHN3`, `AHN4`, `AHN5`, `AHN6`.
* **France:** `IGNLidarHD`.
* **Canada:** `CanElevation`


##  License & Authors

* **Author:** Yair Roorda.
* **License:** MIT License.