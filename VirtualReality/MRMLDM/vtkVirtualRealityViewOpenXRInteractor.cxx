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

// VTK Rendering/OpenXR includes
#include <vtkOpenXRManager.h>

// VTK includes
#include <vtkObjectFactory.h>

//------------------------------------------------------------------------------
vtkStandardNewMacro(vtkVirtualRealityViewOpenXRInteractor);

//------------------------------------------------------------------------------
bool vtkVirtualRealityViewOpenXRInteractor::GetActionPoseWorld(const std::string& actionName,
  uint32_t hand, double worldPosition[3], double worldOrientationWXYZ[4],
  double physicalPosition[3], double worldDirection[3])
{
  if (hand >= vtkOpenXRManager::ControllerIndex::NumberOfControllers)
  {
    return false;
  }
  ActionData* actionData = this->GetActionDataFromName(actionName);
  if (!actionData)
  {
    return false;
  }
  const XrSpaceLocation& location = actionData->ActionStruct.PoseLocations[hand];
  constexpr XrSpaceLocationFlags requiredFlags =
    XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;
  if ((location.locationFlags & requiredFlags) != requiredFlags)
  {
    return false;
  }
  this->ConvertOpenXRPoseToWorldCoordinates(
    location.pose, worldPosition, worldOrientationWXYZ, physicalPosition, worldDirection);
  return true;
}
