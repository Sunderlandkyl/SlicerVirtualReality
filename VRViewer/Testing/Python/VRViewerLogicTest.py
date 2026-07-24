import vtk
import slicer
import VRViewer

# Headless tests for VRViewerLogic: everything that does not require a headset.
#
# WARNING: this test clears the MRML scene. Run it only in an isolated Slicer (ctest),
# never by exec'ing it into a live working session.

logic = VRViewer.VRViewerLogic()


def _addVisibleModel(name, center):
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

# Extent of an AABB along an axis: a 20x40x60 box has vertical (Z) extent 60.
assert abs(VRViewer.VRViewerLogic._extentAlongAxis([-10, 10, -20, 20, -30, 30], [0, 0, 1]) - 60.0) < 1e-9
assert VRViewer.VRViewerLogic._extentAlongAxis([0, -1, 0, 0, 0, 0], [0, 0, 1]) == 0.0  # empty
print("extentAlongAxis: OK")

# computePhysicalToWorld with M0 = identity: the data center should appear at the table
# physical location, i.e. M maps the table point -> data center (zero-extent data, no lift).
identity = vtk.vtkMatrix4x4()
dataCenter = [10.0, 20.0, 30.0]
emptyBounds = [0.0, -1.0, 0.0, -1.0, 0.0, -1.0]
m = logic.computePhysicalToWorld(identity, 1.0, 0.0, emptyBounds, dataCenter, VRViewer.TABLE_PHYSICAL)
mapped = m.MultiplyPoint([VRViewer.TABLE_PHYSICAL[0], VRViewer.TABLE_PHYSICAL[1], VRViewer.TABLE_PHYSICAL[2], 1.0])
for a in range(3):
    assert abs(mapped[a] - dataCenter[a]) < 1e-4, (a, mapped[a], dataCenter[a])

# Placement invariant holds at any rotation angle (data center stays on the table point).
for angleDeg in (37.0, 90.0, 180.0):
    m = logic.computePhysicalToWorld(
        identity, 1.0, vtk.vtkMath.RadiansFromDegrees(angleDeg), emptyBounds, dataCenter, VRViewer.TABLE_PHYSICAL)
    mapped = m.MultiplyPoint([VRViewer.TABLE_PHYSICAL[0], VRViewer.TABLE_PHYSICAL[1], VRViewer.TABLE_PHYSICAL[2], 1.0])
    for a in range(3):
        assert abs(mapped[a] - dataCenter[a]) < 1e-4, (angleDeg, a)

# Scale invariant: at relScale s, a world offset shrinks by 1/s in physical/view space.
m2 = logic.computePhysicalToWorld(identity, 2.0, 0.0, emptyBounds, dataCenter, VRViewer.TABLE_PHYSICAL)
inv = vtk.vtkMatrix4x4()
vtk.vtkMatrix4x4.Invert(m2, inv)  # world -> physical
centerPhys = inv.MultiplyPoint([dataCenter[0], dataCenter[1], dataCenter[2], 1.0])
offsetPhys = inv.MultiplyPoint([dataCenter[0] + 100.0, dataCenter[1], dataCenter[2], 1.0])
dist = ((offsetPhys[0] - centerPhys[0]) ** 2 + (offsetPhys[1] - centerPhys[1]) ** 2 + (offsetPhys[2] - centerPhys[2]) ** 2) ** 0.5
assert abs(dist - 200.0) < 1e-3, dist  # 100 world units * relScale 2 = 200 physical units
print("computePhysicalToWorld: OK")

# Fit-to-table: with base scale factor sf0 (identity M0 -> sf0 = 1), the fit relScale makes the
# data diagonal span the table diameter. A cube with diagonal D -> fitRelScale = 2*R_table/D.
logic._basePhysicalToWorld = vtk.vtkMatrix4x4()  # identity, sf0 = 1
logic._dataBounds = [-50.0, 50.0, -50.0, 50.0, -50.0, 50.0]  # 100 cube, diagonal = 100*sqrt(3)
diag = (3 ** 0.5) * 100.0
expectedFit = (2.0 * VRViewer.TABLE_RADIUS_M) / diag
assert abs(logic._computeFitRelScale() - expectedFit) < 1e-9, logic._computeFitRelScale()
logic._dataBounds = [0.0, -1.0, 0.0, -1.0, 0.0, -1.0]  # empty -> fit 1.0
assert logic._computeFitRelScale() == 1.0
logic._basePhysicalToWorld = None
print("computeFitRelScale: OK")

# Active-slice cycling wraps Red -> Green -> Yellow -> Red.
logic._activeSliceIndex = 0
seen = []
for _i in range(4):
    seen.append(VRViewer.SLICE_NODE_IDS[logic._activeSliceIndex])
    logic.cycleActiveSlice()
assert seen == [VRViewer.SLICE_NODE_IDS[0], VRViewer.SLICE_NODE_IDS[1], VRViewer.SLICE_NODE_IDS[2], VRViewer.SLICE_NODE_IDS[0]], seen
print("cycleActiveSlice: OK")

# Auto-spin toggles.
logic._autoSpin = False
logic.toggleAutoSpin()
assert logic._autoSpin is True
logic.toggleAutoSpin()
assert logic._autoSpin is False
print("toggleAutoSpin: OK")

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

bounds = VRViewer.VRViewerLogic._combinedRASBounds([visibleModel])
assert bounds[0] < bounds[1], bounds
center = VRViewer.VRViewerLogic._combinedRASCenter([visibleModel])
assert all(abs(c) < 1e-6 for c in center), center
print("combinedRASBounds/Center: OK")

# ---------------------------------------------------------------- slices (no scene geometry moved)

red = slicer.mrmlScene.GetNodeByID("vtkMRMLSliceNodeRed")
if red is not None:
    before = red.GetSliceVisible()
    # Capture SliceToRAS to confirm toggling does NOT alter slice geometry.
    original = vtk.vtkMatrix4x4()
    original.DeepCopy(red.GetSliceToRAS())
    logic.toggleSlices()
    after = red.GetSliceVisible()
    assert after != before, (before, after)
    for r in range(4):
        for c in range(4):
            assert abs(red.GetSliceToRAS().GetElement(r, c) - original.GetElement(r, c)) < 1e-9
    logic.toggleSlices()
    assert red.GetSliceVisible() == before

    # scrollActiveSlice moves the active slice's offset by the requested amount.
    logic._activeSliceIndex = 0  # Red
    startOffset = red.GetSliceOffset()
    logic.scrollActiveSlice(12.0)
    assert abs(red.GetSliceOffset() - (startOffset + 12.0)) < 1e-6, red.GetSliceOffset()
    logic.scrollActiveSlice(-12.0)
    assert abs(red.GetSliceOffset() - startOffset) < 1e-6
    print("scrollActiveSlice: OK")
    print("toggleSlices (visibility only, geometry untouched): OK")

# ---------------------------------------------------------------- scene views

svLogic = slicer.modules.sceneviews.logic()
svLogic.CreateSceneView("VRViewerTestView1")
svLogic.CreateSceneView("VRViewerTestView2")
assert logic.sceneViewCount() >= 2, logic.sceneViewCount()
startIndex = logic._sceneViewIndex
logic.cycleSceneView(+1)
assert logic._sceneViewIndex != startIndex or logic.sceneViewCount() == 1
logic.cycleSceneView(-1)
print("cycleSceneView: OK")

slicer.mrmlScene.Clear()
print("VRViewerLogicTest: ALL PASSED")
