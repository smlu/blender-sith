"""Conservative, Blender-independent preparation of partially parsed 3DOs."""
import math

from ..types import Vector2f, Vector3f, Vector4f
from .model3do import GeometryMode, Mesh3doNode


def recoverModel3do(model, warnings, *, recoverUnboundMeshes=True):
    """Keep usable geometry and report every lossy fallback, never edit the file."""
    def warn(message):
        warnings.append(message)
        print(f"Warning: {message}")

    def finite(vector):
        return all(math.isfinite(value) for value in vector)

    if not model.geosets or not model.geosets[0].meshes:
        if warnings and not model.meshHierarchy:
            raise ValueError('No recoverable geometry or hierarchy was found')
        return

    # 1. Sanitize model metadata independently of the available geometry.
    if not math.isfinite(model.radius) or model.radius < 0:
        warn('Invalid model radius replaced with zero.')
        model.radius = 0.0
    if not finite(model.insertOffset):
        warn('Invalid model insert offset replaced with the origin.')
        model.insertOffset = Vector3f(0.0, 0.0, 0.0)

    for geoset in model.geosets:
        for mesh in geoset.meshes:
            label = f"Mesh '{mesh.name}'"

            # 2. Retain finite vertices and build their old-to-new index map.
            # Colors/normals must stay aligned with the surviving vertex table.
            vertexMap = {}
            vertices, colors, normals = [], [], []
            missingColors = missingNormals = 0
            for index, vertex in enumerate(mesh.vertices):
                if not finite(vertex):
                    warn(f"{label}: vertex {index} is nonfinite and was omitted.")
                    continue

                vertexMap[index] = len(vertices)
                vertices.append(vertex)
                color = mesh.vertexColors[index] if index < len(mesh.vertexColors) else None
                normal = mesh.normals[index] if index < len(mesh.normals) else None
                if color is None or not finite(color):
                    color = Vector4f(0.0, 0.0, 0.0, 1.0)
                    missingColors += 1
                if normal is None or not finite(normal):
                    normal = Vector3f(0.0, 0.0, 0.0)
                    missingNormals += 1
                colors.append(color)
                normals.append(normal)

            if missingColors:
                warn(f"{label}: {missingColors} missing/invalid vertex colors replaced with black.")
            if missingNormals:
                warn(f"{label}: {missingNormals} missing/invalid vertex normals; Blender will recompute normals from available faces.")

            mesh.vertices, mesh.vertexColors, mesh.normals = vertices, colors, normals
            if not math.isfinite(mesh.radius) or mesh.radius < 0:
                warn(f"{label}: invalid radius replaced with zero.")
                mesh.radius = 0.0

            # 3. Omit faces that cannot form a valid polygon. For usable faces,
            # remap corners and substitute UVs only where required for texturing.
            faces = []
            sourceUVCount = len(mesh.uvs)
            fallbackUV = None
            for index, face in enumerate(mesh.faces):
                faceLabel = f"{label}, face {index}"
                if (len(face.vertexIdxs) < 3
                        or any(vertex not in vertexMap for vertex in face.vertexIdxs)):
                    warn(f"{faceLabel}: invalid vertex references or incomplete polygon; face omitted.")
                    continue

                # Repeated corners are safe legacy data. The Blender importer
                # expands them to coincident vertices, so recovery need not lose faces.
                face.vertexIdxs = [vertexMap[vertex] for vertex in face.vertexIdxs]
                if face.materialIdx < -1 or face.materialIdx >= len(model.materials):
                    warn(f"{faceLabel}: invalid material {face.materialIdx}; imported without a material.")
                    face.materialIdx = -1
                textured = (min(mesh.geometryMode, face.geometryMode) == GeometryMode.Texture
                            and face.materialIdx >= 0)

                # Keep the original UV count fixed: a newly appended placeholder
                # must not make a previously out-of-range source reference valid.
                uvIndices = []
                for corner in range(len(face.vertexIdxs)):
                    uv = face.uvIdxs[corner] if corner < len(face.uvIdxs) else -1
                    if textured and not (0 <= uv < sourceUVCount and finite(mesh.uvs[uv])):
                        warn(f"{faceLabel}, corner {corner}: invalid UV {uv}; using placeholder (0, 0).")
                        if fallbackUV is None:
                            fallbackUV = len(mesh.uvs)
                            mesh.uvs.append(Vector2f(0.0, 0.0))
                        uv = fallbackUV
                    uvIndices.append(uv)

                face.uvIdxs = uvIndices

                if not finite(face.normal):
                    warn(f"{faceLabel}: invalid normal; Blender will recompute it.")
                    face.normal = Vector3f(0.0, 0.0, 0.0)
                if not finite(face.color):
                    warn(f"{faceLabel}: invalid extra lighting replaced with black.")
                    face.color = Vector4f(0.0, 0.0, 0.0, 1.0)
                faces.append(face)

            mesh.faces = faces

            # Invalid coordinates remain in the source table even after active
            # corners use a placeholder. Sanitize unused entries too, without
            # renumbering valid UVs or hiding invalid-reference diagnostics above.
            for index in range(sourceUVCount):
                if not finite(mesh.uvs[index]):
                    warn(f"{label}: nonfinite texture vertex {index} replaced with (0, 0).")
                    mesh.uvs[index] = Vector2f(0.0, 0.0)

    # 4. Recover a usable hierarchy without inventing missing source transforms.
    # A synthetic root groups otherwise unplaceable meshes at the origin.
    meshes = model.geosets[0].meshes
    nodes = model.meshHierarchy
    if warnings and not nodes and not any(mesh.vertices for mesh in meshes):
        raise ValueError('No recoverable geometry or hierarchy was found')

    syntheticRoot = not nodes
    if syntheticRoot:
        warn('Hierarchy is missing: recovered meshes are grouped at the origin; original node transforms and pivots are unavailable.')
        root = Mesh3doNode('recovered_root')
        root.idx = 0
        nodes.append(root)

    for index, node in enumerate(nodes):
        if node.meshIdx < -1 or node.meshIdx >= len(meshes):
            recoverUnboundMeshes = True
            warn(f"Node '{node.name}': missing mesh {node.meshIdx}; retained as an empty node.")
            node.meshIdx = -1
        if node.parentIdx < -1 or node.parentIdx >= len(nodes) or node.parentIdx == index:
            warn(f"Node '{node.name}': invalid parent {node.parentIdx}; detached to the model root.")
            node.parentIdx = -1

        for field in ('position', 'rotation', 'pivot'):
            if not finite(getattr(node, field)):
                warn(f"Node '{node.name}': invalid {field} replaced with zero.")
                setattr(node, field, Vector3f(0.0, 0.0, 0.0))

    # 5. Break parent cycles after range checks make every parent access safe.
    # Each repaired chain becomes a root rather than an arbitrary reattachment.
    visited = set()
    for index in range(len(nodes)):
        chain = set()
        while index >= 0 and index not in visited:
            if index in chain:
                warn(f"Node '{nodes[index].name}': parent cycle broken at this node.")
                nodes[index].parentIdx = -1
                break
            chain.add(index)
            index = nodes[index].parentIdx
        visited.update(chain)

    # 6. A missing/partial hierarchy or broken binding can leave meshes unplaceable.
    # A complete hierarchy may intentionally omit meshes; do not invent joints.
    referenced = {node.meshIdx for node in nodes}
    for index, mesh in enumerate(meshes):
        if recoverUnboundMeshes and index not in referenced:
            warn(f"Mesh '{mesh.name}': no recovered hierarchy node; placed at the origin with no original transform.")
            node = Mesh3doNode(mesh.name)
            node.idx, node.meshIdx = len(nodes), index
            node.parentIdx = 0 if syntheticRoot else -1
            nodes.append(node)

    # 7. Parent links drive Blender objects. Rebuild their redundant child/sibling
    # links from the repaired hierarchy without reordering surviving source nodes.
    children = [[] for _ in nodes]
    for index, node in enumerate(nodes):
        if node.parentIdx >= 0:
            children[node.parentIdx].append(index)
    for node in nodes:
        node.firstChildIdx, node.siblingIdx, node.numChildren = -1, -1, 0

    for index, childIndices in enumerate(children):
        if childIndices:
            nodes[index].firstChildIdx = childIndices[0]
            nodes[index].numChildren = len(childIndices)
            for child, sibling in zip(childIndices, childIndices[1:]):
                nodes[child].siblingIdx = sibling
