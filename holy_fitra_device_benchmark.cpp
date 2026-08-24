#include "holy_fitra_device_benchmark.h"

#include "holy_fitra_android_topology.h"
#include "holy_fitra_ragged_scheduler.h"
#include "holy_fitra_streamed_neon.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <dirent.h>
#include <fstream>
#include <limits>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>

namespace holyfitra {
namespace {

constexpr int32_t kMaxBenchmarkDModel = 8192;
constexpr int32_t kMaxBenchmarkSequences = 4096;
constexpr int32_t kMaxBenchmarkLength = 4096;
constexpr uint64_t kMaxBenchmarkTokens = 1u << 22;
constexpr uint64_t kMaxBenchmarkElements = 1u << 27;

struct ThermalSample {
    double max_temp_c = std::numeric_limits<double>::quiet_NaN();
    double avg_temp_c = std::numeric_limits<double>::quiet_NaN();
    double max_current_freq_mhz = std::numeric_limits<double>::quiet_NaN();
    double min_current_freq_mhz = std::numeric_limits<double>::quiet_NaN();
    bool valid = false;
};

struct PackedWorkload {
    std::vector<float> q;
    std::vector<float> k;
    std::vector<float> v;
    std::vector<float> output;
    std::vector<int32_t> offsets;
    int32_t d_model = 0;
    int32_t sequence_count = 0;
};

static uint64_t next_random(uint64_t &state) {
    state ^= state << 13;
    state ^= state >> 7;
    state ^= state << 17;
    return state;
}

static double uniform01(uint64_t &state) {
    return static_cast<double>(next_random(state) & 0xFFFFFFu) / static_cast<double>(0x1000000u);
}

static std::string json_escape(const std::string &value) {
    std::string output;
    output.reserve(value.size() + 8);
    for (char c : value) {
        if (c == '\\' || c == '"') { output.push_back('\\'); output.push_back(c); }
        else if (c == '\n') output += "\\n";
        else output.push_back(c);
    }
    return output;
}

static bool read_double_file(const std::string &path, double &value) {
    std::ifstream file(path);
    double raw = 0.0;
    if (!(file >> raw)) return false;
    value = raw;
    return true;
}

static ThermalSample sample_thermal() {
    DIR *directory = opendir("/sys/class/thermal");
    if (!directory) directory = opendir("/sys/devices/virtual/thermal");
    if (!directory) return {};
    double max_temp = -std::numeric_limits<double>::infinity();
    double sum_temp = 0.0;
    int temp_count = 0;
    struct dirent *entry = nullptr;
    while ((entry = readdir(directory)) != nullptr) {
        if (std::strncmp(entry->d_name, "thermal_zone", 11) != 0) continue;
        const std::string base = std::string("/sys/class/thermal/") + entry->d_name;
        double temp = 0.0;
        if (!read_double_file(base + "/temp", temp)) continue;
        if (temp > 1000.0) temp /= 1000.0;
        if (temp < -40.0 || temp > 150.0) continue;
        max_temp = std::max(max_temp, temp);
        sum_temp += temp;
        ++temp_count;
    }
    closedir(directory);
    double max_freq = -std::numeric_limits<double>::infinity();
    double min_freq = std::numeric_limits<double>::infinity();
    for (int cpu = 0; cpu < 64; ++cpu) {
        double freq = 0.0;
        const std::string path = "/sys/devices/system/cpu/cpu" + std::to_string(cpu) + "/cpufreq/scaling_cur_freq";
        if (!read_double_file(path, freq)) continue;
        if (freq > 10000.0) freq /= 1000.0;
        max_freq = std::max(max_freq, freq);
        min_freq = std::min(min_freq, freq);
    }
    ThermalSample sample;
    sample.valid = temp_count > 0 || std::isfinite(max_freq);
    if (temp_count > 0) {
        sample.max_temp_c = max_temp;
        sample.avg_temp_c = sum_temp / static_cast<double>(temp_count);
    }
    if (std::isfinite(max_freq)) sample.max_current_freq_mhz = max_freq;
    if (std::isfinite(min_freq)) sample.min_current_freq_mhz = min_freq;
    return sample;
}

static ThermalState thermal_state_for(const ThermalSample &sample) {
    if (!sample.valid || !std::isfinite(sample.max_temp_c)) return ThermalState::Normal;
    if (sample.max_temp_c >= 90.0) return ThermalState::Critical;
    if (sample.max_temp_c >= 80.0) return ThermalState::Hot;
    if (sample.max_temp_c >= 70.0) return ThermalState::Warm;
    return ThermalState::Normal;
}

static PackedWorkload make_workload(const DeviceBenchmarkConfig &config) {
    PackedWorkload workload;
    workload.d_model = config.d_model;
    workload.sequence_count = config.sequence_count;
    workload.offsets.resize(static_cast<size_t>(config.sequence_count) + 1, 0);
    uint64_t random_state = config.seed;
    for (int32_t sequence = 0; sequence < config.sequence_count; ++sequence) {
        const int64_t range = static_cast<int64_t>(config.max_length) - static_cast<int64_t>(config.min_length) + 1;
        const int32_t length = config.min_length + static_cast<int32_t>(next_random(random_state) % static_cast<uint64_t>(range));
        workload.offsets[static_cast<size_t>(sequence + 1)] = workload.offsets[static_cast<size_t>(sequence)] + length;
    }
    const size_t total_tokens = static_cast<size_t>(workload.offsets.back());
    if (total_tokens > kMaxBenchmarkTokens || static_cast<uint64_t>(total_tokens) > static_cast<uint64_t>(kMaxBenchmarkElements) / static_cast<uint64_t>(config.d_model)) throw std::runtime_error("benchmark workload exceeds resource limit");
    const size_t elements = total_tokens * static_cast<size_t>(config.d_model);
    workload.q.resize(elements);
    workload.k.resize(elements);
    workload.v.resize(elements);
    workload.output.resize(elements, 0.0f);
    for (size_t index = 0; index < elements; ++index) {
        workload.q[index] = static_cast<float>(uniform01(random_state) * 2.0 - 1.0);
        workload.k[index] = static_cast<float>(uniform01(random_state) * 2.0 - 1.0);
        workload.v[index] = static_cast<float>(uniform01(random_state) * 2.0 - 1.0);
    }
    return workload;
}

static double percentile_ns(std::vector<uint64_t> values, double percentile) {
    if (values.empty()) return std::numeric_limits<double>::quiet_NaN();
    std::sort(values.begin(), values.end());
    const double position = percentile * static_cast<double>(values.size() - 1);
    const size_t lower = static_cast<size_t>(position);
    const size_t upper = std::min(values.size() - 1, lower + 1);
    const double fraction = position - static_cast<double>(lower);
    return static_cast<double>(values[lower]) * (1.0 - fraction) + static_cast<double>(values[upper]) * fraction;
}

static std::string json_double(double value) {
    if (!std::isfinite(value)) return "null";
    std::ostringstream stream;
    stream << value;
    return stream.str();
}

static const char *wait_status_name(RaggedWaitStatus status) {
    switch (status) {
        case RaggedWaitStatus::Completed: return "completed";
        case RaggedWaitStatus::Cancelled: return "cancelled";
        case RaggedWaitStatus::DeadlineMissed: return "deadline_missed";
        case RaggedWaitStatus::Timeout: return "timeout";
        default: return "failed";
    }
}

static bool has_cpu_flag(const char *needle) {
    std::ifstream file("/proc/cpuinfo");
    std::string line;
    while (std::getline(file, line)) if (line.find(needle) != std::string::npos) return true;
    return false;
}

struct StreamedLatencySummary {
    double mean_ms = std::numeric_limits<double>::quiet_NaN();
    double p50_ms = std::numeric_limits<double>::quiet_NaN();
    double p95_ms = std::numeric_limits<double>::quiet_NaN();
    double p99_ms = std::numeric_limits<double>::quiet_NaN();
    double macc_per_second = std::numeric_limits<double>::quiet_NaN();
};

static StreamedLatencySummary summarize_streamed_latencies(const std::vector<uint64_t> &latencies, uint64_t multiply_accumulates) {
    StreamedLatencySummary summary;
    if (latencies.empty()) return summary;
    const double total_ns = std::accumulate(latencies.begin(), latencies.end(), 0.0);
    summary.mean_ms = total_ns / static_cast<double>(latencies.size()) / 1e6;
    summary.p50_ms = percentile_ns(latencies, 0.50) / 1e6;
    summary.p95_ms = percentile_ns(latencies, 0.95) / 1e6;
    summary.p99_ms = percentile_ns(latencies, 0.99) / 1e6;
    summary.macc_per_second = total_ns > 0.0 ? static_cast<double>(multiply_accumulates) * static_cast<double>(latencies.size()) / (total_ns / 1e9) : std::numeric_limits<double>::quiet_NaN();
    return summary;
}

static void append_streamed_summary(std::ostringstream &json, const char *name, const StreamedLatencySummary &summary) {
    json << ",\"" << name << "\":{\"latency_ms\":{\"mean\":" << json_double(summary.mean_ms) << ",\"p50\":" << json_double(summary.p50_ms) << ",\"p95\":" << json_double(summary.p95_ms) << ",\"p99\":" << json_double(summary.p99_ms) << "},\"throughput_macc_per_second\":" << json_double(summary.macc_per_second) << "}";
}

} // namespace

DeviceBenchmarkResult run_holy_fitra_device_benchmark(const DeviceBenchmarkConfig &config) {
    DeviceBenchmarkResult result;
    if (config.d_model <= 0 || config.d_model > kMaxBenchmarkDModel || config.sequence_count <= 0 || config.sequence_count > kMaxBenchmarkSequences || config.min_length <= 0 || config.max_length < config.min_length || config.max_length > kMaxBenchmarkLength || static_cast<uint64_t>(config.sequence_count) * static_cast<uint64_t>(config.max_length) > kMaxBenchmarkTokens || config.sequences_per_task <= 0 || config.sequences_per_task > config.sequence_count || config.warmup_iterations < 0 || config.warmup_iterations > 10000 || config.measured_iterations <= 0 || config.measured_iterations > 10000 || config.thermal_sample_period <= 0 || config.thermal_sample_period > 100000) {
        result.json = "{\"completed\":false,\"error\":\"invalid_config\"}";
        return result;
    }

    const AndroidTopology topology = detect_android_topology();
    SchedulerConfig scheduler_config = tuned_android_scheduler_config(topology, 256, config.pin_threads);
    Scheduler scheduler(scheduler_config);
    PackedWorkload workload = make_workload(config);
    hf_ragged_attention_batch batch{workload.q.data(), workload.q.size(), workload.k.data(), workload.k.size(), workload.v.data(), workload.v.size(), workload.output.data(), workload.output.size(), workload.offsets.data(), workload.offsets.size(), workload.sequence_count, workload.d_model};
#if defined(__aarch64__)
    const bool has_neon = has_cpu_flag("asimd") || has_cpu_flag("neon");
#else
    const bool has_neon = false;
#endif
    const bool has_sve = has_cpu_flag(" sve") || has_cpu_flag(" sve2");
    RaggedKernelKind kernel = choose_ragged_kernel(has_sve, has_neon, config.d_model, false, true);
    const uint64_t estimated_work = static_cast<uint64_t>(workload.offsets.back()) * static_cast<uint64_t>(workload.offsets.back()) * static_cast<uint64_t>(config.d_model);
    RaggedDispatchPlan plan;
    plan.kernel = kernel;
    plan.priority = Priority::Throughput;
    plan.sequences_per_task = config.sequences_per_task;
    plan.core_class = choose_ragged_core(kernel, plan.priority, estimated_work, false);

    for (int32_t iteration = 0; iteration < config.warmup_iterations; ++iteration) {
        auto request = submit_ragged_attention(scheduler, batch, plan);
        if (!request) { scheduler.shutdown(); result.json = "{\"completed\":false,\"error\":\"warmup_submit_failed\"}"; return result; }
        if (request->wait(60000) != RaggedWaitStatus::Completed) { scheduler.shutdown(); result.json = "{\"completed\":false,\"error\":\"warmup_failed\"}"; return result; }
    }

    const SchedulerStats stats_before = scheduler.stats();
    const ThermalSample thermal_before = sample_thermal();
    std::vector<uint64_t> latencies;
    latencies.reserve(static_cast<size_t>(config.measured_iterations));
    std::vector<double> temperatures;
    std::vector<double> frequencies;
    temperatures.reserve(static_cast<size_t>(config.measured_iterations));
    frequencies.reserve(static_cast<size_t>(config.measured_iterations));
    uint64_t checksum_bits = 0;
    int32_t failures = 0;
    std::string last_status = "completed";

    for (int32_t iteration = 0; iteration < config.measured_iterations; ++iteration) {
        if (config.continuous_thermal_sampling && (iteration % std::max(1, config.thermal_sample_period) == 0)) {
            const ThermalSample sample = sample_thermal();
            if (sample.valid) {
                if (std::isfinite(sample.max_temp_c)) temperatures.push_back(sample.max_temp_c);
                if (std::isfinite(sample.max_current_freq_mhz)) frequencies.push_back(sample.max_current_freq_mhz);
                scheduler.set_thermal_state(thermal_state_for(sample));
                if (thermal_state_for(sample) == ThermalState::Critical) {
                    plan.core_class = CoreClass::LittlePreferred;
                    if (plan.kernel == RaggedKernelKind::Sve) plan.kernel = has_neon ? RaggedKernelKind::Neon : RaggedKernelKind::Scalar;
                }
            }
        }
        const uint64_t start_ns = monotonic_time_ns();
        auto request = submit_ragged_attention(scheduler, batch, plan);
        if (!request) { ++failures; last_status = "submit_failed"; continue; }
        const RaggedWaitStatus status = request->wait(60000);
        const uint64_t end_ns = monotonic_time_ns();
        last_status = wait_status_name(status);
        if (status == RaggedWaitStatus::Completed) {
            latencies.push_back(end_ns - start_ns);
            const uint32_t bits = static_cast<uint32_t>(workload.output[(static_cast<size_t>(iteration) * 17) % workload.output.size()] * 1000003.0f);
            checksum_bits ^= static_cast<uint64_t>(bits) + 0x9e3779b97f4a7c15ULL + (checksum_bits << 6) + (checksum_bits >> 2);
        } else {
            ++failures;
        }
    }

    const ThermalSample thermal_after = sample_thermal();
    const SchedulerStats stats_after = scheduler.stats();
    scheduler.shutdown();
    const uint64_t completed = stats_after.completed - stats_before.completed;
    const uint64_t submitted = stats_after.submitted - stats_before.submitted;
    const double p50 = percentile_ns(latencies, 0.50) / 1e6;
    const double p95 = percentile_ns(latencies, 0.95) / 1e6;
    const double p99 = percentile_ns(latencies, 0.99) / 1e6;
    const double mean = latencies.empty() ? std::numeric_limits<double>::quiet_NaN() : std::accumulate(latencies.begin(), latencies.end(), 0.0) / static_cast<double>(latencies.size()) / 1e6;
    const double total_seconds = std::accumulate(latencies.begin(), latencies.end(), 0.0) / 1e9;
    const double tokens = static_cast<double>(workload.offsets.back()) * static_cast<double>(latencies.size());
    const double tokens_per_second = total_seconds > 0.0 ? tokens / total_seconds : std::numeric_limits<double>::quiet_NaN();
    const bool frequency_drop = std::isfinite(thermal_before.max_current_freq_mhz) && std::isfinite(thermal_after.max_current_freq_mhz) && thermal_after.max_current_freq_mhz < thermal_before.max_current_freq_mhz * 0.90;
    const bool temperature_rise = std::isfinite(thermal_before.max_temp_c) && !temperatures.empty() && *std::max_element(temperatures.begin(), temperatures.end()) > thermal_before.max_temp_c + 5.0;

    result.completed = failures == 0 && !latencies.empty();
    std::ostringstream json;
    json << "{\"completed\":" << (result.completed ? "true" : "false");
    json << ",\"device_topology_source\":\"" << json_escape(topology.source) << "\"";
    json << ",\"measured_from_sysfs\":" << (topology.measured_from_sysfs ? "true" : "false");
    json << ",\"little_cores\":" << topology.little_cpus.size() << ",\"big_cores\":" << topology.big_cpus.size();
    json << ",\"d_model\":" << config.d_model << ",\"sequence_count\":" << config.sequence_count;
    json << ",\"total_tokens_per_batch\":" << workload.offsets.back() << ",\"min_length\":" << config.min_length << ",\"max_length\":" << config.max_length;
    json << ",\"warmup_iterations\":" << config.warmup_iterations << ",\"measured_iterations\":" << config.measured_iterations;
    json << ",\"kernel\":\"" << ragged_kernel_name(kernel) << "\"";
    json << ",\"has_neon\":" << (has_neon ? "true" : "false") << ",\"has_sve\":" << (has_sve ? "true" : "false");
    json << ",\"latency_ms\":{\"mean\":" << json_double(mean) << ",\"p50\":" << json_double(p50) << ",\"p95\":" << json_double(p95) << ",\"p99\":" << json_double(p99) << "}";
    json << ",\"throughput_tokens_per_second\":" << json_double(tokens_per_second);
    json << ",\"successful_iterations\":" << latencies.size() << ",\"failures\":" << failures;
    json << ",\"scheduler\":{\"submitted\":" << submitted << ",\"completed\":" << completed << ",\"cancelled\":" << (stats_after.cancelled - stats_before.cancelled) << ",\"deadline_missed\":" << (stats_after.deadline_missed - stats_before.deadline_missed) << ",\"rejected\":" << (stats_after.rejected - stats_before.rejected) << ",\"stolen\":" << (stats_after.stolen - stats_before.stolen) << "}";
    json << ",\"thermal\":{\"sample_count\":" << temperatures.size() << ",\"max_temp_c\":" << json_double(temperatures.empty() ? std::numeric_limits<double>::quiet_NaN() : *std::max_element(temperatures.begin(), temperatures.end())) << ",\"min_freq_mhz\":" << json_double(frequencies.empty() ? std::numeric_limits<double>::quiet_NaN() : *std::min_element(frequencies.begin(), frequencies.end())) << ",\"frequency_drop_detected\":" << (frequency_drop ? "true" : "false") << ",\"temperature_rise_detected\":" << (temperature_rise ? "true" : "false") << "}";
    json << ",\"last_status\":\"" << last_status << "\"";
    json << ",\"checksum\":" << checksum_bits << "}";
    result.json = json.str();
    return result;
}

StreamedBlockBenchmarkResult run_holy_fitra_streamed_block_benchmark(const StreamedBlockBenchmarkConfig &config) {
    StreamedBlockBenchmarkResult result;
    if (config.rows <= 0 || config.rows > HF_STREAMED_F32_MAX_ROWS || config.columns <= 0 || config.columns > HF_STREAMED_F32_MAX_COLUMNS || config.warmup_iterations < 0 || config.warmup_iterations > 10000 || config.measured_iterations <= 0 || config.measured_iterations > 10000 || config.thermal_sample_period <= 0 || config.thermal_sample_period > 100000) {
        result.json = "{\"schema\":\"holyfitra.streamed-block-benchmark/v1\",\"completed\":false,\"error\":\"invalid_config\"}";
        return result;
    }
    const size_t rows = static_cast<size_t>(config.rows);
    const size_t columns = static_cast<size_t>(config.columns);
    if (rows > std::numeric_limits<size_t>::max() / columns) {
        result.json = "{\"schema\":\"holyfitra.streamed-block-benchmark/v1\",\"completed\":false,\"error\":\"overflow\"}";
        return result;
    }
    std::vector<float> input(rows);
    std::vector<float> weights(rows * columns);
    std::vector<float> scalar_output(columns, 0.0f);
    std::vector<float> optimized_output(columns, 0.0f);
    uint64_t random_state = config.seed;
    for (float &value : input) value = static_cast<float>(uniform01(random_state) * 2.0 - 1.0);
    for (float &value : weights) value = static_cast<float>(uniform01(random_state) * 2.0 - 1.0);
    auto scalar = [&]() { return hf_streamed_f32_block_matvec_scalar(input.data(), input.size(), weights.data(), weights.size(), scalar_output.data(), scalar_output.size(), config.rows, config.columns, HF_STREAMED_F32_BLOCK_ABI); };
    auto optimized = [&]() { return hf_streamed_f32_block_matvec(input.data(), input.size(), weights.data(), weights.size(), optimized_output.data(), optimized_output.size(), config.rows, config.columns, HF_STREAMED_F32_BLOCK_ABI); };
    for (int32_t iteration = 0; iteration < config.warmup_iterations; ++iteration) {
        if (scalar() != HF_OK || optimized() != HF_OK) {
            result.json = "{\"schema\":\"holyfitra.streamed-block-benchmark/v1\",\"completed\":false,\"error\":\"warmup_failed\"}";
            return result;
        }
    }
    const ThermalSample thermal_before = sample_thermal();
    std::vector<uint64_t> scalar_latencies;
    std::vector<uint64_t> optimized_latencies;
    std::vector<double> temperatures;
    std::vector<double> frequencies;
    scalar_latencies.reserve(static_cast<size_t>(config.measured_iterations));
    optimized_latencies.reserve(static_cast<size_t>(config.measured_iterations));
    double max_abs_error = 0.0;
    double max_reference = 0.0;
    int32_t failures = 0;
    uint64_t checksum = 0;
    for (int32_t iteration = 0; iteration < config.measured_iterations; ++iteration) {
        if (config.continuous_thermal_sampling && iteration % config.thermal_sample_period == 0) {
            const ThermalSample sample = sample_thermal();
            if (std::isfinite(sample.max_temp_c)) temperatures.push_back(sample.max_temp_c);
            if (std::isfinite(sample.max_current_freq_mhz)) frequencies.push_back(sample.max_current_freq_mhz);
        }
        const bool optimized_first = (next_random(random_state) & 1u) != 0;
        auto timed = [](const auto &operation, std::vector<uint64_t> &latencies) {
            const uint64_t start = monotonic_time_ns();
            const hf_status status = operation();
            const uint64_t finish = monotonic_time_ns();
            if (status == HF_OK) latencies.push_back(finish - start);
            return status;
        };
        const hf_status first = optimized_first ? timed(optimized, optimized_latencies) : timed(scalar, scalar_latencies);
        const hf_status second = optimized_first ? timed(scalar, scalar_latencies) : timed(optimized, optimized_latencies);
        if (first != HF_OK || second != HF_OK) { ++failures; continue; }
        for (size_t index = 0; index < columns; ++index) {
            const double reference = std::abs(static_cast<double>(scalar_output[index]));
            const double error = std::abs(static_cast<double>(scalar_output[index]) - static_cast<double>(optimized_output[index]));
            max_reference = std::max(max_reference, reference);
            max_abs_error = std::max(max_abs_error, error);
            checksum ^= static_cast<uint64_t>(static_cast<int64_t>(optimized_output[index] * 1000003.0f) + static_cast<int64_t>(index));
        }
    }
    const ThermalSample thermal_after = sample_thermal();
    const double tolerance = 1e-4 * std::max(1.0, max_reference);
    const bool correct = max_abs_error <= tolerance;
    const StreamedLatencySummary scalar_summary = summarize_streamed_latencies(scalar_latencies, static_cast<uint64_t>(rows) * static_cast<uint64_t>(columns));
    const StreamedLatencySummary optimized_summary = summarize_streamed_latencies(optimized_latencies, static_cast<uint64_t>(rows) * static_cast<uint64_t>(columns));
    const double speedup = optimized_summary.mean_ms > 0.0 ? scalar_summary.mean_ms / optimized_summary.mean_ms : std::numeric_limits<double>::quiet_NaN();
    const bool frequency_drop = std::isfinite(thermal_before.max_current_freq_mhz) && std::isfinite(thermal_after.max_current_freq_mhz) && thermal_after.max_current_freq_mhz < thermal_before.max_current_freq_mhz * 0.90;
    const bool temperature_rise = std::isfinite(thermal_before.max_temp_c) && !temperatures.empty() && *std::max_element(temperatures.begin(), temperatures.end()) > thermal_before.max_temp_c + 5.0;
    result.completed = failures == 0 && correct && scalar_latencies.size() == static_cast<size_t>(config.measured_iterations) && optimized_latencies.size() == static_cast<size_t>(config.measured_iterations);
    std::ostringstream json;
    json << "{\"schema\":\"holyfitra.streamed-block-benchmark/v1\",\"completed\":" << (result.completed ? "true" : "false");
    json << ",\"rows\":" << config.rows << ",\"columns\":" << config.columns << ",\"warmup_iterations\":" << config.warmup_iterations << ",\"measured_iterations\":" << config.measured_iterations;
    json << ",\"has_neon\":" << (hf_streamed_f32_block_has_neon() ? "true" : "false") << ",\"optimized_backend\":\"" << (hf_streamed_f32_block_has_neon() ? "native-neon" : "native-scalar") << "\"";
    append_streamed_summary(json, "scalar", scalar_summary);
    append_streamed_summary(json, "optimized", optimized_summary);
    json << ",\"speedup_scalar_over_optimized\":" << json_double(speedup);
    json << ",\"correctness\":{\"max_abs_error\":" << json_double(max_abs_error) << ",\"tolerance\":" << json_double(tolerance) << ",\"pass\":" << (correct ? "true" : "false") << "}";
    json << ",\"successful_iterations\":{\"scalar\":" << scalar_latencies.size() << ",\"optimized\":" << optimized_latencies.size() << "},\"failures\":" << failures;
    json << ",\"thermal\":{\"sample_count\":" << temperatures.size() << ",\"max_temp_c\":" << json_double(temperatures.empty() ? std::numeric_limits<double>::quiet_NaN() : *std::max_element(temperatures.begin(), temperatures.end())) << ",\"min_freq_mhz\":" << json_double(frequencies.empty() ? std::numeric_limits<double>::quiet_NaN() : *std::min_element(frequencies.begin(), frequencies.end())) << ",\"frequency_drop_detected\":" << (frequency_drop ? "true" : "false") << ",\"temperature_rise_detected\":" << (temperature_rise ? "true" : "false") << "}";
    json << ",\"checksum\":" << checksum << "}";
    result.json = json.str();
    return result;
}

} // namespace holyfitra
