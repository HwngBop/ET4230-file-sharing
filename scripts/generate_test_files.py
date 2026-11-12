"""Deterministic decimal-MB fixtures; no external dependencies."""
import argparse
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZES = (1_000_000, 10_000_000, 50_000_000)
SEED = 4230
BLOCK_SIZE = 65536


def generate_files(output_dir, force=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [output_dir / f"test_{size // 1_000_000}MB.bin" for size in SIZES]
    if not force and any(path.exists() for path in paths):
        raise FileExistsError("Test files already exist; choose another directory or use --force")
    for size, path in zip(SIZES, paths):
        rng = random.Random(SEED + size)
        with path.open("wb" if force else "xb") as stream:
            remaining = size
            while remaining:
                count = min(BLOCK_SIZE, remaining)
                stream.write(rng.randbytes(count))
                remaining -= count
        if path.stat().st_size != size:
            raise OSError(f"Incorrect size: {path}")
        print(f"{path}: {path.stat().st_size} bytes")
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "client_data/uploads")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        generate_files(args.output_dir, args.force)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Cannot generate files: {exc}\n")


if __name__ == "__main__":
    main()
