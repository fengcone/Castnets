package app.castnets

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.castnets.conversation.ConversationEffect
import app.castnets.conversation.ConversationEvent
import app.castnets.conversation.ConversationMachine
import app.castnets.conversation.ConversationPhase
import app.castnets.conversation.ConversationState
import app.castnets.data.CastnetsApi
import app.castnets.data.Episode
import app.castnets.data.HttpCastnetsApi
import app.castnets.data.Podcast
import app.castnets.playback.PlaybackConnection
import app.castnets.playback.PlaybackSnapshot
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CastnetsUiState(
    val apiBaseUrl: String = BuildConfig.CASTNETS_API_BASE_URL,
    val podcasts: List<Podcast> = emptyList(),
    val selectedPodcast: Podcast? = null,
    val episodes: List<Episode> = emptyList(),
    val selectedEpisode: Episode? = null,
    val playback: PlaybackSnapshot = PlaybackSnapshot(),
    val conversation: ConversationState = ConversationState(),
    val question: String = "",
    val loading: Boolean = false,
    val error: String? = null,
)

class CastnetsViewModel(application: Application) : AndroidViewModel(application) {
    private val api: CastnetsApi = HttpCastnetsApi(BuildConfig.CASTNETS_API_BASE_URL)
    private val playback = PlaybackConnection(application)
    private val mutableState = MutableStateFlow(CastnetsUiState())
    val state: StateFlow<CastnetsUiState> = mutableState.asStateFlow()

    init {
        viewModelScope.launch {
            playback.snapshot.collect { snapshot ->
                mutableState.update { it.copy(playback = snapshot) }
            }
        }
        loadPodcasts()
    }

    fun loadPodcasts() {
        viewModelScope.launch {
            mutableState.update { it.copy(loading = true, error = null) }
            runCatching { api.listPodcasts() }
                .onSuccess { podcasts -> mutableState.update { it.copy(podcasts = podcasts, loading = false) } }
                .onFailure(::showFailure)
        }
    }

    fun selectPodcast(podcast: Podcast) {
        mutableState.update { it.copy(selectedPodcast = podcast, episodes = emptyList(), loading = true, error = null) }
        viewModelScope.launch {
            runCatching { api.listEpisodes(podcast.id) }
                .onSuccess { episodes -> mutableState.update { it.copy(episodes = episodes, loading = false) } }
                .onFailure(::showFailure)
        }
    }

    fun leavePodcast() {
        mutableState.update { it.copy(selectedPodcast = null, episodes = emptyList(), error = null) }
    }

    fun playEpisode(episode: Episode) {
        dispatch(ConversationEvent.Reset)
        mutableState.update { it.copy(selectedEpisode = episode, question = "", error = null) }
        playback.play(episode)
    }

    fun leavePlayer() {
        playback.pause()
        dispatch(ConversationEvent.Reset)
        mutableState.update { it.copy(selectedEpisode = null, question = "") }
    }

    fun togglePlayback() = playback.toggle()

    fun seekTo(positionMs: Long) = playback.seekTo(positionMs)

    fun ask() = dispatch(ConversationEvent.AskTapped(mutableState.value.playback.positionMs))

    fun updateQuestion(value: String) {
        mutableState.update { it.copy(question = value) }
    }

    fun submitQuestion() {
        val question = mutableState.value.question
        val before = mutableState.value.conversation
        val transition = ConversationMachine.reduce(before, ConversationEvent.QuestionSubmitted(question))
        if (transition.effects.isNotEmpty()) {
            mutableState.update { it.copy(question = "") }
        }
        applyTransition(transition)
    }

    fun resumePodcast() = dispatch(ConversationEvent.ContinueTapped)

    private fun dispatch(event: ConversationEvent) {
        applyTransition(ConversationMachine.reduce(mutableState.value.conversation, event))
    }

    private fun applyTransition(transition: app.castnets.conversation.ConversationTransition) {
        mutableState.update { it.copy(conversation = transition.state) }
        transition.effects.forEach(::handle)
    }

    private fun handle(effect: ConversationEffect) {
        when (effect) {
            ConversationEffect.PausePlayback -> playback.pause()
            is ConversationEffect.SeekAndPlay -> playback.seekAndPlay(effect.positionMs)
            is ConversationEffect.CreateBranch -> {
                val episodeId = mutableState.value.selectedEpisode?.id ?: return
                request { api.createBranch(episodeId, effect.anchorMs, effect.question) }
            }
            is ConversationEffect.AddTurn -> request { api.addTurn(effect.branchId, effect.question) }
            is ConversationEffect.ResumeBranch -> viewModelScope.launch {
                runCatching { api.resume(effect.branchId) }
                    .onSuccess { branch ->
                        val current = mutableState.value.conversation
                        if (current.phase == ConversationPhase.WAITING_FOR_RESUME &&
                            current.branch?.id == branch.id
                        ) {
                            dispatch(ConversationEvent.ResumeReceived(branch))
                        }
                    }
                    .onFailure { error ->
                        if (mutableState.value.conversation.phase == ConversationPhase.WAITING_FOR_RESUME
                        ) {
                            dispatch(ConversationEvent.RequestFailed(error.message ?: "恢复失败"))
                        }
                    }
            }
        }
    }

    private fun request(block: suspend () -> app.castnets.data.Branch) {
        viewModelScope.launch {
            runCatching { block() }
                .onSuccess { branch ->
                    val current = mutableState.value
                    if (current.selectedEpisode?.id == branch.episodeId &&
                        current.conversation.phase == ConversationPhase.WAITING_FOR_ANSWER
                    ) {
                        dispatch(ConversationEvent.BranchReceived(branch))
                    }
                }
                .onFailure { error ->
                    if (mutableState.value.conversation.phase == ConversationPhase.WAITING_FOR_ANSWER
                    ) {
                        dispatch(ConversationEvent.RequestFailed(error.message ?: "请求失败"))
                    }
                }
        }
    }

    private fun showFailure(error: Throwable) {
        mutableState.update { it.copy(loading = false, error = error.message ?: "请求失败") }
    }

    override fun onCleared() {
        playback.release()
        super.onCleared()
    }
}
