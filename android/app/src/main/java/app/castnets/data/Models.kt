package app.castnets.data

data class Podcast(
    val id: String,
    val title: String,
    val description: String,
    val imageUrl: String?,
)

data class Episode(
    val id: String,
    val title: String,
    val audioUrl: String,
    val durationMs: Long?,
    val publishedAt: String?,
)

data class Answer(
    val spokenAnswer: String,
    val visualSummary: List<String>,
    val confidence: String,
    val limitations: List<String>,
)

data class Turn(
    val id: String,
    val question: String,
    val answer: Answer,
)

data class Branch(
    val id: String,
    val episodeId: String,
    val anchorMs: Long,
    val resumePositionMs: Long,
    val state: String,
    val turns: List<Turn>,
)
