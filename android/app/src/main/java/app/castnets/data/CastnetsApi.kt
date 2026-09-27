package app.castnets.data

interface CastnetsApi {
    suspend fun listPodcasts(): List<Podcast>
    suspend fun listEpisodes(podcastId: String): List<Episode>
    suspend fun createBranch(episodeId: String, anchorMs: Long, question: String): Branch
    suspend fun addTurn(branchId: String, question: String): Branch
    suspend fun resume(branchId: String): Branch
}
