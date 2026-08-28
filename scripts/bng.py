"""
British National Grid (OSGB36) eastings/northings to WGS84 latitude and
longitude.

The ONS publishes MSOA population-weighted centroids as BNG eastings and
northings. Everything else in this repo - club_master, the distance
calculations, the maps - is WGS84 decimal degrees. Getting this wrong does
not fail loudly: it silently places every centroid a few hundred miles
into the North Sea, which is why docs/catchment-data.md warns about it and
why the result is validated against an independent WGS84 source.

Two steps, both standard:
  1. Inverse transverse Mercator onto the Airy 1830 ellipsoid.
  2. Helmert datum shift from OSGB36 to WGS84.

A naive affine approximation is accurate to a few hundred metres at best
and degrades at the edges of the grid; the Helmert transform is good to
about a metre, which is far inside the precision this model needs.
"""

import math

# Airy 1830 - the ellipsoid the National Grid is projected onto.
A_AIRY, B_AIRY = 6377563.396, 6356256.909
# WGS84.
A_WGS, B_WGS = 6378137.000, 6356752.31424518

# National Grid true origin and scale.
F0 = 0.9996012717
LAT0, LON0 = math.radians(49.0), math.radians(-2.0)
E0, N0 = 400000.0, -100000.0

# Helmert OSGB36 -> WGS84. Translations in metres, rotations in seconds of
# arc, scale in parts per million.
TX, TY, TZ = 446.448, -125.157, 542.060
RX, RY, RZ = 0.1502, 0.2470, 0.8421
S_PPM = -20.4894


def _to_cartesian(lat, lon, h, a, b):
    e2 = (a * a - b * b) / (a * a)
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return (
        (nu + h) * math.cos(lat) * math.cos(lon),
        (nu + h) * math.cos(lat) * math.sin(lon),
        ((1 - e2) * nu + h) * math.sin(lat),
    )


def _from_cartesian(x, y, z, a, b):
    e2 = (a * a - b * b) / (a * a)
    p = math.sqrt(x * x + y * y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(12):                      # converges in a handful
        nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * nu * math.sin(lat), p)
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return lat, math.atan2(y, x), p / math.cos(lat) - nu


def _helmert(x, y, z):
    s = 1 + S_PPM / 1e6
    rx, ry, rz = (math.radians(r / 3600.0) for r in (RX, RY, RZ))
    return (
        TX + x * s - y * rz + z * ry,
        TY + x * rz + y * s - z * rx,
        TZ - x * ry + y * rx + z * s,
    )


def bng_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """(easting, northing) in metres -> (latitude, longitude) in degrees."""
    a, b = A_AIRY, B_AIRY
    e2 = (a * a - b * b) / (a * a)
    n = (a - b) / (a + b)

    # Walk northwards until the meridional arc matches the target northing.
    lat = LAT0
    m = 0.0
    while abs(northing - N0 - m) >= 0.00001:
        lat += (northing - N0 - m) / (a * F0)
        dl, sl = lat - LAT0, lat + LAT0
        m = b * F0 * (
            (1 + n + 1.25 * n**2 + 1.25 * n**3) * dl
            - (3 * n + 3 * n**2 + 2.625 * n**3) * math.sin(dl) * math.cos(sl)
            + (1.875 * n**2 + 1.875 * n**3) * math.sin(2 * dl) * math.cos(2 * sl)
            - (35 / 24) * n**3 * math.sin(3 * dl) * math.cos(3 * sl)
        )

    sin_lat, cos_lat, tan_lat = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * F0 / math.sqrt(1 - e2 * sin_lat**2)
    rho = a * F0 * (1 - e2) / (1 - e2 * sin_lat**2) ** 1.5
    eta2 = nu / rho - 1

    t2, t4, t6 = tan_lat**2, tan_lat**4, tan_lat**6
    vii = tan_lat / (2 * rho * nu)
    viii = tan_lat / (24 * rho * nu**3) * (5 + 3 * t2 + eta2 - 9 * t2 * eta2)
    ix = tan_lat / (720 * rho * nu**5) * (61 + 90 * t2 + 45 * t4)
    x_ = 1 / (cos_lat * nu)
    xi = 1 / (cos_lat * 6 * nu**3) * (nu / rho + 2 * t2)
    xii = 1 / (cos_lat * 120 * nu**5) * (5 + 28 * t2 + 24 * t4)
    xiia = 1 / (cos_lat * 5040 * nu**7) * (61 + 662 * t2 + 1320 * t4 + 720 * t6)

    de = easting - E0
    lat_36 = lat - vii * de**2 + viii * de**4 - ix * de**6
    lon_36 = LON0 + x_ * de - xi * de**3 + xii * de**5 - xiia * de**7

    x, y, z = _to_cartesian(lat_36, lon_36, 0.0, A_AIRY, B_AIRY)
    lat_84, lon_84, _ = _from_cartesian(*_helmert(x, y, z), A_WGS, B_WGS)
    return math.degrees(lat_84), math.degrees(lon_84)
