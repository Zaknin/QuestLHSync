"""Offline quality, fixed-ROI, and station-center FOV analysis for P3-K."""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

CAMERAS = (0, 3, 4, 5)
LOW_CAMERAS = (4, 5)
PHASES = ("baseline", "off", "restored")
REQUIRED_ACTIONS = ("BASELINE_READY", "OFF", "OFF_READY", "ON", "ON_READY", "SPINUP_DONE", "PASS_DONE")
NS = 1_000_000_000
TRIM_NS = 2 * NS
MIN_HOLD_NS = {"baseline": 20 * NS, "off": 20 * NS, "spinup": 25 * NS, "restored": 20 * NS}
MIN_WINDOW_NS = 15 * NS
MIN_CAMERA_FRAMES = 200
MIN_POSES = 100
POSE_MATCH_NS = 20_000_000
POSE_SAMPLE_HZ = 5
STATIONARY_SAMPLE_HZ = 10
MIN_STATIONARY_BINS = 8
MIN_STATIONARY_RATIO = 0.75
MATCH_POSITION_M, MATCH_ANGLE_DEG = 0.05, 5.0
PREFERRED_POSITION_M, PREFERRED_ANGLE_DEG = 0.02, 3.0
MIN_MATCH_COVERAGE, PREFERRED_MATCH_COVERAGE = 0.70, 0.50
ROI_PEAK_THRESHOLD = 100
ROI_CLUSTER_RADIUS_PX = 12.0
ROI_MATCH_RADIUS_PX = 12.0
ROI_MAX_CANDIDATES = 8
ROI_MAX_CLUSTERS = 512
ROI_MIN_BASELINE_HITS = 5
ROI_MIN_ON_RATE = 0.01
ROI_MAX_OFF_RATE_RATIO = 0.20
ROI_OFF_PERSISTENCE_RATE = 0.02
MAX_LINE_BYTES = 1_000_000
HEAD_FROM_BODY = (0.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0,
                  0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


class QualityError(ValueError):
    pass


@dataclass(frozen=True)
class Pose:
    qpc_ns: int
    matrix: tuple[float, ...]


@dataclass(frozen=True)
class Frame:
    qpc_ns: int
    camera: int
    sequence: int
    blobs: tuple[tuple[float, float, int], ...]


@dataclass(frozen=True)
class Station:
    qpc_ns: int
    position: tuple[float, float, float]


@dataclass
class Cluster:
    x_sum: float = 0.0
    y_sum: float = 0.0
    points: int = 0
    frames: int = 0
    peak_sum: int = 0
    first_ns: int = 0
    last_ns: int = 0
    first_sequence: int = 0
    last_sequence: int = 0

    @property
    def center(self):
        return self.x_sum / self.points, self.y_sum / self.points


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_frame(parts: list[str]) -> Frame:
    if len(parts) < 8 or parts[1:3] != ["U", "F"]:
        raise ValueError("malformed frame")
    camera, sequence = int(parts[3]), int(parts[4])
    stamp, mean, count = int(parts[5]), int(parts[6]), int(parts[7])
    if camera not in CAMERAS or sequence < 0 or stamp < 0 or mean < 0 or not 0 <= count <= 4096:
        raise ValueError("frame field outside bounds")
    if len(parts) != 8 + 4 * count:
        raise ValueError("blob count mismatch")
    blobs = []
    for offset in range(8, len(parts), 4):
        x, y, area, peak = map(int, parts[offset:offset + 4])
        if not (0 <= x <= 6400 and 0 <= y <= 4800 and 1 <= area <= 307200 and 0 <= peak <= 255):
            raise ValueError("blob field outside bounds")
        blobs.append((x / 10.0, y / 10.0, peak))
    return Frame(int(parts[0]), camera, sequence, tuple(blobs))


def _parse_pose(parts: list[str]) -> Pose:
    if len(parts) != 15 or parts[1:3] != ["P", "0"]:
        raise ValueError("malformed P 0 record")
    matrix = tuple(float(value) for value in parts[3:])
    if len(matrix) != 12 or not all(math.isfinite(value) for value in matrix):
        raise ValueError("invalid P 0 matrix")
    return Pose(int(parts[0]), matrix)


def _parse_station(parts: list[str]) -> Station | None:
    # Exact raw writer schema: S serial channel x y z qw qx qy qz.
    if len(parts) != 11 or parts[1] != "S":
        return None
    try:
        if int(parts[3]) != 7:
            return None
        xyz = tuple(float(value) for value in parts[4:7])
        quat = tuple(float(value) for value in parts[7:11])
    except ValueError:
        return None
    if not all(math.isfinite(value) for value in (*xyz, *quat)) or sum(v * v for v in quat) < 1e-12:
        return None
    return Station(int(parts[0]), xyz)


def read_markers(path: Path) -> dict[str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"Action", "Channel", "QpcNs"}.issubset(reader.fieldnames):
            raise QualityError("marker CSV lacks Action, Channel, or QpcNs")
        rows = list(reader)
    if len(rows) != len(REQUIRED_ACTIONS):
        raise QualityError("marker count does not match the required seven-event sequence")
    result, seqs = {}, []
    for row, expected in zip(rows, REQUIRED_ACTIONS):
        try:
            action, channel, stamp = row["Action"], int(row["Channel"]), int(row["QpcNs"])
            if row.get("Seq") not in (None, ""):
                seqs.append(int(row["Seq"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise QualityError("malformed marker field") from exc
        if action != expected or channel != 7 or stamp <= 0 or action in result:
            raise QualityError("marker action order, channel, or timestamp is invalid")
        result[action] = stamp
    if seqs and seqs != list(range(1, len(REQUIRED_ACTIONS) + 1)):
        raise QualityError("marker sequence numbers are not contiguous")
    stamps = [result[action] for action in REQUIRED_ACTIONS]
    if any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise QualityError("marker timestamps are not strictly monotonic")
    return result


def _windows(markers):
    return {
        "baseline": (markers["BASELINE_READY"] + TRIM_NS, markers["OFF"] - TRIM_NS),
        "off": (markers["OFF_READY"] + TRIM_NS, markers["ON"] - TRIM_NS),
        "restored": (markers["SPINUP_DONE"] + TRIM_NS, markers["PASS_DONE"] - TRIM_NS),
    }


def _inside(stamp, interval):
    return interval[0] <= stamp < interval[1]


def _position_delta(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in (3, 7, 11)))


def _rotation_angle(a, b):
    trace = sum(a[row * 4 + col] * b[row * 4 + col]
                for row in range(3) for col in range(3))
    return math.degrees(math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0))))


def _nearest_index(times, target):
    if not times:
        return None
    index = bisect.bisect_left(times, target)
    candidates = [i for i in (index - 1, index) if 0 <= i < len(times)]
    return min(candidates, key=lambda i: abs(times[i] - target))


def _sample_poses(poses, interval, hz):
    if not poses:
        return []
    times = [pose.qpc_ns for pose in poses]
    step = round(NS / hz)
    target = interval[0] + step // 2
    samples = []
    while target < interval[1] - step // 2:
        index = _nearest_index(times, target)
        if index is not None and abs(times[index] - target) <= step // 2:
            pose = poses[index]
            if not samples or samples[-1].qpc_ns != pose.qpc_ns:
                samples.append(pose)
        target += step
    return samples


def _pose_matches(left, right, position_limit, angle_limit):
    edges = []
    for li, a in enumerate(left):
        for ri, b in enumerate(right):
            position = _position_delta(a.matrix, b.matrix)
            if position > position_limit:
                continue
            angle = _rotation_angle(a.matrix, b.matrix)
            if angle <= angle_limit:
                edges.append((position / position_limit + angle / angle_limit, li, ri))
    edges.sort()
    used_left, used_right, matches = set(), set(), []
    for _, li, ri in edges:
        if li not in used_left and ri not in used_right:
            used_left.add(li)
            used_right.add(ri)
            matches.append((li, ri))
    return matches


def _overlap(left, right):
    matches = _pose_matches(left, right, MATCH_POSITION_M, MATCH_ANGLE_DEG)
    preferred = _pose_matches(left, right, PREFERRED_POSITION_M, PREFERRED_ANGLE_DEG)
    left_ids, right_ids = {i for i, _ in matches}, {j for _, j in matches}
    left_pref, right_pref = {i for i, _ in preferred}, {j for _, j in preferred}
    left_cov = len(matches) / len(left) if left else 0.0
    right_cov = len(matches) / len(right) if right else 0.0
    pref_cov = min(len(left_pref) / len(left) if left else 0.0,
                   len(right_pref) / len(right) if right else 0.0)
    report = {"matched_pairs": len(matches), "left_samples": len(left), "right_samples": len(right),
              "left_coverage": left_cov, "right_coverage": right_cov,
              "coverage_5cm_5deg": min(left_cov, right_cov),
              "coverage_2cm_3deg": pref_cov,
              "preferred_target_met": pref_cov >= PREFERRED_MATCH_COVERAGE}
    return report, {"left": left_ids, "right": right_ids}


def _stationarity(poses, interval):
    samples = _sample_poses(poses, interval, STATIONARY_SAMPLE_HZ)
    groups = defaultdict(list)
    for pose in samples:
        groups[(pose.qpc_ns - interval[0]) // NS].append(pose)
    measured = broad = preferred = 0
    for group in groups.values():
        if len(group) < 5:
            continue
        center = tuple(median(pose.matrix[i] for pose in group) for i in (3, 7, 11))
        rotation = min(group, key=lambda a: sum(_rotation_angle(a.matrix, b.matrix) for b in group))
        broad_in, preferred_in = 0, 0
        for pose in group:
            distance = math.dist((pose.matrix[3], pose.matrix[7], pose.matrix[11]), center)
            angle = _rotation_angle(pose.matrix, rotation.matrix)
            broad_in += distance <= 0.05 and angle <= 5.0
            preferred_in += distance <= 0.02 and angle <= 3.0
        measured += 1
        broad += broad_in / len(group) >= 0.80
        preferred += preferred_in / len(group) >= 0.80
    return {"measured_one_second_bins": measured,
            "stationary_bins_5cm_5deg": broad,
            "stationary_bins_2cm_3deg": preferred,
            "stationary_ratio_5cm_5deg": broad / measured if measured else 0.0,
            "stationary_seconds_minimum": broad}


def _cluster_frame(clusters, frame):
    touched = set()
    for x, y, peak in frame.blobs:
        if peak < ROI_PEAK_THRESHOLD:
            continue
        closest, closest_distance = None, ROI_CLUSTER_RADIUS_PX
        for index, cluster in enumerate(clusters):
            if cluster.points == 0:
                continue
            cx, cy = cluster.center
            distance = math.hypot(x - cx, y - cy)
            if distance <= closest_distance:
                closest, closest_distance = index, distance
        if closest is None:
            if len(clusters) >= ROI_MAX_CLUSTERS:
                continue
            clusters.append(Cluster())
            closest = len(clusters) - 1
        cluster = clusters[closest]
        cluster.x_sum += x
        cluster.y_sum += y
        cluster.points += 1
        cluster.peak_sum += peak
        if closest not in touched:
            cluster.frames += 1
            touched.add(closest)
        if not cluster.first_ns:
            cluster.first_ns = frame.qpc_ns
            cluster.first_sequence = frame.sequence
        cluster.last_ns = frame.qpc_ns
        cluster.last_sequence = frame.sequence


def _select_rois(clusters, baseline_frames):
    minimum = max(ROI_MIN_BASELINE_HITS, math.ceil(baseline_frames * 0.01))
    ranked = [item for item in clusters if item.frames >= minimum]
    ranked.sort(key=lambda item: (-item.frames, -item.peak_sum / item.points,
                                  item.center[1], item.center[0]))
    chosen = []
    for item in ranked:
        if any(math.dist(item.center, current.center) <= ROI_MATCH_RADIUS_PX for current in chosen):
            continue
        chosen.append(item)
        if len(chosen) == ROI_MAX_CANDIDATES:
            break
    return chosen


def _load_calibration(path):
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("mapping_verified") is True or data.get("pose_verified") is True:
        raise QualityError("diagnostic calibration unexpectedly enables a safety gate")
    cameras = data.get("cameras")
    if not isinstance(cameras, list) or len(cameras) != 4:
        raise QualityError("private calibration draft does not contain four cameras")
    by_factory, ids, candidate_mapping = {}, set(), {}
    for camera in cameras:
        try:
            cid, factory = int(camera["id"]), int(camera["factory_camera"])
            size = camera["size"]
            tbs = tuple(float(value) for value in camera["T_BS"])
            intr = tuple(float(value) for value in camera["intrinsics"])
            dist = tuple(float(value) for value in camera["distortion"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QualityError("private calibration schema is invalid") from exc
        if cid not in CAMERAS or cid in ids or factory not in range(4) or factory in by_factory:
            raise QualityError("private calibration camera IDs are not unique and complete")
        if size != [640, 480] or (len(tbs), len(intr), len(dist)) != (16, 5, 4):
            raise QualityError("private calibration dimensions or coefficient lengths are invalid")
        if not all(math.isfinite(v) for v in (*tbs, *intr, *dist)) or intr[0] < 0 or intr[1] <= 0 or intr[2] <= 0:
            raise QualityError("private calibration contains invalid Omni/Radtan values")
        if (any(abs(value) > 1e-6 for value in tbs[12:15]) or abs(tbs[15] - 1.0) > 1e-6):
            raise QualityError("private factory extrinsic is not a rigid row-major 4x4 matrix")
        columns = tuple((tbs[col], tbs[4 + col], tbs[8 + col]) for col in range(3))
        for col in columns:
            if abs(sum(value * value for value in col) - 1.0) > 0.01:
                raise QualityError("private factory extrinsic rotation is not normalized")
        for i, j in ((0, 1), (1, 2), (2, 0)):
            if abs(sum(a * b for a, b in zip(columns[i], columns[j]))) > 0.01:
                raise QualityError("private factory extrinsic rotation is not orthogonal")
        cross = (columns[0][1] * columns[1][2] - columns[0][2] * columns[1][1],
                 columns[0][2] * columns[1][0] - columns[0][0] * columns[1][2],
                 columns[0][0] * columns[1][1] - columns[0][1] * columns[1][0])
        if math.dist(cross, columns[2]) > 0.02:
            raise QualityError("private factory extrinsic rotation is not proper")
        by_factory[factory] = {"T_BS": tbs, "intrinsics": intr, "distortion": dist}
        ids.add(cid)
        candidate_mapping[cid] = factory
    if ids != set(CAMERAS) or set(by_factory) != set(range(4)):
        raise QualityError("private calibration must map C0/C3/C4/C5 to factory cameras 0..3")
    if candidate_mapping != {0: 0, 3: 1, 4: 2, 5: 3}:
        raise QualityError("private calibration is not the frozen candidate camera mapping")
    return by_factory, hashlib.sha256(raw).hexdigest()


def _mul4(a, b):
    return tuple(sum(a[row * 4 + k] * b[k * 4 + col] for k in range(4))
                 for row in range(4) for col in range(4))


def _world_from_head(matrix):
    return tuple(matrix) + (0.0, 0.0, 0.0, 1.0)


def _in_station_fov(pose, camera, station):
    world_camera = _mul4(_world_from_head(pose.matrix), _mul4(HEAD_FROM_BODY, camera["T_BS"]))
    dx, dy, dz = (station[i] - world_camera[i * 4 + 3] for i in range(3))
    cx = world_camera[0] * dx + world_camera[4] * dy + world_camera[8] * dz
    cy = world_camera[1] * dx + world_camera[5] * dy + world_camera[9] * dz
    cz = world_camera[2] * dx + world_camera[6] * dy + world_camera[10] * dz
    xi, fx, fy, cx0, cy0 = camera["intrinsics"]
    k1, k2, p1, p2 = camera["distortion"]
    norm = math.sqrt(cx * cx + cy * cy + cz * cz)
    denominator = cz + xi * norm
    if not math.isfinite(denominator) or denominator <= 1e-12:
        return False
    x, y = cx / denominator, cy / denominator
    r2 = x * x + y * y
    radial = 1.0 + k1 * r2 + k2 * r2 * r2
    u = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
    v = y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
    px, py = fx * u + cx0, fy * v + cy0
    return math.isfinite(px + py) and 0 <= px <= 640 and 0 <= py <= 480


def _geometry(calibration, station_rows, samples, matched):
    if calibration is None:
        return {"status": "BLOCKED_CALIBRATION_UNAVAILABLE", "candidate": {}, "placement_guess": {}}
    if len(station_rows) < 10:
        return {"status": "BLOCKED_CHANNEL_7_STATION_POSE_UNAVAILABLE", "candidate": {}, "placement_guess": {}}
    by_factory, digest = calibration
    station = tuple(median(row.position[i] for row in station_rows) for i in range(3))
    map_defs = {"candidate": {4: 2, 5: 3}, "placement_guess": {4: 3, 5: 2}}
    indexes = {
        "baseline": matched["baseline_off"]["left"] | matched["baseline_restored"]["left"],
        "off": matched["baseline_off"]["right"],
        "restored": matched["baseline_restored"]["right"],
    }
    out = {"status": "STATION_CENTER_FOV_ONLY", "calibration_sha256": digest,
           "head_from_body": "frozen_-Y_+X_+Z_zero_translation",
           "station_position_source": "median_channel7_raw_S_in_baseline_window",
           "candidate": {}, "placement_guess": {}}
    for map_name, factory_ids in map_defs.items():
        for camera_id in LOW_CAMERAS:
            camera = by_factory[factory_ids[camera_id]]
            phase_data = {}
            for phase in PHASES:
                chosen = sorted(indexes[phase])
                count = sum(_in_station_fov(samples[phase][index], camera, station)
                            for index in chosen if index < len(samples[phase]))
                phase_data[phase] = {"eligible_samples": len(chosen), "in_fov_samples": count,
                                     "in_fov_percent": (100.0 * count / len(chosen)) if chosen else None}
            out[map_name][f"C{camera_id}"] = phase_data
    return out


def analyze_capture(recording: Path, markers_path: Path, calibration_path: Path | None = None) -> dict:
    recording, markers_path = Path(recording), Path(markers_path)
    if not recording.is_file() or not markers_path.is_file():
        raise QualityError("recording and marker CSV must both exist")
    recording_hash = _sha256(recording)
    marker_hash = _sha256(markers_path)
    markers = read_markers(markers_path)
    windows = _windows(markers)
    timing_errors = []
    durations = {
        "baseline_hold": markers["OFF"] - markers["BASELINE_READY"],
        "off_hold": markers["ON"] - markers["OFF_READY"],
        "spinup": markers["SPINUP_DONE"] - markers["ON_READY"],
        "restored_hold": markers["PASS_DONE"] - markers["SPINUP_DONE"],
    }
    duration_checks = (("baseline", durations["baseline_hold"], MIN_HOLD_NS["baseline"]),
                       ("off", durations["off_hold"], MIN_HOLD_NS["off"]),
                       ("spinup", durations["spinup"], MIN_HOLD_NS["spinup"]),
                       ("restored", durations["restored_hold"], MIN_HOLD_NS["restored"]))
    for name, observed, minimum in duration_checks:
        if observed < minimum:
            timing_errors.append(f"{name} hold shorter than required duration")
    for phase, (begin, end) in windows.items():
        if end - begin < MIN_WINDOW_NS:
            timing_errors.append(f"{phase} stable window shorter than 15 seconds after trim")

    phase_stats = {phase: {"camera_frames": {f"C{cam}": 0 for cam in CAMERAS},
                           "pose_count": 0, "malformed_records": 0,
                           "duration_seconds": max(0.0, (windows[phase][1] - windows[phase][0]) / NS)}
                   for phase in PHASES}
    poses = {phase: [] for phase in PHASES}
    station_rows = []
    cluster_builders = {camera: [] for camera in LOW_CAMERAS}
    baseline_frame_count = {camera: 0 for camera in LOW_CAMERAS}

    def phase_for(stamp):
        for phase in PHASES:
            if _inside(stamp, windows[phase]):
                return phase
        return None

    # First pass: count frames/poses, collect baseline-only ROI candidates and channel-7 S poses.
    with recording.open("r", encoding="ascii", errors="replace") as stream:
        for raw in stream:
            if len(raw) > MAX_LINE_BYTES:
                try:
                    oversize_stamp = int(raw.split(None, 1)[0])
                    oversize_phase = phase_for(oversize_stamp)
                except (ValueError, IndexError):
                    oversize_phase = None
                if oversize_phase is not None:
                    phase_stats[oversize_phase]["malformed_records"] += 1
                continue
            parts = raw.split()
            if len(parts) < 3:
                continue
            try:
                stamp = int(parts[0])
            except ValueError:
                continue
            phase = phase_for(stamp)
            if phase is None:
                continue
            if parts[1:3] == ["P", "0"]:
                try:
                    pose = _parse_pose(parts)
                except (ValueError, IndexError):
                    phase_stats[phase]["malformed_records"] += 1
                    continue
                poses[phase].append(pose)
                phase_stats[phase]["pose_count"] += 1
            elif parts[1:3] == ["U", "F"]:
                try:
                    camera = int(parts[3]) if len(parts) > 3 else -1
                    frame = _parse_frame(parts)
                except (ValueError, IndexError):
                    if camera in CAMERAS:
                        phase_stats[phase]["malformed_records"] += 1
                    continue
                phase_stats[phase]["camera_frames"][f"C{frame.camera}"] += 1
                if phase == "baseline" and frame.camera in LOW_CAMERAS:
                    baseline_frame_count[frame.camera] += 1
                    _cluster_frame(cluster_builders[frame.camera], frame)
            elif parts[1] == "S" and phase == "baseline":
                try:
                    station = _parse_station(parts)
                except (ValueError, IndexError):
                    station = None
                if station is not None:
                    station_rows.append(station)

    for phase in PHASES:
        poses[phase].sort(key=lambda pose: pose.qpc_ns)
    rois_by_camera = {camera: _select_rois(cluster_builders[camera], baseline_frame_count[camera])
                      for camera in LOW_CAMERAS}
    samples = {phase: _sample_poses(poses[phase], windows[phase], POSE_SAMPLE_HZ)
               for phase in PHASES}
    overlap, matched_indexes = {}, {}
    for pair, right in (("baseline_off", "off"), ("baseline_restored", "restored")):
        report, matched = _overlap(samples["baseline"], samples[right])
        overlap[pair] = report
        matched_indexes[pair] = {"left": matched["left"], "right": matched["right"]}
    stationary = {phase: _stationarity(poses[phase], windows[phase]) for phase in PHASES}

    quality_errors = list(timing_errors)
    if not any(phase_stats[phase]["pose_count"] or sum(phase_stats[phase]["camera_frames"].values())
               for phase in PHASES):
        quality_errors.append("no recording records overlap marker windows; QPC alignment unavailable")
    for phase in PHASES:
        data = phase_stats[phase]
        if data["pose_count"] < MIN_POSES:
            quality_errors.append(f"{phase} has fewer than {MIN_POSES} HMD poses")
        for camera in CAMERAS:
            if data["camera_frames"][f"C{camera}"] < MIN_CAMERA_FRAMES:
                quality_errors.append(f"{phase} has fewer than {MIN_CAMERA_FRAMES} frames for C{camera}")
        if data["malformed_records"]:
            quality_errors.append(f"{phase} contains malformed relevant records")
        stats = stationary[phase]
        if stats["measured_one_second_bins"] < MIN_STATIONARY_BINS or \
                stats["stationary_ratio_5cm_5deg"] < MIN_STATIONARY_RATIO:
            quality_errors.append(f"{phase} lacks sufficient stationary intervals")
    for pair, report in overlap.items():
        if report["coverage_5cm_5deg"] < MIN_MATCH_COVERAGE:
            quality_errors.append(f"{pair} pose overlap is below the 5 cm / 5 degree target")

    matched_times = {
        "baseline_off": {"baseline": set(), "off": set()},
        "baseline_restored": {"baseline": set(), "restored": set()},
    }
    for pair, pair_indexes in matched_indexes.items():
        right_phase = "off" if pair == "baseline_off" else "restored"
        matched_times[pair]["baseline"] = {samples["baseline"][index].qpc_ns for index in pair_indexes["left"]}
        matched_times[pair][right_phase] = {samples[right_phase][index].qpc_ns for index in pair_indexes["right"]}
    phase_sample_times = {phase: [pose.qpc_ns for pose in samples[phase]] for phase in PHASES}
    phase_pose_times = {phase: [pose.qpc_ns for pose in poses[phase]] for phase in PHASES}
    matched_camera_frames = {
        f"C{camera}": {"baseline_off": {"baseline": 0, "off": 0},
                       "baseline_restored": {"baseline": 0, "restored": 0}}
        for camera in LOW_CAMERAS
    }
    roi_counts = {
        camera: {phase: [{"hits": 0, "frames": 0, "pose_eligible_frames": 0,
                          "matched_frames": {"baseline_off": 0, "baseline_restored": 0},
                          "matched_hits": {"baseline_off": 0, "baseline_restored": 0}}
                         for _ in rois_by_camera[camera]] for phase in PHASES}
        for camera in LOW_CAMERAS
    }

    # Second pass: apply the already-frozen baseline ROIs to every phase.
    with recording.open("r", encoding="ascii", errors="replace") as stream:
        for raw in stream:
            if len(raw) > MAX_LINE_BYTES:
                continue
            parts = raw.split()
            if len(parts) < 8 or parts[1:3] != ["U", "F"]:
                continue
            try:
                stamp = int(parts[0])
                phase = phase_for(stamp)
                if phase is None:
                    continue
                frame = _parse_frame(parts)
            except (ValueError, IndexError):
                continue
            if frame.camera not in LOW_CAMERAS:
                continue
            pose_times = phase_pose_times[phase]
            pose_index = _nearest_index(pose_times, stamp)
            pose_eligible = pose_index is not None and abs(pose_times[pose_index] - stamp) <= POSE_MATCH_NS
            sample_times = phase_sample_times[phase]
            sample_index = _nearest_index(sample_times, stamp)
            sample_time = sample_times[sample_index] if sample_index is not None else None
            sample_ok = sample_time is not None and abs(sample_time - stamp) <= NS // (2 * POSE_SAMPLE_HZ)
            pairs = []
            if sample_ok:
                if phase in matched_times["baseline_off"] and \
                        sample_time in matched_times["baseline_off"][phase]:
                    pairs.append("baseline_off")
                if phase in matched_times["baseline_restored"] and \
                        sample_time in matched_times["baseline_restored"][phase]:
                    pairs.append("baseline_restored")
            cam_name = f"C{frame.camera}"
            for pair in pairs:
                matched_camera_frames[cam_name][pair][phase] += 1
            for index, cluster in enumerate(rois_by_camera[frame.camera]):
                row = roi_counts[frame.camera][phase][index]
                row["frames"] += 1
                row["pose_eligible_frames"] += int(pose_eligible)
                hit = any(peak >= ROI_PEAK_THRESHOLD and
                          math.hypot(x - cluster.center[0], y - cluster.center[1]) <= ROI_MATCH_RADIUS_PX
                          for x, y, peak in frame.blobs)
                row["hits"] += int(hit)
                for pair in pairs:
                    row["matched_frames"][pair] += 1
                    row["matched_hits"][pair] += int(hit)

    roi_result, roi_status = {}, {}
    for camera in LOW_CAMERAS:
        name = f"C{camera}"
        clusters = rois_by_camera[camera]
        roi_status[name] = "BASELINE_ROIS_FROZEN" if clusters else "NO_BASELINE_ROI_FROZEN"
        rows = []
        for index, cluster in enumerate(clusters):
            counts = {phase: roi_counts[camera][phase][index] for phase in PHASES}
            matched = {
                "baseline_off": {
                    phase: {"hits": counts[phase]["matched_hits"]["baseline_off"],
                            "eligible_frames": counts[phase]["matched_frames"]["baseline_off"]}
                    for phase in ("baseline", "off")},
                "baseline_restored": {
                    phase: {"hits": counts[phase]["matched_hits"]["baseline_restored"],
                            "eligible_frames": counts[phase]["matched_frames"]["baseline_restored"]}
                    for phase in ("baseline", "restored")},
            }
            def rate(pair, phase):
                data = matched[pair][phase]
                return data["hits"] / data["eligible_frames"] if data["eligible_frames"] else 0.0
            r_base_off, r_off = rate("baseline_off", "baseline"), rate("baseline_off", "off")
            r_base_restore, r_restore = rate("baseline_restored", "baseline"), rate("baseline_restored", "restored")
            enough_frames = all(matched[pair][phase]["eligible_frames"] >= 100
                                for pair, phase in (("baseline_off", "baseline"), ("baseline_off", "off"),
                                                    ("baseline_restored", "baseline"), ("baseline_restored", "restored")))
            if quality_errors:
                classification = "NOT_CLASSIFIED_QUALITY_INSUFFICIENT"
            elif not enough_frames:
                classification = "NOT_CLASSIFIED_LOW_MATCHED_FRAME_COUNT"
            elif (r_base_off >= ROI_MIN_ON_RATE and r_restore >= ROI_MIN_ON_RATE and
                  r_off >= ROI_OFF_PERSISTENCE_RATE and
                  r_off >= 0.5 * min(r_base_off, r_restore) and
                  matched["baseline_off"]["off"]["hits"] >= 3):
                classification = "REJECT_OFF_PERSISTENT"
            elif (r_base_off >= ROI_MIN_ON_RATE and r_base_restore >= ROI_MIN_ON_RATE and
                  r_restore >= ROI_MIN_ON_RATE and
                  r_off <= ROI_MAX_OFF_RATE_RATIO * min(r_base_off, r_base_restore, r_restore) and
                  matched["baseline_off"]["off"]["hits"] < 3 and
                  matched["baseline_off"]["baseline"]["hits"] >= 3 and
                  matched["baseline_restored"]["restored"]["hits"] >= 3):
                classification = "ON_OFF_ON_CANDIDATE"
            else:
                classification = "INCONCLUSIVE"
            rows.append({
                "roi_id": f"{name}-ON-{index + 1:02d}",
                "center_px": [round(cluster.center[0], 1), round(cluster.center[1], 1)],
                "match_radius_px": ROI_MATCH_RADIUS_PX,
                "peak_threshold": ROI_PEAK_THRESHOLD,
                "selected_from": "BASELINE_ON_ONLY",
                "selection_window_qpc_ns": list(windows["baseline"]),
                "selection_frame_range": {"qpc_ns": [cluster.first_ns, cluster.last_ns],
                                          "camera_sequence": [cluster.first_sequence, cluster.last_sequence]},
                "baseline_unique_hit_frames": cluster.frames,
                "baseline_mean_peak": round(cluster.peak_sum / cluster.points, 1),
                "all_phase_counts": {phase: {"hits": counts[phase]["hits"],
                                               "camera_frames": counts[phase]["frames"],
                                               "pose_eligible_frames": counts[phase]["pose_eligible_frames"]}
                                     for phase in PHASES},
                "matched": matched,
                "classification": classification,
            })
        roi_result[name] = rows

    controls = {}
    for camera_name, rows in roi_result.items():
        control_ids = [row["roi_id"] for row in rows if row["classification"] == "REJECT_OFF_PERSISTENT"]
        controls[camera_name] = {"status": "BASELINE_SELECTED_OFF_PERSISTENT_CONTROL" if control_ids else "NOT_IDENTIFIED",
                                 "roi_ids": control_ids, "selection_source": "BASELINE_ON_ONLY"}
    calibration, calibration_error = None, None
    if calibration_path:
        try:
            calibration = _load_calibration(Path(calibration_path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            calibration_error = "BLOCKED_CALIBRATION_INVALID"
    geometry = _geometry(calibration, station_rows, samples, matched_indexes)
    if calibration_error:
        geometry = {"status": calibration_error, "candidate": {}, "placement_guess": {}}
    if _sha256(recording) != recording_hash or _sha256(markers_path) != marker_hash:
        raise QualityError("recording or marker file changed during analysis")

    result = {
        "schema": "p3k_ch7_capture_analysis_v1",
        "capture_quality": "CAPTURE_QUALITY_PASS" if not quality_errors else "CAPTURE_QUALITY_INSUFFICIENT",
        "quality_errors": quality_errors,
        "inputs": {"recording_filename": recording.name, "recording_bytes": recording.stat().st_size,
                   "recording_sha256": recording_hash, "markers_filename": markers_path.name,
                   "markers_bytes": markers_path.stat().st_size, "markers_sha256": marker_hash,
                   "calibration_sha256": calibration[1] if calibration else None},
        "marker_qpc_ns": markers,
        "marker_semantics": "QPC captured after operator confirms requested power action; not the physical transition instant",
        "phases": {phase: {"duration_seconds": round(phase_stats[phase]["duration_seconds"], 3),
                            "camera_frames": phase_stats[phase]["camera_frames"],
                            "hmd_pose_count": phase_stats[phase]["pose_count"],
                            "malformed_records": phase_stats[phase]["malformed_records"],
                            "stationarity": stationary[phase]} for phase in PHASES},
        "pose_overlap": overlap,
        "matched_camera_frames": matched_camera_frames,
        "roi_rules": {"selected_only_from": "initial stable ON baseline window",
                      "peak_threshold": ROI_PEAK_THRESHOLD, "cluster_radius_px": ROI_CLUSTER_RADIUS_PX,
                      "match_radius_px": ROI_MATCH_RADIUS_PX,
                      "minimum_baseline_hits": ROI_MIN_BASELINE_HITS,
                      "maximum_candidates_per_camera": ROI_MAX_CANDIDATES,
                      "on_off_on_candidate_min_on_rate": ROI_MIN_ON_RATE,
                      "off_persistent_rejection_min_rate": ROI_OFF_PERSISTENCE_RATE,
                      "off_persistent_rejection_rate_ratio": 0.5,
                      "off_candidate_max_rate_ratio": ROI_MAX_OFF_RATE_RATIO},
        "roi_status": roi_status,
        "rois": roi_result,
        "false_positive_control": controls,
        "geometry_fov": geometry,
        "interpretation_limits": [
            "ON_OFF_ON_CANDIDATE is a power-correlated optical candidate, not proof that it is the channel-7 emitter.",
            "An OFF-persistent ROI selected from baseline is rejected as a channel-specific hypothesis and retained as a negative-control candidate.",
            "FOV is modeled station-center projection only; it does not model sweep planes, emitter rays, reflections, or physical source identity.",
            "No mapping, HeadFromBody, timestamp, station position, or association threshold is optimized.",
            "No runtime or calibration safety gate is changed.",
        ],
        "safety_gates": {"mapping_verified": False, "pose_verified": False, "exact_time": False,
                         "shared_buffer_identity_verified": False, "frame_meta_bridge_verified": False,
                         "physical_event_verified": False, "live_lighthouse_correction_allowed": False,
                         "observe_only": True},
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("markers", type=Path)
    parser.add_argument("--calibration", type=Path,
                        help="private candidate calibration JSON; raw coefficients are not copied to output")
    parser.add_argument("--output", type=Path, help="private JSON output; defaults beside the recording")
    args = parser.parse_args()
    try:
        result = analyze_capture(args.recording, args.markers, args.calibration)
        output = args.output or args.recording.with_suffix(".ch7-analysis.private.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            stream_context = output.open("x", encoding="utf-8", newline="")
        except FileExistsError as exc:
            raise QualityError("analysis output already exists; choose a new private output path") from exc
        with stream_context as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}")
        return 2
    print(result["capture_quality"])
    print(f"Recording: {result['inputs']['recording_filename']} sha256={result['inputs']['recording_sha256']}")
    print(f"Markers:   {result['inputs']['markers_filename']} sha256={result['inputs']['markers_sha256']}")
    print(f"Private analysis: {output}")
    print("ROIs were selected using baseline ON only; no candidate is labeled channel 7 without power-state evidence.")
    return 0 if result["capture_quality"] == "CAPTURE_QUALITY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
