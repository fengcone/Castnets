package app.castnets

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.castnets.conversation.ConversationPhase
import app.castnets.data.Episode
import app.castnets.data.Podcast

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CastnetsApp(viewModel: CastnetsViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val selectedPodcast = state.selectedPodcast
    MaterialTheme {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("Castnets") },
                    actions = { Text(state.apiBaseUrl, style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(12.dp)) },
                )
            },
        ) { padding ->
            Column(Modifier.fillMaxSize().padding(padding)) {
                state.error?.let { ErrorCard(it, viewModel::loadPodcasts) }
                when {
                    state.selectedEpisode != null -> PlayerScreen(state, viewModel)
                    selectedPodcast != null -> EpisodeList(
                        podcast = selectedPodcast,
                        episodes = state.episodes,
                        loading = state.loading,
                        onBack = viewModel::leavePodcast,
                        onEpisode = viewModel::playEpisode,
                    )
                    else -> PodcastList(state.podcasts, state.loading, viewModel::selectPodcast)
                }
            }
        }
    }
}

@Composable
private fun PodcastList(podcasts: List<Podcast>, loading: Boolean, onPodcast: (Podcast) -> Unit) {
    if (loading && podcasts.isEmpty()) {
        Loading()
        return
    }
    LazyColumn(Modifier.fillMaxSize()) {
        item { Text("选择节目", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(16.dp)) }
        items(podcasts, key = { it.id }) { podcast ->
            Column(
                Modifier.fillMaxWidth().clickable { onPodcast(podcast) }.padding(horizontal = 16.dp, vertical = 14.dp),
            ) {
                Text(podcast.title, fontWeight = FontWeight.Bold)
                if (podcast.description.isNotBlank()) Text(podcast.description, style = MaterialTheme.typography.bodySmall)
            }
            HorizontalDivider()
        }
    }
}

@Composable
private fun EpisodeList(
    podcast: Podcast,
    episodes: List<Episode>,
    loading: Boolean,
    onBack: () -> Unit,
    onEpisode: (Episode) -> Unit,
) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(horizontal = 8.dp)) {
                TextButton(onClick = onBack) { Text("返回") }
                Text(podcast.title, style = MaterialTheme.typography.headlineSmall)
            }
        }
        if (loading) item { Loading() }
        items(episodes, key = { it.id }) { episode ->
            Column(
                Modifier.fillMaxWidth().clickable { onEpisode(episode) }.padding(horizontal = 16.dp, vertical = 14.dp),
            ) {
                Text(episode.title, fontWeight = FontWeight.SemiBold)
                Text(formatTime(episode.durationMs ?: 0), style = MaterialTheme.typography.bodySmall)
            }
            HorizontalDivider()
        }
    }
}

@Composable
private fun PlayerScreen(state: CastnetsUiState, viewModel: CastnetsViewModel) {
    val episode = requireNotNull(state.selectedEpisode)
    val playback = state.playback
    val conversation = state.conversation
    val duration = (playback.durationMs ?: episode.durationMs ?: 1L).coerceAtLeast(1L)
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        TextButton(onClick = viewModel::leavePlayer) { Text("返回单集列表") }
        Text(episode.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Slider(
            value = playback.positionMs.coerceIn(0, duration).toFloat(),
            onValueChange = { viewModel.seekTo(it.toLong()) },
            valueRange = 0f..duration.toFloat(),
            enabled = conversation.phase == ConversationPhase.PLAYING,
        )
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("${formatTime(playback.positionMs)} / ${formatTime(duration)}")
            Text(if (playback.connected) "媒体会话已连接" else "正在连接媒体会话")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(
                onClick = viewModel::togglePlayback,
                enabled = playback.connected && conversation.phase == ConversationPhase.PLAYING,
            ) {
                Text(if (playback.isPlaying) "暂停" else "播放")
            }
            OutlinedButton(
                onClick = viewModel::ask,
                enabled = playback.connected && conversation.phase == ConversationPhase.PLAYING,
            ) { Text("提问") }
        }

        if (conversation.phase != ConversationPhase.PLAYING) {
            HorizontalDivider()
            Text("支线 · ${formatTime(conversation.anchorMs ?: 0)}", fontWeight = FontWeight.Bold)
            OutlinedTextField(
                value = state.question,
                onValueChange = viewModel::updateQuestion,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(if (conversation.branch == null) "你的问题" else "继续追问") },
                enabled = conversation.phase in setOf(ConversationPhase.COMPOSING, ConversationPhase.ANSWERED),
            )
            Button(
                onClick = viewModel::submitQuestion,
                enabled = state.question.isNotBlank() && conversation.phase in setOf(
                    ConversationPhase.COMPOSING,
                    ConversationPhase.ANSWERED,
                ),
            ) { Text("发送") }

            if (conversation.phase in setOf(ConversationPhase.WAITING_FOR_ANSWER, ConversationPhase.WAITING_FOR_RESUME)) {
                CircularProgressIndicator()
            }
            conversation.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            conversation.branch?.turns?.forEach { turn ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("你：${turn.question}", fontWeight = FontWeight.SemiBold)
                        Text(turn.answer.spokenAnswer)
                        turn.answer.visualSummary.forEach { Text("• $it") }
                        Text("置信度：${turn.answer.confidence}", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
            if (conversation.phase == ConversationPhase.ANSWERED) {
                Button(onClick = viewModel::resumePodcast) { Text("继续播放") }
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun Loading() {
    Row(Modifier.fillMaxWidth().padding(24.dp), horizontalArrangement = Arrangement.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun ErrorCard(message: String, retry: () -> Unit) {
    Card(Modifier.fillMaxWidth().padding(12.dp)) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(message, color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f))
            TextButton(onClick = retry) { Text("重试") }
        }
    }
}

private fun formatTime(valueMs: Long): String {
    val totalSeconds = valueMs.coerceAtLeast(0) / 1000
    val hours = totalSeconds / 3600
    val minutes = totalSeconds % 3600 / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds) else "%d:%02d".format(minutes, seconds)
}
