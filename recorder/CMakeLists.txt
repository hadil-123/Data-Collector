cmake_minimum_required(VERSION 3.14)
project(lidar_recorder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(recorder main.cpp pcap_writer.cpp bag_writer.cpp args.cpp packet_parse.cpp)

# Unit tests (Catch2) are opt-in: `cmake -S recorder -B recorder/build -DBUILD_TESTS=ON`.
# Off by default so a plain build of the recorder binary never needs Catch2
# installed.
option(BUILD_TESTS "Build the Catch2 unit test suite" OFF)
if(BUILD_TESTS)
    find_package(Catch2 3 REQUIRED)
    include(CTest)
    include(Catch)

    add_executable(recorder_tests
        tests/test_args.cpp
        tests/test_packet_parse.cpp
        tests/test_pcap_writer.cpp
        tests/test_bag_writer.cpp
        args.cpp
        packet_parse.cpp
        pcap_writer.cpp
        bag_writer.cpp
    )
    target_include_directories(recorder_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_link_libraries(recorder_tests PRIVATE Catch2::Catch2WithMain)
    catch_discover_tests(recorder_tests)
endif()
