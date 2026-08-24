package com.holyfitra.benchmark

import org.json.JSONObject

/** Android-facing runner for sustained Holy Fitra ragged-scheduler measurements. */
class HolyFitraBenchmark {
    companion object {
        init { System.loadLibrary("holyfitra_benchmark") }
    }

    data class Config(
        val dModel: Int = 64,
        val sequenceCount: Int = 16,
        val minLength: Int = 16,
        val maxLength: Int = 128,
        val sequencesPerTask: Int = 2,
        val warmupIterations: Int = 10,
        val measuredIterations: Int = 100,
        val seed: Long = 12345L,
        val pinThreads: Boolean = true,
        val thermalSamplePeriod: Int = 1,
    ) {
        fun validate() {
            require(dModel > 0 && dModel % 4 == 0) { "dModel must be positive and divisible by four" }
            require(sequenceCount > 0) { "sequenceCount must be positive" }
            require(minLength > 0 && maxLength >= minLength) { "invalid length range" }
            require(sequencesPerTask > 0) { "sequencesPerTask must be positive" }
            require(warmupIterations >= 0 && measuredIterations > 0) { "invalid iteration counts" }
            require(thermalSamplePeriod > 0) { "thermalSamplePeriod must be positive" }
        }
    }

    data class StreamedBlockConfig(
        val rows: Int = 64,
        val columns: Int = 64,
        val warmupIterations: Int = 20,
        val measuredIterations: Int = 200,
        val seed: Long = 12345L,
        val thermalSamplePeriod: Int = 1,
    ) {
        fun validate() {
            require(rows in 1..8192 && columns in 1..512) { "streamed block dimensions are outside native safety bounds" }
            require(warmupIterations >= 0 && measuredIterations > 0) { "invalid iteration counts" }
            require(thermalSamplePeriod > 0) { "thermalSamplePeriod must be positive" }
        }
    }

    /** Blocking entry point for a dedicated worker thread or instrumentation harness. */
    fun runSync(config: Config = Config()): Result {
        config.validate()
        val json = nativeRun(config.dModel, config.sequenceCount, config.minLength, config.maxLength,
            config.sequencesPerTask, config.warmupIterations, config.measuredIterations,
            config.seed, config.pinThreads, config.thermalSamplePeriod)
        return Result(json)
    }

    suspend fun run(config: Config = Config()): Result = runSync(config)

    /** Runs scalar and runtime-selected streamed float32 block paths in alternating order. */
    fun runStreamedBlockSync(config: StreamedBlockConfig = StreamedBlockConfig()): StreamedBlockResult {
        config.validate()
        return StreamedBlockResult(nativeRunStreamedBlock(config.rows, config.columns, config.warmupIterations, config.measuredIterations, config.seed, config.thermalSamplePeriod))
    }

    class Result(private val rawJson: String) {
        val json: JSONObject get() = JSONObject(rawJson)
        val completed: Boolean get() = json.optBoolean("completed", false)
        val p50Ms: Double get() = json.optJSONObject("latency_ms")?.optDouble("p50", Double.NaN) ?: Double.NaN
        val p95Ms: Double get() = json.optJSONObject("latency_ms")?.optDouble("p95", Double.NaN) ?: Double.NaN
        val p99Ms: Double get() = json.optJSONObject("latency_ms")?.optDouble("p99", Double.NaN) ?: Double.NaN
        val throughputTokensPerSecond: Double get() = json.optDouble("throughput_tokens_per_second", Double.NaN)
        val thermalThrottleDetected: Boolean
            get() = json.optJSONObject("thermal")?.let {
                it.optBoolean("frequency_drop_detected", false) || it.optBoolean("temperature_rise_detected", false)
            } ?: false
        fun toCsvRow(): String {
            return listOf(
                json.optString("device_topology_source"),
                json.optInt("d_model"),
                json.optInt("sequence_count"),
                json.optString("kernel"),
                p50Ms,
                p95Ms,
                p99Ms,
                throughputTokensPerSecond,
                thermalThrottleDetected,
                json.optInt("failures"),
            ).joinToString(",")
        }
        override fun toString(): String = rawJson
    }

    class StreamedBlockResult(private val rawJson: String) {
        val json: JSONObject get() = JSONObject(rawJson)
        val completed: Boolean get() = json.optBoolean("completed", false)
        val hasNeon: Boolean get() = json.optBoolean("has_neon", false)
        val optimizedBackend: String get() = json.optString("optimized_backend", "unknown")
        val speedupScalarOverOptimized: Double get() = json.optDouble("speedup_scalar_over_optimized", Double.NaN)
        val correctnessPass: Boolean get() = json.optJSONObject("correctness")?.optBoolean("pass", false) ?: false
        val thermalThrottleDetected: Boolean
            get() = json.optJSONObject("thermal")?.let {
                it.optBoolean("frequency_drop_detected", false) || it.optBoolean("temperature_rise_detected", false)
            } ?: false
        override fun toString(): String = rawJson
    }

    private external fun nativeRun(
        dModel: Int,
        sequenceCount: Int,
        minLength: Int,
        maxLength: Int,
        sequencesPerTask: Int,
        warmupIterations: Int,
        measuredIterations: Int,
        seed: Long,
        pinThreads: Boolean,
        thermalSamplePeriod: Int,
    ): String
    private external fun nativeRunStreamedBlock(rows: Int, columns: Int, warmupIterations: Int, measuredIterations: Int, seed: Long, thermalSamplePeriod: Int): String
}
