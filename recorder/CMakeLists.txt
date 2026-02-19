cmake_minimum_required(VERSION 3.14)
project(lidar_recorder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(recorder main.cpp pcap_writer.cpp bag_writer.cpp)
