"""Create a PRIVATE, UNVERIFIED Pico 4 Pro factory calibration draft.

Takes the user's own sensor.yaml tar (read-only), does not contain calibration constants
or publish any data. The output is deliberately NOT accepted by the live solver until
physical camera mapping and SteamVR HeadFromBody are independently validated.
"""
import argparse
import json
from pathlib import Path
import re
import tarfile

# Observed Binder IDs 0/3/4/5 have matching visual camera positions; factory
# cam0/1/3/2 is a PHYSICAL-PLACEMENT HYPOTHESIS, not verified via vendor metadata.
BINDER_TO_FACTORY_HYPOTHESIS = {0: 0, 3: 1, 4: 3, 5: 2}


def vector(text, key):
    if key == "T_BS":
        found = re.search(r"(?ms)^T_BS:\s*.*?^\s*data:\s*\[([^]]+)\]", text)
    else:
        found = re.search(r"(?m)^" + re.escape(key) + r":\s*\[([^]]+)\]", text)
    if not found:
        raise ValueError(f"missing {key}")
    return [float(q.strip()) for q in found.group(1).split(",")]


def make_draft(input_path):
    with tarfile.open(input_path, "r:*") as archive:
        cameras = []
        for binder_id, factory_id in BINDER_TO_FACTORY_HYPOTHESIS.items():
            member = archive.getmember(f"cam{factory_id}/sensor.yaml")
            if not member.isfile() or member.size > 65536:
                raise ValueError("unexpected sensor.yaml entry")
            src = archive.extractfile(member).read().decode("utf-8")
            if not re.search(r"(?m)^camera_model:\s*omni\s*$", src):
                raise ValueError("expected omni camera_model")
            if not re.search(r"(?m)^distortion_model:\s*radtan\s*$", src):
                raise ValueError("expected radtan distortion_model")
            size = vector(src, "resolution")
            matrix = vector(src, "T_BS")
            intr = vector(src, "intrinsics")
            dist = vector(src, "distortion_coefficients")
            if size != [640, 480] or len(matrix) != 16 or len(intr) != 5 or len(dist) != 4:
                raise ValueError("unexpected Pico tracking camera schema")
            cameras.append({
                "id": binder_id, "factory_camera": factory_id,
                "size": size, "T_BS": matrix,
                "intrinsics": intr, "distortion": dist,
            })
    return {
        "kind": "pico", "device": "PICO 4 Pro",
        "mapping_verified": False, "pose_verified": False,
        "HeadFromBody": None,
        "cameras": cameras,
        "WARNING": "DRAFT ONLY: mapping inferred by camera positions; SteamVR body->HMD transform unknown."
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("tar", type=Path, help="private sensor.yaml archive extracted from your own Pico")
    p.add_argument("--output", type=Path, default=Path("out/pico-calibration-DRAFT.json"))
    args = p.parse_args()
    data = make_draft(args.tar)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved PRIVATE UNVERIFIED draft to {args.output}")
    print("Factory cameras 0..3 are all 640x480 Omni/Radtan; candidate mapping:")
    for cam in data["cameras"]:
        print(f"  Binder C{cam['id']} -> factory cam{cam['factory_camera']} (UNVERIFIED)")
    print("Live tracking must remain disabled: both verification flags are false.")


if __name__ == "__main__":
    main()
