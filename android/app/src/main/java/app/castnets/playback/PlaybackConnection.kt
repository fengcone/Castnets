package app.castnets.playback

import android.content.ComponentName
import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import app.castnets.data.Episode
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class PlaybackSnapshot(
    val connected: Boolean = false,
    val episodeId: String? = null,
    val isPlaying: Boolean = false,
    val positionMs: Long = 0,
    val durationMs: Long? = null,
)

class PlaybackConnection(context: Context) : Player.Listener {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val controllerFuture = MediaController.Builder(
        appContext,
        SessionToken(appContext, ComponentName(appContext, PlaybackService::class.java)),
    ).buildAsync()
    private var controller: MediaController? = null
    private var pendingEpisode: Episode? = null
    private var declaredDurationMs: Long? = null
    private val mutableSnapshot = MutableStateFlow(PlaybackSnapshot())
    val snapshot: StateFlow<PlaybackSnapshot> = mutableSnapshot.asStateFlow()

    private val positionTicker = object : Runnable {
        override fun run() {
            publish()
            mainHandler.postDelayed(this, 500)
        }
    }

    init {
        controllerFuture.addListener({
            runCatching { controllerFuture.get() }.onSuccess { connectedController ->
                controller = connectedController
                connectedController.addListener(this)
                publish()
                pendingEpisode?.let(::play)
                pendingEpisode = null
                mainHandler.post(positionTicker)
            }
        }, ContextCompat.getMainExecutor(appContext))
    }

    fun play(episode: Episode) {
        val player = controller
        if (player == null) {
            pendingEpisode = episode
            return
        }
        declaredDurationMs = episode.durationMs
        val item = MediaItem.Builder()
            .setMediaId(episode.id)
            .setUri(episode.audioUrl)
            .setMediaMetadata(MediaMetadata.Builder().setTitle(episode.title).build())
            .build()
        player.setMediaItem(item)
        player.prepare()
        player.play()
        publish()
    }

    fun toggle() {
        controller?.let { player -> if (player.isPlaying) player.pause() else player.play() }
        publish()
    }

    fun pause() {
        controller?.pause()
        publish()
    }

    fun seekTo(positionMs: Long) {
        controller?.seekTo(positionMs.coerceAtLeast(0L))
        publish()
    }

    fun seekAndPlay(positionMs: Long) {
        controller?.let { player ->
            player.seekTo(positionMs.coerceAtLeast(0L))
            player.play()
        }
        publish()
    }

    fun release() {
        mainHandler.removeCallbacks(positionTicker)
        controller?.removeListener(this)
        controller = null
        MediaController.releaseFuture(controllerFuture)
    }

    override fun onEvents(player: Player, events: Player.Events) {
        publish()
    }

    private fun publish() {
        val player = controller
        if (player == null) {
            mutableSnapshot.value = PlaybackSnapshot()
            return
        }
        val playerDuration = player.duration.takeIf { it != C.TIME_UNSET && it >= 0 }
        mutableSnapshot.value = PlaybackSnapshot(
            connected = true,
            episodeId = player.currentMediaItem?.mediaId,
            isPlaying = player.isPlaying,
            positionMs = player.currentPosition.coerceAtLeast(0L),
            durationMs = playerDuration ?: declaredDurationMs,
        )
    }
}
