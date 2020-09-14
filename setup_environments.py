import os
import pathlib

import numpy as np
from pydrake.multibody.parsing import Parser
from pydrake.multibody.plant import MultibodyPlant, AddMultibodyPlantSceneGraph
from pydrake.math import RigidTransform

from contact_aware_control.plan_runner.setup_three_link_arm import (
    robot_sdf_path, ground_sdf_path)

module_path = pathlib.Path(__file__).parent.absolute()


def CreatePlantFor2dArmWithFreeBox(builder):
    """
    :param builder: a DiagramBuilder object.
    :return:
    """
    # MultibodyPlant
    plant = MultibodyPlant(1e-3)
    _, scene_graph = AddMultibodyPlantSceneGraph(builder, plant=plant)
    parser = Parser(plant=plant, scene_graph=scene_graph)

    # Add ground
    parser.AddModelFromFile(ground_sdf_path)
    X_WG = RigidTransform.Identity()
    X_WG.set_translation([0, 0, -0.5])  # "ground"
    plant.WeldFrames(A=plant.world_frame(),
                     B=plant.GetFrameByName("ground"),
                     X_AB=X_WG)

    # Add Robot
    X_WR = RigidTransform()
    X_WR.set_translation([0, 0, 0.1])
    robot_model = parser.AddModelFromFile(robot_sdf_path)
    plant.WeldFrames(
        plant.world_frame(), plant.GetFrameByName("link_0"), X_WR)
    plant.mutable_gravity_field().set_gravity_vector([0, 0, 0])

    # Add object
    object_sdf_path = os.path.join(module_path, "models", "box.sdf")
    object_model = parser.AddModelFromFile(object_sdf_path)
    plant.Finalize()

    return (plant,
            scene_graph,
            robot_model,
            object_model)


def CreatePlantFor2dArmWith2dBox(builder):
    """
    This function should be called when constructing a Diagram in RobotSimulator.
    :param builder: a reference to the DiagramBuilder.
    :return:
    """
    # MultibodyPlant
    plant = MultibodyPlant(1e-3)
    _, scene_graph = AddMultibodyPlantSceneGraph(builder, plant=plant)
    parser = Parser(plant=plant, scene_graph=scene_graph)

    # Add ground
    parser.AddModelFromFile(ground_sdf_path)
    X_WG = RigidTransform.Identity()
    X_WG.set_translation([0, 0, -0.5])  # "ground"
    plant.WeldFrames(A=plant.world_frame(),
                     B=plant.GetFrameByName("ground"),
                     X_AB=X_WG)

    # Add robot.
    X_WR = RigidTransform()
    X_WR.set_translation([0, 0, 0.1])
    robot_model = parser.AddModelFromFile(robot_sdf_path)
    plant.WeldFrames(
        plant.world_frame(), plant.GetFrameByName("link_0"), X_WR)
    plant.mutable_gravity_field().set_gravity_vector([0, 0, 0])

    # Add object
    object_sdf_path = os.path.join(module_path, "models", "sphere_yz.sdf")
    object_model = parser.AddModelFromFile(object_sdf_path)
    plant.Finalize()

    return (plant,
            scene_graph,
            robot_model,
            object_model)


def CreatePlantFor2dGripper(builder):
    """
    This function should be called when constructing a Diagram in RobotSimulator.
    :param builder: a reference to the DiagramBuilder.
    :return:
    """
    # MultibodyPlant
    plant = MultibodyPlant(1e-3)
    _, scene_graph = AddMultibodyPlantSceneGraph(builder, plant=plant)
    parser = Parser(plant=plant, scene_graph=scene_graph)
    plant.mutable_gravity_field().set_gravity_vector([0, 0, 0])

    # Add ground
    parser.AddModelFromFile(ground_sdf_path)
    X_WG = RigidTransform.Identity()
    X_WG.set_translation([0, 0, -0.5])  # "ground"
    plant.WeldFrames(A=plant.world_frame(),
                     B=plant.GetFrameByName("ground"),
                     X_AB=X_WG)

    # Add robot.
    gripper_sdf_path = os.path.join(module_path, "models", "gripper.sdf")
    robot_model = parser.AddModelFromFile(gripper_sdf_path)

    # Add object
    object_sdf_path = os.path.join(module_path, "models", "sphere_yz.sdf")
    object_model = parser.AddModelFromFile(object_sdf_path)

    plant.Finalize()

    return (plant,
            scene_graph,
            robot_model,
            object_model)