package app.castnets.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ApiJsonTest {
    @Test
    fun mapsPodcastAndEpisodeResponses() {
        val podcasts = ApiJson.podcasts(
            """[{"id":"pod-1","title":"面基","description":"介绍","image_url":null}]""",
        )
        assertEquals("pod-1", podcasts.single().id)
        assertNull(podcasts.single().imageUrl)

        val episodes = ApiJson.episodes(
            """[{"id":"ep-1","title":"一期","audio_url":"https://example.test/audio.mp3","duration_ms":123000,"published_at":null}]""",
        )
        assertEquals(123000L, episodes.single().durationMs)
        assertEquals("https://example.test/audio.mp3", episodes.single().audioUrl)
        assertNull(episodes.single().publishedAt)
    }

    @Test
    fun mapsStructuredBranchAnswerAndServerResumePosition() {
        val branch = ApiJson.branch(
            """
            {
              "id":"branch-1",
              "episode_id":"ep-1",
              "anchor_ms":675000,
              "resume_position_ms":670000,
              "state":"active",
              "turns":[{
                "id":"turn-1",
                "question":"RWA 是什么？",
                "answer":{
                  "spoken_answer":"这是演示释义。",
                  "visual_summary":["第一点","第二点"],
                  "confidence":"draft",
                  "limitations":["离线 mock"]
                }
              }]
            }
            """.trimIndent(),
        )

        assertEquals(670000L, branch.resumePositionMs)
        assertEquals("这是演示释义。", branch.turns.single().answer.spokenAnswer)
        assertEquals(listOf("第一点", "第二点"), branch.turns.single().answer.visualSummary)
    }
}
