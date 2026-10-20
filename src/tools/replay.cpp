// qlhs_replay: run a QuestLHSync recording through the driver's Sync, as if live.
//   qlhs_replay <log> --calib <camera calibration json> --dir <state dir> [--out file] [--learn] [--expo s]
//               [--learn-grid] [--pings]
// Logs without clock round trips use the arrival envelope clock and EXPO 0.020. --pings: the round trips alone, like the
// live driver (QuestLHSync recordings have them).
// --learn: round-trip-less logs still learn the timing (starting from --expo), to test the estimator.
// --learn-grid: learn the cameras' frame period as for headsets other than the Quest Pro, to test that.
// --channel SERIAL=N: a base station's channel, for older logs.
// --xf file: the transform applied to the lighthouse devices (raw -> Quest: pc_ns qw qx qy qz tx ty tz), every 0.25 s
#include <chrono>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "../driver/json.h"
#include "../driver/sync.h"

namespace {
struct PicoFrameRecord {
  long long pc_ns = 0;
  int cam = -1;
  unsigned sequence = 0;
  long long headset_us = 0;
  int mean = 0;
  int blobs = 0;
  std::string f_line;
};

struct PicoStationRecord {
  std::string serial;
  int channel = 0;
  double values[7] = {};
};

enum class PicoStationRecordKind { RawChannelFirst, ChannelLast, Ambiguous, Malformed };

struct PicoCameraCounts { long frames = 0, blobs = 0, submitted = 0; };

bool ParseInteger(const std::string &s, long long &out, bool unsigned_only = false) {
  if (s.empty()) return false;
  size_t i = 0;
  if (!unsigned_only && (s[0] == '-' || s[0] == '+')) i++;
  if (i == s.size()) return false;
  for (; i < s.size(); ++i) if (s[i] < '0' || s[i] > '9') return false;
  errno = 0;
  char *end = nullptr;
  long long v = std::strtoll(s.c_str(), &end, 10);
  if (errno == ERANGE || end != s.c_str() + s.size()) return false;
  out = v;
  return true;
}

bool ParseFiniteDecimal(const std::string &s, double &out) {
  if (s.empty()) return false;
  size_t i = 0;
  if (s[i] == '+' || s[i] == '-') ++i;
  bool digits = false;
  while (i < s.size() && s[i] >= '0' && s[i] <= '9') { ++i; digits = true; }
  if (i < s.size() && s[i] == '.') {
    ++i;
    while (i < s.size() && s[i] >= '0' && s[i] <= '9') { ++i; digits = true; }
  }
  if (!digits) return false;
  if (i < s.size() && (s[i] == 'e' || s[i] == 'E')) {
    ++i;
    if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
    size_t exponent_start = i;
    while (i < s.size() && s[i] >= '0' && s[i] <= '9') ++i;
    if (i == exponent_start) return false;
  }
  if (i != s.size()) return false;
  errno = 0;
  char *end = nullptr;
  double value = std::strtod(s.c_str(), &end);
  if (errno == ERANGE || end != s.c_str() + s.size() || !std::isfinite(value)) return false;
  out = value;
  return true;
}

PicoStationRecordKind ParsePicoStationRecord(const char *rest, PicoStationRecord &out) {
  std::istringstream input(rest ? rest : "");
  std::vector<std::string> fields;
  std::string field;
  while (input >> field) fields.push_back(field);
  if (fields.size() != 9 || fields[0].empty() || fields[0].size() > 63) return PicoStationRecordKind::Malformed;

  long long raw_channel = -1, last_channel = -1;
  bool raw_layout = ParseInteger(fields[1], raw_channel) && raw_channel >= 0 && raw_channel <= 15;
  bool channel_last_layout = ParseInteger(fields[8], last_channel) && last_channel >= 0 && last_channel <= 15;
  double raw_values[7] = {}, channel_last_values[7] = {};
  for (size_t i = 0; i < 7; ++i) {
    if (!ParseFiniteDecimal(fields[i + 2], raw_values[i])) raw_layout = false;
    if (!ParseFiniteDecimal(fields[i + 1], channel_last_values[i])) channel_last_layout = false;
  }

  out.serial = fields[0];
  if (raw_layout && channel_last_layout) return PicoStationRecordKind::Ambiguous;
  if (channel_last_layout) return PicoStationRecordKind::ChannelLast;
  if (!raw_layout) return PicoStationRecordKind::Malformed;
  out.channel = static_cast<int>(raw_channel);
  for (size_t i = 0; i < 7; ++i) out.values[i] = raw_values[i];
  return PicoStationRecordKind::RawChannelFirst;
}

bool ParsePicoFrameRecord(const std::string &line, PicoFrameRecord &out) {
  for (unsigned char c : line) if (c < 0x20 && c != ' ') return false;
  std::vector<std::string> fields;
  std::vector<size_t> starts;
  for (size_t i = 0; i < line.size();) {
    while (i < line.size() && line[i] == ' ') ++i;
    if (i == line.size()) break;
    starts.push_back(i);
    size_t j = i;
    while (j < line.size() && line[j] != ' ') ++j;
    fields.emplace_back(line.substr(i, j - i));
    i = j;
  }
  if (fields.size() < 8 || fields[1] != "U" || fields[2] != "F") return false;
  long long pc = 0, cam = 0, seq = 0, hs = 0, mean = 0, blobs = 0;
  if (!ParseInteger(fields[0], pc, true) || !ParseInteger(fields[3], cam, true) || cam > 15 ||
      !ParseInteger(fields[4], seq, true) || seq > std::numeric_limits<unsigned>::max() ||
      !ParseInteger(fields[5], hs, true) || !ParseInteger(fields[6], mean, true) || mean > 1000000 ||
      !ParseInteger(fields[7], blobs, true) || blobs > 4096) return false;
  const size_t expected = 8 + static_cast<size_t>(blobs) * 4;
  if (fields.size() != expected) return false;
  for (size_t i = 8; i < fields.size(); ++i) {
    long long value = 0;
    if (!ParseInteger(fields[i], value, false) || value < std::numeric_limits<int>::min() ||
        value > std::numeric_limits<int>::max()) return false;
  }
  out.pc_ns = pc;
  out.cam = static_cast<int>(cam);
  out.sequence = static_cast<unsigned>(seq);
  out.headset_us = hs;
  out.mean = static_cast<int>(mean);
  out.blobs = static_cast<int>(blobs);
  out.f_line = line.substr(starts[2]);
  return true;
}

bool SupportedPicoCamera(int cam) { return cam == 0 || cam == 3 || cam == 4 || cam == 5; }
bool SelectedPicoCamera(int cam, bool upper) { return SupportedPicoCamera(cam) && (!upper || cam == 0 || cam == 3); }

bool PicoRigid(const std::vector<double> &a) {
  if (a.size() != 16) return false;
  for (double v : a) if (!std::isfinite(v)) return false;
  if (std::fabs(a[12]) + std::fabs(a[13]) + std::fabs(a[14]) + std::fabs(a[15] - 1) > 1e-6) return false;
  const double x[3] = {a[0], a[4], a[8]}, y[3] = {a[1], a[5], a[9]}, z[3] = {a[2], a[6], a[10]};
  auto dot3 = [](const double *u, const double *v) { return u[0]*v[0] + u[1]*v[1] + u[2]*v[2]; };
  if (std::fabs(dot3(x, x) - 1) > 0.005 || std::fabs(dot3(y, y) - 1) > 0.005 ||
      std::fabs(dot3(z, z) - 1) > 0.005 || std::fabs(dot3(x, y)) > 0.005 ||
      std::fabs(dot3(y, z)) > 0.005 || std::fabs(dot3(z, x)) > 0.005) return false;
  const double cross[3] = {x[1]*y[2] - x[2]*y[1], x[2]*y[0] - x[0]*y[2], x[0]*y[1] - x[1]*y[0]};
  return std::hypot(std::hypot(cross[0] - z[0], cross[1] - z[1]), cross[2] - z[2]) <= 0.01;
}

bool ReadTransform(const std::string &path, std::vector<double> &transform) {
  std::ifstream f(path, std::ios::binary);
  if (!f) return false;
  std::string text((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
  if (text.size() > 65536) return false;
  JVal root;
  if (!JParse(text, root) || root.t != JVal::Arr || root.a.size() != 16) return false;
  transform.clear();
  for (const auto &v : root.a) {
    if (v.t != JVal::Num || !std::isfinite(v.n)) return false;
    transform.push_back(v.n);
  }
  if (!PicoRigid(transform)) return false;
  bool identity = true;
  for (size_t i = 0; i < 16; ++i) identity = identity && std::fabs(transform[i] - (i % 5 == 0 ? 1.0 : 0.0)) < 1e-12;
  return !identity;  // identity is available only through the explicit diagnostic-control flag
}

JVal *MutableMember(JVal &root, const char *key) {
  if (root.t != JVal::Obj) return nullptr;
  for (auto &kv : root.o) if (kv.first == key) return &kv.second;
  return nullptr;
}

void AppendJsonString(std::ostringstream &out, const std::string &s) {
  out << '"';
  for (unsigned char c : s) {
    switch (c) {
      case '"': out << "\\\""; break;
      case '\\': out << "\\\\"; break;
      case '\b': out << "\\b"; break;
      case '\f': out << "\\f"; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (c < 0x20) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << (int)c << std::dec;
        else out << (char)c;
    }
  }
  out << '"';
}

void SerializeJson(std::ostringstream &out, const JVal &v) {
  switch (v.t) {
    case JVal::Null: out << "null"; break;
    case JVal::Bool: out << (v.b ? "true" : "false"); break;
    case JVal::Num: out << std::setprecision(17) << v.n; break;
    case JVal::Str: AppendJsonString(out, v.s); break;
    case JVal::Arr:
      out << '[';
      for (size_t i = 0; i < v.a.size(); ++i) { if (i) out << ','; SerializeJson(out, v.a[i]); }
      out << ']';
      break;
    case JVal::Obj:
      out << '{';
      for (size_t i = 0; i < v.o.size(); ++i) {
        if (i) out << ',';
        AppendJsonString(out, v.o[i].first); out << ':'; SerializeJson(out, v.o[i].second);
      }
      out << '}';
      break;
  }
}

bool BuildPicoLabCalibration(const std::string &input, const std::vector<double> &transform,
                             const std::string &mapping_hypothesis,
                             std::string &output, std::string &error) {
  JVal root;
  if (!JParse(input, root) || root.t != JVal::Obj) { error = "invalid calibration JSON"; return false; }
  const JVal *kind = root.get("kind"), *map = root.get("mapping_verified"), *pose = root.get("pose_verified");
  const JVal *old_transform = root.get("HeadFromBody"), *cameras = root.get("cameras");
  if (!kind || kind->t != JVal::Str || kind->s != "pico" || !map || map->t != JVal::Bool || map->b ||
      !pose || pose->t != JVal::Bool || pose->b || !old_transform || old_transform->t != JVal::Null ||
      !PicoRigid(transform)) {
    error = "Pico lab mode requires the unverified draft and a valid explicit rigid-transform hypothesis";
    return false;
  }
  if (!cameras || cameras->t != JVal::Arr || cameras->a.size() != 4) {
    error = "Pico lab mode requires the four-camera draft"; return false;
  }
  const int expected_id[4] = {0, 3, 4, 5};
  const int candidate_factory[4] = {0, 1, 2, 3};
  const int placement_guess_factory[4] = {0, 1, 3, 2};
  const int *expected_factory = mapping_hypothesis == "candidate" ? candidate_factory : placement_guess_factory;
  if (mapping_hypothesis != "candidate" && mapping_hypothesis != "placement-guess") {
    error = "unsupported camera mapping hypothesis"; return false;
  }
  bool ids[6] = {};
  for (const JVal &c : cameras->a) {
    const JVal *id = c.get("id"), *factory = c.get("factory_camera");
    if (!id || id->t != JVal::Num || !factory || factory->t != JVal::Num) {
      error = "Pico lab mode requires the selected candidate camera mapping"; return false;
    }
    if (!std::isfinite(id->n) || !std::isfinite(factory->n) || std::floor(id->n) != id->n ||
        std::floor(factory->n) != factory->n || id->n < 0 || id->n >= 6 || factory->n < 0 || factory->n >= 4) {
      error = "Pico lab mode requires integer camera and factory IDs within range"; return false;
    }
    int i = (int)id->n;
    if (i < 0 || i >= 6 || ids[i]) { error = "invalid candidate camera mapping"; return false; }
    ids[i] = true;
    bool found = false;
    for (int k = 0; k < 4; ++k) if (i == expected_id[k] && (int)factory->n == expected_factory[k]) found = true;
    if (!found) { error = "calibration does not match the selected unverified C0/C3/C4/C5 mapping hypothesis"; return false; }
  }
  JVal *m = MutableMember(root, "mapping_verified"), *p = MutableMember(root, "pose_verified"), *h = MutableMember(root, "HeadFromBody");
  if (!m || !p || !h) { error = "incomplete calibration draft"; return false; }
  m->t = p->t = JVal::Bool; m->b = p->b = true;
  h->t = JVal::Arr;
  for (double value : transform) { JVal n; n.t = JVal::Num; n.n = value; h->a.push_back(n); }
  std::ostringstream out; SerializeJson(out, root); output = out.str();
  return true;
}

bool EnsureEmptyLabStateDir(const std::string &path) {
  if (path.empty()) return false;
  namespace fs = std::filesystem;
  fs::path dir(path);
  std::error_code ec;
  fs::file_status st = fs::symlink_status(dir, ec);
  if (!ec && fs::exists(st)) {
    if (!fs::is_directory(st) || fs::is_symlink(st)) return false;
    if (fs::directory_iterator(dir, ec) != fs::directory_iterator() || ec) return false;
  } else {
    ec.clear();
    if (!fs::create_directories(dir, ec) || ec) return false;
  }
  return true;
}

void PrintPicoStatus(const Sync::Status &st, long long pc_ns, double elapsed,
                     const std::map<std::string, int> &channels) {
  printf("PICO_STATUS pc_qpc_ns=%lld elapsed_s=%.3f has_alignment=%s locked=%s condition=%s median_deg=",
         pc_ns, elapsed, st.has_x ? "true" : "false", st.locked ? "true" : "false",
         st.cond ? "true" : "false");
  if (st.med >= 0) printf("%.5f", st.med); else printf("NA");
  printf(" exposure_ms=%.3f timing_learned=%s acquire_success=%s acquire_support=%d tight_support=%d stations=%d support_ch=",
         st.expo * 1000, st.timing_learned ? "true" : "false", st.acquire_succeeded ? "true" : "false",
         st.acquisition_support, st.tight_support, st.nstations);
  bool first = true;
  for (const auto &e : st.st) {
    auto it = channels.find(e.serial);
    if (it == channels.end() || it->second <= 0) continue;
    printf("%s%d:%d", first ? "" : ",", it->second, e.support);
    first = false;
  }
  if (first) printf("unavailable");
  printf("\n");
}
}

int main(int argc, char **argv) {
  std::string log, calib, dir, outp, xfp;
  bool learn = false, learn_grid = false, pings = false;
  bool pico_offline = false, pico_identity_control = false, pico_upper = false;
  std::string pico_transform_path, pico_audit_path;
  std::string pico_mapping_hypothesis = "candidate";
  bool pico_cameras_set = false, pico_mapping_set = false;
  double expo = -1;
  std::map<std::string, int> chans;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    if (a == "--channel" && i + 1 < argc) {
      std::string v = argv[++i];
      size_t eq = v.find('=');
      if (eq != std::string::npos) chans[v.substr(0, eq)] = atoi(v.c_str() + eq + 1);
    } else if (a == "--calib" && i + 1 < argc) calib = argv[++i];
    else if (a == "--dir" && i + 1 < argc) dir = argv[++i];
    else if (a == "--out" && i + 1 < argc) outp = argv[++i];
    else if (a == "--xf" && i + 1 < argc) xfp = argv[++i];
    else if (a == "--rays" && i + 1 < argc) g_ray_dump = fopen(argv[++i], "w");  // every sighting + the stations
    else if (a == "--expo" && i + 1 < argc) expo = atof(argv[++i]);
    else if (a == "--learn") learn = true;
    else if (a == "--learn-grid") learn_grid = true;
    else if (a == "--pings") pings = true;
    else if (a == "--pico-offline") pico_offline = true;
    else if (a == "--pico-identity-control") pico_identity_control = true;
    else if (a == "--pico-head-from-body" && i + 1 < argc) pico_transform_path = argv[++i];
    else if (a == "--pico-camera-mapping" && i + 1 < argc) {
      pico_mapping_hypothesis = argv[++i]; pico_mapping_set = true;
      if (pico_mapping_hypothesis != "candidate" && pico_mapping_hypothesis != "placement-guess") {
        fprintf(stderr, "invalid --pico-camera-mapping value\n"); return 2;
      }
    }
    else if (a == "--pico-cameras" && i + 1 < argc) {
      std::string mode = argv[++i];
      if (mode != "all" && mode != "upper") { fprintf(stderr, "invalid --pico-cameras value\n"); return 2; }
      pico_upper = mode == "upper"; pico_cameras_set = true;
    }
    else if (a == "--pico-audit" && i + 1 < argc) pico_audit_path = argv[++i];
    else log = a;
  }
  if (!pico_offline && (pico_identity_control || !pico_transform_path.empty() || pico_cameras_set ||
                        pico_mapping_set || !pico_audit_path.empty())) {
    fprintf(stderr, "Pico replay options require --pico-offline\n"); return 2;
  }
  if (pico_offline && (pico_identity_control == !pico_transform_path.empty())) {
    fprintf(stderr, "--pico-offline requires exactly one explicit --pico-identity-control or --pico-head-from-body file\n"); return 2;
  }
  if (log.empty() || calib.empty() || (pico_offline && !EnsureEmptyLabStateDir(dir))) {
    fprintf(stderr, "usage: qlhs_replay <log> --calib file --dir statedir [--out f] [--learn] [--expo s] [--pico-offline (--pico-identity-control | --pico-head-from-body file) [--pico-camera-mapping candidate|placement-guess] [--pico-cameras all|upper] [--pico-audit file]]\n"); return 2;
  }
  std::ifstream cf(calib, std::ios::binary);
  std::stringstream ss;
  ss << cf.rdbuf();
  std::string calibration = ss.str();
  std::vector<double> pico_transform;
  std::string pico_hypothesis = "none";
  if (pico_offline) {
    if (!cf && calibration.empty()) { fprintf(stderr, "calibration: cannot read file\n"); return 1; }
    if (pico_identity_control) {
      pico_transform = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
      pico_hypothesis = "IDENTITY_DIAGNOSTIC_CONTROL_UNVERIFIED";
    } else {
      if (!ReadTransform(pico_transform_path, pico_transform)) {
        fprintf(stderr, "PICO_TRANSFORM_REJECTED: expected a non-identity finite 4x4 rigid-transform JSON array\n"); return 1;
      }
      pico_hypothesis = "FILE_TRANSFORM_HYPOTHESIS_UNVERIFIED";
    }
    std::string lab_calibration, error;
    if (!BuildPicoLabCalibration(calibration, pico_transform, pico_mapping_hypothesis, lab_calibration, error)) {
      fprintf(stderr, "PICO_LAB_CALIBRATION_REJECTED: %s\n", error.c_str()); return 1;
    }
    calibration.swap(lab_calibration); // in-memory replay copy only; source JSON remains unchanged
  }
  double t0 = 0, tnow = 0;
  auto logfn = [&](const std::string &s) {
    printf("%6.0fs    %s\n", tnow - t0, s.c_str());
  };
  SyncConfig cfg;
  cfg.dir = dir;
  cfg.arrival_clock = !pings;
  cfg.learn_timing = learn;
  cfg.learn_grid = learn_grid;
  Sync sync(cfg, logfn);
  if (expo >= 0) sync.ForceExpo(expo);
  sync.SetStreamer("replay");
  sync.SetChannels(chans);
  std::string err;
  if (!sync.SetCalibration(calibration, &err)) { fprintf(stderr, "calibration: %s\n", err.c_str()); return 1; }
  FILE *out = outp.empty() ? nullptr : fopen(outp.c_str(), "w");
  FILE *xf = xfp.empty() ? nullptr : fopen(xfp.c_str(), "w");
  long ticks = 0;
  FILE *f = fopen(log.c_str(), "rb");
  if (!f) { fprintf(stderr, "can't open %s\n", log.c_str()); return 1; }
  FILE *pico_audit = nullptr;
  if (pico_offline && !pico_audit_path.empty()) {
    pico_audit = fopen(pico_audit_path.c_str(), "wb");
    if (!pico_audit) { fprintf(stderr, "PICO_AUDIT_OPEN_FAILED\n"); fclose(f); return 1; }
  }
  static char line[1 << 16];
  std::map<std::string, std::pair<V3, M3>> raw;
  std::map<std::string, int> source_channels;
  std::set<std::string> pico_raw_schema_ids, pico_channel_last_schema_ids, pico_ambiguous_schema_ids;
  std::set<std::string> pico_raw_station_ids;
  std::map<int, PicoCameraCounts> pico_camera_counts;
  long pico_frames_parsed = 0, pico_frames_submitted = 0, pico_frames_excluded = 0, pico_unsupported_cameras = 0;
  long pico_station_raw_schema = 0, pico_station_channel_last = 0, pico_station_ambiguous = 0, pico_station_malformed = 0;
  long long pico_first_pc_ns = 0, pico_last_pc_ns = 0;
  long pico_line_error = 0;
  bool pico_last_locked = false;
  long pico_lock_episodes = 0, pico_lock_breaks = 0, pico_locked_steps = 0, pico_current_lock_steps = 0, pico_max_lock_steps = 0;
  double pico_next_status = 0;
  double next_tick = 0, next_print = 0;
  long nl = 0;
  auto wall = std::chrono::steady_clock::now();
  while (fgets(line, sizeof line, f)) {
    size_t L = strlen(line);
    while (L && (line[L - 1] == '\n' || line[L - 1] == '\r')) line[--L] = 0;
    char *sp = strchr(line, ' ');
    if (!sp || sp[1] == 0 || sp[2] != ' ') continue;
    long long raw_pc_ns = atoll(line);
    double pc = raw_pc_ns / 1e9;
    char kind = sp[1];
    const char *rest = sp + 3;
    if (!t0) { t0 = pc; next_tick = pc; next_print = pc + 10; }
    tnow = pc;
    nl++;
    if (pico_offline && kind == 'U') {
      PicoFrameRecord frame;
      std::string record(line, L);
      if (!ParsePicoFrameRecord(record, frame)) {
        pico_line_error = nl;
        break;
      }
      if (frame.pc_ns != raw_pc_ns) {
        pico_line_error = nl;
        break;
      }
      if (!SupportedPicoCamera(frame.cam)) { ++pico_unsupported_cameras; continue; }
      PicoCameraCounts &cc = pico_camera_counts[frame.cam];
      ++cc.frames; cc.blobs += frame.blobs; ++pico_frames_parsed;
      if (!SelectedPicoCamera(frame.cam, pico_upper)) { ++pico_frames_excluded; continue; }
      ++cc.submitted; ++pico_frames_submitted;
      if (!pico_first_pc_ns) pico_first_pc_ns = frame.pc_ns;
      pico_last_pc_ns = frame.pc_ns;
      if (pico_audit) {
        fprintf(pico_audit, "%lld\t%s\n", frame.pc_ns, frame.f_line.c_str());
        if (ferror(pico_audit)) { pico_line_error = nl; break; }
      }
      sync.OnLine(pc, frame.f_line.c_str());
    } else if (kind == 'P') {
      int idx;
      double m[12];
      if (sscanf(rest, "%d %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf", &idx, &m[0], &m[1], &m[2], &m[3], &m[4], &m[5],
                 &m[6], &m[7], &m[8], &m[9], &m[10], &m[11]) == 13 && idx == 0) {
        M3 R;
        for (int r = 0; r < 3; r++)
          for (int c = 0; c < 3; c++) R.m[r][c] = m[r * 4 + c];
        sync.OnHmdPose(pc, ToQuat(R), V3{m[3], m[7], m[11]});
      }
    } else if (kind == 'S') {
      if (pico_offline) {
        PicoStationRecord station;
        PicoStationRecordKind record_kind = ParsePicoStationRecord(rest, station);
        if (record_kind == PicoStationRecordKind::RawChannelFirst) {
          ++pico_station_raw_schema;
          pico_raw_schema_ids.insert(station.serial);
          pico_raw_station_ids.insert(station.serial);
          // Only raw source poses may populate the map passed to SetStationsRaw.
          auto existing = source_channels.find(station.serial);
          int station_index;
          if (existing == source_channels.end()) {
            station_index = (int)source_channels.size() + 1;
            source_channels.emplace(station.serial, station_index);
          } else {
            station_index = existing->second;
          }
          std::string key = "P3C-STATION-" + std::to_string(station_index);
          raw[key] = {V3{station.values[0], station.values[1], station.values[2]},
                      ToM3(Quat{station.values[3], station.values[4], station.values[5], station.values[6]})};
          sync.SetStationsRaw(raw);
          int channel = station.channel;
          auto override_channel = chans.find(station.serial);
          if (override_channel != chans.end()) channel = override_channel->second;
          if (channel > 0) chans[key] = channel;
          sync.SetChannels(chans);
        } else if (record_kind == PicoStationRecordKind::ChannelLast) {
          ++pico_station_channel_last;
          pico_channel_last_schema_ids.insert(station.serial);
        } else if (record_kind == PicoStationRecordKind::Ambiguous) {
          ++pico_station_ambiguous;
          pico_ambiguous_schema_ids.insert(station.serial);
        } else {
          ++pico_station_malformed;
        }
      } else {
        // Preserve the legacy generic replay contract: S serial x y z qw qx qy qz [channel].
        char serial[64];
        double v[7];
        int ch = 0;
        int got = sscanf(rest, "%63s %lf %lf %lf %lf %lf %lf %lf %d", serial, &v[0], &v[1], &v[2],
                         &v[3], &v[4], &v[5], &v[6], &ch);
        if (got >= 8) {
          std::string key = serial;
          raw[key] = {V3{v[0], v[1], v[2]}, ToM3(Quat{v[3], v[4], v[5], v[6]})};
          sync.SetStationsRaw(raw);
          if (got == 9 && ch > 0 && !chans.count(serial)) {  // recorded channels; --channel wins
            chans[serial] = ch;
            sync.SetChannels(chans);
          }
        }
      }
    } else if (kind == 'F') {
      sync.OnLine(pc, sp + 1);
    } else if (kind == 'B') {  // worn and held lighthouse devices (reference frame)
      int dev;
      double v[3];
      if (sscanf(rest, "%d %lf %lf %lf", &dev, &v[0], &v[1], &v[2]) == 4) sync.OnBodyPose(dev, pc, V3{v[0], v[1], v[2]});
    } else if (kind == 'Q') {  // QuestLHSync recordings: clock round trips "Q pc_send pc_recv hs"
      double a, b, h;
      if (sscanf(rest, "%lf %lf %lf", &a, &b, &h) == 3) sync.OnPing(a, b, h);
    }
    while (pc >= next_tick) {
      bool step = sync.WillStep(next_tick);
      Transform x = sync.Tick(next_tick);
      if (pico_offline) {
        Sync::Status pst = sync.GetStatus(next_tick);
        if (pst.locked) {
          ++pico_locked_steps; ++pico_current_lock_steps;
          if (!pico_last_locked) ++pico_lock_episodes;
        } else {
          if (pico_last_locked) ++pico_lock_breaks;
          pico_max_lock_steps = std::max(pico_max_lock_steps, pico_current_lock_steps);
          pico_current_lock_steps = 0;
        }
        pico_last_locked = pst.locked;
        if (pico_next_status == 0) pico_next_status = next_tick;
        if (next_tick + 1e-6 >= pico_next_status) {
          PrintPicoStatus(pst, (long long)std::llround(next_tick * 1e9), next_tick - t0, chans);
          pico_next_status += 1.0;
        }
      }
      if (xf && x.active && ticks++ % 5 == 0)
        fprintf(xf, "%lld %.7f %.7f %.7f %.7f %.5f %.5f %.5f\n", (long long)(next_tick * 1e9), x.q.w, x.q.x, x.q.y, x.q.z,
                x.t.x, x.t.y, x.t.z);
      if (step && out) {
        auto st = sync.GetStatus(next_tick);
        if (st.has_x)
          fprintf(out, "%lld %.5f %.5f %.5f %.5f\n", (long long)(next_tick * 1e9), st.x[0] * kDeg, st.x[1], st.x[2], st.x[3]);
      }
      next_tick += 0.05;
    }
    if (pc >= next_print) {
      next_print += 10;
      auto st = sync.GetStatus(pc);
      std::string sts;
      for (auto &e : st.st) sts += " " + e.serial + ":" + std::to_string(e.support);
      if (st.has_x)
        printf("%6.0fs yaw %+.3f t [%.1f %.1f %.1f] cm n %d med %.3f%s%s expo %.1f ms\n", pc - t0, st.x[0] * kDeg, st.x[1] * 100,
               st.x[2] * 100, st.x[3] * 100, st.n, st.med, sts.c_str(), st.cond ? " cond" : "", st.expo * 1000);
      else
        printf("%6.0fs unlocked%s\n", pc - t0, sts.c_str());
    }
  }
  if (pico_audit) fclose(pico_audit);
  fclose(f);
  if (pico_line_error) {
    fprintf(stderr, "MALFORMED_PICO_FRAME line=%ld\n", pico_line_error);
    if (out) fclose(out); if (xf) fclose(xf); if (g_ray_dump) fclose(g_ray_dump);
    return 1;
  }
  pico_max_lock_steps = std::max(pico_max_lock_steps, pico_current_lock_steps);
  auto st = sync.GetStatus(tnow);
  double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - wall).count();
  printf("replayed %ld lines (%.0f s of log) in %.1f s; expo %.1f ms%s\n", nl, tnow - t0, secs, st.expo * 1000,
         st.timing_learned ? " (learned)" : "");
  printf("%s\n", Sync::Describe({}, sync.spots()).c_str());
  if (pico_offline) {
    Sync::Spots sp = sync.spots();
    Sync::ReplayDiagnostics diag = sync.GetReplayDiagnostics();
    printf("PICO_OFFLINE hypothesis=%s camera_mapping=%s camera_set=%s parsed_supported_frames=%ld frames_submitted=%ld excluded_by_camera_set=%ld unsupported_camera_frames=%ld first_pc_qpc_ns=%lld last_pc_qpc_ns=%lld\n",
           pico_hypothesis.c_str(), pico_mapping_hypothesis.c_str(), pico_upper ? "upper-C0-C3" : "all-C0-C3-C4-C5", pico_frames_parsed,
           pico_frames_submitted, pico_frames_excluded, pico_unsupported_cameras, pico_first_pc_ns, pico_last_pc_ns);
    printf("PICO_SYNC frames_admitted=%ld blobs_admitted=%ld observations_solver_add=%ld still=%ld fast=%ld large=%ld other=%ld dim=%ld pending_frames=%ld\n",
           sp.frames, sp.seen, sp.used + sp.dim, sp.still, sp.fast, sp.big, sp.other, sp.dim, diag.pending_frames);
    printf("PICO_NATIVE acquire_candidate_successes=%ld candidate_rejections=%ld support_rejections=%ld gain_rejections=%ld body_ambiguity_rejections=%ld accepted_alignments=%ld timing_estimate_successes=%ld lock_episodes=%ld lock_breaks=%ld locked_seconds=%.2f max_locked_seconds=%.2f final_alignment=%s final_locked=%s final_condition=%s final_median_deg=",
           diag.acquire_candidate_successes, diag.acquire_candidate_rejections, diag.acquire_support_rejections,
           diag.acquire_gain_rejections, diag.acquire_body_ambiguity_rejections, diag.alignment_accepts,
           diag.timing_estimate_successes, pico_lock_episodes, pico_lock_breaks,
           pico_locked_steps * 0.05, pico_max_lock_steps * 0.05, st.has_x ? "true" : "false", st.locked ? "true" : "false",
           st.cond ? "true" : "false");
    if (st.med >= 0) printf("%.5f", st.med); else printf("NA");
    printf(" final_exposure_ms=%.3f timing_learned=%s\n", st.expo * 1000, st.timing_learned ? "true" : "false");
    for (const auto &kv : pico_camera_counts)
      printf("PICO_CAMERA cam=%d frames_seen=%ld blobs_seen=%ld frames_submitted=%ld\n", kv.first,
             kv.second.frames, kv.second.blobs, kv.second.submitted);
    for (const auto &kv : diag.cameras)
      printf("PICO_STAGE cam=%d frames_admitted=%ld clock_map_failures=%ld pose_failures=%ld still_blobs=%ld large_blobs=%ld invalid_rays=%ld valid_rays=%ld fast_blobs=%ld solver_adds=%ld\n",
             kv.first, kv.second.frames, kv.second.clock_map_failures, kv.second.pose_failures, kv.second.still_blobs,
             kv.second.large_blobs, kv.second.invalid_rays, kv.second.valid_rays, kv.second.fast_blobs, kv.second.solver_adds);
    long shared_station_ids = 0;
    for (const auto &id : pico_raw_schema_ids) if (pico_channel_last_schema_ids.count(id)) ++shared_station_ids;
    printf("PICO_STATION_RECORDS raw_schema=%ld channel_last_rejected=%ld ambiguous_rejected=%ld malformed_rejected=%ld unique_raw_ids=%zu unique_channel_last_ids=%zu unique_ambiguous_ids=%zu cross_format_ids=%ld\n",
           pico_station_raw_schema, pico_station_channel_last, pico_station_ambiguous, pico_station_malformed,
           pico_raw_station_ids.size(), pico_channel_last_schema_ids.size(), pico_ambiguous_schema_ids.size(),
           shared_station_ids);
  }
  if (out) fclose(out);
  if (xf) fclose(xf);
  if (g_ray_dump) {
    std::vector<std::string> keys;
    std::vector<V3> S, Z;
    sync.StationsForDump(keys, S);
    for (size_t i = 0; i < keys.size(); i++) fprintf(g_ray_dump, "S %s %.6f %.6f %.6f\n", keys[i].c_str(), S[i].x, S[i].y, S[i].z);
    fprintf(g_ray_dump, "X %.6f %.6f %.6f %.6f %.5f\n", st.x[0] * kDeg, st.x[1], st.x[2], st.x[3], st.expo);
    fclose(g_ray_dump);
  }
  return 0;
}
