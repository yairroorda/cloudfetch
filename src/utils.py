import logging
import time
from contextlib import contextmanager
from functools import wraps


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(levelname)s] | %(name)s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def open_in_cloudcompare(dataset_path):
    import os
    import subprocess

    if os.path.exists(dataset_path):
        print(f"Opening {dataset_path} in CloudCompare...")

        cmd = ["flatpak", "run", "org.cloudcompare.CloudCompare", str(dataset_path)]

        subprocess.Popen(cmd)
    else:
        print(f"Error: Could not find file at {dataset_path}")


def timed(task_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger = get_logger("Timing")
            logger.info(f"{task_name} took {elapsed:.3f}s")
            return result

        return wrapper

    return decorator


@contextmanager
def status_spinner(message: str):
    logger = get_logger("Task")
    logger.info(message)
    yield
    logger.info("Done.")
