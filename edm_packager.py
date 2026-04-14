from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import hmac
import json
import os
import zlib
from pathlib import Path

EDM_SIGNING_KEY = os.environ.get("ECHO_DECK_EDM_SIGNING_KEY", "echo-deck-dev-signing-key")
EDM_FORMAT_VERSION = 1
DECK_MODULE_API_VERSION = "1.0"


def _normalize_module_key(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")


def _edm_canonical_json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _extract_module_manifest_from_source(module_path: Path) -> dict:
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    for node in tree.body:
        value_node = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MODULE_MANIFEST":
                    value_node = node.value
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "MODULE_MANIFEST":
                value_node = node.value

        if value_node is None:
            continue

        manifest = ast.literal_eval(value_node)
        if not isinstance(manifest, dict):
            raise ValueError(f"MODULE_MANIFEST must be a dict in: {module_path}")
        return manifest

    raise ValueError(f"MODULE_MANIFEST not found in: {module_path}")


def _sign_edm(manifest: dict, payload_b64: str, signing_key: str | bytes = EDM_SIGNING_KEY) -> str:
    key_bytes = signing_key.encode("utf-8") if isinstance(signing_key, str) else signing_key
    signed_blob = _edm_canonical_json(manifest) + b"." + payload_b64.encode("utf-8")
    return hmac.new(key_bytes, signed_blob, hashlib.sha256).hexdigest()


def _default_edm_output_path(module_path: Path, manifest: dict) -> Path:
    display_name = str(manifest.get("display_name") or "").strip()
    if display_name:
        stem = "".join(ch for ch in display_name.title() if ch.isalnum())
    else:
        stem = "".join(part.capitalize() for part in module_path.stem.split("_") if part)
    stem = stem or "Module"
    return module_path.with_name(f"{stem}.edm")


def package_module_to_edm(module_source: Path, output_path: Path | None = None, signing_key: str | bytes = EDM_SIGNING_KEY) -> Path:
    module_path = Path(module_source)
    if module_path.suffix.lower() != ".py":
        raise ValueError(f"Expected a Python module file (.py), got: {module_path}")
    if not module_path.exists():
        raise FileNotFoundError(f"Module payload file not found: {module_path}")

    manifest = _extract_module_manifest_from_source(module_path)
    key = _normalize_module_key(str(manifest.get("key") or module_path.stem))
    if not key:
        raise ValueError("Manifest key is required")

    module_file = module_path.name
    normalized_manifest = {
        "format_version": EDM_FORMAT_VERSION,
        "key": key,
        "display_name": str(manifest.get("display_name") or key.replace("_", " ").title()),
        "version": str(manifest.get("version") or "0.1.0"),
        "deck_api_version": str(manifest.get("deck_api_version") or DECK_MODULE_API_VERSION),
        "home_category": str(manifest.get("home_category") or manifest.get("category") or "External Modules"),
        "tab_definitions": list(manifest.get("tab_definitions") or manifest.get("tabs") or []),
        "hook_registrations": list(manifest.get("hook_registrations") or []),
        "shared_resource": manifest.get("shared_resource"),
        "shared_resource_priority": int(manifest.get("shared_resource_priority", 1000) or 1000),
        "settings_sections": list(manifest.get("settings_sections") or []),
        "dependencies": list(manifest.get("dependencies") or []),
        "pip_dependencies": list(manifest.get("pip_dependencies") or manifest.get("requires") or []),
        "bound_deck_id": str(manifest.get("bound_deck_id") or ""),
        "assets": [],
        "entry_file": str(module_file),
        "entry_function": str(manifest.get("entry_function") or "register"),
        "description": str(manifest.get("description") or ""),
    }

    payload = {
        "entry_file": str(module_file),
        "entry_function": normalized_manifest["entry_function"],
        "module_source": module_path.read_text(encoding="utf-8"),
        "assets": {},
    }
    payload_b64 = base64.b64encode(zlib.compress(_edm_canonical_json(payload), 9)).decode("ascii")
    package = {
        "edm_schema": "echo_deck_module",
        "manifest": normalized_manifest,
        "payload_b64": payload_b64,
    }
    package["signature"] = _sign_edm(normalized_manifest, payload_b64, signing_key=signing_key)

    if output_path is None:
        output_path = _default_edm_output_path(module_path, manifest)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Package a single module .py file into an .edm artifact.")
    parser.add_argument("module_py", help="Path to module Python file with MODULE_MANIFEST")
    parser.add_argument("--out", dest="out", help="Optional output .edm path")
    args = parser.parse_args()

    built = package_module_to_edm(Path(args.module_py), output_path=(Path(args.out) if args.out else None))
    print(f"Created EDM module: {built}")


if __name__ == "__main__":
    main()
