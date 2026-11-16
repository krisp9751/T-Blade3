"""Entry point of the T-Blade3 worker process: python -m tblade3.engine._worker <lib> <work dir> <fd>."""
import sys
from multiprocessing.connection import Connection

from .library import worker_main

if __name__ == "__main__":
    worker_main(Connection(int(sys.argv[3])), sys.argv[1], sys.argv[2])
