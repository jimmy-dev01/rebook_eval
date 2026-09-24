"""The client's shipped grader, loaded unchanged from their package, as the baseline to compare against."""
import importlib.util
import sys

from rebook.paths import CLIENT


def load_naive_grader():
    """Import naive_grader.py without writing a __pycache__ folder into the client's package."""
    spec = importlib.util.spec_from_file_location("naive_grader", CLIENT / "naive_grader.py")
    module = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module
