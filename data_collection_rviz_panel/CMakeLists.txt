cmake_minimum_required(VERSION 3.16)
project(data_collection_rviz_panel)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(rviz_common REQUIRED)
find_package(rviz_rendering REQUIRED)
find_package(rviz_default_plugins REQUIRED)
find_package(Qt5 REQUIRED COMPONENTS Widgets Network)

add_executable(data_collection_rviz_panel
  src/main.cpp
  src/main_window.cpp
)
target_include_directories(data_collection_rviz_panel PRIVATE include)
target_link_libraries(data_collection_rviz_panel Qt5::Widgets Qt5::Network)
ament_target_dependencies(data_collection_rviz_panel
  rclcpp std_msgs sensor_msgs geometry_msgs tf2_ros
  rviz_common rviz_rendering rviz_default_plugins
)

install(TARGETS data_collection_rviz_panel DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(panel_contract test/test_panel_contract.py)
endif()

ament_package()
