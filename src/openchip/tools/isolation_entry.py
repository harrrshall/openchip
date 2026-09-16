"""Trusted resource-limit launcher, entered only inside the EDA namespace."""
import os
import resource
import sys

seconds = int(sys.argv[1])
resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024**2, 256 * 1024**2))
resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
os.execv(sys.argv[2], sys.argv[2:])
