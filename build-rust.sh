#!/usr/bin/env bash
# Build the Rust quote matcher into sg/_verify.abi3.so. Without it, sg/dataroom.py uses the Python one.
# Needs Rust (rustup.rs) and a C linker (apt install build-essential).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.cargo/bin:$PATH"
cargo build --release --manifest-path rust/verify/Cargo.toml
cp rust/verify/target/release/lib_verify.so sg/_verify.abi3.so
python3 -m unittest discover -s tests -t .
