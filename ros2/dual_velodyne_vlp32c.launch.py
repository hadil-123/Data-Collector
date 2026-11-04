#!/usr/bin/env python3
"""Launch two Velodyne VLP-32C stacks with separated namespaces/topics."""

import os
import yaml

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch.substitutions import PythonExpression
from launch_ros.actions import Node


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_stack(namespace, device_ip_cfg, frame_id_cfg, calibration_cfg, condition=None):
    driver_share = get_package_share_directory("velodyne_driver")
    driver_defaults = _load_yaml(
        os.path.join(driver_share, "config", "VLP32C-velodyne_driver_node-params.yaml")
    )["velodyne_driver_node"]["ros__parameters"]

    pointcloud_share = get_package_share_directory("velodyne_pointcloud")
    pointcloud_defaults = _load_yaml(
        os.path.join(pointcloud_share, "config", "VLP32C-velodyne_transform_node-params.yaml")
    )["velodyne_transform_node"]["ros__parameters"]

    laserscan_share = get_package_share_directory("velodyne_laserscan")
    laserscan_defaults = _load_yaml(
        os.path.join(laserscan_share, "config", "default-velodyne_laserscan_node-params.yaml")
    )["velodyne_laserscan_node"]["ros__parameters"]

    pointcloud_defaults["calibration"] = calibration_cfg

    driver_params = dict(driver_defaults)
    driver_params["device_ip"] = device_ip_cfg
    driver_params["frame_id"] = frame_id_cfg

    # Explicit remaps avoid collisions even if upstream nodes use absolute topic names.
    remaps = [
        ("/velodyne_packets", f"/{namespace}/velodyne_packets"),
        ("/velodyne_points", f"/{namespace}/velodyne_points"),
        ("/scan", f"/{namespace}/scan"),
    ]

    return [
        Node(
            package="velodyne_driver",
            executable="velodyne_driver_node",
            name="velodyne_driver_node",
            namespace=namespace,
            output="screen",
            parameters=[driver_params],
            remappings=remaps,
            condition=condition,
        ),
        Node(
            package="velodyne_pointcloud",
            executable="velodyne_transform_node",
            name="velodyne_transform_node",
            namespace=namespace,
            output="screen",
            parameters=[pointcloud_defaults],
            remappings=remaps,
            condition=condition,
        ),
        Node(
            package="velodyne_laserscan",
            executable="velodyne_laserscan_node",
            name="velodyne_laserscan_node",
            namespace=namespace,
            output="screen",
            parameters=[laserscan_defaults],
            remappings=remaps,
            condition=condition,
        ),
    ]


def generate_launch_description():
    pointcloud_share = get_package_share_directory("velodyne_pointcloud")
    default_calib = os.path.join(pointcloud_share, "params", "VeloView-VLP-32C.yaml")

    ip_a = LaunchConfiguration("ip_a")
    ip_b = LaunchConfiguration("ip_b")
    frame_a = LaunchConfiguration("frame_a")
    frame_b = LaunchConfiguration("frame_b")
    calib_a = LaunchConfiguration("calibration_a")
    calib_b = LaunchConfiguration("calibration_b")

    ld = LaunchDescription(
        [
            DeclareLaunchArgument("ip_a", default_value="192.168.1.202"),
            DeclareLaunchArgument("ip_b", default_value=""),
            DeclareLaunchArgument("frame_a", default_value="lidar_a"),
            DeclareLaunchArgument("frame_b", default_value="lidar_b"),
            DeclareLaunchArgument("calibration_a", default_value=default_calib),
            DeclareLaunchArgument("calibration_b", default_value=default_calib),
        ]
    )

    for node in _build_stack("lidar_a", ip_a, frame_a, calib_a):
        ld.add_action(node)
    sensor_b_condition = IfCondition(PythonExpression(["'", ip_b, "' != ''"]))
    for node in _build_stack("lidar_b", ip_b, frame_b, calib_b, sensor_b_condition):
        ld.add_action(node)

    return ld

