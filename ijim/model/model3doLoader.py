from ijim.text.tokenizer import TokenType, Tokenizer
from .model3do import *
import os

def _skip_to_next_model_section(tok: Tokenizer):
    t = tok.getToken()
    while t.type != TokenType.EOF and (t.type != TokenType.Identifier or t.value.upper() != "SECTION"):
        t = tok.getToken()

    if t.type != TokenType.EOF:
        tok.assertPunctuator(":")

def _parse_model_header_section(tok: Tokenizer):
    file_sig = tok.getSpaceDelimitedString()
    if file_sig.upper() != "3DO":
        raise IOError("Invalid 3do model file!")

    version = tok.getFloatNumber()
    if version != 2.3:
        raise IOError("Invalid file version of 3do model!")
    return version

def _parse_model_resource_section(tok: Tokenizer, model: Model):
    tok.assertIdentifier("MATERIALS")

    listLen = tok.getIntNumber()
    for i in range(0, listLen):
        idx = tok.getIntNumber()
        assert idx == i
        tok.assertPunctuator(':')
        model.materials.append(tok.getSpaceDelimitedString())

def _parse_model_geometry_section(tok: Tokenizer, model: Model):
    tok.assertIdentifier("RADIUS")
    model.radius = tok.getFloatNumber()

    tok.assertIdentifier("INSERT")
    tok.assertIdentifier("OFFSET")
    model.insertOffset = tok.getVector3f()

    tok.assertIdentifier("GEOSETS")
    numGeoSets = tok.getIntNumber()
    for i in range(0, numGeoSets):
        geoset = ModelGeoSet()

        tok.assertIdentifier("GEOSET")
        geosetIdx = tok.getIntNumber()
        assert geosetIdx == i

        tok.assertIdentifier("MESHES")
        numMeshes = tok.getIntNumber()
        for j in range(0, numMeshes):
            tok.assertIdentifier("MESH")
            meshIdx = tok.getIntNumber()
            assert meshIdx == j

            tok.assertIdentifier("NAME")
            name = tok.getDelimitedStringToken(lambda c: c == '\n')

            mesh = ModelMesh(meshIdx, name.value)


            tok.assertIdentifier("RADIUS")
            mesh.radius = tok.getFloatNumber()

            tok.assertIdentifier("GEOMETRYMODE")
            mesh.geometryMode = GeometryMode(tok.getIntNumber())

            tok.assertIdentifier("LIGHTINGMODE")
            mesh.lightMode = LightMode(tok.getIntNumber())

            tok.assertIdentifier("TEXTUREMODE")
            mesh.textureMode = TextureMode(tok.getIntNumber())


            tok.assertIdentifier("VERTICES")
            numVertices = tok.getIntNumber()
            for k in range(0, numVertices):
                vertIdx = tok.getIntNumber()
                assert vertIdx == k
                tok.assertPunctuator(':')

                mesh.vertices.append(tok.getVector3f())
                mesh.verticesColor.append(tok.getVector4f())

            tok.assertIdentifier("TEXTURE")
            tok.assertIdentifier("VERTICES")
            numTexVertices = tok.getIntNumber()
            for k in range(0, numTexVertices):
                vertIdx = tok.getIntNumber()
                assert vertIdx == k
                tok.assertPunctuator(':')
                mesh.textureVertices.append(tok.getVector2f())

            tok.assertIdentifier("VERTEX")
            tok.assertIdentifier("NORMALS")
            for k in range(0, numVertices):
                normalIdx = tok.getIntNumber()
                assert normalIdx == k
                tok.assertPunctuator(':')
                mesh.normals.append(tok.getVector3f())

            tok.assertIdentifier("FACES")
            numFaces = tok.getIntNumber()
            for k in range(0, numFaces):
                face = MeshFace()

                faceIdx = tok.getIntNumber()
                assert faceIdx == k
                tok.assertPunctuator(':')

                face.materialIdx  = tok.getIntNumber()
                face.type         = FaceType(tok.getIntNumber())
                face.geometryMode = GeometryMode(tok.getIntNumber())
                face.lightMode    = LightMode(tok.getIntNumber())
                face.textureMode  = TextureMode(tok.getIntNumber())
                face.color        = tok.getVector4f()


                numFaceVerts = tok.getIntNumber()
                for l in range(0, numFaceVerts):
                    idxs = tok.getPairOfInts()
                    face.vertexIdxs.append(idxs[0])
                    face.texVertexIdxs.append(idxs[1])

                mesh.faces.append(face)

            tok.assertIdentifier("FACE")
            tok.assertIdentifier("NORMALS")
            for k in range(0, numFaces):
                faceNormalIdx = tok.getIntNumber()
                assert faceNormalIdx == k
                tok.assertPunctuator(':')
                mesh.faces[k].normal = tok.getVector3f()


            geoset.meshes.append(mesh)
        model.geosets.append(geoset)

def _parse_hierarchy_section(tok: Tokenizer, model: Model):
    tok.assertIdentifier("HIERARCHY")
    tok.assertIdentifier("NODES")

    numNodes = tok.getIntNumber()
    for i in range(0, numNodes):
        node = MeshHierarchyNode()

        nodeIdx = tok.getIntNumber()
        assert nodeIdx == i
        tok.assertPunctuator(':')

        node.flags         = tok.getIntNumber()
        node.type          = MeshNodeType(tok.getIntNumber())
        node.meshIdx       = tok.getIntNumber()
        node.parentIdx     = tok.getIntNumber()
        node.firstChildIdx = tok.getIntNumber()
        node.siblingIdx    = tok.getIntNumber()
        node.numChildren   = tok.getIntNumber()

        node.position = tok.getVector3f()
        node.rotation = tok.getVector3f()
        node.pivot    = tok.getVector3f()

        node.name = tok.getSpaceDelimitedString()

        model.hierarchyNodes.append(node)





def LoadModel3do(filePath) -> Model:
    f = open(filePath, 'r')
    tok = Tokenizer(f)

    file_version = 0.0
    model = Model(os.path.basename(filePath))

    while True:
        _skip_to_next_model_section(tok)
        t = tok.getToken()
        if t.type == TokenType.EOF:
            break

        if t.value.upper() == "HEADER":
            file_version = _parse_model_header_section(tok)

        elif t.value.upper() == "MODELRESOURCE":
            _parse_model_resource_section(tok, model)

        elif t.value.upper() == "GEOMETRYDEF":
            _parse_model_geometry_section(tok, model)

        elif t.value.upper() == "HIERARCHYDEF":
            _parse_hierarchy_section(tok, model)

    return model


if __name__ == '__main__':
    model = LoadModel3do("gen_vo.3do")
