import logging
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

import requests

from .exceptions import ProviderFetchError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def download_file(url: str, dest_path: Path, timeout: int = 15, chunk_size: int = 8192) -> Path:
    """
    Downloads a file safely using streaming to prevent memory overload.
    Cleans up the destination file if the download fails or is interrupted.
    """
    try:
        # stream=True ensures we don't load 300MB GPKG files into RAM
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()  # Fails immediately on 404, 500, etc.

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)

        return dest_path

    except requests.exceptions.RequestException as exc:
        # Delete the file if it partially downloaded before the connection died
        if dest_path.exists():
            dest_path.unlink()

        raise ProviderFetchError("Network", f"Failed to download {url}: {exc}") from exc


def open_in_cloudcompare(dataset_path: Path | str) -> None:
    import os
    import subprocess

    if os.path.exists(dataset_path):
        logger.info(f"Opening {dataset_path} in CloudCompare...")
        cmd = ["flatpak", "run", "org.cloudcompare.CloudCompare", str(dataset_path)]

        subprocess.Popen(cmd)
    else:
        logger.warning(f"Could not find file at {dataset_path}.")


def timed(task_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger.info(f"{task_name} took {elapsed:.3f}s")
            return result

        return wrapper

    return decorator


@contextmanager
def status_spinner(message: str):
    logger.info(message)
    yield
    logger.info("Done.")
