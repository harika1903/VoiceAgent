"""Allow `python -m app.worker --worker-id xyz` to start a single worker process."""

import argparse
import asyncio

from app.worker.worker import worker_main

parser = argparse.ArgumentParser()
parser.add_argument("--worker-id", default=None)
args = parser.parse_args()

asyncio.run(worker_main(args.worker_id))
