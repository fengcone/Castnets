package app.castnets.conversation

import app.castnets.data.Branch

enum class ConversationPhase {
    PLAYING,
    COMPOSING,
    WAITING_FOR_ANSWER,
    ANSWERED,
    WAITING_FOR_RESUME,
}

data class ConversationState(
    val phase: ConversationPhase = ConversationPhase.PLAYING,
    val anchorMs: Long? = null,
    val branch: Branch? = null,
    val error: String? = null,
)

sealed interface ConversationEvent {
    data class AskTapped(val playerPositionMs: Long) : ConversationEvent
    data class QuestionSubmitted(val question: String) : ConversationEvent
    data class BranchReceived(val branch: Branch) : ConversationEvent
    data object ContinueTapped : ConversationEvent
    data class ResumeReceived(val branch: Branch) : ConversationEvent
    data class RequestFailed(val message: String) : ConversationEvent
    data object Reset : ConversationEvent
}

sealed interface ConversationEffect {
    data object PausePlayback : ConversationEffect
    data class CreateBranch(val anchorMs: Long, val question: String) : ConversationEffect
    data class AddTurn(val branchId: String, val question: String) : ConversationEffect
    data class ResumeBranch(val branchId: String) : ConversationEffect
    data class SeekAndPlay(val positionMs: Long) : ConversationEffect
}

data class ConversationTransition(
    val state: ConversationState,
    val effects: List<ConversationEffect> = emptyList(),
)

object ConversationMachine {
    fun reduce(state: ConversationState, event: ConversationEvent): ConversationTransition = when (event) {
        is ConversationEvent.AskTapped -> if (state.phase != ConversationPhase.PLAYING) {
            ConversationTransition(state)
        } else {
            ConversationTransition(
                ConversationState(
                    phase = ConversationPhase.COMPOSING,
                    anchorMs = event.playerPositionMs.coerceAtLeast(0L),
                ),
                listOf(ConversationEffect.PausePlayback),
            )
        }

        is ConversationEvent.QuestionSubmitted -> {
            val question = event.question.trim()
            if (question.isEmpty() || state.phase !in setOf(ConversationPhase.COMPOSING, ConversationPhase.ANSWERED)) {
                ConversationTransition(state)
            } else if (state.branch == null) {
                val anchor = requireNotNull(state.anchorMs) { "An anchor is required before the first question" }
                ConversationTransition(
                    state.copy(phase = ConversationPhase.WAITING_FOR_ANSWER, error = null),
                    listOf(ConversationEffect.CreateBranch(anchor, question)),
                )
            } else {
                ConversationTransition(
                    state.copy(phase = ConversationPhase.WAITING_FOR_ANSWER, error = null),
                    listOf(ConversationEffect.AddTurn(state.branch.id, question)),
                )
            }
        }

        is ConversationEvent.BranchReceived -> if (state.phase != ConversationPhase.WAITING_FOR_ANSWER) {
            ConversationTransition(state)
        } else {
            ConversationTransition(
                state.copy(phase = ConversationPhase.ANSWERED, branch = event.branch, error = null),
            )
        }

        ConversationEvent.ContinueTapped -> {
            val branch = state.branch
            if (state.phase != ConversationPhase.ANSWERED || branch == null) {
                ConversationTransition(state)
            } else {
                ConversationTransition(
                    state.copy(phase = ConversationPhase.WAITING_FOR_RESUME, error = null),
                    listOf(ConversationEffect.ResumeBranch(branch.id)),
                )
            }
        }

        is ConversationEvent.ResumeReceived -> if (
            state.phase != ConversationPhase.WAITING_FOR_RESUME || state.branch?.id != event.branch.id
        ) {
            ConversationTransition(state)
        } else {
            ConversationTransition(
                ConversationState(phase = ConversationPhase.PLAYING),
                listOf(ConversationEffect.SeekAndPlay(event.branch.resumePositionMs)),
            )
        }

        is ConversationEvent.RequestFailed -> ConversationTransition(
            state.copy(
                phase = if (state.branch == null) ConversationPhase.COMPOSING else ConversationPhase.ANSWERED,
                error = event.message,
            ),
        )

        ConversationEvent.Reset -> ConversationTransition(ConversationState())
    }
}
