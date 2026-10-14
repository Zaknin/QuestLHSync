// Pico tracking-camera optics: OpenCV omnidirectional (Mei xi) + Brown/Conrady Radtan.
// Mathematical model only. No device-specific values, camera IDs or headset pose assumed.
#pragma once
#include <cmath>

namespace pico_optics {
struct Vec3 { double x = 0, y = 0, z = 1; };
struct Intrinsics {
  double xi = 0, fx = 0, fy = 0, cx = 0, cy = 0;
  double k1 = 0, k2 = 0, p1 = 0, p2 = 0;
};

inline bool Valid(const Intrinsics &c) {
  return std::isfinite(c.xi + c.fx + c.fy + c.cx + c.cy + c.k1 + c.k2 + c.p1 + c.p2) &&
         c.xi >= 0 && c.fx > 0 && c.fy > 0;
}

inline void Radtan(const Intrinsics &c, double x, double y, double &u, double &v) {
  double r2 = x*x + y*y;
  double radial = 1 + c.k1*r2 + c.k2*r2*r2;
  u = x*radial + 2*c.p1*x*y + c.p2*(r2 + 2*x*x);
  v = y*radial + c.p1*(r2 + 2*y*y) + 2*c.p2*x*y;
}

// Unit direction in the camera coordinate frame -> image coordinates.
inline bool Project(const Intrinsics &c, Vec3 d, double &px, double &py) {
  if (!Valid(c)) return false;
  double n = std::sqrt(d.x*d.x + d.y*d.y + d.z*d.z);
  if (!std::isfinite(n) || n < 1e-15) return false;
  double den = d.z + c.xi*n;
  if (!(den > 1e-12)) return false;
  double u, v;
  Radtan(c, d.x/den, d.y/den, u, v);
  px = c.fx*u + c.cx;
  py = c.fy*v + c.cy;
  return std::isfinite(px) && std::isfinite(py);
}

// Pixel -> unit direction. Newton inverts Radtan; closed-form Mei inverse maps to sphere.
inline bool Unproject(const Intrinsics &c, double px, double py, Vec3 &d) {
  if (!Valid(c) || !std::isfinite(px + py)) return false;
  double tu = (px-c.cx)/c.fx, tv = (py-c.cy)/c.fy;
  double x = tu, y = tv;
  bool converged = false;
  for (int i = 0; i < 40; ++i) {
    double u, v;
    Radtan(c, x, y, u, v);
    double eu = u-tu, ev = v-tv, e2 = eu*eu + ev*ev;
    if (e2 < 1e-24) { converged = true; break; }
    double r2 = x*x + y*y;
    double radial = 1 + c.k1*r2 + c.k2*r2*r2;
    double g = c.k1 + 2*c.k2*r2;
    double j11 = radial + 2*g*x*x + 2*c.p1*y + 6*c.p2*x;
    double j22 = radial + 2*g*y*y + 6*c.p1*y + 2*c.p2*x;
    double j12 = 2*g*x*y + 2*c.p1*x + 2*c.p2*y;
    double det = j11*j22 - j12*j12;
    if (!std::isfinite(det) || std::fabs(det) < 1e-15) return false;
    double dx = (j22*eu-j12*ev)/det;
    double dy = (j11*ev-j12*eu)/det;
    bool better = false;
    for (double alpha = 1; alpha >= 1.0/1024; alpha *= 0.5) {
      double nx = x-alpha*dx, ny = y-alpha*dy, nu, nv;
      Radtan(c, nx, ny, nu, nv);
      double ne2 = (nu-tu)*(nu-tu) + (nv-tv)*(nv-tv);
      if (std::isfinite(ne2) && ne2 < e2) { x=nx; y=ny; better=true; break; }
    }
    if (!better) return false;
  }
  if (!converged) {
    double u,v; Radtan(c,x,y,u,v);
    if (std::hypot(u-tu,v-tv) > 1e-9) return false;
  }
  double r2 = x*x + y*y;
  double discr = 1 + (1 - c.xi*c.xi)*r2;
  if (discr < 0) {
    if (discr < -1e-12) return false;
    discr = 0;
  }
  double lam = (c.xi + std::sqrt(discr))/(1+r2);
  double X = lam*x, Y = lam*y, Z = lam-c.xi;
  double n = std::sqrt(X*X+Y*Y+Z*Z);
  if (!std::isfinite(n) || n < 1e-15) return false;
  d = {X/n, Y/n, Z/n};
  return true;
}
} // namespace pico_optics
