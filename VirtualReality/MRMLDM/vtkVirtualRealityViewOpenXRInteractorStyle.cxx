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

// VR MRMLDM includes
#include "vtkVirtualRealityViewOpenXRInteractor.h"
#include "vtkVirtualRealityViewOpenXRInteractorStyle.h"

// VTK Rendering/OpenXR includes
#include <vtkOpenXRManager.h>
#include <vtkOpenXRRenderWindowInteractor.h>

// VTK includes
#include <vtkActor.h>
#include <vtkConeSource.h>
#include <vtkMath.h>
#include <vtkNew.h>
#include <vtkObjectFactory.h>
#include <vtkPolyDataMapper.h>
#include <vtkProperty.h>
#include <vtkRenderer.h>

// STD includes
#include <algorithm>
#include <cmath>
#include <iostream>

//----------------------------------------------------------------------------
vtkStandardNewMacro(vtkVirtualRealityViewOpenXRInteractorStyle);

//----------------------------------------------------------------------------
vtkVirtualRealityViewOpenXRInteractorStyle::vtkVirtualRealityViewOpenXRInteractorStyle()
{
  this->ControllerEventCallbackCommand = vtkSmartPointer<vtkCallbackCommand>::New();
  this->ControllerEventCallbackCommand->SetClientData(this);
  this->ControllerEventCallbackCommand->SetCallback(
    vtkVirtualRealityViewOpenXRInteractorStyle::ProcessControllerEvents);
}

//----------------------------------------------------------------------------
vtkVirtualRealityViewOpenXRInteractorStyle::~vtkVirtualRealityViewOpenXRInteractorStyle()
{
  // Defensive: remove the indicator actors from whatever renderer they were added to, in case a
  // future refactoring keeps the renderer alive longer than this interactor style instance.
  vtkRenderer* renderer = this->GetCurrentRenderer();
  if (renderer)
  {
    if (this->LeftHandIndicatorActor)
    {
      renderer->RemoveActor(this->LeftHandIndicatorActor);
    }
    if (this->RightHandIndicatorActor)
    {
      renderer->RemoveActor(this->RightHandIndicatorActor);
    }
  }
}

//----------------------------------------------------------------------------
void vtkVirtualRealityViewOpenXRInteractorStyle::SetupActions(vtkRenderWindowInteractor* iren)
{
  // Intentionally does not call Superclass::SetupActions(): the base class
  // registers the legacy curated action set (elevation, movement, showmenu,
  // triggeraction, ...), none of which are declared in this module's own
  // vtk_openxr_actions.json manifest.
  vtkOpenXRRenderWindowInteractor* oiren = vtkOpenXRRenderWindowInteractor::SafeDownCast(iren);
  if (!oiren)
  {
    return;
  }

  // Action -> event ID bindings, in the same order as the ControllerEvents enum (see the
  // header for details).
  oiren->AddAction("left_grip_pose", static_cast<vtkCommand::EventIds>(LeftGripPoseEvent));
  oiren->AddAction("right_grip_pose", static_cast<vtkCommand::EventIds>(RightGripPoseEvent));
  oiren->AddAction("left_aim_pose", static_cast<vtkCommand::EventIds>(LeftAimPoseEvent));
  oiren->AddAction("right_aim_pose", static_cast<vtkCommand::EventIds>(RightAimPoseEvent));

  oiren->AddAction("left_grip_value", static_cast<vtkCommand::EventIds>(LeftGripValueEvent));
  oiren->AddAction("right_grip_value", static_cast<vtkCommand::EventIds>(RightGripValueEvent));
  oiren->AddAction("left_grip_click", static_cast<vtkCommand::EventIds>(LeftGripClickEvent));
  oiren->AddAction("right_grip_click", static_cast<vtkCommand::EventIds>(RightGripClickEvent));
  oiren->AddAction("left_trigger_value", static_cast<vtkCommand::EventIds>(LeftTriggerValueEvent));
  oiren->AddAction("right_trigger_value", static_cast<vtkCommand::EventIds>(RightTriggerValueEvent));
  oiren->AddAction("left_trigger_click", static_cast<vtkCommand::EventIds>(LeftTriggerClickEvent));
  oiren->AddAction("right_trigger_click", static_cast<vtkCommand::EventIds>(RightTriggerClickEvent));
  oiren->AddAction("left_trigger_touch", static_cast<vtkCommand::EventIds>(LeftTriggerTouchEvent));
  oiren->AddAction("right_trigger_touch", static_cast<vtkCommand::EventIds>(RightTriggerTouchEvent));

  oiren->AddAction("left_pinch_pose", static_cast<vtkCommand::EventIds>(LeftPinchPoseEvent));
  oiren->AddAction("right_pinch_pose", static_cast<vtkCommand::EventIds>(RightPinchPoseEvent));
  oiren->AddAction("left_poke_pose", static_cast<vtkCommand::EventIds>(LeftPokePoseEvent));
  oiren->AddAction("right_poke_pose", static_cast<vtkCommand::EventIds>(RightPokePoseEvent));

  oiren->AddAction("left_pinch_value", static_cast<vtkCommand::EventIds>(LeftPinchValueEvent));
  oiren->AddAction("right_pinch_value", static_cast<vtkCommand::EventIds>(RightPinchValueEvent));
  oiren->AddAction("left_pinch_click", static_cast<vtkCommand::EventIds>(LeftPinchClickEvent));
  oiren->AddAction("right_pinch_click", static_cast<vtkCommand::EventIds>(RightPinchClickEvent));
  oiren->AddAction("left_pinch_ready", static_cast<vtkCommand::EventIds>(LeftPinchReadyEvent));
  oiren->AddAction("right_pinch_ready", static_cast<vtkCommand::EventIds>(RightPinchReadyEvent));

  oiren->AddAction("left_grasp_value", static_cast<vtkCommand::EventIds>(LeftGraspValueEvent));
  oiren->AddAction("right_grasp_value", static_cast<vtkCommand::EventIds>(RightGraspValueEvent));
  oiren->AddAction("left_grasp_click", static_cast<vtkCommand::EventIds>(LeftGraspClickEvent));
  oiren->AddAction("right_grasp_click", static_cast<vtkCommand::EventIds>(RightGraspClickEvent));
  oiren->AddAction("left_grasp_ready", static_cast<vtkCommand::EventIds>(LeftGraspReadyEvent));
  oiren->AddAction("right_grasp_ready", static_cast<vtkCommand::EventIds>(RightGraspReadyEvent));

  oiren->AddAction(
    "left_aim_activate_value", static_cast<vtkCommand::EventIds>(LeftAimActivateValueEvent));
  oiren->AddAction(
    "right_aim_activate_value", static_cast<vtkCommand::EventIds>(RightAimActivateValueEvent));
  oiren->AddAction(
    "left_aim_activate_click", static_cast<vtkCommand::EventIds>(LeftAimActivateClickEvent));
  oiren->AddAction(
    "right_aim_activate_click", static_cast<vtkCommand::EventIds>(RightAimActivateClickEvent));
  oiren->AddAction(
    "left_aim_activate_ready", static_cast<vtkCommand::EventIds>(LeftAimActivateReadyEvent));
  oiren->AddAction(
    "right_aim_activate_ready", static_cast<vtkCommand::EventIds>(RightAimActivateReadyEvent));

  oiren->AddAction("left_thumbstick", static_cast<vtkCommand::EventIds>(LeftThumbstickEvent));
  oiren->AddAction("right_thumbstick", static_cast<vtkCommand::EventIds>(RightThumbstickEvent));
  oiren->AddAction("left_thumbstick_click", static_cast<vtkCommand::EventIds>(LeftThumbstickClickEvent));
  oiren->AddAction("right_thumbstick_click", static_cast<vtkCommand::EventIds>(RightThumbstickClickEvent));
  oiren->AddAction("left_thumbstick_touch", static_cast<vtkCommand::EventIds>(LeftThumbstickTouchEvent));
  oiren->AddAction("right_thumbstick_touch", static_cast<vtkCommand::EventIds>(RightThumbstickTouchEvent));

  oiren->AddAction("left_thumbrest_touch", static_cast<vtkCommand::EventIds>(LeftThumbrestTouchEvent));
  oiren->AddAction("right_thumbrest_touch", static_cast<vtkCommand::EventIds>(RightThumbrestTouchEvent));

  oiren->AddAction("left_button1_click", static_cast<vtkCommand::EventIds>(LeftButton1ClickEvent));
  oiren->AddAction("left_button1_touch", static_cast<vtkCommand::EventIds>(LeftButton1TouchEvent));
  oiren->AddAction("left_button2_click", static_cast<vtkCommand::EventIds>(LeftButton2ClickEvent));
  oiren->AddAction("left_button2_touch", static_cast<vtkCommand::EventIds>(LeftButton2TouchEvent));
  oiren->AddAction("left_menu_click", static_cast<vtkCommand::EventIds>(LeftMenuClickEvent));

  oiren->AddAction("right_button1_click", static_cast<vtkCommand::EventIds>(RightButton1ClickEvent));
  oiren->AddAction("right_button1_touch", static_cast<vtkCommand::EventIds>(RightButton1TouchEvent));
  oiren->AddAction("right_button2_click", static_cast<vtkCommand::EventIds>(RightButton2ClickEvent));
  oiren->AddAction("right_button2_touch", static_cast<vtkCommand::EventIds>(RightButton2TouchEvent));
  oiren->AddAction("right_system_click", static_cast<vtkCommand::EventIds>(RightSystemClickEvent));

  // Observe exactly the ControllerEvents that ProcessControllerEvents() translates into a
  // default VTK 3D event (annotated "also translated" above) -- keep this list in sync with
  // that function's switch.
  oiren->AddObserver(
    static_cast<unsigned long>(RightThumbstickEvent), this->ControllerEventCallbackCommand, this->Priority);
  oiren->AddObserver(
    static_cast<unsigned long>(RightThumbstickTouchEvent), this->ControllerEventCallbackCommand, this->Priority);
  oiren->AddObserver(
    static_cast<unsigned long>(LeftGripClickEvent), this->ControllerEventCallbackCommand, this->Priority);
  oiren->AddObserver(
    static_cast<unsigned long>(RightGripClickEvent), this->ControllerEventCallbackCommand, this->Priority);

  // Pinch-to-grab (hand tracking): thumb tip to index fingertip drives the same grab/move
  // behavior as LeftGripClickEvent/RightGripClickEvent do for controllers.
  oiren->AddObserver(
    static_cast<unsigned long>(LeftPinchClickEvent), this->ControllerEventCallbackCommand, this->Priority);
  oiren->AddObserver(
    static_cast<unsigned long>(RightPinchClickEvent), this->ControllerEventCallbackCommand, this->Priority);

  // Point-to-fly (hand tracking): LeftPokePoseEvent/RightPokePoseEvent alone drives flying, for
  // as long as that hand's poke pose (fingertip-pointing direction) is tracked -- no separate
  // click/grasp gesture gates it. See the LeftPokePoseEvent case in ProcessControllerEvents() and
  // the doc comment in the header for the full rationale.
  oiren->AddObserver(
    static_cast<unsigned long>(LeftPokePoseEvent), this->ControllerEventCallbackCommand, this->Priority);
  oiren->AddObserver(
    static_cast<unsigned long>(RightPokePoseEvent), this->ControllerEventCallbackCommand, this->Priority);
}

//----------------------------------------------------------------------------
void vtkVirtualRealityViewOpenXRInteractorStyle::ProcessControllerEvents(
  vtkObject* vtkNotUsed(object), unsigned long event, void* clientData, void* callData)
{
  vtkVirtualRealityViewOpenXRInteractorStyle* self =
    static_cast<vtkVirtualRealityViewOpenXRInteractorStyle*>(clientData);

  // Invoke on the interactor (not directly on this style object): both this style's own
  // dispatch (vtkInteractorStyle::ProcessEvents, registered as an observer on the interactor,
  // which calls OnViewerMovement3D/OnPositionProp3D) and any other code observing these
  // default VTK 3D events on the interactor (e.g. vtkVirtualRealityViewInteractorObserver) only
  // react to events invoked on the interactor. RightButton1ClickEvent/RightButton2ClickEvent/
  // LeftMenuClickEvent are intentionally not translated into Select3DEvent/Menu3DEvent/
  // NextPose3DEvent here; see the ControllerEvents doc comment above.
  vtkRenderWindowInteractor* interactor = self->GetInteractor();
  switch (event)
  {
  case RightThumbstickEvent:
  case RightThumbstickTouchEvent:
    interactor->InvokeEvent(vtkCommand::ViewerMovement3DEvent, callData);
    break;
  case LeftGripClickEvent:
  case RightGripClickEvent:
  case LeftPinchClickEvent:
  case RightPinchClickEvent:
    interactor->InvokeEvent(vtkCommand::PositionProp3DEvent, callData);
    break;
  case LeftPokePoseEvent:
  case RightPokePoseEvent:
  {
    vtkEventDataDevice3D* edd = static_cast<vtkEventData*>(callData)->GetAsEventDataDevice3D();
    vtkVirtualRealityViewOpenXRInteractor* xrInteractor =
      vtkVirtualRealityViewOpenXRInteractor::SafeDownCast(interactor);
    if (!edd || !xrInteractor)
    {
      break;
    }
    bool isLeftHand = (event == LeftPokePoseEvent);
    uint32_t hand =
      isLeftHand ? vtkOpenXRManager::ControllerIndex::Left : vtkOpenXRManager::ControllerIndex::Right;

    // The event's own WorldPosition/WorldOrientation always carry the "handpose" (aim) pose, not
    // this action's pose (see GetActionPoseWorld()'s doc) -- fetch the actual poke pose (index
    // fingertip position, oriented along the finger) and grip pose (palm) directly instead.
    double pokePos[3], pokeWXYZ[4], pokePhysPos[3], pokeDir[3];
    double gripPos[3], gripWXYZ[4], gripPhysPos[3], gripDir[3];
    if (!xrInteractor->GetActionPoseWorld(isLeftHand ? "left_poke_pose" : "right_poke_pose", hand,
          pokePos, pokeWXYZ, pokePhysPos, pokeDir)
      || !xrInteractor->GetActionPoseWorld(isLeftHand ? "left_grip_pose" : "right_grip_pose", hand,
          gripPos, gripWXYZ, gripPhysPos, gripDir))
    {
      break;
    }

    // The poke pose is tracked whenever the hand is, not only while pointing -- so gate flying
    // on an "index finger extended" check: physical (meters, magnification-independent) distance
    // between fingertip (poke) and palm (grip). Absolute thresholds would assume one hand size
    // (an adult's extended finger reaches ~0.10-0.12 m from the palm, a child's may only reach
    // ~0.07 m), so the gate self-calibrates instead: the largest fingertip-to-palm distance seen
    // for this hand during the session is that user's own extended-finger reach, and the
    // start/stop thresholds are fractions of it. The running maximum starts at a conservative
    // small-hand value and only grows (clamped to a plausible anatomical ceiling to reject
    // tracking glitches), so a small hand is flyable immediately and a large hand tightens its
    // own thresholds the first time its finger is extended. Hysteresis (start fraction > stop
    // fraction) prevents flicker at the boundary.
    constexpr double initialFingerReach = 0.07;   // meters; conservative small-hand default
    constexpr double maximumFingerReach = 0.13;   // meters; anatomical ceiling, rejects glitches
    constexpr double startPointingFraction = 0.75; // of the calibrated reach
    constexpr double stopPointingFraction = 0.55;  // of the calibrated reach
    double fingertipToPalm =
      std::sqrt(vtkMath::Distance2BetweenPoints(pokePhysPos, gripPhysPos));

    double& fingerReach =
      isLeftHand ? self->LeftCalibratedFingerReach : self->RightCalibratedFingerReach;
    if (fingerReach < initialFingerReach)
    {
      fingerReach = initialFingerReach;
    }
    fingerReach = std::min(std::max(fingerReach, fingertipToPalm), maximumFingerReach);

    const double startPointingDistance = startPointingFraction * fingerReach;
    const double stopPointingDistance = stopPointingFraction * fingerReach;

    bool& flyActive = isLeftHand ? self->LeftFlyActive : self->RightFlyActive;
    if (!flyActive && fingertipToPalm > startPointingDistance)
    {
      flyActive = true;
      // Enter VTKIS_DOLLY for this hand. StartAction() only reads edd->GetDevice() and the
      // explicit state argument, never edd->GetAction(), so it is safe to call with the shared
      // event object even though HandlePoseAction() never sets its Action field.
      self->StartAction(VTKIS_DOLLY, edd);
      // Update the pose first: it lazily creates the indicator actor, which
      // SetHandIndicatorActive() needs to already exist to make visible.
      self->UpdateHandIndicatorPose(isLeftHand, pokePos, pokeWXYZ);
      self->SetHandIndicatorActive(isLeftHand, true);
      // TEMPORARY DIAGNOSTIC for on-device gesture threshold tuning -- remove once tuned.
      std::cout << "[point-to-fly] " << (isLeftHand ? "left" : "right")
                << " start (fingertip-palm " << fingertipToPalm << " m, calibrated reach "
                << fingerReach << " m, start threshold " << startPointingDistance << " m)"
                << std::endl;
    }
    else if (flyActive && fingertipToPalm < stopPointingDistance)
    {
      flyActive = false;
      self->EndAction(VTKIS_DOLLY, edd);
      self->SetHandIndicatorActive(isLeftHand, false);
      // TEMPORARY DIAGNOSTIC for on-device gesture threshold tuning -- remove once tuned.
      std::cout << "[point-to-fly] " << (isLeftHand ? "left" : "right")
                << " stop (fingertip-palm " << fingertipToPalm << " m, calibrated reach "
                << fingerReach << " m, stop threshold " << stopPointingDistance << " m)"
                << std::endl;
    }

    if (flyActive)
    {
      self->UpdateHandIndicatorPose(isLeftHand, pokePos, pokeWXYZ);

      // Build a fresh event instead of forwarding edd/callData directly: edd is the ONE shared
      // per-hand event object that vtkOpenXRRenderWindowInteractor::PollXrActions() mutates for
      // EVERY action dispatched to this hand this frame, and only HandleBooleanAction() ever
      // touches its Action field -- so it could be carrying a stale Press/Release value left by
      // an unrelated boolean action processed earlier in this frame's dispatch loop. A freshly
      // constructed vtkEventDataDevice3D defaults its Action to vtkEventDataAction::Unknown,
      // which is neither Press nor Release, so vtkVRInteractorStyle::Movement3D() falls through
      // to its "already in VTKIS_DOLLY -> call Dolly3D()" branch -- exactly mirroring how a
      // continuously-deflected thumbstick drives repeated Dolly3D() calls.
      vtkNew<vtkEventDataDevice3D> flyEvent;
      flyEvent->SetDevice(edd->GetDevice());
      flyEvent->SetInput(vtkEventDataDeviceInput::Trigger);
      flyEvent->SetType(vtkCommand::ViewerMovement3DEvent);
      flyEvent->SetWorldPosition(pokePos);
      flyEvent->SetWorldOrientation(pokeWXYZ);
      flyEvent->SetWorldDirection(pokeDir);
      // Fixed full-speed forward "throttle": since the event's Type is ViewerMovement3DEvent,
      // vtkInteractorStyle3D::Dolly3D() refreshes its speed (LastTrackPadPosition) FROM THIS
      // EVENT's TrackPadPosition -- so it must be set here, on the event itself, exactly as a
      // physical thumbstick held fully forward would report (this was previously set on the
      // style's own LastTrackPadPosition member, which Dolly3D() immediately overwrote with
      // this event's default (0,0), making fly speed zero).
      //
      // \warning LastTrackPadPosition and LastDolly3DEventTime (vtkInteractorStyle3D) are shared
      // across ALL devices, not indexed per hand: if both hands are flying at once, their motion
      // vector-sums rather than being tracked independently per hand. Accepted as v1 behavior.
      flyEvent->SetTrackPadPosition(0.0, 1.0);

      interactor->InvokeEvent(vtkCommand::ViewerMovement3DEvent, flyEvent);
    }
    break;
  }
  default:
    break;
  }
}

//----------------------------------------------------------------------------
void vtkVirtualRealityViewOpenXRInteractorStyle::OnPositionProp3D(vtkEventData* edata)
{
  // Mirrors vtkVRInteractorStyle::OnSelect3D(), which is the only generic 3D event that VTK
  // wires into the StartAction()/EndAction() grab/move state machine. PositionProp3DEvent is
  // not handled by VTK itself, so this override is what allows it (and therefore
  // LeftGripClickEvent/RightGripClickEvent, translated into it by ProcessControllerEvents())
  // to also drive VTKIS_POSITION_PROP. Unlike OnSelect3D(), the state is hardcoded rather than
  // looked up via GetMappedAction(): that lookup only matters for VTK's built-in 3D menu
  // (vtkVRInteractorStyle::MenuCallback), which this module deliberately does not use (see
  // ControllerEvents doc comment), so PositionProp3DEvent is never remapped to anything other
  // than VTKIS_POSITION_PROP.
  vtkEventDataDevice3D* bd = edata->GetAsEventDataDevice3D();
  if (!bd)
  {
    return;
  }

  int x = this->Interactor->GetEventPosition()[0];
  int y = this->Interactor->GetEventPosition()[1];
  this->FindPokedRenderer(x, y);

  switch (bd->GetAction())
  {
  case vtkEventDataAction::Press:
  case vtkEventDataAction::Touch:
    this->StartAction(VTKIS_POSITION_PROP, bd);
    break;
  case vtkEventDataAction::Release:
  case vtkEventDataAction::Untouch:
    this->EndAction(VTKIS_POSITION_PROP, bd);
    break;
  default:
    break;
  }
}

//----------------------------------------------------------------------------
void vtkVirtualRealityViewOpenXRInteractorStyle::SetHandIndicatorActive(bool isLeftHand, bool active)
{
  vtkSmartPointer<vtkActor>& actor = isLeftHand ? this->LeftHandIndicatorActor : this->RightHandIndicatorActor;
  if (!actor)
  {
    // Not created yet (no poke-pose update has been received for this hand yet); nothing to show.
    return;
  }
  actor->SetVisibility(active);
  // Bright green while flying; the actor is hidden the rest of the time so its idle color is
  // never seen, but set something sane regardless.
  actor->GetProperty()->SetColor(active ? 0.2 : 0.5, active ? 0.9 : 0.5, active ? 0.2 : 0.5);
}

//----------------------------------------------------------------------------
void vtkVirtualRealityViewOpenXRInteractorStyle::UpdateHandIndicatorPose(
  bool isLeftHand, const double worldPosition[3], const double worldOrientationWXYZ[4])
{
  vtkSmartPointer<vtkActor>& actor = isLeftHand ? this->LeftHandIndicatorActor : this->RightHandIndicatorActor;
  if (!actor)
  {
    // Lazily create on first use: a renderer is not guaranteed to be attached to this interactor
    // style yet at construction time (see SetCurrentRenderer() usage in qMRMLVirtualRealityView).
    vtkRenderer* renderer = this->GetCurrentRenderer();
    if (!renderer)
    {
      return;
    }
    vtkNew<vtkConeSource> coneSource;
    coneSource->SetHeight(0.05);
    coneSource->SetRadius(0.015);
    coneSource->SetResolution(16);
    // Point along -Z, matching the "forward" convention vtkInteractorStyle3D::Dolly3D() itself
    // uses when building a direction vector from WorldOrientation.
    coneSource->SetDirection(0.0, 0.0, -1.0);

    vtkNew<vtkPolyDataMapper> mapper;
    mapper->SetInputConnection(coneSource->GetOutputPort());

    vtkNew<vtkActor> newActor;
    newActor->SetMapper(mapper);
    newActor->SetVisibility(false);
    renderer->AddActor(newActor);
    actor = newActor;
  }

  actor->SetPosition(worldPosition[0], worldPosition[1], worldPosition[2]);
  actor->SetOrientation(0.0, 0.0, 0.0);
  actor->RotateWXYZ(worldOrientationWXYZ[0], worldOrientationWXYZ[1], worldOrientationWXYZ[2],
    worldOrientationWXYZ[3]);
}
