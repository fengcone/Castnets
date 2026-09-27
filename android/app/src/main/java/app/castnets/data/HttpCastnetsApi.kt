package app.castnets.data

import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

class HttpCastnetsApi(baseUrl: String) : CastnetsApi {
    private val baseUri = URI(baseUrl.trimEnd('/')).also { uri ->
        require(uri.scheme == "http" || uri.scheme == "https") { "API URL must use HTTP or HTTPS" }
        require(!uri.host.isNullOrBlank()) { "API URL must include a host" }
    }

    override suspend fun listPodcasts(): List<Podcast> =
        ApiJson.podcasts(request("GET", "/v1/podcasts"))

    override suspend fun listEpisodes(podcastId: String): List<Episode> =
        ApiJson.episodes(request("GET", "/v1/podcasts/${segment(podcastId)}/episodes"))

    override suspend fun createBranch(episodeId: String, anchorMs: Long, question: String): Branch =
        ApiJson.branch(request("POST", "/v1/branches", JSONObject()
            .put("episode_id", episodeId)
            .put("anchor_ms", anchorMs)
            .put("question", question)))

    override suspend fun addTurn(branchId: String, question: String): Branch =
        ApiJson.branch(request("POST", "/v1/branches/${segment(branchId)}/turns", JSONObject()
            .put("question", question)))

    override suspend fun resume(branchId: String): Branch =
        ApiJson.branch(request("POST", "/v1/branches/${segment(branchId)}/resume", JSONObject()))

    private suspend fun request(method: String, path: String, body: JSONObject? = null): String =
        withContext(Dispatchers.IO) {
            val connection = baseUri.resolve(path).toURL().openConnection() as HttpURLConnection
            try {
                connection.requestMethod = method
                connection.connectTimeout = 10_000
                connection.readTimeout = 15_000
                connection.setRequestProperty("Accept", "application/json")
                if (body != null) {
                    val bytes = body.toString().toByteArray(StandardCharsets.UTF_8)
                    connection.doOutput = true
                    connection.setRequestProperty("Content-Type", "application/json")
                    connection.setFixedLengthStreamingMode(bytes.size)
                    connection.outputStream.use { output -> output.write(bytes) }
                }
                val code = connection.responseCode
                val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                val raw = stream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() }.orEmpty()
                if (code !in 200..299) {
                    val message = runCatching {
                        JSONObject(raw).getJSONObject("error").getString("message")
                    }.getOrDefault("HTTP $code")
                    throw CastnetsApiException(code, message)
                }
                raw
            } finally {
                connection.disconnect()
            }
        }

    private fun segment(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")
}

class CastnetsApiException(val status: Int, message: String) : Exception(message)
