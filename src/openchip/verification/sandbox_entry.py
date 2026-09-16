"""Trusted entry point inside the reference sandbox, before importing model code."""
import resource
import runpy
import sys

resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
