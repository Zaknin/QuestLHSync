#include "../src/omni_radtan.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
using namespace pico_optics;
int main(int argc, char** argv) {
  // Factory coefficients are provided privately on stdin; never checked into Git.
  // Synthetic defaults protect against accidentally baking headset-specific calibration in the test.
  Intrinsics p {3.56, 1066, 1065, 323, 243, 1.2, 15.4, 0.002, -0.003};
  if (argc == 2 && std::string(argv[1]) == "--stdin") {
    if (!(std::cin >> p.xi >> p.fx >> p.fy >> p.cx >> p.cy >> p.k1 >> p.k2 >> p.p1 >> p.p2)) return 2;
  }
  int ok = 0, invalid = 0;
  double max_err = 0;
  for (int y=0;y<480;y+=16) for(int x=0;x<640;x+=16){
    Vec3 ray; if (!Unproject(p, x+0.5, y+0.5, ray)){invalid++;continue;}
    double px, py;
    if (!Project(p, ray, px, py)) return 3;
    double err=std::hypot(px-(x+0.5),py-(y+0.5));
    if (!std::isfinite(err) || err>1e-3) return 4;
    max_err=std::max(max_err,err);ok++;
  }
  Vec3 central;
  if(!Unproject(p,p.cx,p.cy,central)||std::hypot(central.x,central.y)>1e-7||central.z<0.99999)return 5;
  std::printf("valid=%d invalid=%d max_roundtrip_error_px=%.9g\n",ok,invalid,max_err);
  return ok>200?0:6;
}
