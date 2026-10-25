"""Spoken teacher remarks after each practice pass.

The Maestro gives at most two sentences after a pass: how it went (or how it compares with
the last one), then the one thing worth naming: the note, the bar, the pulse. The first time
a problem shows up it is named; the second time comes the way to fix it; after that, a word
or two. Clean passes in a row stay quiet apart from the streak at three and five. So loop
practice hears something only when there is something new to say.

Two styles: warm (the default: encouraging, says what went well first) and strict (dry and
demanding). Facts and instructions are shared; verdicts, greetings and sign-offs differ.
Wording is drawn from phrase pools and avoids the last half of each pool, remembered between
sessions when the Coach is given a memory file. Criticism is about the playing, never the
player.
"""

from __future__ import annotations

import json
import logging
import pathlib
import random
import re
import statistics

log = logging.getLogger(__name__)

_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
_BLACK = {1, 3, 6, 8, 10}
_SHARPS = ["C", "C sharp", "D", "D sharp", "E", "F", "F sharp", "G", "G sharp", "A", "A sharp", "B"]
_FLATS = ["C", "D flat", "D", "E flat", "E", "F", "G flat", "G", "A flat", "A", "B flat", "B"]
_MIXED = ["C", "C sharp", "D", "E flat", "E", "F", "F sharp", "G", "A flat", "A", "B flat", "B"]
_NAME_RE = re.compile(r"^([A-G])([#b]?)(-?\d+)$")
_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

STYLES = ("warm", "strict")
DEFAULT_STYLE = "warm"
STREAK_NEWS = (3, 5)  # clean passes in a row that get a remark; the others stay quiet
MILESTONES = (5, 10, 20)

# -- phrase pools shared by both styles: what happened, and how to fix it ---------

COMMON = {
    "acc": [
        "Bar {bar}: that's {exp}, not {played}.",
        "{Exp}, not {played}, in bar {bar}.",
        "In bar {bar} it's {exp}; you played {played}.",
        "You played {played} in bar {bar}, where the music wants {exp}.",
        "Watch bar {bar}: it's {exp} there, not {played}.",
        "Bar {bar} needs {exp}, and you went to {played}.",
        "That {played} in bar {bar} should be {exp}.",
        "Bar {bar} is {exp}, not {played}; check the sharps and flats.",
    ],
    "acc-again": [
        "The {exp} in bar {bar} slipped again; say it in your head just before you get there.",
        "{Exp} in bar {bar}, same as last time; look at the key signature before you start.",
        "That's the {exp} in bar {bar} twice now; slow down just before it.",
        "Bar {bar} again: {exp}, not {played}; name the black key before you play it.",
        "The {exp} keeps catching you in bar {bar}; mark it in your mind before the pass.",
        "Same {exp} in bar {bar}; try that bar slowly a few times on its own.",
        "Bar {bar}'s {exp} is the one to fix; think it before your hand moves.",
        "{Exp} again in bar {bar}; play up to it slowly and land on it deliberately.",
    ],
    "wrong": [
        "In bar {bar} you played {played} instead of {exp}.",
        "Bar {bar}: that was {played}; it should be {exp}.",
        "Bar {bar} has {exp} where you played {played}.",
        "A wrong note in bar {bar}: {exp}, not {played}.",
        "In bar {bar}, look for {exp}; you found {played}.",
        "Bar {bar} wants {exp}, and {played} came out.",
        "Check bar {bar}: it's {exp}, not {played}.",
        "You hit {played} in bar {bar}; the note is {exp}.",
    ],
    "hot": [
        "Bar {bar} cost you {count}.",
        "Most of the slips were in bar {bar}.",
        "Bar {bar} had {count} go wrong.",
        "Bar {bar} is the trouble spot, with {count} off.",
        "{Count} slipped in bar {bar}.",
        "Bar {bar} is where the pass came apart.",
        "Bar {bar} needs attention: {count} missed or wrong.",
        "The problems cluster in bar {bar}.",
    ],
    "hot-again": [
        "Bar {bar} again, {times} now; take it on its own, slowly.",
        "Bar {bar} is still the spot; play just that bar until it feels easy.",
        "Bar {bar}, {times} in a row; isolate it at half speed.",
        "Same bar, bar {bar}; try it hands separately first.",
        "Bar {bar} keeps tripping you; loop it slowly five times clean.",
        "Bar {bar} again; practise it alone, then put it back in.",
        "That's bar {bar} {times}; slow it right down and get it clean.",
        "Bar {bar} is the bar to work on; give it a few slow, careful repeats.",
    ],
    "stall": [
        "You paused for {secs} seconds in bar {bar}.",
        "Bar {bar} made you stop and think.",
        "The longest wait was in bar {bar}, about {secs} seconds.",
        "Bar {bar} isn't in your fingers yet; you paused there.",
        "You hesitated in bar {bar}.",
        "Bar {bar} slowed you down the most.",
        "Bar {bar} took a while to find.",
        "You got stuck for a moment in bar {bar}.",
    ],
    "flag-rushing": [
        "You rushed bar {bar}.", "Bar {bar} ran ahead of the beat.", "Bar {bar} came in a little early.",
        "You hurried through bar {bar}.", "Bar {bar} got ahead of the pulse.", "Bar {bar} sped up.",
        "You pushed the tempo in bar {bar}.", "Bar {bar} was in a hurry.",
    ],
    "flag-dragging": [
        "Bar {bar} dragged.", "You slowed down in bar {bar}.", "Bar {bar} fell behind the beat.",
        "Bar {bar} lost some momentum.", "The pulse sagged in bar {bar}.", "Bar {bar} came in late.",
        "You held back in bar {bar}.", "Bar {bar} got heavy and slow.",
    ],
    "flag-hesitation": [
        "You hesitated in bar {bar}.", "There was a stutter in bar {bar}.", "Bar {bar} wasn't quite confident.",
        "A little catch in bar {bar}.", "Bar {bar} had a hiccup.", "You paused briefly in bar {bar}.",
        "Bar {bar} wobbled for a moment.", "Bar {bar} sounded unsure.",
    ],
    "flag-clipped notes": [
        "The notes in bar {bar} are a bit short; give them their full value.",
        "Bar {bar} sounds choppy; hold the notes longer.", "You're letting go early in bar {bar}.",
        "Bar {bar} needs longer notes.", "Hold through the notes in bar {bar}.", "The notes in bar {bar} are clipped.",
        "Bar {bar} would sing more with longer notes.", "Let the notes in bar {bar} ring for their full length.",
    ],
    "flag-over-held": [
        "Notes in bar {bar} are running into each other; lift on time.", "Bar {bar} is a little muddy; release cleanly.",
        "You're holding notes too long in bar {bar}.", "Let go a touch sooner in bar {bar}.",
        "Bar {bar} smears; lift between the notes.", "The notes in bar {bar} overlap.",
        "Release the keys on time in bar {bar}.", "Bar {bar} needs cleaner releases.",
    ],
    "flag-pedal": [
        "Check your pedalling in bar {bar}.", "The pedal blurred bar {bar}.", "Bar {bar} needs a pedal change.",
        "Lift the pedal sooner in bar {bar}.", "The pedal timing in bar {bar} is off.",
        "Bar {bar} got muddy from the pedal.", "Change the pedal with the harmony in bar {bar}.",
        "Listen to the pedal in bar {bar}.",
    ],
    "timing": [
        "Your pulse was uneven.", "The rhythm wobbled a little.", "The beats weren't quite even.",
        "The timing drifted around.", "Some notes came early and some late.", "The beat wasn't steady.",
        "The rhythm needs to settle.", "The beat wandered in places.",
    ],
    "missed": [
        "You left out {count}.", "{Count} went missing.", "You skipped {count}.", "{Count} didn't get played.",
        "There were {count} missing.", "{Count} got dropped.", "You passed over {count}.", "{Count} weren't there.",
    ],
    # The second time a problem shows up: how to fix it.
    "fix-wrong": [
        "Read each note before you play it.", "Keep your eyes on the score in bar {bar}.",
        "Slow bar {bar} down and get it right.", "Find the note with your eyes first, then your hand.",
        "Take bar {bar} slowly once on its own.", "Name the notes of bar {bar} out loud.",
        "Look a beat ahead of your hands.", "Accuracy first; the speed comes later.",
    ],
    "fix-stall": [
        "Get the next hand position ready before you need it.", "Keep your eyes one beat ahead of your fingers.",
        "Work out the fingering for bar {bar} before you start.", "Practise the move into bar {bar} on its own.",
        "Read bar {bar} through once before you play it.", "Play bar {bar} slowly a few times until it flows.",
        "Look ahead to bar {bar} while you're still in the bar before.", "Prepare the shift into bar {bar} a little early.",
    ],
    "fix-rushing": [
        "Count out loud.", "Subdivide: one and two and.", "Put the metronome on and stay with it.",
        "Breathe and let the beat come to you.", "Feel the smallest note value as you play.",
        "Hold back a little in bar {bar}.", "Count bar {bar} out loud as you play it.", "Let the metronome lead in bar {bar}.",
    ],
    "fix-dragging": [
        "Keep the pulse moving through bar {bar}.", "Commit to the beat, even if a note goes wrong.",
        "Count out loud and don't let it slow.", "Keep going; don't stop to fix things.",
        "Feel the beat carry you through bar {bar}.", "Try bar {bar} with the metronome on.",
        "Think ahead so bar {bar} doesn't hold you up.", "Keep the tempo steady into bar {bar}.",
    ],
    "fix-timing": [
        "Aim for even beats, like a clock.", "Feel the beat before you start.", "Count a full bar in before you play.",
        "Try a pass with the metronome.", "Tap the beat with your foot as you play.", "Count quietly the whole way through.",
        "Listen for an even pulse.", "Slow it down a little and keep it steady.",
    ],
    "fix-articulation": [
        "Listen to how long each note lasts.", "Listen to yourself, not just your fingers.",
        "Match the note lengths on the page.", "Pay attention to when you let go.",
        "Make the releases as clean as the attacks.", "Listen for the gaps between the notes.",
        "Give each note its written length.", "Play bar {bar} slowly and listen to the endings.",
    ],
    "fix-missed": [
        "Don't skip notes to keep up; slow the tempo instead.", "Every note counts, even at a slower tempo.",
        "Slower and complete beats faster and patchy.", "Bring the tempo down until every note fits.",
        "Keep all the notes, even if it means slowing down.", "Make sure every note sounds, then build speed.",
        "If a passage is too fast, drop the tempo a little.", "Play them all, even if it's slower.",
    ],
}

# -- phrase pools per style: verdicts, comparisons, greetings, sign-offs ---------

VOICE = {
    "warm": {
        "verdict-clean": ["Clean, nicely done.", "That's it, every note.", "Lovely, that was clean.", "Clean pass, well played.",
                          "Yes, that's the one.", "Every note in place.", "That was solid all the way through.", "Clean and confident."],
        "verdict-close": ["Close, just a couple of slips.", "Nearly there.", "Very close.", "That was good, with a few loose ends.",
                          "Almost clean.", "Most of that was right.", "Good pass, just a little tidying left.", "So close."],
        "verdict-shaky": ["A few too many slips that time.", "That one got a bit shaky.", "Some of it held, some of it slipped.",
                          "That's still settling in.", "Parts of that are there, parts aren't yet.", "A bit unsteady that time.",
                          "That one wobbled.", "It's coming, but it isn't secure yet."],
        "verdict-rough": ["That one got away from you.", "That was a tough pass.", "That's not ready at this speed yet.",
                          "Lots of slips there.", "That passage isn't learned yet, and that's fine.", "That one fell apart a bit.",
                          "That was a struggle.", "This one needs slower work."],
        "improved": ["Better than last time.", "That's progress.", "Improving.", "Fewer slips than before.",
                     "That's moving the right way.", "Nice, that's an improvement.", "Better, keep going that way.",
                     "That's cleaner than the last one."],
        "worse": ["That one slipped compared to the last.", "A step back from the last pass.", "The last pass was cleaner.",
                  "That one was harder than the last.", "A few more slips that time.", "Not as clean as before.",
                  "That one got away a little more.", "Last time was tidier."],
        "same": ["Again.", "Same spot.", "One more.", "Keep at it.", "Stay with it.", "Once more.", "Nearly.", "Getting there."],
        "do-clean": ["Again, and listen to your tone.", "Once more, make it even and musical.", "Try it without looking at your hands.",
                     "Again, and shape the phrases this time.", "One more, eyes on the music.", "Now let it breathe a little.",
                     "Again, and enjoy it.", "Try it once more, a touch more relaxed."],
        "do-streak": ["{Streak} clean in a row; try it five percent faster.", "That's {streak} clean passes; try it from memory.",
                      "{Streak} in a row, you've earned a faster tempo.", "{Streak} clean, time to raise the tempo or play from memory.",
                      "{Streak} in a row, that's settled.", "{Streak} clean passes; nudge the tempo up.",
                      "That's {streak} clean in a row, really solid.", "{Streak} clean; you could move on or go faster."],
        "do-streak-learn": ["{Streak} clean in a row; switch to Rehearse and play it in time.",
                            "That's {streak} clean, the notes are learned; try Rehearse.",
                            "{Streak} in a row, you're ready to play it in time.", "{Streak} clean; let the cursor move on its own now.",
                            "{Streak} clean passes; give Rehearse a go.", "The notes are there, {streak} in a row; time for Rehearse.",
                            "{Streak} clean in a row; try it at tempo.", "That's {streak} without a slip; take it to Rehearse."],
        "do-rough": ["Slow it right down.", "Try hands separately.", "Half tempo, and get it right.",
                     "Go back to Learn mode until the notes feel sure.", "Take a smaller section.",
                     "Slow down and let the notes settle.", "Try it at a slower tempo.", "Work on a few bars at a time."],
        "do-close": ["Again.", "One more, clean this time.", "From the top, nice and steady.", "Again, and tidy that up.",
                     "One more time.", "Once more, you're close.", "Again, a little slower.", "Go again."],
        "greet-new": ["{Title}, a new piece; let's see how it goes.", "First time with {title}; take your time.",
                      "{Title}, fresh pages; no pressure on the first go.", "Let's start {title}.",
                      "{Title}, new for you; enjoy the first look.", "Here's {title}; nobody's perfect on day one.",
                      "{Title}; let's get to know it.", "A new one, {title}; let's begin."],
        "greet-back": ["{Title} again; your best is {best}.", "Back to {title}; last best was {best}.",
                       "{Title}, {takes} so far, best {best}.", "Welcome back to {title}; best score {best}.",
                       "{Title}; your record is {best}, let's see today.", "Back with {title}; the best so far is {best}.",
                       "{Title} again, {takes} in, best {best}.", "Good to see {title} again; best is {best}."],
        "greet-away": ["{Days} days since {title}; let's see what stuck.", "It's been {days} days with {title}; take it easy at first.",
                       "{Title}, {days} days on; let's warm it up.", "Back to {title} after {days} days.",
                       "{Days} days away from {title}; ease back in.", "{Title} again after {days} days; let's see how it feels.",
                       "{Days} days since you played {title}; a slow first pass helps.", "Welcome back to {title}, {days} days on."],
        "greet-key": ["{Count}: {names}.", "Remember the key, {count}: {names}.", "{Names}; that's the key.",
                      "Keep {names} in mind.", "The key has {count}: {names}.", "Watch for {names}.",
                      "{Count} in the key: {names}.", "Key signature: {names}."],
        "greet-wait": ["Learn mode; the cursor waits for you.", "Take your time; the cursor will wait.", "Learn mode, slow is fine.",
                       "The cursor waits for each chord.", "Learn mode; get the notes right first.", "No rush; the cursor waits.",
                       "Learn mode; play each chord when you're ready.", "The cursor will wait for the right notes."],
        "greet-rehearsal": ["{Tempo} percent; the cursor keeps moving.", "Rehearse at {tempo} percent.",
                            "{Tempo} percent, in time; count yourself in.", "Rehearse at {tempo} percent; keep going if you slip.",
                            "{Tempo} percent, and the cursor won't wait.", "Rehearse, {tempo} percent; feel the beat first.",
                            "In time at {tempo} percent.", "{Tempo} percent; keep the pulse going."],
        "milestone": ["Pass {pass}; your hands are warming up.", "That's pass {pass}, nice persistence.",
                      "Pass {pass}; this is how it gets learned.", "{Pass} passes in, keep it up.",
                      "Pass {pass}; maybe a sip of water soon.", "That's {pass} passes.", "Pass {pass}, steady work.",
                      "{Pass} passes; good stamina."],
        "pb": ["New personal best on {title}, {score}!", "{Score}, that's a record for you on {title}.", "Personal best, {score}!",
               "{Score} on {title}, your best yet.", "That's a new best, {score}.", "Record score on {title}: {score}.",
               "{Score}, the best you've done on {title}.", "Personal best on {title}, {score}, well done."],
        "wrap": ["{Passes} passes; pass {best_pass} was the best{best_score}.",
                 "That's {passes} passes today, best was pass {best_pass}{best_score}.",
                 "{Passes} passes, with pass {best_pass} on top{best_score}.",
                 "Session over, {passes} passes; best was pass {best_pass}{best_score}.",
                 "{Passes} passes done; pass {best_pass} was your best{best_score}.",
                 "That's {passes} passes, and pass {best_pass} stood out{best_score}.",
                 "Good work, {passes} passes; best was pass {best_pass}{best_score}.",
                 "{Passes} passes; your best came on pass {best_pass}{best_score}."],
        "wrap-weak": ["Bar {bar} is the one to work on next time.", "Bar {bar} still needs some love.",
                      "Next time, start with bar {bar}.", "Bar {bar} is your homework.", "Keep an eye on bar {bar} next session.",
                      "Bar {bar} is the last tricky spot.", "Give bar {bar} some slow practice tomorrow.",
                      "Bar {bar} is where to begin next time."],
        "wrap-good": ["Good session, that's real progress.", "Nice work, rest your hands.", "That's progress, well done.",
                      "You got better through that session.", "Remember this feeling; it's called progress.",
                      "Good session; same time tomorrow?", "You improved a lot there.", "Well played; it'll settle overnight."],
        "wrap-flat": ["Same time tomorrow.", "Rest your hands; it settles overnight.", "Come back to it tomorrow.",
                      "Good effort; it'll feel easier next time.", "Sleep on it; that helps more than you'd think.",
                      "Time for a break.", "That's enough for now.", "Take a rest; you'll be fresher tomorrow."],
    },
    "strict": {
        "verdict-clean": ["Clean.", "That's how it's done.", "Now we're talking.", "Clean pass; I'll take it.",
                          "Accurate; now make it effortless.", "Yes, that's the standard.", "Every note, good.", "Solid.",
                          "That's more like it."],
        "verdict-close": ["Close, but close isn't correct.", "Almost.", "Decent, not finished.", "Better, but I heard that.",
                          "Nearly there; nearly isn't there.", "Not bad, not good enough either.", "So close; tidy it up.",
                          "Good effort, sloppy finish."],
        "verdict-shaky": ["Sloppy.", "That's guessing, not playing.", "Messy.", "That one fell apart.",
                          "You're practising mistakes.", "Too many slips.", "That's not ready.", "Too loose."],
        "verdict-rough": ["Stop; that was a train wreck.", "We're not there yet, not even close.", "Way too many mistakes.",
                          "No; start over, slower.", "That was all over the place.", "That isn't learned yet.",
                          "That won't do.", "Nowhere near ready at this speed."],
        "improved": ["Better than last time.", "That's progress.", "Improving.", "Better; keep that direction.",
                     "Fewer mistakes, good.", "That's a step forward.", "Better, now keep it.", "Moving the right way."],
        "worse": ["Worse than the last one; focus.", "You went backwards there.", "That slipped; concentrate.",
                  "Last pass was better; what changed?", "More mistakes than before.", "That was a step back.",
                  "Concentrate; you had it last time.", "Backwards; reset and focus."],
        "same": ["Again.", "Same spot.", "Still there.", "No, again.", "Fix it.", "Again, slower.", "Not yet.", "Same mistake."],
        "do-clean": ["Again, and this time listen to your tone.", "Again; make it even and musical.",
                     "Now do it without looking at your hands.", "Again; prove it wasn't luck.", "Again, and shape it this time.",
                     "Once more, eyes on the music.", "Again, and make it sing.", "Once more; consistency is the point."],
        "do-streak": ["{Streak} clean in a row; take the tempo up five percent.", "That's {streak} clean passes; now try it from memory.",
                      "{Streak} in a row; you've earned a faster tempo.", "{Streak} clean; raise the bar, faster or from memory.",
                      "{Streak} in a row; time for a harder challenge.", "{Streak} clean; now don't let it slip.",
                      "{Streak} clean passes; push the tempo.", "That's {streak} in a row; move on or speed up."],
        "do-streak-learn": ["{Streak} clean in a row; switch to Rehearse and play it in time.",
                            "That's {streak} clean; the notes are learned, now Rehearse it at tempo.",
                            "{Streak} in a row; stop waiting for the cursor and play it in time.",
                            "{Streak} clean; Learn mode is done, go to Rehearse.", "{Streak} in a row; time to play it at tempo.",
                            "{Streak} clean; the cursor shouldn't have to wait any more.",
                            "That's {streak} clean; now prove it in Rehearse.", "{Streak} clean in a row; on to Rehearse."],
        "do-rough": ["Slow down, way down.", "Hands separately, right now.", "Half tempo; get it right, not fast.",
                     "Go back to Learn mode until the notes are certain.", "Smaller section, slower.", "Slower; accuracy first.",
                     "Take a few bars at a time.", "Hands separately until it's boring."],
        "do-close": ["Again.", "One more, clean this time.", "From the top; concentrate.", "Again, and fix it.", "Once more.",
                     "Again; no slips this time.", "Go again.", "Again, with your full attention."],
        "greet-new": ["{Title}, new piece; let's see what you've got.", "Never heard you play {title}; impress me.",
                      "{Title}, first time; nobody's perfect on day one, try anyway.", "Ah, {title}; fresh pages, show me.",
                      "{Title}; let's see how you read it.", "New piece, {title}; eyes on the score.",
                      "{Title}, from scratch; careful, not fast.", "{Title}; first impressions count."],
        "greet-back": ["{Title} again; your best is {best}, beat it.", "Back to {title}; last time you topped out at {best}.",
                       "{Title}, {takes} so far, best {best}; today we raise it.", "You and {title} again; best score {best}, I remember.",
                       "{Title}; {best} is the number to beat.", "Back to {title}; {best} isn't the ceiling.",
                       "{Title}, best {best}; let's do better.", "{Title} again; {takes} in, and the best is {best}."],
        "greet-away": ["{Days} days since you touched {title}; let's see what stuck.",
                       "{Title}; it's been {days} days, don't tell me you forgot it.",
                       "{Days} days away from {title}; show me what you kept.", "{Title}, {days} days on; let's find out.",
                       "{Days} days; {title} won't have waited for you.", "Back to {title} after {days} days; careful first pass.",
                       "{Days} days since {title}; let's see the damage.", "{Title} after {days} days; prove it stuck."],
        "greet-key": ["{Count}: {names}; keep them in your head.", "Remember the key, {count}: {names}.",
                      "{Names}; that's the key, don't make me remind you twice.", "Key signature: {names}; don't forget them.",
                      "{Count} in this key: {names}.", "{Names}; every time.", "Watch the key: {names}.", "{Count}, {names}; respect them."],
        "greet-wait": ["Learn mode; take your time, but get it right.", "The cursor will wait; mistakes won't hide.",
                       "Learn mode; slow is fine, wrong is not.", "Learn mode; every note right.",
                       "The cursor waits; your accuracy shouldn't.", "Learn mode; think, then play.", "Learn mode; no guessing.",
                       "The cursor waits for the right notes, only the right notes."],
        "greet-rehearsal": ["{Tempo} percent; the cursor won't wait for you.", "Rehearse at {tempo} percent; keep up.",
                            "{Tempo} percent, in time; count yourself in.", "{Tempo} percent; don't stop for mistakes.",
                            "Rehearse, {tempo} percent; the beat is the boss.", "{Tempo} percent; stay with the cursor.",
                            "In time at {tempo} percent; no excuses.", "{Tempo} percent; keep the pulse."],
        "milestone": ["Pass {pass}; now it's practice.", "Pass {pass}; your hands are warming up.",
                      "Pass {pass}; persistence, I respect that.", "{Pass} passes; this is how pianists are made.",
                      "Pass {pass}; go drink some water after this one.", "Pass {pass}; stubborn, good.",
                      "{Pass} passes and counting.", "Pass {pass}; keep the standard up."],
        "pb": ["New personal best on {title}, {score}!", "{Score}; that's a record for you on {title}.",
               "Personal best, {score}; write that down.", "{Score} on {title}; your best yet, don't stop there.",
               "Record, {score}.", "{Score}, a new best; now make it normal.", "Best ever on {title}, {score}.",
               "{Score}; personal best, now beat it."],
        "wrap": ["{Passes} passes; best was pass {best_pass}{best_score}.",
                 "That's {passes} passes today; pass {best_pass} was your best{best_score}.",
                 "{Passes} passes; pass {best_pass} set the standard{best_score}.",
                 "{Passes} passes done; the best was pass {best_pass}{best_score}.",
                 "That's {passes} passes; pass {best_pass} was the one{best_score}.",
                 "{Passes} passes; pass {best_pass} came out on top{best_score}.",
                 "Done, {passes} passes; best was pass {best_pass}{best_score}.",
                 "{Passes} passes; nothing beat pass {best_pass}{best_score}."],
        "wrap-weak": ["Bar {bar} is still your weak spot.", "Bar {bar} needs work tomorrow.", "Your homework is bar {bar}.",
                      "Bar {bar}; fix it before next time.", "Bar {bar} is still not good enough.",
                      "Start tomorrow with bar {bar}.", "Bar {bar} is unfinished business.", "Bar {bar}, slowly, tomorrow."],
        "wrap-good": ["Good session; same time tomorrow.", "Remember this feeling; it's called progress.",
                      "That's real progress; rest your hands.", "Better by the end; that's the job.", "Good work today.",
                      "Progress; keep it coming.", "That's what practice looks like.", "Solid session."],
        "wrap-flat": ["Same time tomorrow.", "Go rest your hands; it settles overnight.", "Don't skip tomorrow.",
                      "No progress today; tomorrow there will be.", "Rest, then come back.", "That's enough for today.",
                      "Tomorrow, slower and cleaner.", "Back at it tomorrow."],
    },
}

NPC_NAME = "Maestro"

# Which "how to fix it" pool goes with each problem.
_FIX = {"wrong": "fix-wrong", "stall": "fix-stall", "flag-rushing": "fix-rushing", "flag-dragging": "fix-dragging",
        "flag-hesitation": "fix-stall", "flag-clipped notes": "fix-articulation", "flag-over-held": "fix-articulation",
        "flag-pedal": "fix-articulation", "timing": "fix-timing", "missed": "fix-missed",
        "acc": "acc-again", "hot": "hot-again"}

_FIFTHS_SHARPS = ["F", "C", "G", "D", "A", "E", "B"]
_FIFTHS_FLATS = ["B", "E", "A", "D", "G", "C", "F"]


def key_reminder(fifths: int | None) -> tuple[str, str] | None:
    """('two sharps', 'F sharp and C sharp') for a key signature, or None for C major / unknown."""
    if not fifths:
        return None
    k = min(abs(fifths), 7)
    letters = (_FIFTHS_SHARPS if fifths > 0 else _FIFTHS_FLATS)[:k]
    acc = "sharp" if fifths > 0 else "flat"
    names = [f"{x} {acc}" for x in letters]
    listed = names[0] if k == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{_num(k)} {acc}{'' if k == 1 else 's'}", listed


def _num(k: int) -> str:
    return _WORDS[k] if 0 <= k < len(_WORDS) else str(k)


def _num_or_digits(value) -> str:
    try:
        k = round(float(value))
    except (TypeError, ValueError):
        return "full"
    return _num(k) if k <= 10 else str(k)


def _count(k: int, word: str = "note") -> str:
    return f"{_num(k)} {word}{'' if k == 1 else 's'}"


def _times(k: int) -> str:
    return {1: "once", 2: "twice"}.get(k, f"{_num(k)} times")


def _pitch(name: str) -> int | None:
    m = _NAME_RE.match(name or "")
    if not m:
        return None
    pc = _LETTER_PC[m.group(1)] + {"#": 1, "b": -1, "": 0}[m.group(2)]
    return pc + 12 * (int(m.group(3)) + 1)


def _slip(played: int, expected: list[int]) -> tuple[str, str, str] | None:
    """(kind, expected, played) spoken; 'accidental' when it's a semitone off around a black key."""
    if not expected:
        return None
    exp = min(expected, key=lambda e: abs(e - played))
    if abs(exp - played) == 1 and (exp % 12 in _BLACK) != (played % 12 in _BLACK):
        # Spell both on the same letter: F sharp vs F, B flat vs B.
        black, white = (exp, played) if exp % 12 in _BLACK else (played, exp)
        names = _SHARPS if black == white + 1 else _FLATS
        exp_name = names[exp % 12] + ("" if exp % 12 in _BLACK else " natural")
        return "accidental", exp_name, names[played % 12]
    return "wrong", _MIXED[exp % 12], _MIXED[played % 12]


class Coach:
    """Keeps the context of one practice run (previous passes, recent wording).

    memory: callable() -> path of a JSON file that keeps the style and the recently used
    wording between sessions, or None to keep them in memory only.
    """

    def __init__(self, rng: random.Random | None = None, memory=None) -> None:
        self.rng = rng or random.Random()
        self.memory = memory
        self.history: list[dict] = []
        self.context: dict = {}
        self._recent: dict[str, list[str]] = {}
        self._style = DEFAULT_STYLE
        self._loaded = memory is None

    # -- style and memory --------------------------------------------------------

    @property
    def style(self) -> str:
        self._load()
        return self._style

    @style.setter
    def style(self, value: str) -> None:
        if value not in STYLES:
            raise ValueError(f"style must be one of {', '.join(STYLES)}")
        self._load()
        self._style = value
        self._save()

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(pathlib.Path(self.memory()).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if data.get("style") in STYLES:
            self._style = data["style"]
        recent = data.get("recent")
        if isinstance(recent, dict):
            self._recent = {k: [s for s in v if isinstance(s, str)] for k, v in recent.items() if isinstance(v, list)}

    def _save(self) -> None:
        if self.memory is None:
            return
        try:
            pathlib.Path(self.memory()).write_text(json.dumps({"style": self._style, "recent": self._recent}, indent=1),
                                                   encoding="utf-8")
        except OSError as exc:
            log.warning("could not save the Maestro's memory: %s", exc)

    def reset(self) -> None:
        self.history.clear()
        self.context = {}

    def _pick(self, pool: str, **values) -> str:
        self._load()
        options = VOICE[self._style].get(pool) or COMMON[pool]
        key = f"{self._style}:{pool}" if pool in VOICE[self._style] else pool
        recent = self._recent.setdefault(key, [])
        fresh = [o for o in options if o not in recent] or options
        choice = self.rng.choice(fresh)
        recent.append(choice)
        del recent[: max(0, len(recent) - len(options) // 2)]
        caps = {k[:1].upper() + k[1:]: (v[:1].upper() + v[1:] if isinstance(v, str) else v) for k, v in values.items()}
        return choice.format(**values, **caps)

    # -- start and end of a run (the Maestro greets you and signs off) -------------

    def start(self, context: dict) -> str:
        """Begin a run and greet it. context: title, mode, tempo_percent, fifths (key signature),
        best_before (best earlier score on this piece and hand), takes_before, days_away."""
        self.reset()
        self.context = dict(context)
        title = context.get("title") or "this piece"
        best, takes, days = context.get("best_before"), context.get("takes_before") or 0, context.get("days_away")
        if days and days >= 2:
            parts = [self._pick("greet-away", title=title, days=_num(days))]
        elif best is not None:
            parts = [self._pick("greet-back", title=title, best=str(best), takes=_count(takes, "take"))]
        else:
            parts = [self._pick("greet-new", title=title)]
        key = key_reminder(context.get("fifths"))
        mode = context.get("mode")
        if key and (best is None or mode not in ("wait", "rehearsal") or self.rng.random() < 0.5):
            parts.append(self._pick("greet-key", count=key[0], names=key[1]))
        elif mode in ("wait", "rehearsal"):
            parts.append(self._pick("greet-" + mode, tempo=_num_or_digits(context.get("tempo_percent"))))
        self._save()
        return " ".join(parts)

    def wrap_up(self) -> str | None:
        """Sign-off for a run of two or more finished passes."""
        if len(self.history) < 2:
            return None
        scored = [(i, h["score"]) for i, h in enumerate(self.history, 1) if h["score"] is not None]
        if scored:
            best_pass, best_score = max(scored, key=lambda p: p[1])
            score_text = f", {best_score}"
        else:
            best_pass = min(range(len(self.history)), key=lambda i: self.history[i]["errors"]) + 1
            score_text = ""
        parts = [self._pick("wrap", passes=_num(len(self.history)), best_pass=_num(best_pass), best_score=score_text)]
        weak: dict[int, int] = {}
        for h in self.history:
            if h["hot_bar"]:
                weak[h["hot_bar"]] = weak.get(h["hot_bar"], 0) + h["hot_count"]
        if weak:
            parts.append(self._pick("wrap-weak", bar=max(weak, key=weak.get)))
        else:
            half = len(self.history) // 2
            early = statistics.fmean(h["errors"] for h in self.history[:half])
            late = statistics.fmean(h["errors"] for h in self.history[half:])
            good = late < early or all(h["grade"] == "clean" for h in self.history[half:])
            parts.append(self._pick("wrap-good" if good else "wrap-flat"))
        self._save()
        return " ".join(parts)

    # -- facts -----------------------------------------------------------------

    @staticmethod
    def _facts(summary: dict, report: dict | None) -> dict:
        wait = summary.get("mode") == "wait"
        total = max(1, summary.get("notes_total") or 0)
        wrong = summary.get("wrong_presses") or 0
        missed = 0 if wait else summary.get("missed") or 0
        per_bar = summary.get("per_bar") or {}
        hot = max(per_bar.items(), key=lambda kv: kv[1].get("wrong", 0) + kv[1].get("missed", 0), default=None)
        hot_count = hot[1].get("wrong", 0) + hot[1].get("missed", 0) if hot else 0
        stall = None
        if wait and len(per_bar) > 1:
            waits = [v["wait_sec"] for v in per_bar.values() if v.get("wait_sec")]
            med = statistics.median(waits) if waits else 0
            bar, v = max(per_bar.items(), key=lambda kv: kv[1].get("wait_sec", 0))
            if v.get("wait_sec", 0) > max(2.0, 2.2 * med):
                stall = (int(bar), v["wait_sec"])
        slip = None
        for s in summary.get("slips") or []:
            found = _slip(s["played"], s["expected"])
            if found:
                slip = (found, s["bar"])
                if found[0] == "accidental":
                    break
        if slip is None and report:
            for m in report.get("mistakes") or []:
                if m.get("type") == "wrong":
                    exp, played = _pitch(m.get("expected", "")), _pitch(m.get("played", ""))
                    if exp is not None and played is not None:
                        slip = (_slip(played, [exp]), m["bar"])
                        break
        flag = None
        if report and not wait:
            for b in report.get("worst_bars") or []:
                for f in b.get("flags") or []:
                    if "flag-" + f in COMMON:
                        flag = (f, b["bar"])
                        break
                if flag:
                    break
        timing_ms = (report or {}).get("timing", {}).get("median_error_ms") if not wait else None
        score = ((report or {}).get("scores") or {}).get("overall")
        accuracy = (summary.get("hits") or 0) / total
        errors = wrong + missed
        if errors == 0 and not stall:
            grade = "clean"
        elif accuracy >= 0.9 and errors <= 3:
            grade = "close"
        elif accuracy >= 0.75:
            grade = "shaky"
        else:
            grade = "rough"
        return {
            "grade": grade, "errors": errors, "missed": missed, "accuracy": accuracy, "score": score,
            "hot_bar": int(hot[0]) if hot and hot_count else None, "hot_count": hot_count,
            "stall": stall, "slip": slip, "flag": flag, "timing_ms": timing_ms,
        }

    @staticmethod
    def _issue(f: dict, prev: dict | None) -> tuple[str | None, int | None, dict]:
        """The one thing worth naming, most instructive first: (pool, bar, values)."""
        slip, hot = f["slip"], f["hot_bar"]
        if slip and slip[0][0] == "accidental":
            (_, exp, played), bar = slip
            return "acc", bar, {"exp": exp, "played": played}
        recurring = hot and prev and prev["hot_bar"] == hot and max(f["hot_count"], prev["hot_count"]) >= 2
        if f["stall"] and not recurring and (not hot or f["hot_count"] < 2):
            bar, secs = f["stall"]
            return "stall", bar, {"secs": _num(round(secs))}
        if hot and (recurring or f["hot_count"] >= 2):
            return "hot", hot, {"count": _count(f["hot_count"])}
        if slip:
            (_, exp, played), bar = slip
            return "wrong", bar, {"exp": exp, "played": played}
        if f["flag"]:
            flag, bar = f["flag"]
            return "flag-" + flag, bar, {}
        if f["timing_ms"] and f["timing_ms"] > 60:
            return "timing", None, {}
        if f["missed"] >= 2:
            return "missed", None, {"count": _count(f["missed"])}
        return None, None, {}

    # -- remark ----------------------------------------------------------------

    def remark(self, summary: dict | None, report: dict | None = None) -> str | None:
        """What to say after a pass: at most two sentences, a word or two when nothing is new,
        or None for a clean pass in a streak that isn't worth a remark."""
        if not summary or not summary.get("notes_total"):
            return None
        f = self._facts(summary, report)
        prev = self.history[-1] if self.history else None
        pool, bar, values = self._issue(f, prev)
        f["issue"] = (pool, bar) if pool else None
        run = 1
        if pool:
            for h in reversed(self.history):
                if h.get("issue") != f["issue"]:
                    break
                run += 1
        self.history.append(f)
        streak = 0
        for h in reversed(self.history):
            if h["grade"] != "clean":
                break
            streak += 1
        n = len(self.history)

        lead = None
        # Beating the best from earlier sessions is announced once per run.
        best = self.context.get("best_before")
        if f["score"] is not None and best is not None and f["score"] > best and not self.context.get("pb_said"):
            lead = self._pick("pb", title=self.context.get("title") or "this piece", score=str(f["score"]))
            self.context["pb_said"] = True
        elif n in MILESTONES:
            lead = self._pick("milestone", **{"pass": _num(n)})
        news = (lead is not None or prev is None or f["grade"] != prev["grade"]
                or (pool is not None and run <= 2) or (f["grade"] == "clean" and streak in STREAK_NEWS))
        if not news:
            said = None if f["grade"] == "clean" else self._pick("same")
            self._save()
            return said

        if lead is None:
            if prev and f["grade"] != "clean" and f["errors"] < prev["errors"]:
                lead = self._pick("improved")
            elif prev and f["grade"] != "clean" and f["errors"] > prev["errors"] + 1:
                lead = self._pick("worse")
            else:
                lead = self._pick("verdict-" + f["grade"])

        if pool and run == 1:
            point = self._pick(pool, bar=bar, **values)
        elif pool:
            # Seen before: how to fix it.
            point = self._pick(_FIX[pool], bar=bar, times=_times(run), **values)
        elif f["grade"] == "clean" and streak in STREAK_NEWS:
            learn = summary.get("mode") == "wait" and streak >= 3
            point = self._pick("do-streak-learn" if learn else "do-streak", streak=_num(streak))
        elif f["grade"] == "clean":
            point = self._pick("do-clean")
        elif f["grade"] == "rough":
            point = self._pick("do-rough")
        else:
            point = self._pick("do-close")
        self._save()
        return f"{lead} {point}"
