from setuptools import setup

package_name = "robofleet_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools", "websockets"],
    zip_safe=True,
    maintainer="RoboFleet",
    maintainer_email="dev@local",
    description="Optional ROS 2 bridge for RoboFleet",
    license="MIT",
    entry_points={
        "console_scripts": [
            "bridge_node = robofleet_bridge.bridge_node:main",
        ],
    },
)
