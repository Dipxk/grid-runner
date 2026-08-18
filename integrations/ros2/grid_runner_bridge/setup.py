from setuptools import setup

package_name = "grid_runner_bridge"

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
    maintainer="Grid Runner",
    maintainer_email="dev@local",
    description="Optional ROS 2 bridge for Grid Runner",
    license="MIT",
    entry_points={
        "console_scripts": [
            "bridge_node = grid_runner_bridge.bridge_node:main",
        ],
    },
)
