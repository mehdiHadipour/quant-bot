package com.quantbot.companion

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : AppCompatActivity() {

    private lateinit var repoInput: EditText
    private lateinit var statusText: TextView

    private val prefs by lazy {
        getSharedPreferences("quant_bot", Context.MODE_PRIVATE)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }

        repoInput = EditText(this).apply {
            hint = "owner/repository"
            setText(prefs.getString("repo", ""))
        }

        val refresh = Button(this).apply {
            text = "بررسی وضعیت ربات"
        }

        val openActions = Button(this).apply {
            text = "باز کردن GitHub Actions"
        }

        statusText = TextView(this).apply {
            textSize = 16f
            text = "نام مخزن را وارد کنید."
        }

        content.addView(repoInput)
        content.addView(refresh)
        content.addView(openActions)
        content.addView(statusText)

        setContentView(
            ScrollView(this).apply {
                addView(content)
            }
        )

        refresh.setOnClickListener {
            loadStatus()
        }

        openActions.setOnClickListener {
            val repo = repoInput.text.toString().trim()

            if (repo.isNotEmpty()) {
                val intent = Intent(
                    Intent.ACTION_VIEW,
                    Uri.parse("https://github.com/$repo/actions")
                )
                startActivity(intent)
            }
        }
    }

    private fun loadStatus() {
        val repo = repoInput.text.toString().trim()

        if (!repo.matches(Regex("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"))) {
            statusText.text = "فرمت مخزن باید owner/repository باشد."
            return
        }

        prefs.edit()
            .putString("repo", repo)
            .apply()

        statusText.text = "در حال دریافت وضعیت امن و عمومی GitHub..."

        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                fetchLatestRun(repo)
            }

            statusText.text = result
        }
    }

    private fun fetchLatestRun(repo: String): String {
        return try {
            val url = URL(
                "https://api.github.com/repos/$repo/actions/runs?per_page=1"
            )

            val conn = url.openConnection() as HttpURLConnection

            conn.requestMethod = "GET"
            conn.setRequestProperty(
                "Accept",
                "application/vnd.github+json"
            )
            conn.connectTimeout = 8000
            conn.readTimeout = 8000

            if (conn.responseCode != 200) {
                return "خطای GitHub API: HTTP ${conn.responseCode}"
            }

            val json = JSONObject(
                conn.inputStream.bufferedReader().use {
                    it.readText()
                }
            )

            val run = json
                .getJSONArray("workflow_runs")
                .optJSONObject(0)
                ?: return "هنوز اجرای Workflow پیدا نشد."

            val name = run.optString(
                "name",
                "Unknown"
            )

            val status = run.optString(
                "status",
                "unknown"
            )

            val conclusion = run.optString(
                "conclusion",
                "در حال اجرا"
            )

            "Workflow: $name\n" +
                    "وضعیت: $status\n" +
                    "نتیجه: $conclusion\n" +
                    "آخرین اجرا: ${run.optString("updated_at", "-")}"

        } catch (e: Exception) {
            "عدم دسترسی به GitHub: ${
                e.message ?: "خطای ناشناخته"
            }"
        }
    }
}
