package app.castnets.data

import org.json.JSONArray
import org.json.JSONObject

internal object ApiJson {
    fun podcasts(raw: String): List<Podcast> = JSONArray(raw).mapObjects { value ->
        Podcast(
            id = value.getString("id"),
            title = value.getString("title"),
            description = value.optString("description"),
            imageUrl = value.nullableString("image_url"),
        )
    }

    fun episodes(raw: String): List<Episode> = JSONArray(raw).mapObjects { value ->
        Episode(
            id = value.getString("id"),
            title = value.getString("title"),
            audioUrl = value.getString("audio_url"),
            durationMs = if (value.isNull("duration_ms")) null else value.getLong("duration_ms"),
            publishedAt = value.nullableString("published_at"),
        )
    }

    fun branch(raw: String): Branch {
        val value = JSONObject(raw)
        return Branch(
            id = value.getString("id"),
            episodeId = value.getString("episode_id"),
            anchorMs = value.getLong("anchor_ms"),
            resumePositionMs = value.getLong("resume_position_ms"),
            state = value.getString("state"),
            turns = value.getJSONArray("turns").mapObjects(::turn),
        )
    }

    private fun turn(value: JSONObject): Turn {
        val answer = value.getJSONObject("answer")
        return Turn(
            id = value.getString("id"),
            question = value.getString("question"),
            answer = Answer(
                spokenAnswer = answer.getString("spoken_answer"),
                visualSummary = answer.getJSONArray("visual_summary").mapStrings(),
                confidence = answer.getString("confidence"),
                limitations = answer.getJSONArray("limitations").mapStrings(),
            ),
        )
    }

    private fun JSONObject.nullableString(name: String): String? =
        if (isNull(name)) null else getString(name)

    private fun <T> JSONArray.mapObjects(transform: (JSONObject) -> T): List<T> =
        List(length()) { index -> transform(getJSONObject(index)) }

    private fun JSONArray.mapStrings(): List<String> =
        List(length()) { index -> getString(index) }
}
