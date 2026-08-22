#include <jni.h>


#include <exception>

#include "holy_fitra_device_benchmark.h"

extern "C" JNIEXPORT jstring JNICALL
Java_com_holyfitra_benchmark_HolyFitraBenchmark_nativeRun(
        JNIEnv *env,
        jobject,
        jint d_model,
        jint sequence_count,
        jint min_length,
        jint max_length,
        jint sequences_per_task,
        jint warmup_iterations,
        jint measured_iterations,
        jlong seed,
        jboolean pin_threads,
        jint thermal_sample_period) {
    holyfitra::DeviceBenchmarkConfig config;
    config.d_model = static_cast<int32_t>(d_model);
    config.sequence_count = static_cast<int32_t>(sequence_count);
    config.min_length = static_cast<int32_t>(min_length);
    config.max_length = static_cast<int32_t>(max_length);
    config.sequences_per_task = static_cast<int32_t>(sequences_per_task);
    config.warmup_iterations = static_cast<int32_t>(warmup_iterations);
    config.measured_iterations = static_cast<int32_t>(measured_iterations);
    config.seed = static_cast<uint64_t>(seed);
    config.pin_threads = pin_threads == JNI_TRUE;
    config.thermal_sample_period = static_cast<int32_t>(thermal_sample_period);
    try {
        const holyfitra::DeviceBenchmarkResult result = holyfitra::run_holy_fitra_device_benchmark(config);
        return env->NewStringUTF(result.json.c_str());
    } catch (const std::bad_alloc &) {
        jclass clazz = env->FindClass("java/lang/OutOfMemoryError");
        if (clazz) env->ThrowNew(clazz, "Holy Fitra benchmark allocation failed");
        return nullptr;
    } catch (const std::exception &error) {
        jclass clazz = env->FindClass("java/lang/IllegalStateException");
        if (clazz) env->ThrowNew(clazz, error.what());
        return nullptr;
    }
}
