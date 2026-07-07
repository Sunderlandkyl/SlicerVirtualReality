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
#include "vtkVirtualRealityViewOpenXRInteractorStyle.h"

// VTK Rendering/OpenXR includes
#include <vtkOpenXRRenderWindowInteractor.h>

// VTK includes
#include <vtkActor.h>
#include <vtkConeSource.h>
#include <vtkNew.h>
#include <vtkObjectFactory.h>
#include <vtkPolyDataMapper.h>
#include <vtkProperty.h>
#include <vtkRenderer.h>

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
    if (!edd)
    {
      break;
    }
    bool isLeftHand = (event == LeftPokePoseEvent);
    // No separate click/grasp gesture gates flying: LeftPokePoseEvent/RightPokePoseEvent alone
    // drives it, for as long as that hand's poke pose (fingertip-pointing direction) is tracked.
    // vtkOpenXRRenderWindowInteractor::HandlePoseAction() only invokes this event at all while
    // pose.isActive is true (unconditionally every frame in that case, unlike a boolean action),
    // and never invokes it once inactive -- so there is no separate "stop" event to react to;
    // flying simply stops being driven the moment this event stops arriving (hand no longer
    // tracked/pointing).
    self->UpdateHandIndicatorPose(isLeftHand, edd);
    self->SetHandIndicatorActive(isLeftHand, true);

    bool& flyStarted = isLeftHand ? self->LeftFlyActive : self->RightFlyActive;
    if (!flyStarted)
    {
      // Enter VTKIS_DOLLY once, the first time this hand's poke pose is seen. StartAction()
      // only reads edd->GetDevice() and the explicit state argument (VTKIS_DOLLY), never
      // edd->GetAction(), so it is safe to call here even though HandlePoseAction() never sets
      // that field (see the \warning below on why the per-frame synthetic event further down
      // still avoids reading it).
      flyStarted = true;
      self->StartAction(VTKIS_DOLLY, edd);
    }

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
    flyEvent->SetWorldPosition(edd->GetWorldPosition());
    flyEvent->SetWorldOrientation(edd->GetWorldOrientation());
    flyEvent->SetWorldDirection(edd->GetWorldDirection());

    // Fixed-speed forward flight: hand-tracking gestures have no analog throttle equivalent to
    // the physical thumbstick's deflection amount.
    //
    // \warning LastTrackPadPosition and LastDolly3DEventTime (vtkInteractorStyle3D) are shared
    // across ALL devices, not indexed per hand: if both hands are flying at once, their motion
    // vector-sums rather than being tracked independently per hand. Accepted as v1 behavior.
    self->LastTrackPadPosition[0] = 0.0;
    self->LastTrackPadPosition[1] = 1.0;

    interactor->InvokeEvent(vtkCommand::ViewerMovement3DEvent, flyEvent);
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
  bool isLeftHand, vtkEventDataDevice3D* edd)
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

  const double* wpos = edd->GetWorldPosition();
  actor->SetPosition(wpos[0], wpos[1], wpos[2]);
  const double* wori = edd->GetWorldOrientation();
  actor->SetOrientation(0.0, 0.0, 0.0);
  actor->RotateWXYZ(wori[0], wori[1], wori[2], wori[3]);
}
