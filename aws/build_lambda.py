"""Build lambda-deployment.zip for the backend.

Run from the repo root:   python aws/build_lambda.py
Requires Docker Desktop running. Dependencies are installed inside the
official AWS Lambda Python image so compiled wheels match Lambda's Linux
x86_64 runtime, then api/ and aws/lambda_handler.py are copied in and zipped.
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "api"
PKG = ROOT / "lambda-package"
ZIP = ROOT / "lambda-deployment.zip"

# api/ entries that must not be shipped to Lambda.
EXCLUDE = {
    "__pycache__", "tests", "specs", "sql", ".pytest_cache", ".venv", ".env",
    "Dockerfile", "docker-compose.yml", "README.md", "CLAUDE.md",
    "requirements-dev.txt", "pyproject.toml", "requirements.txt",
}


def main() -> None:
    print("Cleaning previous build...")
    shutil.rmtree(PKG, ignore_errors=True)
    ZIP.unlink(missing_ok=True)
    PKG.mkdir()

    print("Installing dependencies for the Lambda runtime (Docker)...")
    subprocess.run(
        [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            "--entrypoint", "",
            "-v", f"{API}:/var/task/api:ro",
            "-v", f"{PKG}:/var/task/out",
            "public.ecr.aws/lambda/python:3.12",
            "/bin/sh", "-c",
            "pip install --target /var/task/out -r /var/task/api/requirements.txt "
            "--platform manylinux2014_x86_64 --only-binary=:all: --upgrade",
        ],
        check=True,
    )

    print("Copying application code...")
    for item in API.iterdir():
        if item.name in EXCLUDE or item.name.endswith(".pyc"):
            continue
        dest = PKG / item.name
        if item.is_dir():
            shutil.copytree(item, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, dest)
    shutil.copy2(ROOT / "aws" / "lambda_handler.py", PKG / "lambda_handler.py")

    print("Creating zip...")
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in PKG.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(PKG))

    unzipped = sum(p.stat().st_size for p in PKG.rglob("*") if p.is_file()) / 1024 / 1024
    zipped = ZIP.stat().st_size / 1024 / 1024
    print(f"Created {ZIP.name}: {zipped:.1f} MB zipped, {unzipped:.1f} MB unzipped")
    print("Lambda limits: 50 MB zipped for direct upload (use S3 above that), 250 MB unzipped.")
    if unzipped > 250:
        print("WARNING: over the 250 MB unzipped limit -- use a container image instead.")
        sys.exit(1)


if __name__ == "__main__":
    main()
