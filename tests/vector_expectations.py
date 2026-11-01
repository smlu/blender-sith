"""Independent expectations shared by the on-disk vector regression suites."""
import json
from fixtures import TV

VALID_MODELS = ('order_colors.3do', 'shared_mesh.3do', 'legacy_pixels.3do',
                'rgb22.3do', 'loose_vertices.3do', 'empty.3do', 'color_seams.3do',
                'degenerate_faces.3do')
RECOVERY = json.loads((TV / 'model/recovery/expected.json').read_text())
INVALID_KEYS = ('invalid_timing.key', 'duplicate_joint.key', 'out_of_range.key',
                'unordered_entries.key', 'truncated_entry.key')

DEGENERATE_VERTICES = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0), (0, 0, 0), (9, 9, 9))
DEGENERATE_COLORS = ((1, 0, 0, 0.25), (0, 1, 0, 0.5), (0, 0, 1, 0.75),
                     (-0.25, 2, 0.5, 1), (0.2, 0.4, 0.6, 0.8), (2, -0.5, 0.25, 0))
DEGENERATE_CORNERS = ((0, 1, 2), (1, 0, 0), (0, 0, 2), (0, 1, 0, 2),
                      (0, 1, 2, 0), (1, 1, 1), (0, 1, 3), (0, 4, 2), (2, 1, 0))
DEGENERATE_UVS = ((0, 0), (1, 0), (0, 1), (0.25, 0.75), (0.8, 0.2))
DEGENERATE_FACE_UVS = ((0, 1, 2), (0, 3, 4), (1, 2, 3), (0, 1, 3, 2),
                       (0, 1, 2, 4), (0, 1, 2), (0, 1, 2), (0, 4, 2), (2, 1, 0))
# Only repeated corners receive new Blender vertex IDs, in face/corner order.
DEGENERATE_VERTEX_SOURCES = (0, 1, 2, 3, 4, 5, 0, 0, 0, 0, 1, 1)
DEGENERATE_EXPANDED_FACES = ((0, 1, 2), (1, 0, 6), (0, 7, 2), (0, 1, 8, 2),
                           (0, 1, 2, 9), (1, 10, 11), (0, 1, 3), (0, 4, 2), (2, 1, 0))


def color_for_version(color, version):
    """The declared file formats, not an invocation of the writer under test."""
    if version.value == 2.1:
        intensity = sum(color[:3]) / 3
        return (intensity, intensity, intensity, 1)
    if version.value == 2.2:
        return (*color[:3], 1)
    return tuple(color)
