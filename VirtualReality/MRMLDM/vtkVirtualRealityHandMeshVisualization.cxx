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

#include "vtkVirtualRealityHandMeshVisualization.h"

// VTK Rendering/OpenXR includes
#include <vtkOpenXR.h> // must come before XrExtensions.h (provides the XR_* extension guards)
#include <XrExtensions.h>
#include <vtkOpenXRManager.h>
#include <vtkOpenXRRenderWindow.h>
#include <vtkOpenXRUtilities.h>

// VTK includes
#include <vtkActor.h>
#include <vtkCellArray.h>
#include <vtkFloatArray.h>
#include <vtkMath.h>
#include <vtkMatrix4x4.h>
#include <vtkNew.h>
#include <vtkObjectFactory.h>
#include <vtkPointData.h>
#include <vtkPoints.h>
#include <vtkPolyData.h>
#include <vtkPolyDataMapper.h>
#include <vtkProperty.h>
#include <vtkRenderer.h>
#include <vtkSmartPointer.h>
#include <vtkWeakPointer.h>

// STD includes
#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>

//----------------------------------------------------------------------------
class vtkVirtualRealityHandMeshVisualization::vtkInternal
{
public:
  struct HandData
  {
    XrHandTrackerEXT HandTracker{ XR_NULL_HANDLE };

    // Static mesh data returned by xrGetHandMeshFB (bind pose / mesh space)
    std::vector<XrVector3f> BindPositions;
    std::vector<XrVector3f> BindNormals;
    std::vector<XrVector4sFB> BlendIndices;
    std::vector<XrVector4f> BlendWeights;
    // One inverse bind pose matrix per joint, used by linear blend skinning
    std::vector<std::array<double, 16>> InverseBindMatrices;

    // Rendering pipeline (points/normals are overwritten every frame)
    vtkSmartPointer<vtkPoints> Points;
    vtkSmartPointer<vtkFloatArray> Normals;
    vtkSmartPointer<vtkPolyData> PolyData;
    vtkSmartPointer<vtkActor> Actor;
  };

  bool InitializeHand(HandData& hand, XrHandEXT handType);
  void UpdateHand(HandData& hand, XrTime time, XrSpace baseSpace);
  void DestroyHand(HandData& hand);

  xr::ExtensionDispatchTable Extensions;
  bool Initialized{ false };
  bool Visibility{ true };
  vtkWeakPointer<vtkOpenXRRenderWindow> RenderWindow;
  vtkWeakPointer<vtkRenderer> Renderer;
  HandData Hands[2];
  vtkNew<vtkMatrix4x4> PhysicalToWorldMatrix;
};

//----------------------------------------------------------------------------
bool vtkVirtualRealityHandMeshVisualization::vtkInternal::InitializeHand(
  HandData& hand, XrHandEXT handType)
{
  vtkOpenXRManager& manager = vtkOpenXRManager::GetInstance();

  XrHandTrackerCreateInfoEXT trackerCreateInfo{ XR_TYPE_HAND_TRACKER_CREATE_INFO_EXT };
  trackerCreateInfo.hand = handType;
  trackerCreateInfo.handJointSet = XR_HAND_JOINT_SET_DEFAULT_EXT;
  if (!manager.XrCheckOutput(vtkOpenXRManager::WarningOutput,
        this->Extensions.xrCreateHandTrackerEXT(
          manager.GetSession(), &trackerCreateInfo, &hand.HandTracker),
        "Failed to create hand tracker"))
  {
    hand.HandTracker = XR_NULL_HANDLE;
    return false;
  }

  // Two-call idiom: query the element counts, then retrieve the mesh.
  XrHandTrackingMeshFB mesh{ XR_TYPE_HAND_TRACKING_MESH_FB };
  if (!manager.XrCheckOutput(vtkOpenXRManager::WarningOutput,
        this->Extensions.xrGetHandMeshFB(hand.HandTracker, &mesh),
        "Failed to query hand mesh element counts"))
  {
    return false;
  }
  if (mesh.jointCountOutput == 0 || mesh.vertexCountOutput == 0 || mesh.indexCountOutput == 0)
  {
    vtkWarningWithObjectMacro(nullptr, "Runtime returned an empty hand mesh");
    return false;
  }

  std::vector<XrPosef> jointBindPoses(mesh.jointCountOutput);
  std::vector<float> jointRadii(mesh.jointCountOutput);
  std::vector<XrHandJointEXT> jointParents(mesh.jointCountOutput);
  std::vector<XrVector2f> vertexUVs(mesh.vertexCountOutput);
  std::vector<int16_t> indices(mesh.indexCountOutput);
  hand.BindPositions.resize(mesh.vertexCountOutput);
  hand.BindNormals.resize(mesh.vertexCountOutput);
  hand.BlendIndices.resize(mesh.vertexCountOutput);
  hand.BlendWeights.resize(mesh.vertexCountOutput);

  mesh.jointCapacityInput = mesh.jointCountOutput;
  mesh.jointBindPoses = jointBindPoses.data();
  mesh.jointRadii = jointRadii.data();
  mesh.jointParents = jointParents.data();
  mesh.vertexCapacityInput = mesh.vertexCountOutput;
  mesh.vertexPositions = hand.BindPositions.data();
  mesh.vertexNormals = hand.BindNormals.data();
  mesh.vertexUVs = vertexUVs.data();
  mesh.vertexBlendIndices = hand.BlendIndices.data();
  mesh.vertexBlendWeights = hand.BlendWeights.data();
  mesh.indexCapacityInput = mesh.indexCountOutput;
  mesh.indices = indices.data();
  if (!manager.XrCheckOutput(vtkOpenXRManager::WarningOutput,
        this->Extensions.xrGetHandMeshFB(hand.HandTracker, &mesh),
        "Failed to retrieve hand mesh"))
  {
    return false;
  }

  hand.InverseBindMatrices.resize(mesh.jointCountOutput);
  vtkNew<vtkMatrix4x4> bindMatrix;
  for (uint32_t jointIndex = 0; jointIndex < mesh.jointCountOutput; ++jointIndex)
  {
    vtkOpenXRUtilities::SetMatrixFromXrPose(bindMatrix, jointBindPoses[jointIndex]);
    vtkMatrix4x4::Invert(bindMatrix->GetData(), hand.InverseBindMatrices[jointIndex].data());
  }

  hand.Points = vtkSmartPointer<vtkPoints>::New();
  hand.Points->SetDataTypeToFloat();
  hand.Points->SetNumberOfPoints(mesh.vertexCountOutput);
  hand.Normals = vtkSmartPointer<vtkFloatArray>::New();
  hand.Normals->SetName("Normals");
  hand.Normals->SetNumberOfComponents(3);
  hand.Normals->SetNumberOfTuples(mesh.vertexCountOutput);
  for (uint32_t vertexIndex = 0; vertexIndex < mesh.vertexCountOutput; ++vertexIndex)
  {
    const XrVector3f& position = hand.BindPositions[vertexIndex];
    const XrVector3f& normal = hand.BindNormals[vertexIndex];
    hand.Points->SetPoint(vertexIndex, position.x, position.y, position.z);
    hand.Normals->SetTuple3(vertexIndex, normal.x, normal.y, normal.z);
  }

  vtkNew<vtkCellArray> triangles;
  for (uint32_t index = 0; index + 2 < mesh.indexCountOutput; index += 3)
  {
    const vtkIdType triangle[3] = { static_cast<vtkIdType>(indices[index]),
      static_cast<vtkIdType>(indices[index + 1]), static_cast<vtkIdType>(indices[index + 2]) };
    triangles->InsertNextCell(3, triangle);
  }

  hand.PolyData = vtkSmartPointer<vtkPolyData>::New();
  hand.PolyData->SetPoints(hand.Points);
  hand.PolyData->GetPointData()->SetNormals(hand.Normals);
  hand.PolyData->SetPolys(triangles);

  vtkNew<vtkPolyDataMapper> mapper;
  mapper->SetInputData(hand.PolyData);

  hand.Actor = vtkSmartPointer<vtkActor>::New();
  hand.Actor->SetMapper(mapper);
  hand.Actor->GetProperty()->SetColor(0.83, 0.67, 0.56);
  hand.Actor->GetProperty()->SetAmbient(0.1);
  hand.Actor->GetProperty()->SetDiffuse(0.9);
  hand.Actor->GetProperty()->SetSpecular(0.1);
  // The hands follow the user: keep them out of the scene bounds so that they
  // do not affect ResetCamera/ResetCameraClippingRange, and make them
  // non-pickable so that they do not interfere with interaction.
  hand.Actor->UseBoundsOff();
  hand.Actor->PickableOff();
  // Hidden until the runtime reports valid tracking in UpdateHand()
  hand.Actor->VisibilityOff();

  return true;
}

//----------------------------------------------------------------------------
void vtkVirtualRealityHandMeshVisualization::vtkInternal::UpdateHand(
  HandData& hand, XrTime time, XrSpace baseSpace)
{
  if (hand.HandTracker == XR_NULL_HANDLE || hand.Actor == nullptr)
  {
    return;
  }

  std::array<XrHandJointLocationEXT, XR_HAND_JOINT_COUNT_EXT> jointLocations{};
  XrHandJointsLocateInfoEXT locateInfo{ XR_TYPE_HAND_JOINTS_LOCATE_INFO_EXT };
  locateInfo.baseSpace = baseSpace;
  locateInfo.time = time;
  XrHandJointLocationsEXT locations{ XR_TYPE_HAND_JOINT_LOCATIONS_EXT };
  locations.jointCount = static_cast<uint32_t>(jointLocations.size());
  locations.jointLocations = jointLocations.data();
  if (XR_FAILED(this->Extensions.xrLocateHandJointsEXT(hand.HandTracker, &locateInfo, &locations))
    || !locations.isActive)
  {
    hand.Actor->SetVisibility(false);
    return;
  }

  const uint32_t jointCount = std::min(
    static_cast<uint32_t>(hand.InverseBindMatrices.size()), locations.jointCount);
  constexpr XrSpaceLocationFlags requiredFlags =
    XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;

  // Skinning matrix per joint: joint pose (reference space) * inverse bind pose
  std::vector<std::array<double, 16>> skinningMatrices(jointCount);
  vtkNew<vtkMatrix4x4> jointMatrix;
  for (uint32_t jointIndex = 0; jointIndex < jointCount; ++jointIndex)
  {
    if ((jointLocations[jointIndex].locationFlags & requiredFlags) != requiredFlags)
    {
      // An untracked joint would distort the whole mesh: hide the hand instead
      hand.Actor->SetVisibility(false);
      return;
    }
    vtkOpenXRUtilities::SetMatrixFromXrPose(jointMatrix, jointLocations[jointIndex].pose);
    vtkMatrix4x4::Multiply4x4(jointMatrix->GetData(),
      hand.InverseBindMatrices[jointIndex].data(), skinningMatrices[jointIndex].data());
  }

  // Linear blend skinning of positions and normals (rigid joint transforms,
  // so the rotation part can be applied to normals directly)
  const vtkIdType vertexCount = static_cast<vtkIdType>(hand.BindPositions.size());
  for (vtkIdType vertexIndex = 0; vertexIndex < vertexCount; ++vertexIndex)
  {
    const XrVector3f& bindPosition = hand.BindPositions[vertexIndex];
    const XrVector3f& bindNormal = hand.BindNormals[vertexIndex];
    const XrVector4sFB& blendIndices = hand.BlendIndices[vertexIndex];
    const XrVector4f& blendWeights = hand.BlendWeights[vertexIndex];
    const int16_t jointIndices[4] = { blendIndices.x, blendIndices.y, blendIndices.z,
      blendIndices.w };
    const float weights[4] = { blendWeights.x, blendWeights.y, blendWeights.z, blendWeights.w };

    double position[3] = { 0.0, 0.0, 0.0 };
    double normal[3] = { 0.0, 0.0, 0.0 };
    for (int influence = 0; influence < 4; ++influence)
    {
      const float weight = weights[influence];
      if (weight <= 0.0f || jointIndices[influence] < 0
        || static_cast<uint32_t>(jointIndices[influence]) >= jointCount)
      {
        continue;
      }
      const double* m = skinningMatrices[jointIndices[influence]].data();
      position[0] += weight * (m[0] * bindPosition.x + m[1] * bindPosition.y + m[2] * bindPosition.z + m[3]);
      position[1] += weight * (m[4] * bindPosition.x + m[5] * bindPosition.y + m[6] * bindPosition.z + m[7]);
      position[2] += weight * (m[8] * bindPosition.x + m[9] * bindPosition.y + m[10] * bindPosition.z + m[11]);
      normal[0] += weight * (m[0] * bindNormal.x + m[1] * bindNormal.y + m[2] * bindNormal.z);
      normal[1] += weight * (m[4] * bindNormal.x + m[5] * bindNormal.y + m[6] * bindNormal.z);
      normal[2] += weight * (m[8] * bindNormal.x + m[9] * bindNormal.y + m[10] * bindNormal.z);
    }
    vtkMath::Normalize(normal);
    hand.Points->SetPoint(vertexIndex, position);
    hand.Normals->SetTuple3(vertexIndex, normal[0], normal[1], normal[2]);
  }
  hand.Points->Modified();
  hand.Normals->Modified();
  hand.PolyData->Modified();

  // Joint locations are in the XR reference space ("physical" space in VTK
  // terms): the user matrix maps them into world coordinates.
  hand.Actor->SetUserMatrix(this->PhysicalToWorldMatrix);
  hand.Actor->SetVisibility(this->Visibility);
}

//----------------------------------------------------------------------------
void vtkVirtualRealityHandMeshVisualization::vtkInternal::DestroyHand(HandData& hand)
{
  if (hand.HandTracker != XR_NULL_HANDLE && this->Extensions.xrDestroyHandTrackerEXT != nullptr)
  {
    this->Extensions.xrDestroyHandTrackerEXT(hand.HandTracker);
    hand.HandTracker = XR_NULL_HANDLE;
  }
  if (hand.Actor != nullptr && this->Renderer != nullptr)
  {
    this->Renderer->RemoveActor(hand.Actor);
  }
  hand.Actor = nullptr;
  hand.PolyData = nullptr;
  hand.Points = nullptr;
  hand.Normals = nullptr;
}

//----------------------------------------------------------------------------
vtkStandardNewMacro(vtkVirtualRealityHandMeshVisualization);

//----------------------------------------------------------------------------
vtkVirtualRealityHandMeshVisualization::vtkVirtualRealityHandMeshVisualization()
{
  this->Internal = new vtkInternal();
}

//----------------------------------------------------------------------------
vtkVirtualRealityHandMeshVisualization::~vtkVirtualRealityHandMeshVisualization()
{
  this->Finalize();
  delete this->Internal;
  this->Internal = nullptr;
}

//----------------------------------------------------------------------------
void vtkVirtualRealityHandMeshVisualization::PrintSelf(ostream& os, vtkIndent indent)
{
  this->Superclass::PrintSelf(os, indent);
  os << indent << "Initialized: " << this->Internal->Initialized << "\n";
  os << indent << "Visibility: " << this->Internal->Visibility << "\n";
}

//----------------------------------------------------------------------------
bool vtkVirtualRealityHandMeshVisualization::Initialize(
  vtkOpenXRRenderWindow* renderWindow, vtkRenderer* renderer)
{
  if (this->Internal->Initialized)
  {
    return true;
  }
  if (renderWindow == nullptr || renderer == nullptr)
  {
    vtkErrorMacro("Initialize: render window and renderer must be set");
    return false;
  }

  vtkOpenXRManager& manager = vtkOpenXRManager::GetInstance();
  if (manager.GetSession() == XR_NULL_HANDLE)
  {
    vtkErrorMacro("Initialize: the OpenXR session has not been created yet");
    return false;
  }
  if (!manager.IsHandTrackingMeshSupported())
  {
    vtkDebugMacro("Initialize: XR_FB_hand_tracking_mesh is not supported by the runtime");
    return false;
  }

  this->Internal->Extensions.PopulateDispatchTable(manager.GetXrRuntimeInstance());
  if (this->Internal->Extensions.xrCreateHandTrackerEXT == nullptr
    || this->Internal->Extensions.xrLocateHandJointsEXT == nullptr
    || this->Internal->Extensions.xrGetHandMeshFB == nullptr)
  {
    vtkWarningMacro("Initialize: failed to load hand tracking extension functions");
    return false;
  }

  this->Internal->RenderWindow = renderWindow;
  this->Internal->Renderer = renderer;

  const XrHandEXT handTypes[2] = { XR_HAND_LEFT_EXT, XR_HAND_RIGHT_EXT };
  bool anyHandInitialized = false;
  for (int handIndex = 0; handIndex < 2; ++handIndex)
  {
    vtkInternal::HandData& hand = this->Internal->Hands[handIndex];
    if (this->Internal->InitializeHand(hand, handTypes[handIndex]))
    {
      renderer->AddActor(hand.Actor);
      anyHandInitialized = true;
    }
    else
    {
      this->Internal->DestroyHand(hand);
    }
  }
  if (!anyHandInitialized)
  {
    vtkWarningMacro("Initialize: could not retrieve any hand mesh from the runtime");
    return false;
  }

  this->Internal->Initialized = true;
  return true;
}

//----------------------------------------------------------------------------
bool vtkVirtualRealityHandMeshVisualization::IsInitialized()
{
  return this->Internal->Initialized;
}

//----------------------------------------------------------------------------
void vtkVirtualRealityHandMeshVisualization::Finalize()
{
  for (vtkInternal::HandData& hand : this->Internal->Hands)
  {
    this->Internal->DestroyHand(hand);
  }
  this->Internal->RenderWindow = nullptr;
  this->Internal->Renderer = nullptr;
  this->Internal->Initialized = false;
}

//----------------------------------------------------------------------------
void vtkVirtualRealityHandMeshVisualization::Update()
{
  if (!this->Internal->Initialized || this->Internal->RenderWindow == nullptr)
  {
    return;
  }
  vtkOpenXRManager& manager = vtkOpenXRManager::GetInstance();
  if (!manager.IsSessionRunning())
  {
    return;
  }
  const XrTime time = manager.GetPredictedDisplayTime();
  if (time == 0)
  {
    // No frame has been started yet
    return;
  }
  this->Internal->RenderWindow->GetPhysicalToWorldMatrix(this->Internal->PhysicalToWorldMatrix);
  for (vtkInternal::HandData& hand : this->Internal->Hands)
  {
    this->Internal->UpdateHand(hand, time, manager.GetReferenceSpace());
  }
}

//----------------------------------------------------------------------------
void vtkVirtualRealityHandMeshVisualization::SetVisibility(bool visibility)
{
  if (this->Internal->Visibility == visibility)
  {
    return;
  }
  this->Internal->Visibility = visibility;
  if (!visibility)
  {
    // Hide immediately; showing again is handled by the next Update()
    for (vtkInternal::HandData& hand : this->Internal->Hands)
    {
      if (hand.Actor != nullptr)
      {
        hand.Actor->SetVisibility(false);
      }
    }
  }
  this->Modified();
}

//----------------------------------------------------------------------------
bool vtkVirtualRealityHandMeshVisualization::GetVisibility()
{
  return this->Internal->Visibility;
}
