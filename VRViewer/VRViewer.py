import logging
import math
import time
from typing import Annotated

import numpy as np
import vtk
from vtk.util import numpy_support
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
the user stands in a fixed room with a turntable in front of them. Scene data appears on the
turntable and is rotated with the left thumbstick; world scale and scene-view navigation are
driven by controller buttons. A grabbable arbitrary reformat plane lets the data be sliced from
any angle, with a floating screen showing the reformatted image live.

The viewer does not modify the user's loaded data: turntable placement, scale and rotation are
applied only to the VR view (via its PhysicalToWorldMatrix), so the desktop 3D and slice views
are left untouched. The Red/Green/Yellow slice planes are not shown.

Controller bindings (Oculus Touch):
- Left thumbstick left/right: rotate the turntable
- Either grip (hold): the reformat plane follows that controller's position/orientation for as
  long as the grip is held - release to leave it in place. A floating screen beside the plane
  shows the reformatted image live. Hidden until toggled on (see below).
- Right thumbstick click: show/hide the reformat plane and its floating screen
- B button: increase scale, Y button: decrease scale
- Right/Left trigger: next/previous scene view
- Left thumbstick click: recenter the data on the table (scale 1.0)
- Left menu button: toggle hands-free auto-spin
- Right A: aim the right controller at the anatomy (or the revealed reformat plane, for
  volume-only data) and press to place a measurement point; press again to complete the pair
  into a persisted distance measurement. Left X: undo the last point or measurement.
- Two-controller A+X gesture: freely move/scale/rotate (the room follows)
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
    magnificationStep - multiplicative factor applied to world scale per +/- button press.
    showRoom - if true, room walls are drawn (the floor and table are always drawn).
    fitToTable - if true, auto-scale each framing so the data spans the table. Off by default:
        with it on, different scene views (with different data extents) land at very different
        scales; off, every framing uses the same real-world scale (1.0 = normal VR size).
    overheadLight - if true, the table is lit by a light rig anchored above it (with softer
        fill lights derived from it) instead of the VR view's default lighting.
    """

    rotationSpeedDegPerSec: Annotated[float, WithinRange(1.0, 360.0)] = 180.0
    magnificationStep: Annotated[float, WithinRange(1.01, 4.0)] = 1.25
    showRoom: bool = True
    fitToTable: bool = False
    overheadLight: bool = True


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
        if self.logic:
            self.logic.exitViewerMode()
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()
        self.updateGUIFromLogic()

    def exit(self) -> None:
        self.setParameterNode(None)

    def onSceneStartClose(self, caller, event) -> None:
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

# Raised collar/apron band around the table's whole perimeter, sitting directly under the
# tabletop cap (in the space otherwise occupied only by the thin column) - gives the table a
# real, constructed pedestal-table silhouette (post -> collar -> cap) instead of a plain disc,
# and gives the monitor housing (see MONITOR_* below) a wide, sturdy-looking base to be mounted
# into. Inset from TABLE_RADIUS_M so the cap overhangs the collar as a lip.
RIM_BAND_RADIUS_M = TABLE_RADIUS_M * 0.90
RIM_BAND_HEIGHT_M = 0.22          # must clear the monitor housing's footprint, see MONITOR_* below

# Bright "medical sci-fi" palette: cool steel room/floor with a cyan holo-tech accent used for
# every glowing trim/rim/readout, so the room reads as one coherent kit of parts rather than a
# grab-bag of colors.
ACCENT_COLOR = (0.25, 0.85, 1.0)
ACCENT_COLOR_DIM = (0.10, 0.35, 0.42)
FLOOR_BASE_COLOR = (0.62, 0.68, 0.75)
WALL_BASE_COLOR = (0.80, 0.85, 0.90)
COLUMN_COLOR = (0.30, 0.34, 0.40)
TABLE_RING_COLOR = (0.40, 0.46, 0.54)
TABLE_SCREEN_BG_COLOR = (0.03, 0.07, 0.11)
RIM_BAND_COLOR = (0.34, 0.38, 0.44)   # between COLUMN_COLOR and TABLE_RING_COLOR

# Table "screen" (the circular holo-readout inset in the tabletop), as a fraction of
# TABLE_RADIUS_M so it scales if the table size is tuned. Recessed below the surrounding cap's
# top surface (see _annulusActor) rather than sitting proud on it, so it reads as a screen sunk
# into the table rather than a decal stuck on top - must leave enough floor thickness below it
# (TABLE_TOP_THICKNESS_M - RECESS_DEPTH_M) to still read as solid.
TABLE_SCREEN_RADIUS_FRAC = 0.85
TABLE_SCREEN_RECESS_DEPTH_M = 0.015
# Emissive glow for the screen's texture (see _tableScreenTexture) - lets the circuit/ring
# pattern read as self-lit "holo" tech, independent of the overhead light rig, using VTK's PBR
# emissive-texture pipeline rather than the plain ambient-only trick used for the ring/rim glows.
TABLE_SCREEN_EMISSIVE_FACTOR = (1.0, 1.0, 1.0)

# Seam-line glow ring marking where the cap overhangs the collar (see RIM_BAND_RADIUS_M), as
# fractions of RIM_BAND_RADIUS_M rather than TABLE_RADIUS_M since it now trims the collar, not
# the cap's own edge.
COLLAR_SEAM_RING_INNER_FRAC = 0.97
COLLAR_SEAM_RING_OUTER_FRAC = 1.01

# Floor "landing pad" glow ring drawn around the table's footprint.
FLOOR_RING_INNER_M = TABLE_RADIUS_M + 0.25
FLOOR_RING_OUTER_M = TABLE_RADIUS_M + 0.32

# Back-wall signage: the control-scheme text lives on the wall behind the table (rather than
# crowding the table edge closest to the user), keeping the table itself uncluttered so the
# anatomy on it is easy to read accurately.
# The panel/text are held noticeably proud of the actual wall (tens of cm, not mm) - at the
# ~3m viewing distance out here, the same absolute gap that looks fine on the nearby table (see
# the mm-scale offsets above) resolves to far less usable z-buffer precision, so a small gap
# z-fights. The panel border is baked into its texture (see _signagePanelTexture) rather than
# a second coincident plane, for the same reason.
BACK_WALL_Z_M = -(ROOM_SIZE_M[2] / 2.0) + 0.05
BACK_WALL_PANEL_OFFSET_M = 0.20   # panel in front of the wall
BACK_WALL_TEXT_OFFSET_M = 0.24    # text in front of the wall (i.e. ~4cm proud of the panel)
HELP_PANEL_CENTER_Y_M = ROOM_CENTER_Y_M + 0.35
HELP_PANEL_WIDTH_M = 2.4
HELP_TITLE_HEIGHT_M = 0.14
HELP_BODY_HEIGHT_M = 0.085
HELP_BODY_LINE_COUNT = 8          # keep in sync with the body text in _backWallSignageActors
HELP_TITLE_BODY_GAP_M = 0.05      # deliberate breathing room between title and body
HELP_PANEL_TEXT_MARGIN_M = 0.05   # from the usable (border-excluded) interior edge to the text
HELP_PANEL_BORDER_FRAC = 0.05     # must match _signagePanelTexture's default borderFrac

# HELP_PANEL_HEIGHT_M is derived, not hand-tuned: vtkTextActor3D's rendered height for N lines at
# heightMeters is always <= N * heightMeters (measured ~0.955x), so budgeting with the nominal
# heightMeters values here is already conservative. Deriving the panel height from that budget -
# instead of picking one by eye - keeps title+body guaranteed to fit inside the border (previously
# they didn't) if the body text or font sizes above are ever edited.
_HELP_BODY_BLOCK_HEIGHT_M = HELP_BODY_LINE_COUNT * HELP_BODY_HEIGHT_M
_HELP_CONTENT_HEIGHT_M = (2.0 * HELP_PANEL_TEXT_MARGIN_M + HELP_TITLE_HEIGHT_M
                           + HELP_TITLE_BODY_GAP_M + _HELP_BODY_BLOCK_HEIGHT_M)
HELP_PANEL_HEIGHT_M = _HELP_CONTENT_HEIGHT_M / (1.0 - 2.0 * HELP_PANEL_BORDER_FRAC)

# Info screen content: the live scale (line 1) and current scene view name (line 2), rendered
# on the monitor housing built into the table's collar (see MONITOR_* below). Text layout is
# unchanged from the module's original standing-sign design - only the housing/mounting geometry
# around it changed.
INFO_SCREEN_LINE_HEIGHT_M = 0.035    # the scale readout ("1.00x") - short, room to stay large
INFO_SCREEN_LINE_GAP_M = 0.015
INFO_SCREEN_TEXT_MARGIN_M = 0.02
INFO_SCREEN_BORDER_FRAC = 0.05    # must match _signagePanelTexture's default borderFrac
# The scene-view name gets its own (smaller) line height, distinct from the scale line above it:
# on the monitor's narrower MONITOR_SCREEN_WIDTH_M, the old shared size overflowed the screen's
# edges for long names. Truncation (see _fitNameToScreenWidth / INFO_SCREEN_NAME_MAX_WIDTH_M
# below, once MONITOR_SCREEN_WIDTH_M is defined) is based on each name's actual rendered width,
# not a fixed character count - a fixed count either truncated ordinary short names that had
# plenty of room left, or would still overflow on unusually wide ones.
INFO_SCREEN_NAME_LINE_HEIGHT_M = 0.0105

_INFO_SCREEN_CONTENT_HEIGHT_M = (2.0 * INFO_SCREEN_TEXT_MARGIN_M + INFO_SCREEN_LINE_HEIGHT_M
                                  + INFO_SCREEN_NAME_LINE_HEIGHT_M + INFO_SCREEN_LINE_GAP_M)
INFO_SCREEN_HEIGHT_M = _INFO_SCREEN_CONTENT_HEIGHT_M / (1.0 - 2.0 * INFO_SCREEN_BORDER_FRAC)

# Monitor housing: a physically-modeled screen module (housing shell + textured screen face +
# live text), mounted into the table's collar near the edge closest to the user, reclined so
# it's legible without standing tall enough to occlude anatomy sitting further back on the
# table. See _buildMonitorAssembly.
MONITOR_SCREEN_WIDTH_M = 0.24        # narrower than the old standing sign - reads as one
                                       # embedded module now, not a sign
# The scene-view name is truncated to whatever actually fits this width (see
# _fitNameToScreenWidth), measured via the live text actor's own rendered bounds rather than a
# fixed character count - matches the screen's interior width, i.e. inside both the texture's
# baked border and the same text margin used for the vertical layout above.
INFO_SCREEN_NAME_MAX_WIDTH_M = (MONITOR_SCREEN_WIDTH_M * (1.0 - 2.0 * INFO_SCREEN_BORDER_FRAC)
                                  - 2.0 * INFO_SCREEN_TEXT_MARGIN_M)
MONITOR_BEZEL_MARGIN_M = 0.025       # housing overhang beyond the screen face, per side
MONITOR_HOUSING_DEPTH_M = 0.05
MONITOR_SCREEN_PROUD_M = 0.006       # screen face proud of the housing shell's front face
MONITOR_TEXT_PROUD_M = 0.01          # text proud of the screen face
MONITOR_MOUNT_PROUD_M = 0.015        # housing pulled proud of the collar's tangent radius
# RIM_BAND_HEIGHT_M must exceed the housing's bezel-inclusive footprint
# (INFO_SCREEN_HEIGHT_M + 2*MONITOR_BEZEL_MARGIN_M =~ 0.189m) so it fits inside the collar band
# with clearance top and bottom (checked, not eyeballed): 0.22m leaves ~1.5cm each side.
MONITOR_TILT_FROM_HORIZONTAL_DEG = 27.5   # midpoint of the agreed-on 25-30 degree recline
# The panel/text are authored in a vertical ("standing sign") local frame, same as the module's
# original design, then pivoted back to the shallow recline as one rigid group - see
# _buildMonitorAssembly for why a vtkAssembly pivot is used instead of repositioning each part.
MONITOR_HINGE_ROTATION_DEG = 90.0 - MONITOR_TILT_FROM_HORIZONTAL_DEG

# R/L/A/P/S/I orientation labels are authored directly in RAS/world (not anchored to physical
# space like the rest of the chrome - see _updateOrientationLabels), so they turn with the
# anatomy as the turntable spins and always show which anatomical direction currently faces the
# user. vtkBillboardTextActor3D keeps a constant on-screen size and always faces the camera.
ORIENTATION_LABEL_AXES = {
    "R": (1.0, 0.0, 0.0),
    "L": (-1.0, 0.0, 0.0),
    "A": (0.0, 1.0, 0.0),
    "P": (0.0, -1.0, 0.0),
    "S": (0.0, 0.0, 1.0),
    "I": (0.0, 0.0, -1.0),
}
ORIENTATION_LABEL_MARGIN_MM = 40.0
ORIENTATION_LABEL_DEFAULT_RADIUS_MM = 150.0
ORIENTATION_LABEL_FONT_SIZE = 22

# Extra clearance between the anatomy's bottom and the table surface (see computePhysicalToWorld),
# so the data floats just above the table instead of sitting flush against it. Kept comfortably
# larger than ORIENTATION_LABEL_MARGIN_MM so the I label (which sits that margin below the data's
# bottom) still clears the table surface too, rather than poking into it.
TABLE_LIFT_BUFFER_MM = 60.0

# The physical point the data center is placed at (table top), and the physical "up" direction
# (true gravity) - the room chrome (floor/table/walls) is authored directly in physical meters
# along this axis and is therefore always level, however the world is currently oriented.
TABLE_PHYSICAL = (0.0, TABLE_HEIGHT_M + TABLE_TOP_THICKNESS_M, TABLE_FORWARD_M)
PHYSICAL_UP = (0.0, 1.0, 0.0)

# World "up" (RAS Superior) that _alignedBaseMatrix calibrates the reference matrix (M0) to at
# entry, so the data starts out standing upright on the table. _worldUp() re-derives the actual
# current world-space up from whichever matrix it's given, falling back to this constant only in
# the degenerate case - see _worldUp for why a live re-derivation (rather than trusting this
# constant everywhere) matters once the built-in free-move/rotate/scale gesture is used.
WORLD_UP_RAS = (0.0, 0.0, 1.0)

# The physical direction from the table back toward the user - the opposite of TABLE_FORWARD_M's
# -Z ("in front of the user"). Combined with ANTERIOR_RAS by _frontFacingYawRad so a reset faces
# the anatomy's Anterior side toward the user instead of whatever yaw the captured reference view
# (M0) happened to have.
PHYSICAL_TOWARD_USER = (0.0, 0.0, 1.0)

# MRML RAS convention: R=+X, A=+Y, S=+Z.
ANTERIOR_RAS = (0.0, 1.0, 0.0)

# Overhead light rig (authored in physical meters, anchored to the room like the chrome).
# The key light hangs near the ceiling above the table, mostly illuminating the top of the
# data; on its own a light straight down grazes vertical/side surfaces at a shallow, nearly
# azimuth-independent angle, leaving a large dim band around the sides no matter how the data
# is rotated on the turntable. The fill lights sit lower (near chest height) and spread evenly
# around the table so every side gets real coverage from at least one of them.
OVERHEAD_LIGHT_HEIGHT_M = ROOM_SIZE_M[1] - 0.2
OVERHEAD_LIGHT_COLOR = (1.0, 0.97, 0.92)  # warm white
OVERHEAD_LIGHT_INTENSITY = 0.9
FILL_LIGHT_HEIGHT_M = TABLE_HEIGHT_M + 0.5
FILL_LIGHT_RADIUS_M = 1.3                  # horizontal distance from the table center
FILL_LIGHT_ANGLES_DEG = (60.0, 180.0, 300.0)  # evenly spaced (120 degrees apart) around the table
FILL_LIGHT_INTENSITY_FACTOR = 0.6  # fraction of the key light's intensity, applied to each fill

# Ceiling light panels: a purely visual fixture (baked emissive texture, casts no actual light
# of its own) mounted just below the room's ceiling so the overhead rig above has a visible
# source, rather than the room appearing lit from nowhere. Only relevant when showRoom is set,
# since without walls there's no ceiling surface for it to read as being mounted into.
CEILING_LIGHT_OFFSET_M = 0.01   # just inside the room cube's inner ceiling surface, avoids z-fighting
CEILING_PANEL_BG_COLOR = COLUMN_COLOR
CEILING_LIGHT_EMISSIVE_FACTOR = (1.0, 1.0, 1.0)

MIN_MAGNIFICATION = 0.01
MAX_MAGNIFICATION = 100.0
DEFAULT_MAGNIFICATION = 1.0
# PhysicalToWorld column length (world mm per physical m) at magnification 1.0 (real-world size).
# SlicerVR convention: magnification = 1000 / physicalScale.
UNIT_MAGNIFICATION_SCALE = 1000.0

THUMBSTICK_DEADZONE = 0.15
INPUT_TIMER_INTERVAL_MS = 33  # ~30 Hz continuous-input update (turntable)
AUTO_SPIN_DEG_PER_SEC = 30.0    # hands-free presentation rotation speed

SLICE_NODE_IDS = ["vtkMRMLSliceNodeRed", "vtkMRMLSliceNodeGreen", "vtkMRMLSliceNodeYellow"]

# Arbitrary reformat slice: a plain model-node plane that follows a controller's pose for as
# long as its grip is held (_trackReformatPlaneToController), driving a dedicated, non-layout
# slice node's SliceToRAS. The reformatted image is shown on a floating screen that rides
# alongside the plane (see _updateReformatFromPlane), rather than coincident with it, so the
# translucent handle and the crisp image never occupy the same surface.
REFORMAT_SLICE_LAYOUT_NAME = "VRReformat"
REFORMAT_PLANE_NODE_NAME = "VR Reformat Plane"
REFORMAT_HANDLE_OPACITY = 0.15
REFORMAT_HANDLE_SIZE_FRAC = 0.6   # handle side length, as a fraction of the background volume's
                                   # RAS bounding-box diagonal
DEFAULT_REFORMAT_HANDLE_SIZE_MM = 150.0  # fallback if no volume is loaded yet
REFORMAT_MONITOR_GAP_FRAC = 0.12  # gap between the handle's edge and the screen's edge, as a
                                   # fraction of the handle's half-width

# In-VR measurement tool: point-to-point distance markers for a solo review session, each a real
# vtkMRMLMarkupsLineNode (see the "measurement tool" section for why). MEASURE_COLOR is
# deliberately a different hue from ACCENT_COLOR so measurements read as a distinct layer of
# content from the chrome/orientation labels; MEASURE_RETICLE_RADIUS_MM sizes the raw-VTK aiming
# reticle, the only part of this tool that isn't a MRML node.
MEASURE_COLOR = (1.0, 0.65, 0.15)              # warm amber - tune in-headset
MEASURE_FLASH_COLOR = (1.0, 0.25, 0.2)         # "nothing to act on" feedback - tune in-headset
MEASURE_RETICLE_RADIUS_MM = 4.0
MEASURE_FLASH_DURATION_S = 0.3
MEASURE_GESTURE_SUPPRESS_WINDOW_S = 0.25       # tune in-headset - see _isButton1PressSuppressed


class VRViewerLogic(ScriptedLoadableModuleLogic):
    """All VR Viewer behavior.

    The viewer is entirely non-destructive to the MRML scene: placement, scale and turntable
    rotation are applied ONLY to the VR view, by overriding its PhysicalToWorldMatrix. The
    desktop 3D and 2D views therefore never move. The math (computePhysicalToWorld and the
    geometry helpers) is pure and covered by the headless test; the chrome/observer paths
    require an active VR view.
    """

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self._parameterNode = None

        self.isActive = False

        # Runtime VR handles (only valid while active).
        self._interactor = None
        self._observerTags = []
        self._rightStickPosTag = None
        self._rightStickTouchTag = None
        self._physicalToWorldConnected = False

        # Chrome (raw VTK props, not MRML). Anchored to physical space via _anchorMatrix,
        # which is kept equal to the VR PhysicalToWorldMatrix we apply.
        self._chromeProps = []
        self._scaleTextActor = None
        self._sceneViewTextActor = None
        self._monitorAssembly = None
        self._anchorMatrix = vtk.vtkMatrix4x4()

        # Table screen (the holo-readout inset): anchored like the rest of the chrome, but also
        # carries its own extra spin - see _updateTableScreenOrientation - so its texture visibly
        # turns along with the turntable instead of staying screen-fixed like the rest of the
        # table.
        self._tableScreenActor = None
        self._turntableAngleRad = 0.0

        # R/L/A/P/S/I orientation labels. Unlike _chromeProps these are authored directly in
        # RAS/world space (no UserMatrix) so they turn with the anatomy - see
        # _updateOrientationLabels.
        self._orientationLabelActors = {}

        # Overhead light rig, anchored to physical space the same way as the chrome. When
        # active it replaces the VR view's default lights (captured/detached in
        # _defaultLights) so the table reads as lit from the room's overhead fixture.
        self._overheadLights = []
        self._defaultLights = []  # [light, ...] - detached from the renderer while active

        # VR framing state. The base matrix is captured on entry (the reference view Slicer
        # establishes) and everything is expressed relative to it, so the data keeps Slicer's
        # upright orientation.
        self._basePhysicalToWorld = None     # M0 captured at enter
        self._savedPhysicalToWorld = None     # restored on exit
        self._magnification = DEFAULT_MAGNIFICATION   # cached displayed scale (derived from the matrix)
        self._fitRelScale = 1.0                        # framing scale (1.0, or fit-to-table if enabled)
        self._dataBounds = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self._dataCenter = [0.0, 0.0, 0.0]

        # Saved VR navigation state, restored on exit.
        self._savedDolly = None
        self._savedGrab = None

        # Continuous inputs (applied on a timer): left-stick rotate.
        self._leftStickX = 0.0
        self._autoSpin = False
        self._inputTimer = qt.QTimer()
        self._inputTimer.setInterval(INPUT_TIMER_INTERVAL_MS)
        self._inputTimer.timeout.connect(self._onInputTimer)

        self._sceneViewIndex = -1

        # Arbitrary reformat slice (see REFORMAT_* constants above): a plain model node (the
        # visible handle) riding a transform node that tracks a controller's pose continuously
        # while its grip is held (see _onGripClick/_onLeftGripPose/_onRightGripPose), plus the
        # private slice node/composite node/logic that reformats the background volume from that
        # transform, and the floating screen actor - see _setupReformatSlice/
        # _teardownReformatSlice/_updateReformatFromPlane. Hidden by default (toggled with the
        # right thumbstick click - see toggleReformatVisible).
        self._reformatPlaneModelNode = None
        self._reformatTransformNode = None
        self._reformatSliceNode = None
        self._reformatCompositeNode = None
        self._reformatSliceLogic = None
        self._reformatMonitorActor = None
        self._reformatMonitorHalfSize = (0.0, 0.0)
        self._reformatGripHeldSide = None  # "Left", "Right", or None - which grip is currently held
        self._reformatVisible = False

        # In-VR point-to-point measurement tool (solo review aid). Unlike the rest of this
        # module's state, completed measurements are real vtkMRMLMarkupsLineNodes left in the
        # scene on exit (see _setupMeasurements/_teardownMeasurements docstrings for why) - only
        # the reticle is a raw VTK actor (pure aiming feedback, not user data).
        self._measurePicker = None                  # vtkCellPicker, created in _setupMeasurements
        self._measureReticleActor = None            # live "where am I aiming" indicator
        self._measureCurrentHit = None              # RAS xyz of the current aim's pick, or None
        self._measurementPendingLineNode = None     # vtkMRMLMarkupsLineNode with point 1 placed,
                                                     # point 2 tracking the aim, or None
        self._measurements = []                     # completed vtkMRMLMarkupsLineNodes (session list)
        self._measureFlashRemaining = 0.0           # seconds left in the "nothing to act on" flash
        self._button1Held = {"Left": False, "Right": False}
        self._button1PressTime = {"Left": None, "Right": None}

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

    def _renderWindow(self):
        """The VR render window, or None. The widget can exist while VR is inactive, in which
        case renderWindow() is None - callers must tolerate that."""
        widget = self._vrViewWidget()
        return widget.renderWindow() if widget is not None else None

    def _vrViewNode(self):
        vrLogic = self._vrLogic()
        return vrLogic.GetVirtualRealityViewNode() if vrLogic else None

    def _vrRenderer(self):
        renderWindow = self._renderWindow()
        if renderWindow is None:
            return None
        renderers = renderWindow.GetRenderers()
        if renderers.GetNumberOfItems() < 1:
            return None
        return renderers.GetItemAsObject(0)

    # ------------------------------------------------------------------ enter/exit

    def enterViewerMode(self) -> None:
        """Activate VR (if needed), build the room, and install controls. Never mutates the scene."""
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

        # Disable free navigation so the left stick / buttons are ours. This alone does NOT
        # actually stop the right thumbstick's default fly/dolly in practice - _installObservers
        # additionally observes and aborts the right-stick events at high priority, which is what
        # really suppresses it; kept here anyway for save/restore symmetry with _savedDolly and
        # in case it does matter for some other code path. Grab stays disabled too - the reformat
        # plane follows the controller pose while its grip is held
        # (_trackReformatPlaneToController), not dragged via the built-in pick-and-grab, so
        # nothing needs to be grabbable.
        self._savedDolly = widget.isDolly3DEnabled()
        self._savedGrab = widget.isGrabObjectsEnabled()
        widget.setDolly3DEnabled(False)
        widget.setGrabObjectsEnabled(False)
        try:
            widget.setGestureButtonToNone()
        except Exception:  # noqa: BLE001
            pass

        # Let the VR view establish its reference-view framing, then capture it as our base.
        slicer.app.processEvents()
        capturedPhysicalToWorld = vtk.vtkMatrix4x4()
        widget.renderWindow().GetPhysicalToWorldMatrix(capturedPhysicalToWorld)
        self._savedPhysicalToWorld = vtk.vtkMatrix4x4()
        self._savedPhysicalToWorld.DeepCopy(capturedPhysicalToWorld)
        # Our base (M0) is re-oriented so physical up maps exactly onto WORLD_UP_RAS - see
        # _alignedBaseMatrix. The saved matrix above is left untouched (the real reference-view
        # framing) so exiting restores the VR view exactly as SlicerVR set it up.
        self._basePhysicalToWorld = self._alignedBaseMatrix(capturedPhysicalToWorld)

        self._magnification = DEFAULT_MAGNIFICATION
        self._autoSpin = False
        self._leftStickX = 0.0
        self._reformatGripHeldSide = None
        self._reformatVisible = False

        self._buildChrome(renderer)
        self._buildLighting(renderer)
        self._resetFraming()

        # The Red/Green/Yellow slice planes are never shown in the VR viewer - only the
        # reformat plane is. Visibility is global (also affects the desktop 3D view).
        for sliceId in SLICE_NODE_IDS:
            sliceNode = slicer.mrmlScene.GetNodeByID(sliceId)
            if sliceNode is not None:
                sliceNode.SetSliceVisible(False)

        self._setupReformatSlice(renderer)
        self._setupMeasurements(renderer)

        self._installObservers(widget)
        self._inputTimer.start()

        self.isActive = True

    def exitViewerMode(self) -> None:
        """Tear everything down and restore the VR view. Safe when not active; idempotent."""
        if not self.isActive and not self._chromeProps and self._basePhysicalToWorld is None:
            return

        self._inputTimer.stop()
        self._leftStickX = 0.0

        self._removeObservers()

        widget = self._vrViewWidget()
        if widget is not None:
            renderWindow = self._renderWindow()
            if renderWindow is not None and self._savedPhysicalToWorld is not None:
                try:
                    renderWindow.SetPhysicalToWorldMatrix(self._savedPhysicalToWorld)
                except Exception:  # noqa: BLE001
                    pass
            if self._savedDolly is not None:
                widget.setDolly3DEnabled(self._savedDolly)
            if self._savedGrab is not None:
                widget.setGrabObjectsEnabled(self._savedGrab)
        self._savedDolly = None
        self._savedGrab = None

        self._teardownReformatSlice()
        self._teardownMeasurements()
        self._teardownChrome()
        self._teardownLighting()

        self._basePhysicalToWorld = None
        self._savedPhysicalToWorld = None
        self.isActive = False

    # ------------------------------------------------------------------ options

    def applyOptions(self) -> None:
        """Re-read options that can change live. Rotation speed / scale step are read on demand;
        overheadLight is applied immediately; showRoom takes effect on the next enter."""
        if self.isActive:
            self._applyLightingOption()

    # ------------------------------------------------------------------ chrome

    def _buildChrome(self, renderer) -> None:
        """Create the room/floor/table/text props (authored in physical meters) and add them
        to the VR renderer. They are anchored to physical space in _reanchorChrome()."""
        params = self.getParameterNode()
        tableCenterXZ = (0.0, TABLE_FORWARD_M)

        floor = self._discActor(
            center=(0.0, FLOOR_THICKNESS_M / 2.0, 0.0),
            radius=FLOOR_RADIUS_M, height=FLOOR_THICKNESS_M, color=FLOOR_BASE_COLOR)
        floorGrid = self._texturedDiscActor(
            center=(0.0, FLOOR_THICKNESS_M + 0.001, 0.0),
            radius=FLOOR_RADIUS_M, texture=self._arrayToTexture(self._floorPanelTexture()),
            ambient=0.55, diffuse=0.35)
        floorRing = self._glowRingActor(
            center=(tableCenterXZ[0], FLOOR_THICKNESS_M + 0.002, tableCenterXZ[1]),
            innerRadius=FLOOR_RING_INNER_M, outerRadius=FLOOR_RING_OUTER_M,
            color=ACCENT_COLOR, opacity=0.85)

        column = self._discActor(
            center=(0.0, TABLE_HEIGHT_M / 2.0, TABLE_FORWARD_M),
            radius=COLUMN_RADIUS_M, height=TABLE_HEIGHT_M, color=COLUMN_COLOR)
        columnBand = self._glowRingActor(
            center=(tableCenterXZ[0], TABLE_HEIGHT_M * 0.30, tableCenterXZ[1]),
            innerRadius=0.0, outerRadius=COLUMN_RADIUS_M * 1.02,
            color=ACCENT_COLOR_DIM, opacity=0.9)

        # Raised collar/apron band circling the table, sitting directly under the cap (in the
        # space otherwise occupied only by the thin column) - gives the table a real pedestal
        # silhouette (post -> collar -> cap) and a wide base for the monitor housing to mount
        # into. It's wider than the column, so the two simply overlap; no boolean needed.
        collar = self._discActor(
            center=(0.0, TABLE_HEIGHT_M - RIM_BAND_HEIGHT_M / 2.0, TABLE_FORWARD_M),
            radius=RIM_BAND_RADIUS_M, height=RIM_BAND_HEIGHT_M, color=RIM_BAND_COLOR)
        collar.GetProperty().SetMetallic(0.6)

        tableTopY = TABLE_HEIGHT_M + TABLE_TOP_THICKNESS_M
        tableScreenRadius = TABLE_RADIUS_M * TABLE_SCREEN_RADIUS_FRAC
        # The cap is now a ring with a real hole (not a solid disc) so the table screen sits in an
        # actual recessed pocket instead of proud on top of it - the well floor below fills the
        # hole except for the top TABLE_SCREEN_RECESS_DEPTH_M, which is the pocket's visible depth.
        tableTopRing = self._annulusActor(
            center=(0.0, tableTopY, TABLE_FORWARD_M),
            innerRadius=tableScreenRadius, outerRadius=TABLE_RADIUS_M,
            height=TABLE_TOP_THICKNESS_M, color=TABLE_RING_COLOR)
        tableTopRing.GetProperty().SetMetallic(1.0)
        tableTopRing.GetProperty().SetRoughness(0.2)  # mirror-like, since it's the cap's top
        tableTopRing.GetProperty().SetSpecular(0.5)
        tableTopRing.GetProperty().SetInterpolationToPBR()
        wellFloorHeight = TABLE_TOP_THICKNESS_M - TABLE_SCREEN_RECESS_DEPTH_M
        tableWellFloor = self._discActor(
            center=(0.0, TABLE_HEIGHT_M + wellFloorHeight / 2.0, TABLE_FORWARD_M),
            radius=tableScreenRadius, height=wellFloorHeight, color=TABLE_RING_COLOR)
        tableWellFloor.GetProperty().SetMetallic(1.0)
        tableWellFloor.GetProperty().SetRoughness(0.5)  # less mirror than the cap's ring
        tableWellFloor.GetProperty().SetInterpolationToPBR()
        tableScreenTexture = self._arrayToTexture(self._tableScreenTexture())
        self._tableScreenActor = self._texturedDiscActor(
            center=(tableCenterXZ[0], TABLE_HEIGHT_M + wellFloorHeight + 0.002, tableCenterXZ[1]),
            radius=tableScreenRadius, texture=tableScreenTexture, ambient=0.85, diffuse=0.15)
        # Emissive: the screen reads as self-lit "holo" tech, independent of the room's lighting,
        # rather than just a lit texture - only the PBR interpolation model supports emissive
        # textures (see vtkProperty.SetEmissiveTexture), so switch this actor onto that pipeline
        # and feed it the same baked texture as both the base color and the emissive source.
        screenProp = self._tableScreenActor.GetProperty()
        screenProp.SetInterpolationToPBR()
        tableScreenTexture.UseSRGBColorSpaceOn()  # required for albedo/emissive textures
        screenProp.SetBaseColorTexture(tableScreenTexture)
        screenProp.SetEmissiveTexture(tableScreenTexture)
        screenProp.SetEmissiveFactor(*TABLE_SCREEN_EMISSIVE_FACTOR)
        self._turntableAngleRad = 0.0
        self._updateTableScreenOrientation()
        # Seam-line trim on the cap's top surface, directly above where the narrower collar ends
        # below it (an "under-cap" accent marking the structural seam) - stays on TOP of the cap
        # like the original table-edge ring did, since a ring drawn at the actual seam height
        # would sit exactly inside/under the cap's own opaque bottom face and never be visible.
        collarSeamRing = self._glowRingActor(
            center=(tableCenterXZ[0], tableTopY + 0.003, tableCenterXZ[1]),
            innerRadius=RIM_BAND_RADIUS_M * COLLAR_SEAM_RING_INNER_FRAC,
            outerRadius=RIM_BAND_RADIUS_M * COLLAR_SEAM_RING_OUTER_FRAC,
            color=ACCENT_COLOR_DIM, opacity=0.75)

        self._chromeProps = [
            floor, floorGrid, floorRing,
            column, columnBand, collar,
            tableTopRing, tableWellFloor, self._tableScreenActor, collarSeamRing,
        ]

        if params.showRoom:
            self._chromeProps.append(self._roomActor(self._arrayToTexture(self._wallPanelTexture())))
            self._chromeProps.append(self._ceilingLightActor())
            self._chromeProps.extend(self._backWallSignageActors())

        self._monitorAssembly = self._buildMonitorAssembly()
        self._chromeProps.append(self._monitorAssembly)

        for prop in self._chromeProps:
            prop.SetUserMatrix(self._anchorMatrix)  # shared matrix, updated by _reanchorChrome
            renderer.AddViewProp(prop)

        self._buildOrientationLabels(renderer)

        self._updateScaleReadout()
        self._updateSceneViewReadout()

    @staticmethod
    def _signagePanelTexture(size=512, borderFrac=0.05):
        """Dark background with an accent border baked in - a single plane can then carry the
        whole panel look, instead of stacking a separate border plane nearly coincident with it
        (see BACK_WALL_PANEL_OFFSET_M for why that stacking z-fights at this distance)."""
        bg = np.array(TABLE_SCREEN_BG_COLOR) * 255.0
        border = np.array(ACCENT_COLOR) * 255.0
        img = np.tile(bg.astype(np.uint8), (size, size, 1))
        edge = int(size * borderFrac)
        img[:edge, :, :] = border.astype(np.uint8)
        img[-edge:, :, :] = border.astype(np.uint8)
        img[:, :edge, :] = border.astype(np.uint8)
        img[:, -edge:, :] = border.astype(np.uint8)
        return img

    @staticmethod
    def _backWallSignageActors():
        """A signage panel on the back wall, behind the table, holding the control-scheme text
        that used to crowd the table's front edge - keeps the table itself uncluttered while
        staying legible at the wall's distance from the user."""
        halfW = HELP_PANEL_WIDTH_M / 2.0
        halfH = HELP_PANEL_HEIGHT_M / 2.0
        panelSource = vtk.vtkPlaneSource()
        panelSource.SetOrigin(-halfW, -halfH, 0.0)
        panelSource.SetPoint1(halfW, -halfH, 0.0)
        panelSource.SetPoint2(-halfW, halfH, 0.0)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(panelSource.GetOutputPort())
        panel = vtk.vtkActor()
        panel.SetMapper(mapper)
        panel.SetTexture(VRViewerLogic._arrayToTexture(VRViewerLogic._signagePanelTexture()))
        panel.SetPosition(0.0, HELP_PANEL_CENTER_Y_M, BACK_WALL_Z_M + BACK_WALL_PANEL_OFFSET_M)
        panelProp = panel.GetProperty()
        panelProp.SetColor(1.0, 1.0, 1.0)
        panelProp.SetAmbient(0.9)
        panelProp.SetDiffuse(0.1)
        panel.PickableOff()

        # Both anchored bottom-up (vtkTextActor3D's VerticalJustificationToBottom): title sits
        # just inside the top border, body's bottom is placed so title-bottom .. body-top leaves
        # exactly HELP_TITLE_BODY_GAP_M, and body-bottom lands (by construction of
        # HELP_PANEL_HEIGHT_M above) just inside the bottom border.
        interiorHalfH = halfH * (1.0 - 2.0 * HELP_PANEL_BORDER_FRAC)
        titleBottomY = HELP_PANEL_CENTER_Y_M + interiorHalfH - HELP_PANEL_TEXT_MARGIN_M - HELP_TITLE_HEIGHT_M
        bodyBottomY = titleBottomY - HELP_TITLE_BODY_GAP_M - _HELP_BODY_BLOCK_HEIGHT_M

        textZ = BACK_WALL_Z_M + BACK_WALL_TEXT_OFFSET_M
        title = VRViewerLogic._textActor(
            position=(0.0, titleBottomY, textZ),
            heightMeters=HELP_TITLE_HEIGHT_M, color=ACCENT_COLOR)
        title.SetInput(_("VR VIEWER CONTROLS"))

        body = VRViewerLogic._textActor(
            position=(0.0, bodyBottomY, textZ),
            heightMeters=HELP_BODY_HEIGHT_M, color=(0.75, 0.90, 0.95))
        body.SetInput(_(
            "L-stick: rotate turntable\n"
            "B / Y: scale up / down\n"
            "L/R trigger: previous / next scene view\n"
            "Either grip (hold): move reformat plane\n"
            "R-stick click: show/hide reformat plane\n"
            "A: place measurement point, X: undo\n"
            "L-stick click: reset framing\n"
            "L menu: toggle auto-spin"))

        return [panel, title, body]

    def _buildMonitorAssembly(self):
        """The live info readout (current scale + scene view name), mounted as a monitor built
        into the table's collar (see RIM_BAND_* / MONITOR_* above) instead of standing as a sign
        on the flat top - the old sign stood tall enough at the table's near edge to occlude the
        anatomy sitting on the table behind it.

        The housing/screen/text are authored in a simple vertical, "standing sign" local frame -
        the same layout math the module always used for the info screen - with the housing's TOP
        edge at the collar/cap seam and the housing extending DOWN into the collar below it. A
        single vtkAssembly groups all the parts and pivots them as one rigid body about that
        top-edge hinge point, reclining the whole module back to MONITOR_TILT_FROM_HORIZONTAL_DEG.
        Keeping each part's own local geometry vertical, and doing the recline as one pivot on the
        assembly, keeps the live per-frame text updates (_updateScaleReadout /
        _updateSceneViewReadout, which only call .SetInput() on the stored text actors) working
        unchanged.

        Keeps references to the two text actors (_scaleTextActor / _sceneViewTextActor) so they
        can be updated live. Does NOT spin with the turntable, unlike _tableScreenActor - this is
        a fixed instrument panel, not decorative table dressing."""
        halfW = MONITOR_SCREEN_WIDTH_M / 2.0
        halfH = INFO_SCREEN_HEIGHT_M / 2.0
        housingHalfW = halfW + MONITOR_BEZEL_MARGIN_M
        housingHalfH = halfH + MONITOR_BEZEL_MARGIN_M

        hingeX = 0.0
        hingeY = TABLE_HEIGHT_M
        hingeZ = TABLE_FORWARD_M + RIM_BAND_RADIUS_M + MONITOR_MOUNT_PROUD_M

        # At-rest (pre-tilt) frame: housing top edge at the hinge, centered on it in X, extending
        # down into the collar below. The screen face is centered inside the housing (not top-
        # aligned) so the bezel margin reads evenly on all four sides.
        housingCenterY = hingeY - housingHalfH
        housingCenterZ = hingeZ - MONITOR_HOUSING_DEPTH_M / 2.0
        housingShell = self._boxActor(
            center=(hingeX, housingCenterY, housingCenterZ),
            size=(2.0 * housingHalfW, 2.0 * housingHalfH, MONITOR_HOUSING_DEPTH_M),
            color=RIM_BAND_COLOR)

        centerY = housingCenterY
        screenZ = hingeZ + MONITOR_SCREEN_PROUD_M

        panelSource = vtk.vtkPlaneSource()
        panelSource.SetOrigin(-halfW, -halfH, 0.0)
        panelSource.SetPoint1(halfW, -halfH, 0.0)
        panelSource.SetPoint2(-halfW, halfH, 0.0)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(panelSource.GetOutputPort())
        screenFace = vtk.vtkActor()
        screenFace.SetMapper(mapper)
        screenFace.SetTexture(self._arrayToTexture(
            self._signagePanelTexture(borderFrac=INFO_SCREEN_BORDER_FRAC)))
        screenFace.SetPosition(hingeX, centerY, screenZ)
        screenProp = screenFace.GetProperty()
        screenProp.SetColor(1.0, 1.0, 1.0)
        screenProp.SetAmbient(0.9)
        screenProp.SetDiffuse(0.1)
        screenFace.PickableOff()

        # Same bottom-up anchoring as the back-wall panel: scale line sits just inside the top
        # border, view-name line's bottom lands just inside the bottom border (by construction
        # of INFO_SCREEN_HEIGHT_M above).
        interiorHalfH = halfH * (1.0 - 2.0 * INFO_SCREEN_BORDER_FRAC)
        scaleBottomY = centerY + interiorHalfH - INFO_SCREEN_TEXT_MARGIN_M - INFO_SCREEN_LINE_HEIGHT_M
        viewBottomY = scaleBottomY - INFO_SCREEN_LINE_GAP_M - INFO_SCREEN_NAME_LINE_HEIGHT_M
        textZ = screenZ + MONITOR_TEXT_PROUD_M  # proud of the screen face

        self._scaleTextActor = self._textActor(
            position=(hingeX, scaleBottomY, textZ),
            heightMeters=INFO_SCREEN_LINE_HEIGHT_M, color=ACCENT_COLOR)

        self._sceneViewTextActor = self._textActor(
            position=(hingeX, viewBottomY, textZ),
            heightMeters=INFO_SCREEN_NAME_LINE_HEIGHT_M, color=(0.75, 0.90, 0.95))

        # Group as one rigid body and pivot about the hinge - see vtkProp3D's Origin/Orientation/
        # Position composition (Translate(Origin+Position) . Rotate . Scale . Translate(-Origin)):
        # with Position left at the default, this is exactly the textbook pivot
        # p' = R(Orientation)*(p - Origin) + Origin, applied uniformly to every part above.
        assembly = vtk.vtkAssembly()
        for part in (housingShell, screenFace, self._scaleTextActor, self._sceneViewTextActor):
            assembly.AddPart(part)
        assembly.SetOrigin(hingeX, hingeY, hingeZ)
        # Pivots the whole module back from vertical (facing +Z, standing) to a shallow recline.
        # Negated: RotateX(+angle) on this local frame swings the screen's normal toward -Y (face
        # down into the collar) and its far edge backward into the collar's solid body - the
        # opposite of what we want. RotateX(-angle) swings the normal to (0, cos(tilt), sin(tilt))
        # - mostly up, partly toward the user - and swings the panel proud of the collar surface
        # instead of into it.
        assembly.SetOrientation(-MONITOR_HINGE_ROTATION_DEG, 0.0, 0.0)
        assembly.PickableOff()
        return assembly

    def _teardownChrome(self) -> None:
        renderer = self._vrRenderer()
        if renderer is not None:
            for prop in self._chromeProps:
                renderer.RemoveViewProp(prop)
        self._chromeProps = []
        self._scaleTextActor = None
        self._sceneViewTextActor = None
        self._tableScreenActor = None
        self._monitorAssembly = None
        self._turntableAngleRad = 0.0
        self._teardownOrientationLabels()

    # ------------------------------------------------------------------ lighting

    def _buildLighting(self, renderer) -> None:
        """Build the overhead-anchored light rig and record the renderer's current (default)
        lights so they can be detached/restored. The rig is anchored to physical space via
        _anchorMatrix, exactly like the chrome props, so it stays fixed over the table
        regardless of framing/gesture - see _applyLightingOption for why the default lights
        need to be fully removed, not just switched off, while it's active."""
        self._defaultLights = []
        lights = renderer.GetLights()
        if lights is not None:
            lights.InitTraversal()
            light = lights.GetNextItem()
            while light is not None:
                self._defaultLights.append(light)
                light = lights.GetNextItem()

        keyPosition = (0.0, OVERHEAD_LIGHT_HEIGHT_M, TABLE_FORWARD_M)
        key = self._physicalLight(
            position=keyPosition, focalPoint=TABLE_PHYSICAL,
            color=OVERHEAD_LIGHT_COLOR, intensity=OVERHEAD_LIGHT_INTENSITY)

        self._overheadLights = [key]
        for angleDeg in FILL_LIGHT_ANGLES_DEG:
            angleRad = math.radians(angleDeg)
            fillPosition = (
                TABLE_PHYSICAL[0] + FILL_LIGHT_RADIUS_M * math.sin(angleRad),
                FILL_LIGHT_HEIGHT_M,
                TABLE_PHYSICAL[2] + FILL_LIGHT_RADIUS_M * math.cos(angleRad))
            self._overheadLights.append(self._physicalLight(
                position=fillPosition, focalPoint=TABLE_PHYSICAL,
                color=OVERHEAD_LIGHT_COLOR, intensity=OVERHEAD_LIGHT_INTENSITY * FILL_LIGHT_INTENSITY_FACTOR))

        for light in self._overheadLights:
            light.SetTransformMatrix(self._anchorMatrix)  # shared matrix, updated by _reanchorChrome
            renderer.AddLight(light)

        self._applyLightingOption()

    def _teardownLighting(self) -> None:
        renderer = self._vrRenderer()
        if renderer is not None:
            for light in self._overheadLights:
                renderer.RemoveLight(light)
            liveLights = renderer.GetLights()
            for light in self._defaultLights:
                if liveLights.IsItemPresent(light) == 0:
                    renderer.AddLight(light)
        self._overheadLights = []
        self._defaultLights = []

    def _applyLightingOption(self) -> None:
        """Live-toggle between the overhead rig and the VR view's default lights.

        The default lights are fully detached from the renderer (not just switched off) while
        the overhead rig is active, rather than relying on vtkLight::Switch. They're positioned
        directly in world/RAS coordinates with no TransformMatrix, unlike our rig and the room
        chrome, which are both anchored to physical space so they stay visually fixed on screen
        as the world rotates (their world position moves with the current PhysicalToWorldMatrix,
        which exactly cancels out when the camera view is computed). The default lights don't
        get that compensation, so as the turntable rotates the world their apparent direction
        relative to the viewer keeps changing - visible as light shifting across the (otherwise
        static) room walls/ceiling. Some other code can also flip Switch back on for one of them
        independently of us, which a Switch-only toggle here wouldn't survive.
        """
        renderer = self._vrRenderer()
        if renderer is None:
            return
        enabled = self.getParameterNode().overheadLight
        for light in self._overheadLights:
            light.SetSwitch(enabled)
        liveLights = renderer.GetLights()
        for light in self._defaultLights:
            isPresent = liveLights.IsItemPresent(light) != 0
            if enabled and isPresent:
                renderer.RemoveLight(light)
            elif not enabled and not isPresent:
                renderer.AddLight(light)

    @staticmethod
    def _physicalLight(position, focalPoint, color, intensity):
        """A directional (non-positional) light authored in physical meters; direction is
        Position -> FocalPoint, brightness independent of distance so it is unaffected by the
        world scale applied via PhysicalToWorldMatrix."""
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPositional(False)
        light.SetPosition(*position)
        light.SetFocalPoint(*focalPoint)
        light.SetColor(*color)
        light.SetIntensity(intensity)
        return light

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
    def _boxActor(center, size, color):
        """A small solid, flat-shaded box (vtkCubeSource) - used for the monitor housing shell,
        giving it real 3D bulk rather than reading as a texture decal."""
        source = vtk.vtkCubeSource()
        source.SetXLength(size[0])
        source.SetYLength(size[1])
        source.SetZLength(size[2])
        source.SetCenter(center[0], center[1], center[2])
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
    def _roomActor(texture):
        """A large box seen from the inside (front faces culled), wearing a tiled wall-panel
        texture so the bright steel walls read as paneling rather than flat color."""
        source = vtk.vtkCubeSource()
        source.SetXLength(ROOM_SIZE_M[0])
        source.SetYLength(ROOM_SIZE_M[1])
        source.SetZLength(ROOM_SIZE_M[2])
        source.SetCenter(0.0, ROOM_CENTER_Y_M, 0.0)
        tile = vtk.vtkTransformTextureCoords()
        tile.SetInputConnection(source.GetOutputPort())
        tile.SetScale(10.0, 5.0, 10.0)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(tile.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetTexture(texture)
        actor.GetProperty().SetColor(*WALL_BASE_COLOR)
        actor.GetProperty().FrontfaceCullingOn()
        actor.GetProperty().BackfaceCullingOff()
        actor.GetProperty().SetAmbient(0.5)
        actor.GetProperty().SetDiffuse(0.5)
        actor.PickableOff()
        return actor

    @classmethod
    def _ceilingLightActor(cls):
        """A flat panel mounted just below the ceiling, textured with a grid of bright
        fixtures (see _ceilingPanelTexture) and fed to the PBR emissive pipeline exactly like
        _tableScreenActor - gives the overhead light rig (_physicalLight) a visible source
        instead of the room appearing lit from nowhere. Purely cosmetic: it casts no light of
        its own, the actual illumination comes from the vtkLight rig built separately."""
        halfWidth, halfDepth = ROOM_SIZE_M[0] / 2.0, ROOM_SIZE_M[2] / 2.0
        y = ROOM_SIZE_M[1] - CEILING_LIGHT_OFFSET_M
        source = vtk.vtkPlaneSource()
        source.SetOrigin(-halfWidth, y, halfDepth)
        source.SetPoint1(halfWidth, y, halfDepth)
        source.SetPoint2(-halfWidth, y, -halfDepth)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        texture = cls._arrayToTexture(cls._ceilingPanelTexture())
        texture.UseSRGBColorSpaceOn()  # required for albedo/emissive textures
        prop = actor.GetProperty()
        prop.SetInterpolationToPBR()
        prop.SetBaseColorTexture(texture)
        prop.SetEmissiveTexture(texture)
        prop.SetEmissiveFactor(*CEILING_LIGHT_EMISSIVE_FACTOR)
        actor.PickableOff()
        return actor

    @staticmethod
    def _texturedDiscActor(center, radius, texture, innerRadius=0.0, color=(1.0, 1.0, 1.0),
                            opacity=1.0, ambient=0.6, diffuse=0.4, resolution=64):
        """A flat disc (normal = +Y, i.e. lying on the floor/table) carrying a planar texture -
        used for the floor grid and the table's holo-screen inset, which need proper radial UVs
        that vtkCylinderSource's cap doesn't provide."""
        source = vtk.vtkDiskSource()
        source.SetInnerRadius(innerRadius)
        source.SetOuterRadius(radius)
        source.SetRadialResolution(1)
        source.SetCircumferentialResolution(resolution)
        rotation = vtk.vtkTransform()
        rotation.RotateX(-90.0)
        rotate = vtk.vtkTransformPolyDataFilter()
        rotate.SetTransform(rotation)
        rotate.SetInputConnection(source.GetOutputPort())
        tmap = vtk.vtkTextureMapToPlane()
        tmap.SetInputConnection(rotate.GetOutputPort())
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(tmap.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetTexture(texture)
        actor.SetPosition(center[0], center[1], center[2])
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetAmbient(ambient)
        prop.SetDiffuse(diffuse)
        prop.SetOpacity(opacity)
        actor.PickableOff()
        return actor

    @staticmethod
    def _glowRingActor(center, innerRadius, outerRadius, color=ACCENT_COLOR, opacity=1.0,
                        resolution=96):
        """A flat, self-lit (ambient-only) ring used for neon trim - the table rim and the
        floor's landing-pad marking. Ambient-only so it reads as glowing rather than shaded,
        regardless of the room's actual lighting."""
        source = vtk.vtkDiskSource()
        source.SetInnerRadius(innerRadius)
        source.SetOuterRadius(outerRadius)
        source.SetRadialResolution(1)
        source.SetCircumferentialResolution(resolution)
        rotation = vtk.vtkTransform()
        rotation.RotateX(-90.0)
        rotate = vtk.vtkTransformPolyDataFilter()
        rotate.SetTransform(rotation)
        rotate.SetInputConnection(source.GetOutputPort())
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(rotate.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetPosition(center[0], center[1], center[2])
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetAmbient(1.0)
        prop.SetDiffuse(0.0)
        prop.SetOpacity(opacity)
        actor.PickableOff()
        return actor

    @staticmethod
    def _annulusActor(center, innerRadius, outerRadius, height, color, resolution=64):
        """A solid ring with a real hole through it (a flat annulus extruded to real thickness) -
        unlike _discActor's solid disc, this exposes whatever sits underneath through the hole,
        which is how the table cap gets an actual recessed pocket for the table screen to sit in
        (a flat disc alone has no way to reveal a lower surface within its own footprint)."""
        source = vtk.vtkDiskSource()
        source.SetInnerRadius(innerRadius)
        source.SetOuterRadius(outerRadius)
        source.SetRadialResolution(1)
        source.SetCircumferentialResolution(resolution)
        rotation = vtk.vtkTransform()
        rotation.RotateX(-90.0)
        rotate = vtk.vtkTransformPolyDataFilter()
        rotate.SetTransform(rotation)
        rotate.SetInputConnection(source.GetOutputPort())
        extrude = vtk.vtkLinearExtrusionFilter()
        extrude.SetInputConnection(rotate.GetOutputPort())
        extrude.SetExtrusionTypeToVectorExtrusion()
        extrude.SetVector(0.0, -height, 0.0)  # the disc sits at local y=0; extrude downward
        extrude.CappingOn()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(extrude.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetPosition(center[0], center[1], center[2])
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetAmbient(0.3)
        prop.SetDiffuse(0.7)
        actor.PickableOff()
        return actor

    @staticmethod
    def _worldGlowDotActor(radius, color, resolution=16):
        """A small self-lit sphere authored directly in RAS/world (SetPosition, no UserMatrix) -
        used for the measurement reticle, the armed pending point, and committed measurement
        endpoints. Same self-lit (ambient-only) treatment as _glowRingActor, so it reads as
        glowing UI regardless of the room's actual lighting."""
        source = vtk.vtkSphereSource()
        source.SetRadius(radius)
        source.SetThetaResolution(resolution)
        source.SetPhiResolution(resolution)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetAmbient(1.0)
        prop.SetDiffuse(0.0)
        actor.PickableOff()
        actor.VisibilityOff()
        return actor

    # ------------------------------------------------------------------ procedural textures

    @staticmethod
    def _arrayToTexture(rgbArray):
        """uint8 HxWx3 numpy array -> vtkTexture. Generated once per enter (not per-frame), so
        plain numpy is fine - no need to hand-roll pixel loops."""
        height, width, _channels = rgbArray.shape
        image = vtk.vtkImageData()
        image.SetDimensions(width, height, 1)
        # vtkImageData's Y axis runs bottom-to-top; flip so the array reads top-to-bottom as authored.
        flatRGB = np.flipud(rgbArray).reshape(-1, 3).copy()
        dataArray = numpy_support.numpy_to_vtk(flatRGB, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        image.GetPointData().SetScalars(dataArray)
        texture = vtk.vtkTexture()
        texture.SetInputData(image)
        texture.InterpolateOn()
        texture.MipmapOn()
        texture.RepeatOn()
        return texture

    @staticmethod
    def _wallPanelTexture(size=256):
        """Subtle bright panel-line grid for the room walls."""
        bg = np.array(WALL_BASE_COLOR) * 255.0
        line = np.array([0.55, 0.75, 0.85]) * 255.0
        img = np.tile(bg.astype(np.uint8), (size, size, 1))
        spacing = size // 4
        for i in range(0, size, spacing):
            img[max(i - 1, 0):i + 1, :, :] = line.astype(np.uint8)
            img[:, max(i - 1, 0):i + 1, :] = line.astype(np.uint8)
        return img

    @staticmethod
    def _floorPanelTexture(size=512):
        """Bright steel floor grid, matching the wall paneling."""
        bg = np.array(FLOOR_BASE_COLOR) * 255.0
        line = np.array([0.45, 0.55, 0.62]) * 255.0
        img = np.tile(bg.astype(np.uint8), (size, size, 1))
        spacing = size // 8
        for i in range(0, size, spacing):
            img[max(i - 1, 0):i + 1, :, :] = line.astype(np.uint8)
            img[:, max(i - 1, 0):i + 1, :] = line.astype(np.uint8)
        return img

    @staticmethod
    def _ceilingPanelTexture(size=512, rows=2, cols=3, marginFrac=0.10):
        """Grid of bright rectangular light-fixture panels on a dark ceiling background - baked
        once and fed to _ceilingLightActor as both the base color and emissive source (see
        _tableScreenTexture for the same trick), so the overhead light rig (_physicalLight)
        reads as coming from visible fixtures rather than the ceiling glowing uniformly."""
        bg = np.array(CEILING_PANEL_BG_COLOR) * 255.0
        panel = np.array(OVERHEAD_LIGHT_COLOR) * 255.0
        img = np.tile(bg.astype(np.uint8), (size, size, 1))
        cellH, cellW = size / rows, size / cols
        for r in range(rows):
            for c in range(cols):
                y0 = int(r * cellH + cellH * marginFrac)
                y1 = int((r + 1) * cellH - cellH * marginFrac)
                x0 = int(c * cellW + cellW * marginFrac)
                x1 = int((c + 1) * cellW - cellW * marginFrac)
                img[y0:y1, x0:x1, :] = panel.astype(np.uint8)
        return img

    @staticmethod
    def _tableScreenTexture(size=512):
        """Concentric rings + radial spokes on a dark background - a circuit/targeting-pad look
        for the holo-readout inset in the tabletop. Uses the dim accent (not the full-bright
        ACCENT_COLOR) so the pattern stays legible without the table reading as a wash of blue."""
        bg = np.array(TABLE_SCREEN_BG_COLOR) * 255.0
        ring = np.array(ACCENT_COLOR_DIM) * 255.0
        img = np.tile(bg.astype(np.uint8), (size, size, 1))
        yy, xx = np.mgrid[0:size, 0:size]
        cx = cy = (size - 1) / 2.0
        r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (size / 2.0)
        theta = np.arctan2(yy - cy, xx - cx)
        ringMask = (np.abs(np.sin(r * math.pi * 6.0)) > 0.97) & (r < 0.96)
        spokeMask = (np.abs(np.sin(theta * 8.0)) < 0.02) & (r > 0.12) & (r < 0.96)
        edgeMask = (r > 0.93) & (r < 0.97)
        img[ringMask | spokeMask | edgeMask] = ring.astype(np.uint8)
        return img

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
        scale = heightMeters / 48.0
        actor.SetScale(scale, scale, scale)
        actor.SetPosition(position[0], position[1], position[2])
        actor.PickableOff()
        return actor

    def _updateScaleReadout(self) -> None:
        # Derive the displayed scale from the actual matrix so it reflects any source of change,
        # including the built-in A+X gesture - not just our +/- steps.
        self._magnification = self._currentMagnification()
        if self._scaleTextActor is not None:
            # No "Scale:" label - the info screen is small and its position (on the table) and
            # the scene-view name right below it already make it obvious what the number means.
            self._scaleTextActor.SetInput(
                _("{scale:.2f}x").format(scale=self._magnification))

    def _updateSceneViewReadout(self) -> None:
        """Show the current scene view's name on the info screen (or a placeholder before the
        user has cycled to one - see _sceneViewIndex). Scene view names are free text the user
        entered elsewhere, so they're fit to the info screen - see _setSceneViewText."""
        if self._sceneViewTextActor is None:
            return
        logic = self._sceneViewsLogic()
        name = None
        if logic is not None and 0 <= self._sceneViewIndex < logic.GetNumberOfSceneViews():
            name = logic.GetNthSceneViewName(self._sceneViewIndex)
        self._setSceneViewText(name if name else _("(live scene)"))

    def _setSceneViewText(self, name) -> None:
        """Set the scene-view text, truncating (with an ellipsis) only as much as actually
        needed to fit INFO_SCREEN_NAME_MAX_WIDTH_M - measured via the actor's own rendered
        bounds, rather than a fixed character count. A fixed count either truncated ordinary
        short names that had plenty of room left on the screen, or would still overflow on
        unusually wide characters - this instead fits exactly what the current name needs."""
        actor = self._sceneViewTextActor
        bounds = [0.0] * 6

        def fits(text) -> bool:
            actor.SetInput(text)
            actor.GetBounds(bounds)
            return bounds[1] - bounds[0] <= INFO_SCREEN_NAME_MAX_WIDTH_M

        if fits(name):
            return
        truncated = name
        while len(truncated) > 1:
            truncated = truncated[:-1]
            if fits(truncated + "…"):
                return
        actor.SetInput("…")

    def _updateTableScreenOrientation(self) -> None:
        """Spin the table screen's own texture by the accumulated turntable angle, on top of
        the shared anchorMatrix that otherwise keeps all chrome screen-fixed - see
        rotateTurntable/_turntableAngleRad. Only the left-stick/auto-spin turntable control
        drives this, not the built-in two-controller free move/rotate/scale gesture."""
        if self._tableScreenActor is not None:
            angleDeg = vtk.vtkMath.DegreesFromRadians(self._turntableAngleRad)
            self._tableScreenActor.SetOrientation(0.0, angleDeg, 0.0)

    # ------------------------------------------------------------------ orientation labels
    #
    # R/L/A/P/S/I are authored directly in RAS/world coordinates (no UserMatrix), exactly like
    # the actual MRML data. Per computePhysicalToWorld's derivation, real MRML data never
    # actually moves in world space - what changes is the PhysicalToWorldMatrix used to view it,
    # which makes it *appear* transformed by W. Anything else authored in raw world coordinates
    # (with no UserMatrix override) appears to move by that same W, so these labels track the
    # anatomy's apparent rotation/placement automatically, with no extra code needed when the
    # table spins or scales. Contrast with _chromeProps, which use UserMatrix=_anchorMatrix so
    # they stay room-fixed instead.

    @staticmethod
    def _billboardTextActor(text, color=ACCENT_COLOR, fontSize=ORIENTATION_LABEL_FONT_SIZE):
        """A camera-facing, constant-screen-size 3D label anchored at a world/RAS point."""
        actor = vtk.vtkBillboardTextActor3D()
        actor.SetInput(text)
        tprop = actor.GetTextProperty()
        tprop.SetFontSize(fontSize)
        tprop.SetColor(*color)
        tprop.SetBold(True)
        tprop.SetJustificationToCentered()
        tprop.SetVerticalJustificationToCentered()
        tprop.ShadowOn()
        tprop.SetFrameWidth(2)
        actor.PickableOff()

        # The internal textured quad is lit by default, which tints the label
        # under Slicer's default light kit. Reach it via GetActors() and unlit it.
        props = vtk.vtkPropCollection()
        actor.GetActors(props)
        quad = props.GetLastProp()
        if quad is not None:
            quad.GetProperty().LightingOff()

        return actor

    def _buildOrientationLabels(self, renderer) -> None:
        self._orientationLabelActors = {}
        for letter in ORIENTATION_LABEL_AXES:
            actor = self._billboardTextActor(letter)
            renderer.AddViewProp(actor)  # no UserMatrix: authored directly in RAS/world
            self._orientationLabelActors[letter] = actor
        self._updateOrientationLabels()

    def _teardownOrientationLabels(self) -> None:
        renderer = self._vrRenderer()
        if renderer is not None:
            for actor in self._orientationLabelActors.values():
                renderer.RemoveViewProp(actor)
        self._orientationLabelActors = {}

    def _updateOrientationLabels(self) -> None:
        """Reposition the R/L/A/P/S/I labels around the current data bounds/center. Called
        whenever the data set changes (_recomputeDataBounds); rotation/scale need no separate
        update here since the labels are RAS-anchored (see class comment above).

        All six sit the same small margin outside the data's bounds along their own axis. This
        used to plant I below the table surface, because the data's bottom rested exactly on
        it (zero gap) - fixed by lifting the whole anatomy off the table instead (see
        TABLE_LIFT_BUFFER_MM in computePhysicalToWorld), not by treating I specially here.
        """
        if not self._orientationLabelActors:
            return
        bounds = self._dataBounds
        center = self._dataCenter
        radiusXY = 0.5 * max(
            self._extentAlongAxis(bounds, (1.0, 0.0, 0.0)),
            self._extentAlongAxis(bounds, (0.0, 1.0, 0.0)))
        radiusZ = 0.5 * self._extentAlongAxis(bounds, (0.0, 0.0, 1.0))
        if radiusXY <= 0.0 and radiusZ <= 0.0:
            radiusXY = radiusZ = ORIENTATION_LABEL_DEFAULT_RADIUS_MM
        else:
            radiusXY += ORIENTATION_LABEL_MARGIN_MM
            radiusZ += ORIENTATION_LABEL_MARGIN_MM
        for letter, axis in ORIENTATION_LABEL_AXES.items():
            actor = self._orientationLabelActors.get(letter)
            if actor is None:
                continue
            radius = radiusZ if axis[2] != 0.0 else radiusXY
            actor.SetPosition(
                center[0] + axis[0] * radius,
                center[1] + axis[1] * radius,
                center[2] + axis[2] * radius)

    # ------------------------------------------------------------------ VR world transform

    @staticmethod
    def _extentAlongAxis(bounds, axis):
        """Extent (max-min projection) of an RAS AABB onto an axis. 0 for empty bounds."""
        if bounds[0] > bounds[1]:
            return 0.0
        projections = []
        for xi in (bounds[0], bounds[1]):
            for yi in (bounds[2], bounds[3]):
                for zi in (bounds[4], bounds[5]):
                    projections.append(xi * axis[0] + yi * axis[1] + zi * axis[2])
        return max(projections) - min(projections)

    @staticmethod
    def _alignedBaseMatrix(baseMatrix):
        """Pure helper (headless-testable). Rotate the captured reference matrix (M0) about its
        own origin so that physical up (true gravity - what the room chrome and camera are
        always consistently anchored to, see _reanchorChrome) maps exactly onto WORLD_UP_RAS.

        This just sets the data's *starting* orientation (Superior pointing at the ceiling);
        _worldUp() re-derives the actual axis afterwards on every rotate/scale, so this
        alignment isn't required for correctness, only so the data starts upright.
        """
        physicalUp = list(baseMatrix.MultiplyPoint([0.0, 1.0, 0.0, 0.0]))[:3]
        norm = vtk.vtkMath.Norm(physicalUp)
        if norm < 1e-9:
            return baseMatrix
        physicalUp = [c / norm for c in physicalUp]

        target = list(WORLD_UP_RAS)
        axis = [0.0, 0.0, 0.0]
        vtk.vtkMath.Cross(physicalUp, target, axis)
        axisNorm = vtk.vtkMath.Norm(axis)
        if axisNorm < 1e-9:
            # Already aligned (or exactly opposed, an unrecoverable degenerate case) - leave as-is.
            return baseMatrix
        axis = [c / axisNorm for c in axis]
        angleDeg = vtk.vtkMath.DegreesFromRadians(vtk.vtkMath.AngleBetweenVectors(physicalUp, target))

        rotation = vtk.vtkTransform()
        rotation.RotateWXYZ(angleDeg, axis[0], axis[1], axis[2])
        rotationMatrix = vtk.vtkMatrix4x4()
        rotation.GetMatrix(rotationMatrix)

        corrected = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Multiply4x4(rotationMatrix, baseMatrix, corrected)
        for i in range(3):
            corrected.SetElement(i, 3, baseMatrix.GetElement(i, 3))  # keep the reference position
        return corrected

    @staticmethod
    def _worldUp(matrix):
        """The world/RAS direction that `matrix` currently maps physical up (true gravity) to -
        i.e. the table's actual current normal. Re-deriving this from whatever matrix is live
        (rather than trusting a fixed constant) matters because the built-in two-controller
        free move/rotate/scale gesture can tilt the world by an arbitrary amount, outside of
        our own controls; using a stale fixed axis after that would spin/orient the data about
        an axis no longer perpendicular to the table, causing a wobble. Falls back to
        WORLD_UP_RAS in the degenerate (zero-length) case."""
        up = list(matrix.MultiplyPoint([PHYSICAL_UP[0], PHYSICAL_UP[1], PHYSICAL_UP[2], 0.0]))[:3]
        norm = vtk.vtkMath.Norm(up)
        return [c / norm for c in up] if norm > 1e-9 else list(WORLD_UP_RAS)

    @staticmethod
    def _frontFacingYawRad(baseMatrix):
        """Pure helper (headless-testable). The angle to rotate about `_worldUp(baseMatrix)` that
        spins RAS Anterior to face the physical front of the table (toward the user), so a
        reset/scene-view-change presents the anatomy front-on rather than at whatever yaw the
        reference view (M0) happened to capture.

        Both ANTERIOR_RAS and the toward-user direction are projected onto the plane
        perpendicular to `up` (rotation only happens about that axis) before measuring the
        signed angle between them.
        """
        up = VRViewerLogic._worldUp(baseMatrix)
        towardUser = list(baseMatrix.MultiplyPoint(
            [PHYSICAL_TOWARD_USER[0], PHYSICAL_TOWARD_USER[1], PHYSICAL_TOWARD_USER[2], 0.0]))[:3]

        def projectPerpendicular(v):
            d = vtk.vtkMath.Dot(v, up)
            projected = [v[i] - d * up[i] for i in range(3)]
            norm = vtk.vtkMath.Norm(projected)
            return [c / norm for c in projected] if norm > 1e-9 else None

        anterior = projectPerpendicular(list(ANTERIOR_RAS))
        towardUser = projectPerpendicular(towardUser)
        if anterior is None or towardUser is None:
            return 0.0

        cross = [0.0, 0.0, 0.0]
        vtk.vtkMath.Cross(anterior, towardUser, cross)
        return math.atan2(vtk.vtkMath.Dot(cross, up), vtk.vtkMath.Dot(anterior, towardUser))

    @staticmethod
    def computePhysicalToWorld(baseMatrix, relScale, angleRad, dataBounds, dataCenter, tablePhysical):
        """Pure helper (headless-testable). Build the VR PhysicalToWorldMatrix that makes the
        data appear placed on the table, scaled by world factor `relScale`, and spun by
        `angleRad`, while keeping the reference-view orientation in `baseMatrix` (M0).

        We want the data to look transformed by a world-space transform W about its center:
            W = T(target) . R(worldUp, angle) . S(relScale) . T(-dataCenter)
        Viewing world W.X with the original camera is equivalent to setting
            M = W^-1 . M0
        (because view = E^-1 . M^-1, so E^-1 . M^-1 . X == E^-1 . M0^-1 . W . X).
        A point fixed in physical space then appears at E^-1 . p regardless of M, so the room
        chrome (anchored with UserMatrix = M) stays put while the data moves.
        """
        # World "up" and the world point at the table location, both derived from M0.
        up = VRViewerLogic._worldUp(baseMatrix)
        tableWorld = list(baseMatrix.MultiplyPoint(
            [tablePhysical[0], tablePhysical[1], tablePhysical[2], 1.0]))[:3]

        # Float the data just above the table: lift the center by half the (scaled) height, plus
        # a small fixed clearance (TABLE_LIFT_BUFFER_MM, scaled the same way) so the data doesn't
        # sit flush against the table surface.
        halfHeight = 0.5 * VRViewerLogic._extentAlongAxis(dataBounds, up) * relScale
        liftBuffer = TABLE_LIFT_BUFFER_MM * relScale
        target = [tableWorld[i] + up[i] * (halfHeight + liftBuffer) for i in range(3)]

        w = vtk.vtkTransform()
        w.PostMultiply()
        w.Translate(-dataCenter[0], -dataCenter[1], -dataCenter[2])
        w.Scale(relScale, relScale, relScale)
        w.RotateWXYZ(vtk.vtkMath.DegreesFromRadians(angleRad), up[0], up[1], up[2])
        w.Translate(target[0], target[1], target[2])
        wMatrix = vtk.vtkMatrix4x4()
        w.GetMatrix(wMatrix)

        wInverse = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(wMatrix, wInverse)
        result = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Multiply4x4(wInverse, baseMatrix, result)
        return result

    def _currentPhysicalToWorld(self):
        renderWindow = self._renderWindow()
        if renderWindow is None:
            return None
        matrix = vtk.vtkMatrix4x4()
        renderWindow.GetPhysicalToWorldMatrix(matrix)
        return matrix

    def _setPhysicalToWorld(self, matrix) -> None:
        renderWindow = self._renderWindow()
        if renderWindow is None:
            return
        try:
            renderWindow.SetPhysicalToWorldMatrix(matrix)
        except Exception:  # noqa: BLE001
            logging.warning("VRViewer: unable to set PhysicalToWorldMatrix")
        self._reanchorChrome(matrix)
        # Changing the physical scale invalidates the camera near/far planes (they are scaled by
        # physicalScale), so recompute them - the same thing SlicerVR's delegate does after a
        # grab/gesture/magnification change. Without this, data is clipped when the scale changes.
        renderer = self._vrRenderer()
        if renderer is not None:
            renderer.ResetCameraClippingRange()

    def _reanchorChrome(self, matrix=None) -> None:
        """Keep chrome (UserMatrix == _anchorMatrix) equal to the current VR PhysicalToWorld,
        so the room stays fixed relative to the user no matter what moved the world - our
        controls OR the built-in complex (A+X) gesture."""
        if matrix is None:
            matrix = self._currentPhysicalToWorld()
        if matrix is None:
            return
        self._anchorMatrix.DeepCopy(matrix)
        for prop in self._chromeProps:
            prop.Modified()

    def _computeFitRelScale(self):
        """World scale factor that makes the data's diagonal span roughly the table diameter,
        so 'scale 1.0' frames any data (tiny or huge) nicely on the table."""
        if self._basePhysicalToWorld is None:
            return 1.0
        m = self._basePhysicalToWorld
        # world units per physical unit at the reference view = length of a linear column.
        sf0 = (m.GetElement(0, 0) ** 2 + m.GetElement(1, 0) ** 2 + m.GetElement(2, 0) ** 2) ** 0.5
        b = self._dataBounds
        if b[0] > b[1] or sf0 < 1e-9:
            return 1.0
        diagonal = ((b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2 + (b[5] - b[4]) ** 2) ** 0.5
        if diagonal < 1e-6:
            return 1.0
        return (2.0 * TABLE_RADIUS_M * sf0) / diagonal

    def _applyFraming(self) -> None:
        """Absolute framing: data centered on the table at the framing scale (1.0 = normal VR
        size, or fitted if the option is on), upright per the reference view and yawed so
        Anterior faces the user (see _frontFacingYawRad), rotation reset. Also clears any
        gesture drift."""
        if self._basePhysicalToWorld is None:
            return
        yawRad = self._frontFacingYawRad(self._basePhysicalToWorld)
        matrix = self.computePhysicalToWorld(
            self._basePhysicalToWorld, self._fitRelScale, yawRad, self._dataBounds, self._dataCenter, TABLE_PHYSICAL)
        self._setPhysicalToWorld(matrix)
        self._turntableAngleRad = 0.0
        self._updateTableScreenOrientation()
        self._updateScaleReadout()

    def _resetFraming(self) -> None:
        """Recompute the data bounds and reframe (used on enter, reset, and after a scene-view
        change). Fit-to-table is opt-in; otherwise the framing scale is a constant 1.0."""
        self._recomputeDataBounds()
        if self.getParameterNode().fitToTable:
            self._fitRelScale = self._computeFitRelScale()
        else:
            self._fitRelScale = self._framingRelScale(DEFAULT_MAGNIFICATION)  # true life size
        self._applyFraming()

    def _incrementalWorldTransform(self, worldMatrix) -> None:
        """Apply a world-space transform to the current framing: newPTW = worldMatrix^-1 . PTW.
        Composing on the *current* matrix is what lets our controls coexist with the gesture."""
        current = self._currentPhysicalToWorld()
        if current is None:
            return
        inverse = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(worldMatrix, inverse)
        newMatrix = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Multiply4x4(inverse, current, newMatrix)
        self._setPhysicalToWorld(newMatrix)

    def _tableAxle(self, matrix):
        """(worldUp unit vector, table-center world point) for the given PTW matrix - the
        vertical axle the turntable spins/scales about, fixed at the room's table location.
        `up` is re-derived from `matrix` (see _worldUp) so it stays aligned with the table's
        actual current normal even after the free move/rotate/scale gesture tilts the world."""
        up = self._worldUp(matrix)
        axle = list(matrix.MultiplyPoint([TABLE_PHYSICAL[0], TABLE_PHYSICAL[1], TABLE_PHYSICAL[2], 1.0]))[:3]
        return up, axle

    @staticmethod
    def _linearScale(matrix):
        """World-per-physical scale factor of a PhysicalToWorld matrix (length of a column)."""
        return (matrix.GetElement(0, 0) ** 2 + matrix.GetElement(1, 0) ** 2
                + matrix.GetElement(2, 0) ** 2) ** 0.5

    def _currentMagnification(self) -> float:
        """True world magnification: 1.0 = real-world size, matching SlicerVR's convention
        (magnification = 1000 / PhysicalToWorld scale). Derived from the live matrix, so it
        reflects our controls AND the complex gesture."""
        current = self._currentPhysicalToWorld()
        if current is None:
            return self._magnification
        scale = self._linearScale(current)
        return (UNIT_MAGNIFICATION_SCALE / scale) if scale > 1e-9 else self._magnification

    def _framingRelScale(self, magnification):
        """World relScale (relative to the reference view M0) that yields the given real-world
        magnification, so a non-fit framing at magnification 1.0 is true life size."""
        if self._basePhysicalToWorld is None:
            return 1.0
        return self._linearScale(self._basePhysicalToWorld) * magnification / UNIT_MAGNIFICATION_SCALE

    def _onPhysicalToWorldModified(self, caller=None, event=None) -> None:
        self._reanchorChrome()
        self._updateScaleReadout()

    # ------------------------------------------------------------------ data collection

    def _recomputeDataBounds(self) -> None:
        dataNodes = self._collectVisibleDataNodes()
        self._dataBounds = self._combinedRASBounds(dataNodes)
        self._dataCenter = self._combinedRASCenter(dataNodes)
        self._updateOrientationLabels()

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

    # ------------------------------------------------------------------ turntable rotation

    def rotateTurntable(self, deltaRad) -> None:
        current = self._currentPhysicalToWorld()
        if current is None:
            return
        up, axle = self._tableAxle(current)
        t = vtk.vtkTransform()
        t.PostMultiply()
        t.Translate(-axle[0], -axle[1], -axle[2])
        t.RotateWXYZ(vtk.vtkMath.DegreesFromRadians(deltaRad), up[0], up[1], up[2])
        t.Translate(axle[0], axle[1], axle[2])
        w = vtk.vtkMatrix4x4()
        t.GetMatrix(w)
        self._incrementalWorldTransform(w)
        self._turntableAngleRad += deltaRad
        self._updateTableScreenOrientation()

    def toggleAutoSpin(self) -> None:
        """Left menu button: hands-free presentation rotation (paused while the user drives
        the left stick)."""
        self._autoSpin = not self._autoSpin

    def _onInputTimer(self) -> None:
        dt = INPUT_TIMER_INTERVAL_MS / 1000.0

        # Turntable: left stick drives it; otherwise auto-spin if enabled.
        if abs(self._leftStickX) >= THUMBSTICK_DEADZONE:
            speedRad = vtk.vtkMath.RadiansFromDegrees(self.getParameterNode().rotationSpeedDegPerSec)
            self.rotateTurntable(speedRad * self._leftStickX * dt)
        elif self._autoSpin:
            self.rotateTurntable(vtk.vtkMath.RadiansFromDegrees(AUTO_SPIN_DEG_PER_SEC) * dt)

        # Decay the measurement tool's "nothing to act on" flash back to normal reticle color.
        if self._measureFlashRemaining > 0.0:
            self._measureFlashRemaining = max(0.0, self._measureFlashRemaining - dt)
            if self._measureFlashRemaining == 0.0 and self._measureReticleActor is not None:
                self._measureReticleActor.GetProperty().SetColor(*ACCENT_COLOR)
                if self._measureCurrentHit is None:
                    self._measureReticleActor.VisibilityOff()

    # ------------------------------------------------------------------ magnification

    def getMagnification(self) -> float:
        return self._currentMagnification()

    @staticmethod
    def steppedMagnification(current, direction, stepFactor):
        """Pure helper (headless-testable): multiplicative step, clamped."""
        value = current * stepFactor if direction > 0 else current / stepFactor
        return max(MIN_MAGNIFICATION, min(MAX_MAGNIFICATION, value))

    def setMagnification(self, value) -> None:
        """Scale the world about the table axle to the requested scale (relative to the actual
        current scale), so it composes with the gesture rather than snapping."""
        current = self._currentPhysicalToWorld()
        if current is None:
            self._magnification = value
            return
        currentScale = self._currentMagnification()
        newScale = max(MIN_MAGNIFICATION, min(MAX_MAGNIFICATION, value))
        if currentScale <= 0:
            return
        factor = newScale / currentScale
        if abs(factor - 1.0) > 1e-9:
            up, axle = self._tableAxle(current)
            t = vtk.vtkTransform()
            t.PostMultiply()
            t.Translate(-axle[0], -axle[1], -axle[2])
            t.Scale(factor, factor, factor)
            t.Translate(axle[0], axle[1], axle[2])
            w = vtk.vtkMatrix4x4()
            t.GetMatrix(w)
            self._incrementalWorldTransform(w)
        self._updateScaleReadout()

    def stepMagnification(self, direction) -> None:
        stepFactor = self.getParameterNode().magnificationStep
        self.setMagnification(self.steppedMagnification(self._currentMagnification(), direction, stepFactor))

    def resetMagnification(self) -> None:
        """Left-stick click: recenter the data on the table at scale 1.0, rotation zeroed
        (also clears any gesture drift)."""
        self._resetFraming()

    # ------------------------------------------------------------------ arbitrary reformat slice

    @staticmethod
    def _reformatBackgroundVolumeAndGeometry():
        """The volume driving the reformat slice (mirrors Red's current background volume), and
        the handle size/center derived from its RAS bounds - falls back to a fixed size at the
        origin if no volume is loaded yet."""
        volume = None
        redComposite = slicer.mrmlScene.GetNodeByID("vtkMRMLSliceCompositeNodeRed")
        if redComposite is not None:
            volumeID = redComposite.GetBackgroundVolumeID()
            if volumeID:
                volume = slicer.mrmlScene.GetNodeByID(volumeID)
        if volume is None:
            volumes = slicer.mrmlScene.GetNodesByClass("vtkMRMLScalarVolumeNode")
            volumes.UnRegister(None)
            if volumes.GetNumberOfItems() > 0:
                volume = volumes.GetItemAsObject(0)

        size = DEFAULT_REFORMAT_HANDLE_SIZE_MM
        center = [0.0, 0.0, 0.0]
        if volume is not None:
            bounds = [0.0] * 6
            volume.GetRASBounds(bounds)
            if bounds[0] <= bounds[1]:
                diagonal = ((bounds[1] - bounds[0]) ** 2 + (bounds[3] - bounds[2]) ** 2
                            + (bounds[5] - bounds[4]) ** 2) ** 0.5
                if diagonal > 1e-6:
                    size = diagonal * REFORMAT_HANDLE_SIZE_FRAC
                center = [(bounds[0] + bounds[1]) / 2.0, (bounds[2] + bounds[3]) / 2.0,
                          (bounds[4] + bounds[5]) / 2.0]
        return volume, size, center

    def _setupReformatSlice(self, renderer) -> None:
        """Create the reformat plane handle (a plain model node that follows a controller's pose
        for as long as its grip is held, see _trackReformatPlaneToController) and the private
        slice pipeline that reformats the background volume from it."""
        scene = slicer.mrmlScene

        backgroundVolume, size, center = self._reformatBackgroundVolumeAndGeometry()
        self._reformatMonitorHalfSize = (size / 2.0, size / 2.0)

        halfSize = size / 2.0
        planeSource = vtk.vtkPlaneSource()
        planeSource.SetOrigin(-halfSize, -halfSize, 0.0)
        planeSource.SetPoint1(halfSize, -halfSize, 0.0)
        planeSource.SetPoint2(-halfSize, halfSize, 0.0)
        planeSource.Update()

        modelNode = scene.AddNewNodeByClass("vtkMRMLModelNode", REFORMAT_PLANE_NODE_NAME)
        modelNode.SetAndObservePolyData(planeSource.GetOutput())
        modelNode.SetHideFromEditors(True)
        modelNode.SetSaveWithScene(False)
        modelNode.CreateDefaultDisplayNodes()

        displayNode = modelNode.GetDisplayNode()
        if displayNode is not None:
            displayNode.SetColor(*ACCENT_COLOR)
            displayNode.SetOpacity(REFORMAT_HANDLE_OPACITY)
            displayNode.SetBackfaceCulling(False)
            displayNode.SetAmbient(0.9)
            displayNode.SetDiffuse(0.1)
            displayNode.SetVisibility2D(False)

        # The plane's own polydata is authored once, at identity (XY plane, +Z normal), centered
        # on the origin - all subsequent movement happens purely via this transform, which is
        # overwritten wholesale on every grip-pose update while a grip is held (see
        # _onGripClick/_onLeftGripPose/_onRightGripPose).
        transformNode = scene.AddNewNodeByClass(
            "vtkMRMLLinearTransformNode", REFORMAT_PLANE_NODE_NAME + " Transform")
        transformNode.SetHideFromEditors(True)
        transformNode.SetSaveWithScene(False)
        initialMatrix = vtk.vtkMatrix4x4()
        initialMatrix.SetElement(0, 3, center[0])
        initialMatrix.SetElement(1, 3, center[1])
        initialMatrix.SetElement(2, 3, center[2])
        transformNode.SetMatrixTransformToParent(initialMatrix)
        modelNode.SetAndObserveTransformNodeID(transformNode.GetID())

        self._reformatPlaneModelNode = modelNode
        self._reformatTransformNode = transformNode

        sliceLogic = slicer.vtkMRMLSliceLogic()
        sliceLogic.SetMRMLScene(scene)
        sliceNode = sliceLogic.AddSliceNode(REFORMAT_SLICE_LAYOUT_NAME)
        sliceNode.SetHideFromEditors(True)
        sliceNode.SetSaveWithScene(False)
        sliceNode.SetSliceVisible(False)  # the floating screen shows the image, not a coincident model
        sliceNode.SetFieldOfView(size, size, 1.0)

        compositeNode = sliceLogic.GetSliceCompositeNode()
        if compositeNode is not None:
            compositeNode.SetHideFromEditors(True)
            compositeNode.SetSaveWithScene(False)
            if backgroundVolume is not None:
                compositeNode.SetBackgroundVolumeID(backgroundVolume.GetID())

        self._reformatSliceLogic = sliceLogic
        self._reformatSliceNode = sliceNode
        self._reformatCompositeNode = compositeNode

        self._reformatMonitorActor = self._buildReformatMonitorActor(self._reformatMonitorHalfSize)
        texture = vtk.vtkTexture()
        texture.SetInputConnection(sliceLogic.GetExtractModelTexture().GetOutputPort())
        texture.InterpolateOn()
        self._reformatMonitorActor.SetTexture(texture)
        renderer.AddViewProp(self._reformatMonitorActor)

        self._updateReformatFromPlane()
        self._applyReformatVisibility()

    def _teardownReformatSlice(self) -> None:
        renderer = self._vrRenderer()
        if renderer is not None and self._reformatMonitorActor is not None:
            renderer.RemoveViewProp(self._reformatMonitorActor)
        self._reformatMonitorActor = None

        self._reformatSliceLogic = None  # also releases the auto-created (hidden) slice model node
        self._reformatCompositeNode = None

        scene = slicer.mrmlScene
        if self._reformatPlaneModelNode is not None:
            scene.RemoveNode(self._reformatPlaneModelNode)
        self._reformatPlaneModelNode = None

        if self._reformatTransformNode is not None:
            scene.RemoveNode(self._reformatTransformNode)
        self._reformatTransformNode = None

        if self._reformatSliceNode is not None:
            scene.RemoveNode(self._reformatSliceNode)
        self._reformatSliceNode = None

    @staticmethod
    def _buildReformatMonitorActor(halfSize):
        """The floating screen: a plain textured quad (not a MRML node) authored directly in
        RAS/world coordinates, like the orientation labels - repositioned each update to ride
        alongside the reformat plane (see _updateReformatFromPlane)."""
        halfW, halfH = halfSize
        source = vtk.vtkPlaneSource()
        source.SetOrigin(-halfW, -halfH, 0.0)
        source.SetPoint1(halfW, -halfH, 0.0)
        source.SetPoint2(-halfW, halfH, 0.0)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(1.0, 1.0, 1.0)
        prop.SetAmbient(0.9)
        prop.SetDiffuse(0.1)
        prop.BackfaceCullingOff()
        actor.PickableOff()
        return actor

    def _onGripClick(self, side, calldata) -> None:
        """Press: start tracking that hand (and snap immediately, for zero-latency feedback).
        Release: stop tracking, but only if this hand was the one being tracked - the other
        hand's grip may be down at the same time."""
        if self._isPress(calldata):
            self._reformatGripHeldSide = side
            self._trackReformatPlaneToController(calldata)
        elif self._reformatGripHeldSide == side:
            self._reformatGripHeldSide = None

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onLeftGripClick(self, caller, event, calldata):
        self._onGripClick("Left", calldata)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onRightGripClick(self, caller, event, calldata):
        self._onGripClick("Right", calldata)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onLeftGripPose(self, caller, event, calldata):
        # Continuous per-frame pose update (unrelated to click state) - only acts while the left
        # grip is the one currently held (see _onGripClick).
        if self._reformatGripHeldSide == "Left":
            self._trackReformatPlaneToController(calldata)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onRightGripPose(self, caller, event, calldata):
        if self._reformatGripHeldSide == "Right":
            self._trackReformatPlaneToController(calldata)

    def _trackReformatPlaneToController(self, calldata) -> None:
        """Move the reformat plane to the controller pose carried by calldata - called on grip
        press and then continuously (via the grip pose events) for as long as that grip stays
        held, so the plane follows the controller like a physically-attached handle."""
        if self._reformatTransformNode is None:
            return
        try:
            pos = calldata.GetWorldPosition()
            ori = calldata.GetWorldOrientation()
        except Exception:  # noqa: BLE001
            return
        matrix = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.PoseToMatrix(pos, ori, matrix)
        self._reformatTransformNode.SetMatrixTransformToParent(matrix)
        self._updateReformatFromPlane()

    def toggleReformatVisible(self) -> None:
        """Right thumbstick click: show/hide the reformat plane handle and its floating screen
        together. Hidden by default on entry - grabbing/positioning still works while hidden."""
        self._reformatVisible = not self._reformatVisible
        self._applyReformatVisibility()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onToggleReformatVisible(self, caller, event, calldata):
        if self._isPress(calldata):
            self.toggleReformatVisible()

    def _applyReformatVisibility(self) -> None:
        if self._reformatPlaneModelNode is not None:
            displayNode = self._reformatPlaneModelNode.GetDisplayNode()
            if displayNode is not None:
                displayNode.SetVisibility(self._reformatVisible)
        if self._reformatMonitorActor is not None:
            self._reformatMonitorActor.SetVisibility(self._reformatVisible)

    def _updateReformatFromPlane(self) -> None:
        """Rebuild the reformat slice's SliceToRAS from the plane's transform, and move the
        floating screen to ride alongside it. Called on every grip-tracked pose update (see
        _trackReformatPlaneToController)."""
        if self._reformatTransformNode is None or self._reformatSliceNode is None:
            return

        matrix = self._reformatTransformNode.GetMatrixTransformToParent()

        sliceToRAS = self._reformatSliceNode.GetSliceToRAS()
        sliceToRAS.DeepCopy(matrix)
        self._reformatSliceNode.UpdateMatrices()

        if self._reformatMonitorActor is not None:
            halfW, _halfH = self._reformatMonitorHalfSize
            offset = 2.0 * halfW + halfW * REFORMAT_MONITOR_GAP_FRAC
            xAxis = [matrix.GetElement(i, 0) for i in range(3)]
            monitorMatrix = vtk.vtkMatrix4x4()
            monitorMatrix.DeepCopy(matrix)
            for i in range(3):
                monitorMatrix.SetElement(i, 3, matrix.GetElement(i, 3) + xAxis[i] * offset)
            self._reformatMonitorActor.SetUserMatrix(monitorMatrix)

    # ------------------------------------------------------------------ measurement tool
    #
    # In-VR point-to-point distance measurement, for solo review rather than presentation: aim
    # the right controller (RightAimPoseEvent - the forward-pointing ray, distinct from the grip
    # pose the reformat plane uses) at the anatomy, press Right A to place a point, press it
    # again to complete the pair into a real vtkMRMLMarkupsLineNode. Left X undoes the most
    # recent action. Both buttons are otherwise unbound in this module - see the debounce note on
    # _isButton1PressSuppressed for why they're safe to reuse even though the built-in
    # two-controller free-gesture also watches them (held together).
    #
    # Picking uses vtkCellPicker.Pick3DRay against the VR renderer with its default (unrestricted)
    # settings - every VRViewer-owned chrome/label/UI actor already calls PickableOff(), so a
    # plain ray pick naturally only ever hits real MRML data actors (models/segmentations), with
    # no explicit pick-list to maintain. For volume-rendered-only data, revealing the reformat
    # plane (existing right-thumbstick-click toggle) makes its handle - a real, pickable polydata
    # quad coincident with a live reformatted cut - a legitimate, anatomically-meaningful pick
    # target too, at no extra cost.
    #
    # Unlike the rest of this module's chrome (raw VTK, VR-renderer-only, never touching the
    # scene), measurements ARE real content the user creates during review - a real
    # vtkMRMLMarkupsLineNode per measurement, left in the scene on exit (visible in desktop 3D,
    # saved with the scene, deletable via the normal Markups/Data UI). This deliberately reuses
    # Slicer's existing Line markup rather than hand-rolling points/line/label: it already
    # computes live length (GetMeasurement("length")) and renders itself (line, endpoints,
    # distance label via PropertiesLabelVisibility) in every view that shows markups, VR included
    # - no separate actor/texture code needed. Placing the second control point at the same
    # position as the first, then continuously moving it to the current aim while pending (see
    # _updateMeasureReticle), gives the same live "rubber-band" preview a hand-rolled line would,
    # for free. Only an *incomplete* pending line (armed but never finished) is removed on exit -
    # see _teardownMeasurements - completed measurements are left alone.

    def _setupMeasurements(self, renderer) -> None:
        self._measurePicker = vtk.vtkCellPicker()
        self._measureReticleActor = self._worldGlowDotActor(MEASURE_RETICLE_RADIUS_MM, ACCENT_COLOR)
        renderer.AddViewProp(self._measureReticleActor)
        self._measureCurrentHit = None
        self._measurementPendingLineNode = None
        self._measurements = []
        self._measureFlashRemaining = 0.0
        self._button1Held = {"Left": False, "Right": False}
        self._button1PressTime = {"Left": None, "Right": None}

    def _teardownMeasurements(self) -> None:
        renderer = self._vrRenderer()
        if renderer is not None and self._measureReticleActor is not None:
            renderer.RemoveViewProp(self._measureReticleActor)
        self._cancelPendingMeasurement()
        self._measurePicker = None
        self._measureReticleActor = None
        self._measureCurrentHit = None
        self._measurements = []  # completed measurements stay in the scene - see class docstring

    @staticmethod
    def _isButton1PressSuppressed(now, otherHeld, otherPressTime, windowSeconds) -> bool:
        """Pure helper (headless-testable). True if the *other* hand's button1 was pressed and
        is still held within windowSeconds of `now` - keeps a deliberate two-hand free-gesture
        engagement (the built-in A+X combo) from also firing a spurious place/undo action here.
        Guarantees at most one of the two ever fires (whichever press the interactor happens to
        process first fires once, before the other hand registers as held) - the residual single
        spurious action is an accepted, recoverable trade-off, not a bug: fully closing it would
        mean delaying every legitimate single-hand press to see if the other hand follows, adding
        latency to the common case (placing points one at a time) to protect a rarer edge case."""
        return bool(otherHeld) and otherPressTime is not None and (now - otherPressTime) < windowSeconds

    def _updateMeasureReticle(self, calldata) -> None:
        """Per-frame aim-ray pick, called on every RightAimPoseEvent - see _onRightAimPose. While
        a measurement is pending (first point placed), also drags its second control point to
        the current hit - the "live rubber-band" preview, see the class docstring above."""
        renderer = self._vrRenderer()
        if renderer is None or self._measurePicker is None or self._measureReticleActor is None:
            return
        try:
            pos = calldata.GetWorldPosition()
            ori = calldata.GetWorldOrientation()
        except Exception:  # noqa: BLE001
            return
        hit = self._measurePicker.Pick3DRay(pos, ori, renderer)
        if hit:
            self._measureCurrentHit = tuple(self._measurePicker.GetPickPosition())
            self._measureReticleActor.SetPosition(*self._measureCurrentHit)
            self._measureReticleActor.GetProperty().SetColor(*ACCENT_COLOR)
            self._measureReticleActor.VisibilityOn()
            if self._measurementPendingLineNode is not None:
                self._measurementPendingLineNode.SetNthControlPointPositionWorld(1, *self._measureCurrentHit)
        else:
            self._measureCurrentHit = None
            self._measureReticleActor.VisibilityOff()

    def _commitMeasurementPoint(self, point) -> None:
        """First press creates a new Line markup with both control points at the picked position
        (a valid, zero-length line) and arms it as pending - _updateMeasureReticle then drags its
        second point to follow the aim every frame. Second press stops the drag and finalizes it
        as a completed measurement."""
        if self._measurementPendingLineNode is None:
            lineNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", "VR Measurement")
            lineNode.CreateDefaultDisplayNodes()
            lineNode.AddControlPoint(point[0], point[1], point[2])
            lineNode.AddControlPoint(point[0], point[1], point[2])
            displayNode = lineNode.GetDisplayNode()
            if displayNode is not None:
                displayNode.SetColor(*MEASURE_COLOR)
                displayNode.SetSelectedColor(*MEASURE_COLOR)
                displayNode.PropertiesLabelVisibilityOn()
                displayNode.SetUseGlyphScale(False)
            self._measurementPendingLineNode = lineNode
        else:
            self._measurementPendingLineNode.SetNthControlPointPositionWorld(1, point[0], point[1], point[2])
            self._measurements.append(self._measurementPendingLineNode)
            self._measurementPendingLineNode = None

    def _cancelPendingMeasurement(self) -> None:
        """Remove an armed-but-incomplete pending line node (never finished) from the scene -
        unlike a completed measurement, it was never a real, deliberately-finished measurement."""
        if self._measurementPendingLineNode is not None:
            slicer.mrmlScene.RemoveNode(self._measurementPendingLineNode)
            self._measurementPendingLineNode = None

    def undoLastMeasurementAction(self) -> None:
        """Undo priority: cancel an armed-but-incomplete pending line first (most recent action);
        otherwise remove the last completed measurement from the scene; otherwise flash feedback
        (nothing to undo). No dedicated "clear all" control - repeated undo already clears
        everything incrementally."""
        if self._measurementPendingLineNode is not None:
            self._cancelPendingMeasurement()
            return
        if self._measurements:
            slicer.mrmlScene.RemoveNode(self._measurements.pop())
            return
        self._flashMeasureFeedback()

    def _flashMeasureFeedback(self) -> None:
        """Brief color flash on the reticle - feedback for a place/undo press that had nothing
        to act on (no current pick, or no pending/completed measurement to undo). Decayed on the
        30Hz input timer, see _onInputTimer."""
        self._measureFlashRemaining = MEASURE_FLASH_DURATION_S
        if self._measureReticleActor is not None:
            self._measureReticleActor.GetProperty().SetColor(*MEASURE_FLASH_COLOR)
            self._measureReticleActor.VisibilityOn()

    def _trackButton1(self, side, calldata) -> None:
        if self._isPress(calldata):
            self._button1Held[side] = True
            self._button1PressTime[side] = time.time()
        else:
            self._button1Held[side] = False

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onRightAimPose(self, caller, event, calldata):
        self._updateMeasureReticle(calldata)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onPlaceMeasurementPoint(self, caller, event, calldata):
        self._trackButton1("Right", calldata)
        if not self._isPress(calldata):
            return
        if self._isButton1PressSuppressed(
                time.time(), self._button1Held["Left"], self._button1PressTime["Left"],
                MEASURE_GESTURE_SUPPRESS_WINDOW_S):
            return
        if self._measureCurrentHit is None:
            self._flashMeasureFeedback()
            return
        self._commitMeasurementPoint(self._measureCurrentHit)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onUndoMeasurement(self, caller, event, calldata):
        self._trackButton1("Left", calldata)
        if not self._isPress(calldata):
            return
        if self._isButton1PressSuppressed(
                time.time(), self._button1Held["Right"], self._button1PressTime["Right"],
                MEASURE_GESTURE_SUPPRESS_WINDOW_S):
            return
        self.undoLastMeasurementAction()

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
        """Restore the next/previous scene view, then re-apply the VR framing (the data set may
        have changed, but the scene itself is otherwise left as the scene view defines it)."""
        logic = self._sceneViewsLogic()
        if logic is None:
            return
        count = logic.GetNumberOfSceneViews()
        if count <= 0:
            return
        self._sceneViewIndex = (self._sceneViewIndex + (1 if direction > 0 else -1)) % count
        logic.RestoreSceneView(self._sceneViewIndex)
        self._recomputeDataBounds()
        self._updateSceneViewReadout()

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
            self._observerTags.append(interactor.AddObserver(eventId, callback, highPriority))

        add(style.LeftThumbstickEvent, self._onLeftThumbstick)
        # widget.setDolly3DEnabled(False) (see enterViewerMode) does NOT actually suppress the
        # right thumbstick's default fly/dolly behavior in practice - observe both its position
        # and touch events at high priority and abort them instead, the same way the old
        # right-stick-scroll code used to (see _abort).
        self._rightStickPosTag = interactor.AddObserver(style.RightThumbstickEvent, self._onRightThumbstick, highPriority)
        self._rightStickTouchTag = interactor.AddObserver(style.RightThumbstickTouchEvent, self._onRightThumbstickTouch, highPriority)
        self._observerTags.append(self._rightStickPosTag)
        self._observerTags.append(self._rightStickTouchTag)
        add(style.RightButton2ClickEvent, self._onScaleUp)     # B
        add(style.LeftButton2ClickEvent, self._onScaleDown)    # Y
        add(style.RightTriggerClickEvent, self._onNextSceneView)
        add(style.LeftTriggerClickEvent, self._onPrevSceneView)
        add(style.LeftThumbstickClickEvent, self._onResetScale)
        add(style.RightThumbstickClickEvent, self._onToggleReformatVisible)
        add(style.LeftMenuClickEvent, self._onToggleAutoSpin)
        # Click starts/stops tracking that hand (see _onGripClick); the continuous pose events
        # (fired every frame regardless of button state) do the actual following while held.
        add(style.LeftGripClickEvent, self._onLeftGripClick)
        add(style.RightGripClickEvent, self._onRightGripClick)
        add(style.LeftGripPoseEvent, self._onLeftGripPose)
        add(style.RightGripPoseEvent, self._onRightGripPose)
        # Measurement tool: aim ray (right hand only, v1) + place/undo buttons. A/X are otherwise
        # unbound in this module - see the "measurement tool" section for the debounce that keeps
        # them safe to reuse alongside the built-in two-controller free-gesture.
        add(style.RightAimPoseEvent, self._onRightAimPose)
        add(style.RightButton1ClickEvent, self._onPlaceMeasurementPoint)   # A
        add(style.LeftButton1ClickEvent, self._onUndoMeasurement)         # X

        # Re-anchor the room whenever the world moves - including via the built-in A+X gesture.
        widget.connect("physicalToWorldMatrixModified()", self._onPhysicalToWorldModified)
        self._physicalToWorldConnected = True

    def _removeObservers(self) -> None:
        if self._interactor is not None:
            for tag in self._observerTags:
                self._interactor.RemoveObserver(tag)
        self._observerTags = []
        self._interactor = None

        widget = self._vrViewWidget()
        if widget is not None and self._physicalToWorldConnected:
            try:
                widget.disconnect("physicalToWorldMatrixModified()", self._onPhysicalToWorldModified)
            except Exception:  # noqa: BLE001
                pass
        self._physicalToWorldConnected = False

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

    def _abort(self, tag):
        """Stop the default (lower-priority) processing of an event we've taken over."""
        if self._interactor is not None:
            command = self._interactor.GetCommand(tag)
            if command is not None:
                command.AbortFlagOn()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onRightThumbstick(self, caller, event, calldata):
        # Right stick isn't used for anything of ours - this observer exists purely to abort the
        # default fly/dolly translation (see _installObservers for why setDolly3DEnabled(False)
        # alone isn't sufficient).
        self._abort(self._rightStickPosTag)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onRightThumbstickTouch(self, caller, event, calldata):
        # Touch down/up also drives fly start/stop by default; suppress it too.
        self._abort(self._rightStickTouchTag)

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
    def _onToggleAutoSpin(self, caller, event, calldata):
        if self._isPress(calldata):
            self.toggleAutoSpin()


#
# VRViewerTest
#


class VRViewerTest(ScriptedLoadableModuleTest):
    """Runtime self-test mirroring the headless logic assertions (no headset needed)."""

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

        # With M0 = identity and relScale 1, the data center appears TABLE_LIFT_BUFFER_MM above
        # the table location along "up" (zero-extent data, so that's the only offset): M maps
        # the table physical point onto dataCenter - up*liftBuffer.
        identity = vtk.vtkMatrix4x4()
        dataCenter = [10.0, 20.0, 30.0]
        emptyBounds = [0.0, -1.0, 0.0, -1.0, 0.0, -1.0]  # extent 0
        m = logic.computePhysicalToWorld(identity, 1.0, 0.0, emptyBounds, dataCenter, TABLE_PHYSICAL)
        mapped = m.MultiplyPoint([TABLE_PHYSICAL[0], TABLE_PHYSICAL[1], TABLE_PHYSICAL[2], 1.0])
        up = VRViewerLogic._worldUp(identity)
        expected = [dataCenter[a] - up[a] * TABLE_LIFT_BUFFER_MM for a in range(3)]
        for a in range(3):
            self.assertAlmostEqual(mapped[a], expected[a], places=4)

        self.delayDisplay("Test passed")
