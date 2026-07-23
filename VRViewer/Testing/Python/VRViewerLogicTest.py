import vtk
import slicer
import VRViewer

# Headless tests for VRViewerLogic: everything that does not require a headset.
# Run via ctest, or from the Python console with:
#   exec(open(slicer.util.getFilePath(...)).read())

logic = VRViewer.VRViewerLogic()


def _addVisibleModel(name, center):
    """Add a small sphere model at `center` (RAS) with a visible display node."""
    sphere = vtk.vtkSphereSource()
    sphere.SetCenter(center)
    sphere.SetRadius(10.0)
    sphere.Update()
    modelNode = slicer.modules.models.logic().AddModel(sphere.GetOutput())
    modelNode.SetName(name)
    modelNode.GetDisplayNode().SetVisibility(True)
    return modelNode


# ---------------------------------------------------------------- pure helpers

# Multiplicative magnification stepping, clamped to [MIN, MAX].
assert abs(logic.steppedMagnification(1.0, +1, 1.25) - 1.25) < 1e-9
assert abs(logic.steppedMagnification(1.0, -1, 1.25) - 0.8) < 1e-9
assert logic.steppedMagnification(VRViewer.MAX_MAGNIFICATION, +1, 2.0) == VRViewer.MAX_MAGNIFICATION
assert logic.steppedMagnification(VRViewer.MIN_MAGNIFICATION, -1, 2.0) == VRViewer.MIN_MAGNIFICATION
print("steppedMagnification: OK")

# Turntable matrix maps the anchor onto the target, at any rotation about the given axis.
axisZ = [0.0, 0.0, 1.0]
anchor = [10.0, 20.0, 30.0]
target = [100.0, 200.0, 300.0]
for angleDeg in (0.0, 37.0, 90.0, 180.0):
    m = logic.buildTurntableMatrix(vtk.vtkMath.RadiansFromDegrees(angleDeg), axisZ, anchor, target)
    mapped = m.MultiplyPoint([anchor[0], anchor[1], anchor[2], 1.0])
    for a in range(3):
        assert abs(mapped[a] - target[a]) < 1e-4, f"angle {angleDeg}, axis {a}"
# A point offset along +X from the anchor rotates by 90deg about Z into +Y.
m90 = logic.buildTurntableMatrix(vtk.vtkMath.RadiansFromDegrees(90.0), axisZ, anchor, target)
offset = m90.MultiplyPoint([anchor[0] + 5.0, anchor[1], anchor[2], 1.0])
assert abs((offset[0] - target[0]) - 0.0) < 1e-4
assert abs((offset[1] - target[1]) - 5.0) < 1e-4
print("buildTurntableMatrix: OK")

# Extent of an AABB along an axis: a 20x40x60 box has vertical (Z) extent 60.
assert abs(VRViewer.VRViewerLogic._extentAlongAxis([-10, 10, -20, 20, -30, 30], [0, 0, 1]) - 60.0) < 1e-9
assert VRViewer.VRViewerLogic._extentAlongAxis([0, -1, 0, 0, 0, 0], [0, 0, 1]) == 0.0  # empty
print("extentAlongAxis: OK")

# ---------------------------------------------------------------- collection

slicer.mrmlScene.Clear()
visibleModel = _addVisibleModel("VisibleModel", (0.0, 0.0, 0.0))
hiddenModel = _addVisibleModel("HiddenModel", (50.0, 0.0, 0.0))
hiddenModel.GetDisplayNode().SetVisibility(False)

collected = VRViewer.VRViewerLogic._collectVisibleDataNodes()
collectedIds = [n.GetID() for n in collected]
assert visibleModel.GetID() in collectedIds, "visible model should be collected"
assert hiddenModel.GetID() not in collectedIds, "invisible model should be excluded"
print("collectVisibleDataNodes: OK")

# Combined center of a single sphere at origin is ~origin.
center = VRViewer.VRViewerLogic._combinedRASCenter([visibleModel])
assert all(abs(c) < 1e-6 for c in center), center
print("combinedRASCenter: OK")

# ---------------------------------------------------------------- attach/detach

# Model parented under an existing transform - the turntable must go ABOVE that transform.
transformedModel = _addVisibleModel("TransformedModel", (0.0, 0.0, 0.0))
userTransform = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "UserTransform")
transformedModel.SetAndObserveTransformNodeID(userTransform.GetID())

logic._tableCenterWorld = [100.0, 200.0, 300.0]
logic._buildTurntable()
turntableId = logic._turntableNode.GetID()

# Direct (untransformed) model is now parented to the turntable.
assert visibleModel.GetParentTransformNode() is not None
assert visibleModel.GetParentTransformNode().GetID() == turntableId
# The user transform (top of the transformed model's chain) is parented to the turntable,
# and the model still sits under its own transform.
assert userTransform.GetParentTransformNode() is not None
assert userTransform.GetParentTransformNode().GetID() == turntableId
assert transformedModel.GetParentTransformNode().GetID() == userTransform.GetID()
print("attach: OK")

# Rotation updates the turntable matrix without detaching.
logic.rotateTurntable(vtk.vtkMath.RadiansFromDegrees(45.0))
m = vtk.vtkMatrix4x4()
logic._turntableNode.GetMatrixTransformToParent(m)
expected = logic.buildTurntableMatrix(
    logic._turntableAngleRad, logic._turntableAxis, logic._dataCenter, logic._tableTargetWorld)
for r in range(4):
    for c in range(4):
        assert abs(m.GetElement(r, c) - expected.GetElement(r, c)) < 1e-6
print("rotateTurntable: OK")

# Teardown restores original parenting and removes the turntable node.
logic._teardownTurntable()
assert visibleModel.GetParentTransformNode() is None
assert userTransform.GetParentTransformNode() is None
assert transformedModel.GetParentTransformNode().GetID() == userTransform.GetID()
assert slicer.mrmlScene.GetNodesByClass("vtkMRMLTransformNode").GetNumberOfItems() >= 1  # userTransform remains
print("teardown: OK")

# ---------------------------------------------------------------- scene views

# Scene views live in the SceneViews module logic (sequence-browser backed), not as
# top-level vtkMRMLSceneViewNode nodes. Create two and cycle through them.
svLogic = slicer.modules.sceneviews.logic()
svLogic.CreateSceneView("VRViewerTestView1")
svLogic.CreateSceneView("VRViewerTestView2")
assert logic.sceneViewCount() >= 2, logic.sceneViewCount()
logic._buildTurntable()
startIndex = logic._sceneViewIndex
logic.cycleSceneView(+1)
assert logic._sceneViewIndex != startIndex or logic.sceneViewCount() == 1
logic.cycleSceneView(-1)
assert logic._turntableNode is not None
logic._teardownTurntable()
print("cycleSceneView: OK")

slicer.mrmlScene.Clear()
print("VRViewerLogicTest: ALL PASSED")
