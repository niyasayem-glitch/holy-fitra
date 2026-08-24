package org.holyfitra.app

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.holyfitra.benchmark.HolyFitraBenchmark
import org.holyfitra.NibbleFlow
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Local-first Android workbench for the packaged Holy Fitra native stack.
 * Native work is never run on the Android main thread.
 */
class MainActivity : Activity() {
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val running = AtomicBoolean(false)
    private lateinit var status: TextView
    private lateinit var result: TextView
    private lateinit var quickButton: Button
    private lateinit var sustainedButton: Button
    private lateinit var streamedButton: Button
    private lateinit var exportButton: Button
    private var lastReport: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        restoreLastReport()
    }

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(18), dp(20), dp(24))
            setBackgroundColor(getColorCompat(R.color.hf_background))
        }

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(root)
        }
        setContentView(scroll)

        root.addView(label("HOLY FITRA WORKBENCH", 13f, R.color.hf_primary))
        root.addView(label("Native work, measured honestly.", 26f, R.color.hf_text, top = 5))
        root.addView(label("A local ARM64 workbench for the packaged runtime and benchmark surfaces.", 15f, R.color.hf_text_muted, top = 8, bottom = 18))

        val capabilityCard = card()
        capabilityCard.addView(label("DEVICE CAPABILITY", 12f, R.color.hf_primary))
        capabilityCard.addView(label(capabilityText(), 15f, R.color.hf_text, top = 10))
        root.addView(capabilityCard, matchParams(top = 0, bottom = 14))

        status = label("Ready. No measurement has been run on this device yet.", 15f, R.color.hf_text, top = 0, bottom = 14)
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE)
        root.addView(status)

        quickButton = actionButton(getString(R.string.run_quick_check)) { runBenchmark(sustained = false) }
        sustainedButton = actionButton(getString(R.string.run_sustained_check)) { runBenchmark(sustained = true) }
        streamedButton = actionButton("Run streamed scalar vs NEON") { runStreamedBlockBenchmark() }
        exportButton = actionButton(getString(R.string.export_report)) { exportReport() }
        exportButton.isEnabled = false
        root.addView(quickButton, matchParams(bottom = 10))
        root.addView(sustainedButton, matchParams(bottom = 10))
        root.addView(streamedButton, matchParams(bottom = 10))
        root.addView(exportButton, matchParams(bottom = 18))

        result = label("No result yet.", 14f, R.color.hf_text_muted)
        result.setTextIsSelectable(true)
        root.addView(result, matchParams())
    }

    private fun runBenchmark(sustained: Boolean) {
        if (!running.compareAndSet(false, true)) return
        setButtonsEnabled(false)
        val measured = if (sustained) 2000 else 120
        val warmup = if (sustained) 30 else 10
        status.text = if (sustained) {
            "Running sustained native work… Keep the device conditions consistent."
        } else {
            "Running quick native check…"
        }
        status.setTextColor(getColorCompat(R.color.hf_warning))

        executor.execute {
            try {
                val benchmark = HolyFitraBenchmark().runSync(
                    HolyFitraBenchmark.Config(
                        dModel = 64,
                        sequenceCount = if (sustained) 32 else 16,
                        minLength = 16,
                        maxLength = if (sustained) 256 else 128,
                        sequencesPerTask = 2,
                        warmupIterations = warmup,
                        measuredIterations = measured,
                        seed = 12345L,
                        pinThreads = true,
                        thermalSamplePeriod = 1,
                    )
                )
                val report = envelope(benchmark, sustained)
                saveReport(report)
                runOnUiThread {
                    lastReport = report
                    status.text = if (benchmark.completed) "Completed on this device." else "Native run returned an incomplete result."
                    status.setTextColor(if (benchmark.completed) getColorCompat(R.color.hf_success) else getColorCompat(R.color.hf_error))
                    result.text = formatResult(benchmark)
                    exportButton.isEnabled = benchmark.completed
                    setButtonsEnabled(true)
                }
            } catch (error: Throwable) {
                runOnUiThread {
                    status.text = "Native run failed: ${error.message ?: error::class.java.simpleName}"
                    status.setTextColor(getColorCompat(R.color.hf_error))
                    result.text = "No new result was saved. The previous successful result remains available if one exists."
                    setButtonsEnabled(true)
                }
            } finally {
                running.set(false)
            }
        }
    }

    private fun runStreamedBlockBenchmark() {
        if (!running.compareAndSet(false, true)) return
        setButtonsEnabled(false)
        status.text = "Running streamed scalar versus runtime-selected block math… Keep device conditions consistent."
        status.setTextColor(getColorCompat(R.color.hf_warning))
        executor.execute {
            try {
                val benchmark = HolyFitraBenchmark().runStreamedBlockSync(
                    HolyFitraBenchmark.StreamedBlockConfig(rows = 256, columns = 128, warmupIterations = 30, measuredIterations = 300, seed = 12345L, thermalSamplePeriod = 1)
                )
                val report = streamedEnvelope(benchmark)
                saveReport(report)
                runOnUiThread {
                    lastReport = report
                    status.text = if (benchmark.completed) "Streamed block comparison completed on this device." else "Streamed block comparison returned an incomplete result."
                    status.setTextColor(if (benchmark.completed) getColorCompat(R.color.hf_success) else getColorCompat(R.color.hf_error))
                    result.text = formatStreamedResult(benchmark)
                    exportButton.isEnabled = benchmark.completed
                    setButtonsEnabled(true)
                }
            } catch (error: Throwable) {
                runOnUiThread {
                    status.text = "Streamed block comparison failed: ${error.message ?: error::class.java.simpleName}"
                    status.setTextColor(getColorCompat(R.color.hf_error))
                    result.text = "No new result was saved. The previous successful result remains available if one exists."
                    setButtonsEnabled(true)
                }
            } finally {
                running.set(false)
            }
        }
    }

    private fun capabilityText(): String {
        val abi = Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown"
        val neon = try { NibbleFlow.hasNeon().toString() } catch (_: Throwable) { "unavailable" }
        val abiVersion = try { NibbleFlow.abiVersion().toString() } catch (_: Throwable) { "unavailable" }
        return "ABI: $abi\nNEON reported: $neon\nNative ABI version: $abiVersion\nAndroid: ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})\nModel: ${Build.MANUFACTURER} ${Build.MODEL}"
    }

    private fun formatResult(benchmark: HolyFitraBenchmark.Result): String {
        val json = benchmark.json
        val latency = json.optJSONObject("latency_ms")
        val thermal = json.optJSONObject("thermal")
        return buildString {
            appendLine("LAST MEASUREMENT")
            appendLine("Kernel: ${json.optString("kernel", "unknown")}")
            appendLine("Topology source: ${json.optString("device_topology_source", "unknown")}")
            appendLine("p50: ${number(latency?.optDouble("p50"))} ms")
            appendLine("p95: ${number(latency?.optDouble("p95"))} ms")
            appendLine("p99: ${number(latency?.optDouble("p99"))} ms")
            appendLine("Throughput: ${number(json.optDouble("throughput_tokens_per_second"))} tokens/s")
            appendLine("Thermal signal: ${if (benchmark.thermalThrottleDetected) "detected" else "not detected by available sensors"}")
            appendLine("Maximum sampled temperature: ${number(thermal?.optDouble("max_temp_c"))} °C")
            appendLine("Failures: ${json.optInt("failures", -1)}")
            appendLine("Evidence note: this is a device-local measurement, not a universal performance claim.")
        }
    }

    private fun formatStreamedResult(benchmark: HolyFitraBenchmark.StreamedBlockResult): String {
        val json = benchmark.json
        val scalar = json.optJSONObject("scalar")?.optJSONObject("latency_ms")
        val optimized = json.optJSONObject("optimized")?.optJSONObject("latency_ms")
        val thermal = json.optJSONObject("thermal")
        return buildString {
            appendLine("STREAMED BLOCK COMPARISON")
            appendLine("Runtime-selected backend: ${benchmark.optimizedBackend}; NEON reported: ${benchmark.hasNeon}")
            appendLine("Block: ${json.optInt("rows")} × ${json.optInt("columns")}")
            appendLine("Scalar p50: ${number(scalar?.optDouble("p50"))} ms")
            appendLine("Optimized p50: ${number(optimized?.optDouble("p50"))} ms")
            appendLine("Scalar/optimized mean speedup: ${number(benchmark.speedupScalarOverOptimized)}×")
            appendLine("Numerical comparison: ${if (benchmark.correctnessPass) "pass" else "failed"}")
            appendLine("Thermal signal: ${if (benchmark.thermalThrottleDetected) "detected" else "not detected by available sensors"}")
            appendLine("Maximum sampled temperature: ${number(thermal?.optDouble("max_temp_c"))} °C")
            appendLine("Evidence note: this is a device-local comparison, not a universal performance claim.")
        }
    }

    private fun envelope(benchmark: HolyFitraBenchmark.Result, sustained: Boolean): String = JSONObject()
        .put("schema", "holyfitra.workbench.report.v1")
        .put("created_at", now())
        .put("device", capabilityText())
        .put("sustained", sustained)
        .put("benchmark", benchmark.json)
        .toString(2)

    private fun streamedEnvelope(benchmark: HolyFitraBenchmark.StreamedBlockResult): String = JSONObject()
        .put("schema", "holyfitra.workbench.report.v1")
        .put("created_at", now())
        .put("device", capabilityText())
        .put("benchmark_kind", "streamed_block_scalar_vs_optimized")
        .put("benchmark", benchmark.json)
        .toString(2)

    private fun saveReport(report: String) {
        val temporary = File(filesDir, "last_report.json.tmp")
        val destination = File(filesDir, "last_report.json")
        temporary.writeText(report)
        check(temporary.renameTo(destination)) { "could not persist report" }
    }

    private fun restoreLastReport() {
        val file = File(filesDir, "last_report.json")
        if (!file.isFile) return
        try {
            val raw = file.readText()
            val json = JSONObject(raw)
            lastReport = raw
            result.text = "LAST SAVED REPORT\nCreated: ${json.optString("created_at", "unknown")}\n\n${json.optJSONObject("benchmark")?.toString(2) ?: "Report data unavailable."}"
            status.text = "Restored the last local report. Run again to measure fresh conditions."
            status.setTextColor(getColorCompat(R.color.hf_text))
            exportButton.isEnabled = true
        } catch (_: Throwable) {
            file.delete()
        }
    }

    private fun exportReport() {
        val report = lastReport ?: File(filesDir, "last_report.json").takeIf { it.isFile }?.readText()
        if (report == null) {
            Toast.makeText(this, "Run a completed measurement first.", Toast.LENGTH_SHORT).show()
            return
        }
        val share = Intent(Intent.ACTION_SEND).apply {
            type = "application/json"
            putExtra(Intent.EXTRA_TEXT, report)
        }
        startActivity(Intent.createChooser(share, getString(R.string.export_report)))
    }

    private fun setButtonsEnabled(enabled: Boolean) {
        quickButton.isEnabled = enabled
        sustainedButton.isEnabled = enabled
        streamedButton.isEnabled = enabled
        exportButton.isEnabled = enabled && lastReport != null
    }

    private fun card(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(16), dp(15), dp(16), dp(15))
        setBackgroundColor(getColorCompat(R.color.hf_surface))
    }

    private fun actionButton(text: String, action: () -> Unit): Button = Button(this).apply {
        this.text = text
        minHeight = dp(48)
        setTextColor(getColorCompat(R.color.hf_background))
        setBackgroundColor(getColorCompat(R.color.hf_primary))
        setOnClickListener { action() }
        contentDescription = text
    }

    private fun label(text: String, size: Float, color: Int, top: Int = 0, bottom: Int = 0): TextView = TextView(this).apply {
        this.text = text
        textSize = size
        setTextColor(getColorCompat(color))
        setPadding(0, dp(top), 0, dp(bottom))
    }

    private fun matchParams(top: Int = 0, bottom: Int = 0): LinearLayout.LayoutParams = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { setMargins(0, dp(top), 0, dp(bottom)) }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
    private fun now(): String = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date())
    private fun number(value: Double?): String = if (value == null || value.isNaN() || value.isInfinite()) "unavailable" else String.format(Locale.US, "%.3f", value)
    private fun getColorCompat(id: Int): Int = getColor(id)

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }
}
