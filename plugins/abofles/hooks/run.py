"""Hook launcher: imports abofles_hook so Python caches its bytecode in hooks/__pycache__.
Running abofles_hook.py directly recompiles the 3,400-line module on every tool call (~13 ms each)."""
import os
import sys

sys.dont_write_bytecode = False  # the hook environment sets PYTHONDONTWRITEBYTECODE=1; the cache is the point of this file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from abofles_hook import main  # noqa: E402

main()
