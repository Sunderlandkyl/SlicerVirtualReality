/*==============================================================================

  Copyright (c) Laboratory for Percutaneous Surgery (PerkLab)
  Queen's University, Kingston, ON, Canada. All Rights Reserved.

  See COPYRIGHT.txt
  or http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  This file was originally developed by Csaba Pinter, PerkLab, Queen's University
  and was supported through CANARIE's Research Software Program, and Cancer
  Care Ontario.

==============================================================================*/

#ifndef vtkVirtualRealityViewOpenXRInteractorStyle_h
#define vtkVirtualRealityViewOpenXRInteractorStyle_h

// VR MRMLDM includes
#include "vtkSlicerVirtualRealityModuleMRMLDisplayableManagerExport.h"
#include "vtkVirtualRealityViewInteractorStyleDelegate.h"

// VTK Rendering/OpenXR includes
#include <vtkOpenXRInteractorStyle.h>

// VTK includes
#include <vtkCallbackCommand.h>
#include <vtkObject.h>
#include <vtkCommand.h>
#include <vtkEventData.h>
#include <vtkSmartPointer.h>
#include <vtkWeakPointer.h>

class vtkActor;
class vtkMRMLScene;
class vtkMRMLDisplayableManagerGroup;
class vtkWorldPointPicker;


class VTK_SLICER_VIRTUALREALITY_MODULE_MRMLDISPLAYABLEMANAGER_EXPORT vtkVirtualRealityViewOpenXRInteractorStyle
  : public vtkOpenXRInteractorStyle
{
public:
  static vtkVirtualRealityViewOpenXRInteractorStyle *New();
  vtkTypeMacro(vtkVirtualRealityViewOpenXRInteractorStyle,vtkOpenXRInteractorStyle);

  /// Generic, per-physical-control event IDs. One event ID per literal action
  /// output name declared in Resources/Bindings/vtk_openxr_actions.json and
  /// vtk_openxr_binding_oculus_touch_controller.json.
  ///
  /// All of these are dispatched directly by AddAction() in SetupActions()
  /// below and are independently observable by any code that observes the
  /// interactor. A curated subset (RightThumbstickEvent,
  /// RightThumbstickTouchEvent, LeftGripClickEvent, RightGripClickEvent) is
  /// additionally translated by ProcessControllerEvents() into a default VTK
  /// 3D event (ViewerMovement3DEvent, PositionProp3DEvent) invoked on the
  /// interactor, to preserve/add the corresponding end-user behavior.
  ///
  /// RightThumbstickEvent (continuous position) and RightThumbstickTouchEvent
  /// (touch down/lift off) are BOTH translated into ViewerMovement3DEvent,
  /// mirroring VTK's own stock Oculus Touch binding ("movement" and
  /// "startmovement" in VTK's vtk_openxr_actions.json), not an oversight:
  /// vtkOpenXRRenderWindowInteractor::HandleVector2fAction() never sets the
  /// event's Press/Release action, so vtkVRInteractorStyle::Movement3D()
  /// would otherwise only start/stop dolly movement based on a deflection
  /// threshold (fabs(pos[1]) crossing 0.1), which can lag the stick's
  /// physical spring-return. The touch event's Press/Release gives an
  /// immediate, deflection-independent start-on-touch / stop-on-release
  /// signal.
  ///
  /// Several other events are deliberately NOT translated into a default VTK
  /// 3D event, despite VTK's stock Oculus Touch binding doing so:
  /// - RightButton2ClickEvent -> Menu3DEvent would show VTK's built-in 3D
  ///   menu (vtkVRInteractorStyle::OnMenu3D()/vtkVRMenuWidget), which has no
  ///   reliable way to dismiss it if the controller ray misses a menu item,
  ///   leaving the user stuck.
  /// - LeftMenuClickEvent -> NextPose3DEvent would call
  ///   vtkVRInteractorStyle::OnNextPose3D()'s LoadNextCameraPose(), which is
  ///   a pure virtual implemented as an empty no-op by
  ///   vtkOpenXRInteractorStyle (it only does something for OpenVR).
  /// - RightButton1ClickEvent -> Select3DEvent would grab/move props (same
  ///   as LeftGripClickEvent/RightGripClickEvent do via PositionProp3DEvent
  ///   below), but is redundant now that grip-click covers that, so the
  ///   right A button is left raw.
  /// Any of these can still be wired up explicitly from Python, by observing the
  /// corresponding ControllerEvents value and forwarding it to the desired vtkCommand
  /// event via vtkSlicerVirtualRealityLogic::InvokeEvent().
  ///
  /// LeftGripClickEvent and RightGripClickEvent are translated into
  /// PositionProp3DEvent, which OnPositionProp3D() below drives into
  /// VTKIS_POSITION_PROP via StartAction()/EndAction(), the same way
  /// vtkVRInteractorStyle::OnSelect3D() does for Select3DEvent, so that
  /// squeezing either controller's grip grabs/moves props. The actual
  /// grabbing/moving logic is implemented in
  /// vtkVirtualRealityViewInteractorStyleDelegate, via this style's
  /// StartPositionProp()/EndPositionProp()/PositionProp() overrides below.
  ///
  /// To customize which VTK event a given control drives (e.g. move movement from the
  /// right to the left thumbstick), observe the corresponding ControllerEvents value from
  /// Python and forward it to the desired vtkCommand event via
  /// vtkSlicerVirtualRealityLogic::InvokeEvent(); see the "Low-level interception of
  /// events" section of DeveloperGuide.md.
  ///
  /// \warning LeftGripValueEvent, RightGripValueEvent, LeftTriggerValueEvent and
  /// RightTriggerValueEvent correspond to OpenXR "float" actions. As of this
  /// writing, vtkOpenXRRenderWindowInteractor::HandleAction() does not implement
  /// the XR_ACTION_TYPE_FLOAT_INPUT case, so these four events are registered
  /// and bound correctly but will never actually be invoked until VTK adds
  /// float-action dispatch support.
  ///
  /// LeftPinchPoseEvent/RightPinchPoseEvent, LeftPokePoseEvent/RightPokePoseEvent, and the
  /// Value/Click/Ready event triples for Pinch, Grasp, and AimActivate below are all sourced (in
  /// vtk_openxr_binding_hand_interaction.json) from the OpenXR hand-interaction extension
  /// (XR_EXT_hand_interaction)'s "pinch_ext", "poke_ext", "grasp_ext", and "aim_activate_ext"
  /// components, with no equivalent physical control on the Oculus Touch binding. As with the
  /// Oculus Touch actions above, every one of these is independently observable on the
  /// interactor regardless of whether ProcessControllerEvents() also translates it into a
  /// default VTK 3D event.
  ///
  /// \warning LeftPinchValueEvent, RightPinchValueEvent, LeftGraspValueEvent,
  /// RightGraspValueEvent, LeftAimActivateValueEvent and RightAimActivateValueEvent correspond
  /// to OpenXR "float" actions, so (like LeftGripValueEvent etc. above) they are registered and
  /// bound correctly but never actually invoked (see the \warning above).
  ///
  /// Only LeftPokePoseEvent/RightPokePoseEvent (fingertip pointing direction) are translated by
  /// ProcessControllerEvents() into a default behavior: flying, for as long as that hand's poke
  /// pose is tracked -- no separate click/grasp gesture gates it (unlike
  /// LeftGripClickEvent/RightGripClickEvent -> PositionProp3DEvent, or the physical controller's
  /// RightThumbstickEvent/RightThumbstickTouchEvent pair, which need a distinct edge signal to
  /// start/stop). This works because vtkOpenXRRenderWindowInteractor::HandlePoseAction() invokes
  /// a pose event unconditionally every frame while (and only while) that pose is actively
  /// tracked (unlike a boolean action, which only fires on the Press/Release edge, see
  /// HandleBooleanAction()'s changedSinceLastSync gate) -- so simply reacting to the event's
  /// presence or absence each frame is enough to know whether to be flying:
  /// - The first time a given hand's LeftPokePoseEvent/RightPokePoseEvent is seen, an internal
  ///   LeftFlyActive/RightFlyActive flag is set and StartAction(VTKIS_DOLLY, ...) is called once
  ///   (idempotently) to enter that VTK interaction state for that hand -- StartAction() only
  ///   reads the event's device and the explicit state argument, never its Action field, so this
  ///   is safe despite HandlePoseAction() never setting Action.
  /// - Every frame thereafter (including that same first frame) that the event fires,
  ///   ViewerMovement3DEvent is invoked using the poke pose's direction (an extended fingertip
  ///   "pointing" reference, distinct from the aim pose used for LeftAimPoseEvent/
  ///   RightAimPoseEvent), driving vtkInteractorStyle3D::Dolly3D() via
  ///   vtkVRInteractorStyle::Movement3D()'s "already in VTKIS_DOLLY" branch -- mirroring how
  ///   RightThumbstickEvent's continuous deflection drives repeated Dolly3D() calls above -- and
  ///   the point-to-fly hand indicator actor is updated to match.
  /// - There is deliberately no explicit "stop"/EndAction() call: once the event stops arriving
  ///   (hand no longer tracked/pointing), flying simply stops being driven; InteractionState for
  ///   that hand is left at VTKIS_DOLLY indefinitely, which is harmless since actual motion only
  ///   ever happens on frames where this case explicitly invokes ViewerMovement3DEvent.
  /// Because OpenXR reuses ONE shared per-hand vtkEventDataDevice3D across every action
  /// dispatched that frame (see vtkOpenXRRenderWindowInteractor::PollXrActions()), and only
  /// HandleBooleanAction() ever sets that object's Action field, this event could otherwise
  /// inherit a stale Press/Release value left by an unrelated boolean action for the same hand
  /// processed earlier in the same frame's dispatch loop -- so this handling never reads
  /// GetAction() off the event, only WorldPosition/WorldOrientation/WorldDirection.
  ///
  /// LeftPinchClickEvent/RightPinchClickEvent are translated into PositionProp3DEvent (grab/move,
  /// the same way LeftGripClickEvent/RightGripClickEvent are for controllers), since pinch (thumb
  /// tip to index fingertip) is the natural "grab" gesture for hand tracking.
  ///
  /// \warning LastTrackPadPosition and LastDolly3DEventTime (used by
  /// vtkInteractorStyle3D::Dolly3D() to compute fly speed) are single members
  /// shared across ALL devices, not indexed per hand. If both hands are pointing
  /// (and therefore flying) at once, their motion vector-sums rather than being
  /// tracked independently -- accepted as v1 behavior.
  enum ControllerEvents
  {
    FIRST_CONTROLLER_EVENT = vtkCommand::UserEvent + 1000,
    LeftGripPoseEvent = FIRST_CONTROLLER_EVENT,
    RightGripPoseEvent,
    LeftAimPoseEvent,
    RightAimPoseEvent,

    LeftGripValueEvent,
    RightGripValueEvent,
    LeftGripClickEvent,
    RightGripClickEvent,
    LeftTriggerValueEvent,
    RightTriggerValueEvent,
    LeftTriggerClickEvent,
    RightTriggerClickEvent,
    LeftTriggerTouchEvent,
    RightTriggerTouchEvent,

    LeftPinchPoseEvent,
    RightPinchPoseEvent,
    LeftPokePoseEvent,
    RightPokePoseEvent,

    LeftPinchValueEvent,
    RightPinchValueEvent,
    LeftPinchClickEvent,
    RightPinchClickEvent,
    LeftPinchReadyEvent,
    RightPinchReadyEvent,

    LeftGraspValueEvent,
    RightGraspValueEvent,
    LeftGraspClickEvent,
    RightGraspClickEvent,
    LeftGraspReadyEvent,
    RightGraspReadyEvent,

    LeftAimActivateValueEvent,
    RightAimActivateValueEvent,
    LeftAimActivateClickEvent,
    RightAimActivateClickEvent,
    LeftAimActivateReadyEvent,
    RightAimActivateReadyEvent,

    LeftThumbstickEvent,
    RightThumbstickEvent,
    LeftThumbstickClickEvent,
    RightThumbstickClickEvent,
    LeftThumbstickTouchEvent,
    RightThumbstickTouchEvent,

    LeftThumbrestTouchEvent,
    RightThumbrestTouchEvent,

    LeftButton1ClickEvent,
    LeftButton1TouchEvent,
    LeftButton2ClickEvent,
    LeftButton2TouchEvent,
    LeftMenuClickEvent,

    RightButton1ClickEvent,
    RightButton1TouchEvent,
    RightButton2ClickEvent,
    RightButton2TouchEvent,
    RightSystemClickEvent,

    LAST_CONTROLLER_EVENT
  };

  /// Register the 32 generic per-control Oculus Touch actions with the interactor.
  /// Overrides vtkOpenXRInteractorStyle::SetupActions(), which otherwise registers
  /// the legacy curated action set (elevation, movement, nextcamerapose,
  /// positionprop, showmenu, startelevation, startmovement, triggeraction) that
  /// is no longer declared in this module's own action manifest.
  void SetupActions(vtkRenderWindowInteractor* iren) override;

  /// Map PositionProp3DEvent to VTKIS_POSITION_PROP (via StartAction()/EndAction()), the same
  /// way vtkVRInteractorStyle::OnSelect3D() does it for Select3DEvent. vtkInteractorStyle's
  /// own OnPositionProp3D() is an empty stub, but vtkVirtualRealityViewInteractorObserver
  /// forwards PositionProp3DEvent (received on the interactor) to this override, so it is the
  /// entry point that lets ProcessControllerEvents() route LeftGripClickEvent/
  /// RightGripClickEvent into a grab/move action.
  void OnPositionProp3D(vtkEventData* edata) override;

  ///@{
  /// Set/get delegate
  void SetInteractorStyleDelegate(vtkVirtualRealityViewInteractorStyleDelegate* delegate)
  {
    vtkSetSmartPointerBodyMacro(InteractorStyleDelegate, vtkVirtualRealityViewInteractorStyleDelegate, delegate);
    if (delegate != nullptr)
      {
      delegate->SetInteractorStyle(this);
      }
  }
  vtkGetSmartPointerMacro(InteractorStyleDelegate, vtkVirtualRealityViewInteractorStyleDelegate);
  ///}@

  //@{
  /**
  * Interaction mode entry points.
  */
  void StartPositionProp(vtkEventDataDevice3D * edata) override { this->InteractorStyleDelegate->StartPositionProp(edata); }
  void EndPositionProp(vtkEventDataDevice3D * edata) override { this->InteractorStyleDelegate->EndPositionProp(edata); }
  //@}

  //@{
  /**
  * Multitouch events binding.
  */
  void StartGesture() override { this->InteractorStyleDelegate->StartGesture(); }
  void EndGesture() override { this->InteractorStyleDelegate->EndGesture(); }
  void OnPan() override { this->InteractorStyleDelegate->OnPan(); }
  void OnPinch() override { this->InteractorStyleDelegate->OnPinch(); }
  void OnRotate() override { this->InteractorStyleDelegate->OnRotate(); }
  //@}

  //@{
  /**
  * Methods for interaction.
  */
  void PositionProp(vtkEventData* ed, double* lwpos = nullptr, double* lwori = nullptr) override
  {
    this->InteractorStyleDelegate->PositionProp(ed, lwpos, lwori);
  }
  //@}

protected:
  vtkVirtualRealityViewOpenXRInteractorStyle();
  ~vtkVirtualRealityViewOpenXRInteractorStyle() override;

  /// Callback invoked for the ControllerEvents registered as observers in SetupActions().
  static void ProcessControllerEvents(
    vtkObject* object, unsigned long event, void* clientData, void* callData);

  /// Show/hide/recolor the point-to-fly indicator actor for the given hand (creating it first if
  /// needed -- see UpdateHandIndicatorPose()). Called from ProcessControllerEvents() on every
  /// LeftPokePoseEvent/RightPokePoseEvent.
  void SetHandIndicatorActive(bool isLeftHand, bool active);

  /// Update the point-to-fly indicator actor's transform for the given hand from its current poke
  /// pose (fingertip pointing direction). Called from ProcessControllerEvents() on every
  /// LeftPokePoseEvent/RightPokePoseEvent (i.e. every frame that hand's poke pose is tracked), so
  /// the indicator is always correctly positioned/oriented while visible.
  void UpdateHandIndicatorPose(bool isLeftHand, vtkEventDataDevice3D* edd);

  vtkSmartPointer<vtkVirtualRealityViewInteractorStyleDelegate> InteractorStyleDelegate;
  vtkSmartPointer<vtkCallbackCommand> ControllerEventCallbackCommand;

  /// Whether VTKIS_DOLLY has already been entered (via StartAction()) for the left/right hand's
  /// point-to-fly motion, driven by LeftPokePoseEvent/RightPokePoseEvent alone (see the
  /// LeftPokePoseEvent doc comment above) -- guards StartAction() from being called more than
  /// once per hand. Once true, stays true for the lifetime of this interactor style (there is no
  /// corresponding EndAction(), see the doc comment above for why that is harmless).
  bool LeftFlyActive{ false };
  bool RightFlyActive{ false };

  /// Small cone actors shown at the poke-pose position/orientation (fingertip pointing direction)
  /// of a hand while that hand's point-to-fly gesture is active, as a visual indicator of both the
  /// gesture being recognized and the direction flight will take. Created lazily (on the first
  /// poke-pose update for that hand) since a renderer is not yet available at construction time.
  vtkSmartPointer<vtkActor> LeftHandIndicatorActor;
  vtkSmartPointer<vtkActor> RightHandIndicatorActor;

private:
  vtkVirtualRealityViewOpenXRInteractorStyle(const vtkVirtualRealityViewOpenXRInteractorStyle&) = delete;
  void operator=(const vtkVirtualRealityViewOpenXRInteractorStyle&) = delete;
};

#endif
