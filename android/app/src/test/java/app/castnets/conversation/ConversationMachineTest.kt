package app.castnets.conversation

import app.castnets.data.Answer
import app.castnets.data.Branch
import app.castnets.data.Turn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ConversationMachineTest {
    private val branch = Branch(
        id = "branch-1",
        episodeId = "episode-1",
        anchorMs = 675000,
        resumePositionMs = 321000,
        state = "active",
        turns = listOf(Turn("turn-1", "问题", Answer("回答", listOf("摘要"), "draft", emptyList()))),
    )

    @Test
    fun askingPausesAndCapturesCurrentPlayerPosition() {
        val transition = ConversationMachine.reduce(
            ConversationState(),
            ConversationEvent.AskTapped(675123),
        )

        assertEquals(ConversationPhase.COMPOSING, transition.state.phase)
        assertEquals(675123L, transition.state.anchorMs)
        assertEquals(listOf(ConversationEffect.PausePlayback), transition.effects)

        val submitted = ConversationMachine.reduce(
            transition.state,
            ConversationEvent.QuestionSubmitted("  RWA 是什么？  "),
        )
        assertEquals(
            listOf(ConversationEffect.CreateBranch(675123, "RWA 是什么？")),
            submitted.effects,
        )
    }

    @Test
    fun followUpAppendsToExistingBranch() {
        val answered = ConversationState(
            phase = ConversationPhase.ANSWERED,
            anchorMs = branch.anchorMs,
            branch = branch,
        )
        val transition = ConversationMachine.reduce(answered, ConversationEvent.QuestionSubmitted("再解释一下"))

        assertEquals(ConversationPhase.WAITING_FOR_ANSWER, transition.state.phase)
        assertEquals(listOf(ConversationEffect.AddTurn("branch-1", "再解释一下")), transition.effects)
    }

    @Test
    fun resumeSeeksOnlyToPositionReturnedByServer() {
        val answered = ConversationState(
            phase = ConversationPhase.ANSWERED,
            anchorMs = 675000,
            branch = branch,
        )
        val requested = ConversationMachine.reduce(answered, ConversationEvent.ContinueTapped)
        assertEquals(listOf(ConversationEffect.ResumeBranch("branch-1")), requested.effects)

        val serverBranch = branch.copy(resumePositionMs = 432123, state = "resumed")
        val resumed = ConversationMachine.reduce(requested.state, ConversationEvent.ResumeReceived(serverBranch))
        assertEquals(ConversationPhase.PLAYING, resumed.state.phase)
        assertEquals(listOf(ConversationEffect.SeekAndPlay(432123)), resumed.effects)
        assertTrue(resumed.effects.none { it == ConversationEffect.SeekAndPlay(branch.anchorMs - 5000) })
    }

    @Test
    fun ignoresLateResumeAndSecondAskOutsidePlayback() {
        val answered = ConversationState(
            phase = ConversationPhase.ANSWERED,
            anchorMs = branch.anchorMs,
            branch = branch,
        )
        val resumedBranch = branch.copy(resumePositionMs = 1000, state = "resumed")

        val lateResume = ConversationMachine.reduce(answered, ConversationEvent.ResumeReceived(resumedBranch))
        val secondAsk = ConversationMachine.reduce(answered, ConversationEvent.AskTapped(999999))

        assertTrue(lateResume.effects.isEmpty())
        assertEquals(answered, lateResume.state)
        assertTrue(secondAsk.effects.isEmpty())
        assertEquals(answered, secondAsk.state)
    }
}
