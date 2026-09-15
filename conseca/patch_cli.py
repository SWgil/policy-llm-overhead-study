#!/usr/bin/env python3
"""Remove gemini-cli's <untrusted_context> wrapper around tool results (opt-in).

gemini-cli wraps every MCP / shell / web_fetch result in <untrusted_context>
tags before the model sees it (utils/textUtils.js wrapUntrusted). There is no
setting or hook that turns this off: the function reads no config, and hooks
only see text parts, never functionResponse parts. The only way is to edit the
installed bundle, which this script does reversibly.

    python patch_cli.py --apply  [--gemini <path> | --bundle-dir <dir>]
    python patch_cli.py --revert [--gemini <path> | --bundle-dir <dir>]
    python patch_cli.py --status [--gemini <path> | --bundle-dir <dir>]

Every chunk containing the function is patched (the bundle ships several copies
of core); originals are kept as <chunk>.conseca-orig. Apply the same state to
both arms and say which state the report used.

Verified on @google/gemini-cli 0.59.0.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKUP_SUFFIX = ".conseca-orig"
# Body ends at the first closing brace in column 0 (esbuild output layout).
FUNC_RE = re.compile(r"function wrapUntrusted\(text\) \{.*?\n\}", re.S)
PATCHED_BODY = "function wrapUntrusted(text) {\n  return text; // conseca: untrusted_context wrapper removed\n}"


def find_bundle_dir(gemini: str | None, bundle_dir: str | None) -> Path:
    if bundle_dir:
        return Path(bundle_dir)
    candidates = []
    if gemini:
        candidates.append(Path(gemini))
    for name in ("gemini", "gemini.cmd"):
        p = shutil.which(name)
        if p:
            candidates.append(Path(p))
    for c in candidates:
        try:
            real = c.resolve()
        except OSError:
            continue
        for parent in [real, *real.parents]:
            if (parent / "bundle" / "gemini.js").exists():
                return parent / "bundle"
            if (parent / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js").exists():
                return parent / "node_modules" / "@google" / "gemini-cli" / "bundle"
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True).stdout.strip()
        p = Path(root) / "@google" / "gemini-cli" / "bundle"
        if (p / "gemini.js").exists():
            return p
    except Exception:
        pass
    sys.exit("could not locate the gemini-cli bundle directory; pass --bundle-dir")


def chunks_with_function(bundle: Path) -> list[Path]:
    out = []
    for f in sorted(bundle.glob("*.js")):
        if "function wrapUntrusted(text)" in f.read_text(encoding="utf-8", errors="ignore"):
            out.append(f)
    return out


def status(bundle: Path) -> tuple[list[Path], list[Path]]:
    patched, stock = [], []
    for f in chunks_with_function(bundle):
        (patched if "conseca: untrusted_context wrapper removed" in f.read_text(encoding="utf-8") else stock).append(f)
    return patched, stock


def apply(bundle: Path) -> int:
    patched, stock = status(bundle)
    if not patched and not stock:
        sys.exit(f"no chunk in {bundle} contains wrapUntrusted; unsupported gemini-cli version?")
    for f in stock:
        text = f.read_text(encoding="utf-8")
        new, n = FUNC_RE.subn(PATCHED_BODY, text, count=1)
        if n != 1:
            sys.exit(f"{f.name}: could not isolate the function body; not patching")
        backup = f.with_name(f.name + BACKUP_SUFFIX)
        if not backup.exists():
            shutil.copyfile(f, backup)
        f.write_text(new, encoding="utf-8")
        print(f"patched  {f.name}")
    for f in patched:
        print(f"already  {f.name}")
    return 0


def revert(bundle: Path) -> int:
    n = 0
    for backup in sorted(bundle.glob(f"*{BACKUP_SUFFIX}")):
        target = backup.with_name(backup.name[: -len(BACKUP_SUFFIX)])
        shutil.copyfile(backup, target)
        backup.unlink()
        print(f"restored {target.name}")
        n += 1
    if n == 0:
        print("nothing to revert")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--revert", action="store_true")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--gemini", default=None, help="path to the gemini binary (default: PATH)")
    ap.add_argument("--bundle-dir", default=None, help="explicit path to @google/gemini-cli/bundle")
    args = ap.parse_args()
    bundle = find_bundle_dir(args.gemini, args.bundle_dir)
    print(f"bundle: {bundle}")
    if args.apply:
        return apply(bundle)
    if args.revert:
        return revert(bundle)
    patched, stock = status(bundle)
    print(f"patched: {[f.name for f in patched]}\nstock:   {[f.name for f in stock]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
