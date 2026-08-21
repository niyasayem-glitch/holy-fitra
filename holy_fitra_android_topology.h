#ifndef HOLY_FITRA_ANDROID_TOPOLOGY_H
#define HOLY_FITRA_ANDROID_TOPOLOGY_H

#include "holy_fitra_dispatch.h"
#include <string>
#include <vector>

namespace holyfitra {

struct AndroidTopology {
    std::vector<int> little_cpus;
    std::vector<int> big_cpus;
    bool measured_from_sysfs = false;
    std::string source;
};

AndroidTopology detect_android_topology(const std::string &sysfs_root = "/sys/devices/system/cpu");
SchedulerConfig tuned_android_scheduler_config(const AndroidTopology &topology, size_t queue_capacity = 256, bool pin_threads = true);

} // namespace holyfitra

#endif
