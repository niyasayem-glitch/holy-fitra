#include "holy_fitra_android_topology.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>

namespace holyfitra {
namespace {

long long read_number(const std::filesystem::path &path) {
    std::ifstream stream(path);
    long long value = -1;
    if (stream) stream >> value;
    return value;
}

std::vector<int> parse_cpu_list(const std::string &text) {
    constexpr int kMaxCpu = 4095;
    constexpr size_t kMaxCpus = 4096;
    std::vector<int> cpus;
    std::stringstream ranges(text);
    std::string item;
    while (std::getline(ranges, item, ',')) {
        const size_t dash = item.find('-');
        try {
            const int first = std::stoi(item.substr(0, dash));
            const int last = dash == std::string::npos ? first : std::stoi(item.substr(dash + 1));
            if (first < 0 || last < first || last > kMaxCpu || cpus.size() + static_cast<size_t>(last - first + 1) > kMaxCpus) return {};
            for (int cpu = first; cpu <= last; ++cpu) cpus.push_back(cpu);
        } catch (...) {
            return {};
        }
    }
    std::sort(cpus.begin(), cpus.end());
    cpus.erase(std::unique(cpus.begin(), cpus.end()), cpus.end());
    return cpus;
}

std::vector<int> online_cpus(const std::filesystem::path &root) {
    std::vector<int> cpus;
    std::ifstream online_file(root / "online");
    std::string online_text;
    if (online_file && std::getline(online_file, online_text)) cpus = parse_cpu_list(online_text);
    if (!cpus.empty()) return cpus;
    try {
        for (const auto &entry : std::filesystem::directory_iterator(root)) {
            const std::string name = entry.path().filename().string();
            if (name.rfind("cpu", 0) != 0 || name.size() <= 3) continue;
            try { cpus.push_back(std::stoi(name.substr(3))); } catch (...) {}
        }
    } catch (...) {
        cpus.clear();
    }
    std::sort(cpus.begin(), cpus.end());
    cpus.erase(std::unique(cpus.begin(), cpus.end()), cpus.end());
    if (cpus.size() > 4096) cpus.resize(4096);
    return cpus;
}

} // namespace

AndroidTopology detect_android_topology(const std::string &sysfs_root) {
    const std::filesystem::path root(sysfs_root);
    std::vector<int> cpus = online_cpus(root);
    if (cpus.empty()) {
        cpus = {0, 1, 2, 3, 4, 5, 6, 7};
    }
    struct Score { int cpu; long long value; };
    std::vector<Score> scores;
    bool capacity_found = false;
    bool frequency_found = false;
    for (int cpu : cpus) {
        const auto cpu_root = root / ("cpu" + std::to_string(cpu));
        long long value = read_number(cpu_root / "cpu_capacity");
        if (value >= 0) capacity_found = true;
        if (value < 0) {
            value = read_number(cpu_root / "cpufreq" / "cpuinfo_max_freq");
            if (value >= 0) frequency_found = true;
        }
        if (value < 0) value = 1;
        scores.push_back({cpu, value});
    }
    long long min_score = scores.front().value;
    long long max_score = scores.front().value;
    for (const auto &score : scores) {
        min_score = std::min(min_score, score.value);
        max_score = std::max(max_score, score.value);
    }
    AndroidTopology topology;
    topology.measured_from_sysfs = capacity_found || frequency_found;
    topology.source = capacity_found ? "cpu_capacity" : (frequency_found ? "cpuinfo_max_freq" : "fallback");
    const bool heterogeneous = max_score > static_cast<long long>(std::ceil(static_cast<double>(min_score) * 1.15));
    if (heterogeneous) {
        const long long threshold = min_score + static_cast<long long>((max_score - min_score) * 0.6);
        for (const auto &score : scores) {
            if (score.value >= threshold) topology.big_cpus.push_back(score.cpu);
            else topology.little_cpus.push_back(score.cpu);
        }
    } else {
        const size_t split = std::max<size_t>(1, scores.size() / 2);
        for (size_t index = 0; index < scores.size(); ++index) {
            if (index < split) topology.little_cpus.push_back(scores[index].cpu);
            else topology.big_cpus.push_back(scores[index].cpu);
        }
    }
    if (topology.big_cpus.empty()) topology.big_cpus.push_back(topology.little_cpus.back()), topology.little_cpus.pop_back();
    if (topology.little_cpus.empty()) topology.little_cpus.push_back(topology.big_cpus.front());
    return topology;
}

SchedulerConfig tuned_android_scheduler_config(const AndroidTopology &topology, size_t queue_capacity, bool pin_threads) {
    SchedulerConfig config;
    config.queue_capacity = queue_capacity;
    config.pin_threads = pin_threads;
    config.little_cpus = topology.little_cpus;
    config.big_cpus = topology.big_cpus;
    config.little_workers = std::max(1, static_cast<int>(topology.little_cpus.size() / 2));
    config.big_workers = std::max(1, std::min(2, static_cast<int>(topology.big_cpus.size())));
    return config;
}

} // namespace holyfitra
