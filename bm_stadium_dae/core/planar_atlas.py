# SPDX-License-Identifier: GPL-3.0-or-later
"""Continuous UVs for proven non-overlapping axis-aligned planar triangles."""
import numpy as np


def planar_uv(vertices, resolution):
    vertices = np.asarray(vertices, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) % 3 or not np.isfinite(vertices).all():
        return None
    if len(vertices) < 3 or len(vertices) > 6144:
        return None  # Keep overlap verification bounded; generic atlas handles larger meshes.
    spans = np.ptp(vertices, axis=0)
    axes = np.argsort(spans)[1:]
    if spans[axes[0]] < 1e-8 or spans.min() > max(1e-7, spans.max() * 1e-6):
        return None
    points = (vertices[:, axes] - vertices[:, axes].min(axis=0)) / spans[axes]
    triangles = points.reshape(-1, 3, 2)
    e1, e2 = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    cross = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    if np.any(np.abs(cross) < 1e-12) or not (np.all(cross > 0) or np.all(cross < 0)):
        return None
    low, high = triangles.min(axis=1), triangles.max(axis=1)
    for i, triangle in enumerate(triangles):
        candidates = np.flatnonzero(np.all(high[i] > low[i+1:] + 1e-10, axis=1) &
                                    np.all(high[i+1:] > low[i] + 1e-10, axis=1)) + i + 1
        for j in candidates:
            pair = triangles[j]
            edges = np.concatenate((np.roll(triangle, -1, axis=0) - triangle,
                                    np.roll(pair, -1, axis=0) - pair))
            normals = np.stack((-edges[:, 1], edges[:, 0]), axis=1)
            a, b = triangle @ normals.T, pair @ normals.T
            # Shared boundaries are valid. Positive overlap on every separating
            # axis means these triangles would overwrite one another in the bake.
            overlaps = np.minimum(a.max(axis=0), b.max(axis=0)) - np.maximum(a.min(axis=0), b.min(axis=0))
            if np.all(overlaps > 1e-10 * np.linalg.norm(normals, axis=1)):
                return None
    margin = min(.125, 8. / resolution)
    return np.asarray(margin + points * (1 - 2 * margin), dtype=np.float32)
