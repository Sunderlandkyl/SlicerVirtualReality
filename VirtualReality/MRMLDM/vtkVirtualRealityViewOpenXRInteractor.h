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

#ifndef vtkVirtualRealityViewOpenXRInteractor_h
#define vtkVirtualRealityViewOpenXRInteractor_h

// VR MRMLDM includes
#include "vtkSlicerVirtualRealityModuleMRMLDisplayableManagerExport.h"
#include "vtkVirtualRealityComplexGestureRecognizer.h"

// VTK Rendering/OpenXR includes
#include <vtkOpenXRRenderWindowInteractor.h>

// VTK includes
#include <vtkNew.h>


class VTK_SLICER_VIRTUALREALITY_MODULE_MRMLDISPLAYABLEMANAGER_EXPORT vtkVirtualRealityViewOpenXRInteractor
  : public vtkOpenXRRenderWindowInteractor
{
public:
  static vtkVirtualRealityViewOpenXRInteractor *New();
  vtkTypeMacro(vtkVirtualRealityViewOpenXRInteractor,vtkOpenXRRenderWindowInteractor);

  ///@{
  /// Define Slicer specific heuristic for handling complex gestures.
  virtual void HandleComplexGestureEvents(vtkEventData* ed) override
  {
    this->ComplexGestureRecognizer->HandleComplexGestureEvents(ed);
  }
  virtual void RecognizeComplexGesture(vtkEventDataDevice3D* edata) override
  {
    this->ComplexGestureRecognizer->RecognizeComplexGesture(edata);
  }
  ///@}

  /// Retrieve the current pose of one of this interactor's OpenXR pose actions (e.g.
  /// "left_poke_pose") directly from its own action data. This is needed because the
  /// vtkEventDataDevice3D delivered with every dispatched action event always carries the
  /// "handpose" action's pose (see vtkOpenXRRenderWindowInteractor::PollXrActions(), which
  /// builds ONE event object per hand per frame from GetHandPose()), so the individual pose of
  /// any other pose action (poke, pinch, grip, ...) is not available from the event itself.
  /// \param actionName a pose action name declared in vtk_openxr_actions.json
  /// \param hand vtkOpenXRManager::ControllerIndex::Left or Right
  /// \param worldPosition pose position in world (scene) coordinates
  /// \param worldOrientationWXYZ pose orientation in world coordinates as angle-axis
  ///        (angle in degrees, then axis), same convention as vtkEventDataDevice3D
  /// \param physicalPosition pose position in physical (meters) coordinates, unaffected by the
  ///        scene magnification/physical scale -- use this for real-world distance measurements
  ///        such as gesture detection
  /// \param worldDirection pose -Z ("forward") axis in world coordinates
  /// \return false if the action is unknown, not a pose action, or its pose is not currently
  ///         valid (e.g. hand not tracked); output arrays are left unmodified in that case.
  bool GetActionPoseWorld(const std::string& actionName, uint32_t hand, double worldPosition[3],
    double worldOrientationWXYZ[4], double physicalPosition[3], double worldDirection[3]);

protected:
  vtkNew<vtkVirtualRealityComplexGestureRecognizer> ComplexGestureRecognizer;

private:
  vtkVirtualRealityViewOpenXRInteractor()
  {
    this->ComplexGestureRecognizer->SetInteractor(this);
  }
  ~vtkVirtualRealityViewOpenXRInteractor() override = default;

  vtkVirtualRealityViewOpenXRInteractor(const vtkVirtualRealityViewOpenXRInteractor&) = delete;
  void operator=(const vtkVirtualRealityViewOpenXRInteractor&) = delete;
};

#endif
