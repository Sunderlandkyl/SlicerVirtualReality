import logging
from typing import Annotated

import vtk
import qt

import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)


#
# VRViewer
#


class VRViewer(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("VR Viewer")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Virtual Reality")]
        self.parent.dependencies = ["VirtualReality"]
        self.parent.contributors = ["Kyle Sunderland (PerkLab, Queen's University)"]
        self.parent.helpText = _("""
A grounded, presentation-oriented virtual reality viewer. Instead of flying through empty space,
the user stands in a fixed room with a turntable in front of them. Scene data is placed on the
turntable and rotated with the left thumbstick; world scale, scene-view navigation, and slice
visibility are driven by controller buttons.

Controller bindings (Oculus Touch):
- Left thumbstick left/right: rotate the turntable
- B button: increase scale, Y button: decrease scale
- Right/Left trigger: next/previous scene view
- Right thumbstick click: toggle slice visibility
- Left thumbstick click: reset scale to 1.0
""")
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = _("""
This module is part of the SlicerVirtualReality extension.
""")


#
# VRViewerParameterNode
#


@parameterNodeWrapper
class VRViewerParameterNode:
    """User-facing options for the VR Viewer.

    rotationSpeedDegPerSec - turntable angular speed at full thumbstick deflection.
    magnificationStep - multiplicative factor applied to magnification per +/- button press.
    includeSlices - if true, slice planes rotate/scale together with the data on the turntable.
    showRoom - if true, room walls are drawn (the floor and table are always drawn).
    """

    rotationSpeedDegPerSec: Annotated[float, WithinRange(1.0, 360.0)] = 45.0
    magnificationStep: Annotated[float, WithinRange(1.01, 4.0)] = 1.25
    includeSlices: bool = True
    showRoom: bool = True


#
# VRViewerWidget
#


class VRViewerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Thin desktop panel: enter/exit the viewer and edit options.
    All behavior lives in VRViewerLogic so it can be tested headless.
    """

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/VRViewer.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = VRViewerLogic()

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.ui.enterButton.clicked.connect(self.onEnterButton)
        self.ui.exitButton.clicked.connect(self.onExitButton)

        self.initializeParameterNode()
        self.updateGUIFromLogic()

    def cleanup(self) -> None:
        # Leave viewer mode cleanly if the module widget is destroyed while active.
        if self.logic:
            self.logic.exitViewerMode()
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()
        self.updateGUIFromLogic()

    def exit(self) -> None:
        self.setParameterNode(None)

    def onSceneStartClose(self, caller, event) -> None:
        # The turntable/collected nodes are about to disappear; tear down cleanly.
        if self.logic:
            self.logic.exitViewerMode()
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        self.setParameterNode(self.logic.getParameterNode())

    def setParameterNode(self, inputParameterNode) -> None:
        if self._parameterNode == inputParameterNode:
            return
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.onParameterNodeModified)
        self._parameterNode = inputParameterNode
        if self._parameterNode:
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.onParameterNodeModified)

    def onParameterNodeModified(self, caller=None, event=None) -> None:
        # Live-apply option changes while the viewer is active.
        if self.logic:
            self.logic.applyOptions()

    def onEnterButton(self) -> None:
        try:
            self.logic.enterViewerMode()
        except Exception as e:  # noqa: BLE001
            slicer.util.errorDisplay(_("Failed to enter VR Viewer: {error}").format(error=str(e)))
            import traceback
            traceback.print_exc()
        self.updateGUIFromLogic()

    def onExitButton(self) -> None:
        self.logic.exitViewerMode()
        self.updateGUIFromLogic()

    def updateGUIFromLogic(self) -> None:
        active = bool(self.logic and self.logic.isActive)
        self.ui.enterButton.enabled = not active
        self.ui.exitButton.enabled = active
        if active:
            self.ui.statusLabel.text = _("Active - scale {scale:.2f}x").format(scale=self.logic.getMagnification())
        else:
            self.ui.statusLabel.text = _("Not active")


#
# VRViewerLogic
#

# Physical-space layout of the room, in meters. The tracking origin is at the user's
# feet; forward is -Z and up is +Y (VTK VR physical convention). Tune in-headset.
FLOOR_RADIUS_M = 2.0
FLOOR_THICKNESS_M = 0.02
TABLE_RADIUS_M = 0.40
TABLE_TOP_THICKNESS_M = 0.05
TABLE_HEIGHT_M = 0.90            # height of the table top above the floor
TABLE_FORWARD_M = -0.60         # distance in front of the user (-Z)
COLUMN_RADIUS_M = 0.08
ROOM_SIZE_M = (6.0, 3.0, 6.0)   # width (X), height (Y), depth (Z)
ROOM_CENTER_Y_M = 1.5
SCALE_TEXT_HEIGHT_M = 0.04

# World/RAS vertical axis the turntable spins about (RAS superior = Z).
TURNTABLE_AXIS = (0.0, 0.0, 1.0)

MIN_MAGNIFICATION = 0.01
MAX_MAGNIFICATION = 100.0
DEFAULT_MAGNIFICATION = 1.0

THUMBSTICK_DEADZONE = 0.15
ROTATION_TIMER_INTERVAL_MS = 33  # ~30 Hz turntable update

# Slice nodes shown as planes on the turntable.
SLICE_NODE_IDS = ["vtkMRMLSliceNodeRed", "vtkMRMLSliceNodeGreen", "vtkMRMLSliceNodeYellow"]


class VRViewerLogic(ScriptedLoadableModuleLogic):
    """All VR Viewer behavior. The pure MRML/geometry helpers work without a headset
    so they can be exercised by the headless test; the chrome/observer/anchor paths
    require an active VR view.
    """

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self._parameterNode = None

        self.isActive = False

        # Runtime VR handles (only valid while active).
        self._interactor = None
        self._observerTags = []
        self._physicalToWorldConnection = None

        # Chrome (raw VTK props, not MRML). Anchored to physical space via _anchorMatrix.
        self._chromeProps = []
        self._scaleTextActor = None
        self._anchorMatrix = vtk.vtkMatrix4x4()  # copy of PhysicalToWorld, shared by all chrome props

        # Turntable (MRML transform in world/RAS) + attached data.
        self._turntableNode = None
        self._turntableAngleRad = 0.0
        self._dataBounds = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self._dataCenter = [0.0, 0.0, 0.0]
        self._turntableAxis = list(TURNTABLE_AXIS)   # world "up", updated from PhysicalToWorld
        self._tableCenterWorld = [0.0, 0.0, 0.0]     # table-top surface point (world)
        self._tableTargetWorld = [0.0, 0.0, 0.0]     # where the data center lands: surface + up*halfHeight
        self._savedParents = {}        # transformableNodeID -> original parent transform node ID (or None)
        self._savedSliceToRAS = {}     # sliceNodeID -> original SliceToRAS (vtkMatrix4x4)
        self._savedSliceVisible = {}   # sliceNodeID -> original SliceVisible flag

        # Saved VR navigation state, restored on exit.
        self._savedDolly = None
        self._savedGrab = None

        # Turntable rotation driven by a timer from the current stick deflection.
        self._leftStickX = 0.0
        self._rotationTimer = qt.QTimer()
        self._rotationTimer.setInterval(ROTATION_TIMER_INTERVAL_MS)
        self._rotationTimer.timeout.connect(self._onRotationTimer)

        # Scene-view iteration state.
        self._sceneViewIndex = -1

    def getParameterNode(self):
        parameterNode = super().getParameterNode()
        if not self._parameterNode or self._parameterNode.parameterNode != parameterNode:
            self._parameterNode = VRViewerParameterNode(parameterNode)
        return self._parameterNode

    # ------------------------------------------------------------------ VR access

    @staticmethod
    def _vrLogic():
        try:
            return slicer.modules.virtualreality.logic()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _vrViewWidget():
        try:
            return slicer.modules.virtualreality.viewWidget()
        except Exception:  # noqa: BLE001
            return None

    def _vrViewNode(self):
        vrLogic = self._vrLogic()
        return vrLogic.GetVirtualRealityViewNode() if vrLogic else None

    def _vrRenderer(self):
        widget = self._vrViewWidget()
        if not widget:
            return None
        renderers = widget.renderWindow().GetRenderers()
        if renderers.GetNumberOfItems() < 1:
            return None
        return renderers.GetItemAsObject(0)

    # ------------------------------------------------------------------ enter/exit

    def enterViewerMode(self) -> None:
        """Activate VR (if needed), build the room + turntable, and install controls."""
        if self.isActive:
            # Genuinely still running -> nothing to do. Otherwise the state is stale (VR was
            # turned off, or the module was reloaded); clean up so we can re-enter fresh.
            vrLogic = self._vrLogic()
            if vrLogic and vrLogic.GetVirtualRealityActive() and self._chromeProps:
                return
            self.exitViewerMode()

        vrLogic = self._vrLogic()
        if vrLogic is None:
            raise RuntimeError(_("The VirtualReality module is not available."))

        vrLogic.SetVirtualRealityActive(True)

        widget = self._vrViewWidget()
        renderer = self._vrRenderer()
        viewNode = self._vrViewNode()
        if widget is None or renderer is None or viewNode is None:
            raise RuntimeError(_("VR view is not available. Is a headset connected?"))

        # Disable free navigation so the left stick / buttons are ours.
        self._savedDolly = widget.isDolly3DEnabled()
        self._savedGrab = widget.isGrabObjectsEnabled()
        widget.setDolly3DEnabled(False)
        widget.setGrabObjectsEnabled(False)
        try:
            widget.setGestureButtonToNone()
        except Exception:  # noqa: BLE001
            pass

        # World scale starts at the default.
        viewNode.SetMagnification(DEFAULT_MAGNIFICATION)

        # Build the room and place the data on the turntable.
        self._buildChrome(renderer)
        self._buildTurntable()
        self._syncAnchor()  # position chrome + turntable for the current physical-to-world matrix

        # Controls.
        self._installObservers(widget)
        self._rotationTimer.start()

        self.isActive = True

    def exitViewerMode(self) -> None:
        """Tear everything down. Safe to call when not active and idempotent."""
        if not self.isActive and not self._chromeProps and self._turntableNode is None:
            return

        self._rotationTimer.stop()
        self._leftStickX = 0.0

        self._removeObservers()

        # Restore VR navigation state.
        widget = self._vrViewWidget()
        if widget is not None:
            if self._savedDolly is not None:
                widget.setDolly3DEnabled(self._savedDolly)
            if self._savedGrab is not None:
                widget.setGrabObjectsEnabled(self._savedGrab)
        self._savedDolly = None
        self._savedGrab = None

        self._teardownChrome()
        self._teardownTurntable()

        self.isActive = False

    # ------------------------------------------------------------------ options

    def applyOptions(self) -> None:
        """Re-read user options that can change live (currently rotation speed only,
        read on demand). Placeholder for future live-applied settings."""
        if not self.isActive:
            return
        # showRoom / includeSlices changes take effect on next enter; nothing to do live yet.

    # ------------------------------------------------------------------ chrome

    def _buildChrome(self, renderer) -> None:
        """Create the room/floor/table/text props (authored in physical meters) and add
        them to the VR renderer. They are anchored to physical space in _syncAnchor()."""
        params = self.getParameterNode()

        floor = self._discActor(
            center=(0.0, FLOOR_THICKNESS_M / 2.0, 0.0),
            radius=FLOOR_RADIUS_M, height=FLOOR_THICKNESS_M, color=(0.18, 0.20, 0.24))

        column = self._discActor(
            center=(0.0, TABLE_HEIGHT_M / 2.0, TABLE_FORWARD_M),
            radius=COLUMN_RADIUS_M, height=TABLE_HEIGHT_M, color=(0.30, 0.34, 0.40))

        tableTop = self._discActor(
            center=(0.0, TABLE_HEIGHT_M + TABLE_TOP_THICKNESS_M / 2.0, TABLE_FORWARD_M),
            radius=TABLE_RADIUS_M, height=TABLE_TOP_THICKNESS_M, color=(0.35, 0.50, 0.68))

        self._chromeProps = [floor, column, tableTop]

        if params.showRoom:
            self._chromeProps.append(self._roomActor())

        # Scale readout on the front edge of the table, facing the user (+Z).
        self._scaleTextActor = self._textActor(
            position=(0.0, TABLE_HEIGHT_M + 0.06, TABLE_FORWARD_M + TABLE_RADIUS_M),
            heightMeters=SCALE_TEXT_HEIGHT_M)
        self._chromeProps.append(self._scaleTextActor)

        # Static binding hints near the table.
        hint = self._textActor(
            position=(0.0, TABLE_HEIGHT_M + 0.14, TABLE_FORWARD_M + TABLE_RADIUS_M),
            heightMeters=SCALE_TEXT_HEIGHT_M * 0.6, color=(0.7, 0.75, 0.8))
        hint.SetInput(_("L-stick: rotate   B/Y: scale   triggers: scene view"))
        self._chromeProps.append(hint)

        for prop in self._chromeProps:
            prop.SetUserMatrix(self._anchorMatrix)  # shared matrix, updated in-place by _syncAnchor
            renderer.AddViewProp(prop)

        self._updateScaleReadout()

    def _teardownChrome(self) -> None:
        renderer = self._vrRenderer()
        if renderer is not None:
            for prop in self._chromeProps:
                renderer.RemoveViewProp(prop)
        self._chromeProps = []
        self._scaleTextActor = None

    @staticmethod
    def _discActor(center, radius, height, color):
        """A flat cylinder (axis = Y) used for floor/table/column."""
        source = vtk.vtkCylinderSource()
        source.SetRadius(radius)
        source.SetHeight(height)
        source.SetCenter(center[0], center[1], center[2])
        source.SetResolution(64)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetAmbient(0.3)
        actor.GetProperty().SetDiffuse(0.7)
        actor.PickableOff()
        return actor

    @staticmethod
    def _roomActor():
        """A large box seen from the inside (front faces culled)."""
        source = vtk.vtkCubeSource()
        source.SetXLength(ROOM_SIZE_M[0])
        source.SetYLength(ROOM_SIZE_M[1])
        source.SetZLength(ROOM_SIZE_M[2])
        source.SetCenter(0.0, ROOM_CENTER_Y_M, 0.0)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.12, 0.13, 0.16)
        actor.GetProperty().FrontfaceCullingOn()   # see the inside of the room
        actor.GetProperty().BackfaceCullingOff()
        actor.GetProperty().SetAmbient(0.4)
        actor.PickableOff()
        return actor

    @staticmethod
    def _textActor(position, heightMeters, color=(0.9, 0.95, 1.0)):
        """A vtkTextActor3D authored in physical meters, facing +Z (toward the user)."""
        actor = vtk.vtkTextActor3D()
        actor.SetInput(" ")
        tprop = actor.GetTextProperty()
        tprop.SetFontSize(48)
        tprop.SetColor(*color)
        tprop.SetJustificationToCentered()
        tprop.SetVerticalJustificationToBottom()
        # vtkTextActor3D renders text at font-size units; scale it down to the requested
        # physical height (approx: fontSize px -> heightMeters).
        scale = heightMeters / 48.0
        actor.SetScale(scale, scale, scale)
        actor.SetPosition(position[0], position[1], position[2])
        actor.PickableOff()
        return actor

    def _updateScaleReadout(self) -> None:
        if self._scaleTextActor is not None:
            self._scaleTextActor.SetInput(
                _("Scale: {scale:.2f}x").format(scale=self.getMagnification()))

    # ------------------------------------------------------------------ anchor sync

    def _syncAnchor(self, caller=None, event=None) -> None:
        """Keep chrome fixed in physical space and data centered over the table as the
        physical-to-world matrix changes (magnification or user recenter)."""
        widget = self._vrViewWidget()
        if widget is None:
            return
        physicalToWorld = vtk.vtkMatrix4x4()
        widget.renderWindow().GetPhysicalToWorldMatrix(physicalToWorld)

        # Chrome: UserMatrix = PhysicalToWorld (its 1/magnification scale cancels the
        # camera magnification -> the room stays a fixed real-world size and place).
        self._anchorMatrix.DeepCopy(physicalToWorld)
        for prop in self._chromeProps:
            prop.Modified()

        # World "up" = physical +Y mapped into world (as a direction, w=0), normalized.
        # We spin the turntable about this and rest the data on the table along it, so the
        # data neither wobbles nor sinks regardless of the reference view's orientation.
        up = list(physicalToWorld.MultiplyPoint([0.0, 1.0, 0.0, 0.0]))[:3]
        norm = vtk.vtkMath.Norm(up)
        self._turntableAxis = [c / norm for c in up] if norm > 1e-9 else list(TURNTABLE_AXIS)

        # Table-top surface point in world, and the target the data center maps to: lifted
        # up by half the data's extent along "up" so the data's bottom rests on the surface.
        self._tableCenterWorld = list(
            physicalToWorld.MultiplyPoint(
                [0.0, TABLE_HEIGHT_M + TABLE_TOP_THICKNESS_M, TABLE_FORWARD_M, 1.0]))[:3]
        halfHeight = 0.5 * self._extentAlongAxis(self._dataBounds, self._turntableAxis)
        self._tableTargetWorld = [self._tableCenterWorld[i] + self._turntableAxis[i] * halfHeight
                                  for i in range(3)]
        self._updateTurntableTransform()

    # ------------------------------------------------------------------ turntable

    def _buildTurntable(self) -> None:
        self._turntableAngleRad = 0.0
        self._turntableNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLTransformNode", slicer.mrmlScene.GenerateUniqueName("VR Turntable"))
        self._turntableNode.SetHideFromEditors(True)
        self._collectAndAttach()

    def _teardownTurntable(self) -> None:
        self._detachAll()
        if self._turntableNode is not None and slicer.mrmlScene.IsNodePresent(self._turntableNode):
            slicer.mrmlScene.RemoveNode(self._turntableNode)
        self._turntableNode = None
        self._turntableAngleRad = 0.0

    def _collectAndAttach(self) -> None:
        """(Re)collect visible data + slices and attach them to the turntable, centered
        on the table. Used on enter and after each scene-view restore."""
        self._detachAll()
        if self._turntableNode is None:
            return

        dataNodes = self._collectVisibleDataNodes()
        self._dataBounds = self._combinedRASBounds(dataNodes)
        self._dataCenter = self._combinedRASCenter(dataNodes)
        self._attachDataNodes(dataNodes)

        if self.getParameterNode().includeSlices:
            self._attachSlices()

        self._updateTurntableTransform()

    @staticmethod
    def _collectVisibleDataNodes():
        """Displayable data nodes the user would consider 'on the table': visible models,
        segmentations, markups, and volumes shown via volume rendering."""
        nodes = []
        scene = slicer.mrmlScene
        for className in ("vtkMRMLModelNode", "vtkMRMLSegmentationNode", "vtkMRMLMarkupsNode"):
            collection = scene.GetNodesByClass(className)
            collection.UnRegister(None)
            for i in range(collection.GetNumberOfItems()):
                node = collection.GetItemAsObject(i)
                if node.GetHideFromEditors():
                    continue
                displayNode = node.GetDisplayNode()
                if displayNode is None or not displayNode.GetVisibility():
                    continue
                nodes.append(node)

        # Volumes are "on the table" only if they have a visible volume-rendering display.
        volumes = scene.GetNodesByClass("vtkMRMLVolumeNode")
        volumes.UnRegister(None)
        for i in range(volumes.GetNumberOfItems()):
            volume = volumes.GetItemAsObject(i)
            if volume.GetHideFromEditors():
                continue
            for j in range(volume.GetNumberOfDisplayNodes()):
                displayNode = volume.GetNthDisplayNode(j)
                if displayNode and displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode") and displayNode.GetVisibility():
                    nodes.append(volume)
                    break
        return nodes

    @staticmethod
    def _combinedRASBounds(nodes):
        """Union of the RAS bounding boxes of the displayable nodes. Empty -> zeros."""
        combined = None
        for node in nodes:
            if not node.IsA("vtkMRMLDisplayableNode"):
                continue
            bounds = [0.0] * 6
            node.GetRASBounds(bounds)
            if bounds[0] > bounds[1]:  # invalid/empty
                continue
            if combined is None:
                combined = list(bounds)
            else:
                for a in range(3):
                    combined[2 * a] = min(combined[2 * a], bounds[2 * a])
                    combined[2 * a + 1] = max(combined[2 * a + 1], bounds[2 * a + 1])
        return combined if combined is not None else [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    @staticmethod
    def _combinedRASCenter(nodes):
        b = VRViewerLogic._combinedRASBounds(nodes)
        return [(b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0, (b[4] + b[5]) / 2.0]

    def _attachDataNodes(self, nodes) -> None:
        """Insert the turntable above the existing transform chains of the collected nodes,
        recording originals for exact restore. Nodes with no transform are parented directly;
        nodes with a transform have the top of their chain reparented under the turntable."""
        turntableId = self._turntableNode.GetID()
        topTransforms = set()
        for node in nodes:
            if not node.IsA("vtkMRMLTransformableNode"):
                continue
            parent = node.GetParentTransformNode()
            if parent is None:
                if node.GetID() not in self._savedParents:
                    self._savedParents[node.GetID()] = None
                node.SetAndObserveTransformNodeID(turntableId)
            else:
                top = parent
                while top.GetParentTransformNode() is not None:
                    top = top.GetParentTransformNode()
                if top.GetID() != turntableId:
                    topTransforms.add(top)

        for top in topTransforms:
            if top.GetID() not in self._savedParents:
                self._savedParents[top.GetID()] = None  # top-of-chain had no parent
            top.SetAndObserveTransformNodeID(turntableId)

    def _attachSlices(self) -> None:
        """Slice nodes are not transformable, so we rotate them by composing the turntable
        matrix onto their SliceToRAS directly (recorded for restore)."""
        for sliceId in SLICE_NODE_IDS:
            sliceNode = slicer.mrmlScene.GetNodeByID(sliceId)
            if sliceNode is None:
                continue
            original = vtk.vtkMatrix4x4()
            original.DeepCopy(sliceNode.GetSliceToRAS())
            self._savedSliceToRAS[sliceId] = original
            self._savedSliceVisible[sliceId] = sliceNode.GetSliceVisible()

    def _detachAll(self) -> None:
        # Restore data-node parents.
        for nodeId, originalParentId in self._savedParents.items():
            node = slicer.mrmlScene.GetNodeByID(nodeId)
            if node is not None and node.IsA("vtkMRMLTransformableNode"):
                node.SetAndObserveTransformNodeID(originalParentId)
        self._savedParents = {}

        # Restore slice orientations/visibility.
        for sliceId, original in self._savedSliceToRAS.items():
            sliceNode = slicer.mrmlScene.GetNodeByID(sliceId)
            if sliceNode is not None:
                sliceNode.GetSliceToRAS().DeepCopy(original)
                sliceNode.UpdateMatrices()
        for sliceId, visible in self._savedSliceVisible.items():
            sliceNode = slicer.mrmlScene.GetNodeByID(sliceId)
            if sliceNode is not None:
                sliceNode.SetSliceVisible(visible)
        self._savedSliceToRAS = {}
        self._savedSliceVisible = {}

    @staticmethod
    def buildTurntableMatrix(angleRad, axis, anchor, target):
        """Pure helper (headless-testable): map `anchor` -> `target` while rotating about
        `axis` through that point (world/RAS coordinates)."""
        transform = vtk.vtkTransform()
        transform.PostMultiply()
        transform.Translate(-anchor[0], -anchor[1], -anchor[2])
        transform.RotateWXYZ(vtk.vtkMath.DegreesFromRadians(angleRad), axis[0], axis[1], axis[2])
        transform.Translate(target[0], target[1], target[2])
        matrix = vtk.vtkMatrix4x4()
        transform.GetMatrix(matrix)
        return matrix

    @staticmethod
    def _extentAlongAxis(bounds, axis):
        """Extent (max-min projection) of an RAS AABB onto a unit axis. 0 for empty bounds."""
        if bounds[0] > bounds[1]:
            return 0.0
        projections = []
        for xi in (bounds[0], bounds[1]):
            for yi in (bounds[2], bounds[3]):
                for zi in (bounds[4], bounds[5]):
                    projections.append(xi * axis[0] + yi * axis[1] + zi * axis[2])
        return max(projections) - min(projections)

    def _updateTurntableTransform(self) -> None:
        if self._turntableNode is None:
            return
        matrix = self.buildTurntableMatrix(
            self._turntableAngleRad, self._turntableAxis, self._dataCenter, self._tableTargetWorld)
        self._turntableNode.SetMatrixTransformToParent(matrix)

        # Slices are composed directly (they cannot be parented to a transform node).
        for sliceId, original in self._savedSliceToRAS.items():
            sliceNode = slicer.mrmlScene.GetNodeByID(sliceId)
            if sliceNode is None:
                continue
            composed = vtk.vtkMatrix4x4()
            vtk.vtkMatrix4x4.Multiply4x4(matrix, original, composed)
            sliceNode.GetSliceToRAS().DeepCopy(composed)
            sliceNode.UpdateMatrices()

    def rotateTurntable(self, deltaRad) -> None:
        self._turntableAngleRad += deltaRad
        self._updateTurntableTransform()

    def _onRotationTimer(self) -> None:
        if abs(self._leftStickX) < THUMBSTICK_DEADZONE:
            return
        speedRad = vtk.vtkMath.RadiansFromDegrees(self.getParameterNode().rotationSpeedDegPerSec)
        dt = ROTATION_TIMER_INTERVAL_MS / 1000.0
        self.rotateTurntable(speedRad * self._leftStickX * dt)

    # ------------------------------------------------------------------ magnification

    def getMagnification(self) -> float:
        viewNode = self._vrViewNode()
        return viewNode.GetMagnification() if viewNode else DEFAULT_MAGNIFICATION

    def setMagnification(self, value) -> None:
        value = max(MIN_MAGNIFICATION, min(MAX_MAGNIFICATION, value))
        viewNode = self._vrViewNode()
        if viewNode:
            viewNode.SetMagnification(value)
        self._updateScaleReadout()

    @staticmethod
    def steppedMagnification(current, direction, stepFactor):
        """Pure helper (headless-testable): multiplicative step, clamped."""
        value = current * stepFactor if direction > 0 else current / stepFactor
        return max(MIN_MAGNIFICATION, min(MAX_MAGNIFICATION, value))

    def stepMagnification(self, direction) -> None:
        stepFactor = self.getParameterNode().magnificationStep
        self.setMagnification(self.steppedMagnification(self.getMagnification(), direction, stepFactor))

    def resetMagnification(self) -> None:
        self.setMagnification(DEFAULT_MAGNIFICATION)

    # ------------------------------------------------------------------ slices

    def toggleSlices(self) -> None:
        """Toggle 3D visibility of all slice planes together."""
        anyVisible = False
        sliceNodes = []
        for sliceId in SLICE_NODE_IDS:
            sliceNode = slicer.mrmlScene.GetNodeByID(sliceId)
            if sliceNode is None:
                continue
            sliceNodes.append(sliceNode)
            if sliceNode.GetSliceVisible():
                anyVisible = True
        newVisible = not anyVisible
        for sliceNode in sliceNodes:
            sliceNode.SetSliceVisible(newVisible)
        # A newly shown slice must pick up the current turntable orientation.
        if newVisible and self.getParameterNode().includeSlices:
            for sliceNode in sliceNodes:
                if sliceNode.GetID() not in self._savedSliceToRAS:
                    original = vtk.vtkMatrix4x4()
                    original.DeepCopy(sliceNode.GetSliceToRAS())
                    self._savedSliceToRAS[sliceNode.GetID()] = original
                    self._savedSliceVisible.setdefault(sliceNode.GetID(), 0)
            self._updateTurntableTransform()

    # ------------------------------------------------------------------ scene views

    @staticmethod
    def _sceneViewsLogic():
        # The modern SceneViews module stores scene views inside a sequence browser, not as
        # top-level vtkMRMLSceneViewNode nodes, so we go through its logic to enumerate/restore.
        try:
            return slicer.modules.sceneviews.logic()
        except Exception:  # noqa: BLE001
            return None

    def sceneViewCount(self) -> int:
        logic = self._sceneViewsLogic()
        return logic.GetNumberOfSceneViews() if logic else 0

    def cycleSceneView(self, direction) -> None:
        """Restore the next/previous scene view, then re-attach data to the turntable
        (restore reverts MRML, dropping our transform/parenting)."""
        logic = self._sceneViewsLogic()
        if logic is None:
            return
        count = logic.GetNumberOfSceneViews()
        if count <= 0:
            return
        self._sceneViewIndex = (self._sceneViewIndex + (1 if direction > 0 else -1)) % count
        logic.RestoreSceneView(self._sceneViewIndex)

        # The turntable node may have been removed by RestoreScene; recreate if needed.
        if self._turntableNode is None or not slicer.mrmlScene.IsNodePresent(self._turntableNode):
            self._turntableNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLTransformNode", slicer.mrmlScene.GenerateUniqueName("VR Turntable"))
            self._turntableNode.SetHideFromEditors(True)
        self._savedParents = {}
        self._savedSliceToRAS = {}
        self._savedSliceVisible = {}
        self._collectAndAttach()

    # ------------------------------------------------------------------ controller observers

    def _installObservers(self, widget) -> None:
        try:
            import vtkSlicerVirtualRealityModuleMRMLDisplayableManagerPython as vrDM
        except ImportError as e:
            raise RuntimeError(_("Could not import VR interactor style bindings.")) from e

        style = vrDM.vtkVirtualRealityViewOpenXRInteractorStyle
        interactor = widget.interactor()
        self._interactor = interactor
        highPriority = 100.0

        def add(eventId, callback):
            tag = interactor.AddObserver(eventId, callback, highPriority)
            self._observerTags.append(tag)

        add(style.LeftThumbstickEvent, self._onLeftThumbstick)
        add(style.RightButton2ClickEvent, self._onScaleUp)     # B
        add(style.LeftButton2ClickEvent, self._onScaleDown)    # Y
        add(style.RightTriggerClickEvent, self._onNextSceneView)
        add(style.LeftTriggerClickEvent, self._onPrevSceneView)
        add(style.RightThumbstickClickEvent, self._onToggleSlices)
        add(style.LeftThumbstickClickEvent, self._onResetScale)

        self._physicalToWorldConnection = widget.connect(
            "physicalToWorldMatrixModified()", self._syncAnchor)

    def _removeObservers(self) -> None:
        if self._interactor is not None:
            for tag in self._observerTags:
                self._interactor.RemoveObserver(tag)
        self._observerTags = []
        self._interactor = None

        widget = self._vrViewWidget()
        if widget is not None and self._physicalToWorldConnection is not None:
            try:
                widget.disconnect("physicalToWorldMatrixModified()", self._syncAnchor)
            except Exception:  # noqa: BLE001
                pass
        self._physicalToWorldConnection = None

    @staticmethod
    def _isPress(calldata) -> bool:
        try:
            return calldata.GetAction() == vtk.vtkEventDataAction.Press
        except Exception:  # noqa: BLE001
            return True

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onLeftThumbstick(self, caller, event, calldata):
        try:
            pos = calldata.GetTrackPadPosition()
            self._leftStickX = float(pos[0])
        except Exception:  # noqa: BLE001
            self._leftStickX = 0.0

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onScaleUp(self, caller, event, calldata):
        if self._isPress(calldata):
            self.stepMagnification(+1)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onScaleDown(self, caller, event, calldata):
        if self._isPress(calldata):
            self.stepMagnification(-1)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onResetScale(self, caller, event, calldata):
        if self._isPress(calldata):
            self.resetMagnification()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onNextSceneView(self, caller, event, calldata):
        if self._isPress(calldata):
            self.cycleSceneView(+1)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onPrevSceneView(self, caller, event, calldata):
        if self._isPress(calldata):
            self.cycleSceneView(-1)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onToggleSlices(self, caller, event, calldata):
        if self._isPress(calldata):
            self.toggleSlices()


#
# VRViewerTest
#


class VRViewerTest(ScriptedLoadableModuleTest):
    """Runtime self-test. The headless logic assertions live in
    Testing/Python/VRViewerLogicTest.py; this mirrors the key ones so they can be run
    from the Reload & Test panel without a headset."""

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_VRViewerLogic1()

    def test_VRViewerLogic1(self):
        self.delayDisplay("Starting VR Viewer logic test")

        logic = VRViewerLogic()

        # Magnification stepping is pure and clamped.
        self.assertAlmostEqual(logic.steppedMagnification(1.0, +1, 1.25), 1.25)
        self.assertAlmostEqual(logic.steppedMagnification(1.0, -1, 1.25), 0.8)
        self.assertEqual(logic.steppedMagnification(MAX_MAGNIFICATION, +1, 2.0), MAX_MAGNIFICATION)
        self.assertEqual(logic.steppedMagnification(MIN_MAGNIFICATION, -1, 2.0), MIN_MAGNIFICATION)

        # Turntable matrix maps the anchor onto the target, at any rotation.
        axis = [0.0, 0.0, 1.0]
        anchor = [10.0, 20.0, 30.0]
        target = [100.0, 200.0, 300.0]
        for angleDeg in (0.0, 90.0):
            matrix = logic.buildTurntableMatrix(vtk.vtkMath.RadiansFromDegrees(angleDeg), axis, anchor, target)
            mapped = matrix.MultiplyPoint([anchor[0], anchor[1], anchor[2], 1.0])
            for a in range(3):
                self.assertAlmostEqual(mapped[a], target[a], places=4)

        self.delayDisplay("Test passed")
