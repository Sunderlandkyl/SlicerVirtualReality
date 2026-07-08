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

==============================================================================*/

#ifndef vtkVirtualRealityHandMeshVisualization_h
#define vtkVirtualRealityHandMeshVisualization_h

// VR MRMLDM includes
#include "vtkSlicerVirtualRealityModuleMRMLDisplayableManagerExport.h"

// VTK includes
#include <vtkObject.h>

class vtkOpenXRRenderWindow;
class vtkRenderer;

/// \brief Display tracked hands in the VR view using XR_FB_hand_tracking_mesh.
///
/// Retrieves the runtime-provided skinned hand mesh for each hand
/// (XR_FB_hand_tracking_mesh) and animates it every frame with the joint
/// locations reported by XR_EXT_hand_tracking, using linear blend skinning
/// on the CPU. One actor per hand is added to the renderer; a hand is only
/// shown while the runtime reports valid tracking for it (on Meta Quest this
/// is when the controllers are set down and the hands are in view).
class VTK_SLICER_VIRTUALREALITY_MODULE_MRMLDISPLAYABLEMANAGER_EXPORT vtkVirtualRealityHandMeshVisualization
  : public vtkObject
{
public:
  static vtkVirtualRealityHandMeshVisualization* New();
  vtkTypeMacro(vtkVirtualRealityHandMeshVisualization, vtkObject);
  void PrintSelf(ostream& os, vtkIndent indent) override;

  /// Create the hand trackers, retrieve the skinned hand meshes from the
  /// runtime and add one actor per hand to the renderer.
  /// The OpenXR session must already exist (render window VR initialized).
  /// Returns false if XR_FB_hand_tracking_mesh is not supported by the
  /// runtime/system or if no hand mesh could be retrieved.
  bool Initialize(vtkOpenXRRenderWindow* renderWindow, vtkRenderer* renderer);

  /// True after a successful Initialize() and until Finalize().
  bool IsInitialized();

  /// Destroy the hand trackers and remove the hand actors from the renderer.
  /// Safe to call even if Initialize() was never called or failed.
  void Finalize();

  /// Locate the hand joints for the current predicted display time and update
  /// the skinned hand meshes. Hands are hidden while they are not tracked.
  /// Call once per frame, before rendering.
  void Update();

  ///@{
  /// Show/hide the hand meshes (tracked hands only). Visible by default.
  void SetVisibility(bool visibility);
  bool GetVisibility();
  ///@}

protected:
  vtkVirtualRealityHandMeshVisualization();
  ~vtkVirtualRealityHandMeshVisualization() override;

private:
  vtkVirtualRealityHandMeshVisualization(const vtkVirtualRealityHandMeshVisualization&) = delete;
  void operator=(const vtkVirtualRealityHandMeshVisualization&) = delete;

  class vtkInternal;
  vtkInternal* Internal;
};

#endif
