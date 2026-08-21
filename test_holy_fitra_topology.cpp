#include "holy_fitra_android_topology.h"
#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <thread>

using namespace holyfitra;

static void write_number(const std::filesystem::path &path, int value) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream stream(path);
    stream << value;
}

int main() {
    const std::filesystem::path root = std::filesystem::temp_directory_path() / "holyfitra_topology_test";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    for (int cpu = 0; cpu < 8; ++cpu) {
        std::filesystem::create_directories(root / ("cpu" + std::to_string(cpu)));
        write_number(root / ("cpu" + std::to_string(cpu)) / "cpu_capacity", cpu < 6 ? 300 : 1024);
    }
    AndroidTopology topology = detect_android_topology(root.string());
    assert(topology.measured_from_sysfs);
    assert(topology.source == "cpu_capacity");
    assert(topology.little_cpus.size() == 6);
    assert(topology.big_cpus.size() == 2);
    SchedulerConfig config = tuned_android_scheduler_config(topology, 32, false);
    assert(config.little_workers == 3);
    assert(config.big_workers == 2);
    std::filesystem::remove_all(root);

    Scheduler scheduler(config);
    scheduler.set_thermal_state(ThermalState::Critical);
    Task big_only;
    big_only.core_class = CoreClass::BigOnly;
    big_only.function = [](TaskContext &) {};
    assert(scheduler.submit(std::move(big_only)) == SubmitStatus::Rejected);
    Task preferred;
    preferred.core_class = CoreClass::BigPreferred;
    preferred.function = [](TaskContext &) {};
    assert(scheduler.submit(std::move(preferred)) == SubmitStatus::Accepted);
    scheduler.shutdown();
    return 0;
}
